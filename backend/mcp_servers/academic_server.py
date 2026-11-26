"""
Academic Research MCP server (FastMCP, runs over stdio).

Free scholarly APIs behind one small server:
  - arXiv             (no key)
  - OpenAlex          (no key; CONTACT_EMAIL gives the faster "polite pool")
  - Crossref          (no key; CONTACT_EMAIL gives the polite pool)
  - Semantic Scholar  (works without a key but is heavily rate-limited;
                       optional free SEMANTIC_SCHOLAR_API_KEY)

Tools
  search_papers(query, max_results, sources)  merged + de-duplicated results from all sources
  search_arxiv / search_openalex / search_crossref / search_semantic_scholar
  get_paper_by_doi(doi)                       Crossref metadata for one DOI

Every paper has the same shape:
  {title, authors[], published, doi, url, abstract, venue, source, citations}
Nothing is invented: a field the API did not return stays empty.

Run manually:  python mcp_servers/academic_server.py
"""

import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

import requests
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("academic-research")

CONTACT = os.getenv("CONTACT_EMAIL", "")
S2_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
UA = f"ResearchAgent/1.0 (student project; mailto:{CONTACT or 'not-provided'})"
TIMEOUT = 15
MAX_RETRIES = 3


# ----------------------------------------------------------- rate limits + HTTP

class _Limiter:
    def __init__(self, interval: float):
        self.interval, self._next, self._lock = interval, 0.0, threading.Lock()

    def wait(self):
        with self._lock:
            now = time.time()
            delay = self._next - now
            self._next = max(now, self._next) + self.interval
        if delay > 0:
            time.sleep(delay)


# Minimum seconds between calls to each API (arXiv asks for >= 3s; S2 free pool is ~1 req/s).
LIMITS = {
    "arxiv": _Limiter(3.1),
    "openalex": _Limiter(0.2),
    "crossref": _Limiter(0.25),
    "semantic_scholar": _Limiter(1.1 if not S2_KEY else 0.2),
}


def _http_get(service: str, url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
    """GET with rate limiting, timeout, and retry/backoff on 429 / 5xx / network errors."""
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        LIMITS[service].wait()
        try:
            resp = requests.get(url, params=params, timeout=TIMEOUT,
                                headers={"User-Agent": UA, **(headers or {})})
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 2 ** attempt * 1.5
                last = RuntimeError(f"HTTP {resp.status_code}")
                time.sleep(min(delay, 10))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"{service} unavailable: {last}")


# ------------------------------------------------------------------ helpers

def _paper(title, authors, published, doi, url, abstract, venue, source, citations=None) -> dict:
    doi = (doi or "").lower().replace("https://doi.org/", "").replace("http://dx.doi.org/", "").strip()
    return {
        "title": re.sub(r"\s+", " ", title or "").strip(),
        "authors": [a for a in (authors or []) if a],
        "published": published or "",
        "doi": doi,
        "url": url or (f"https://doi.org/{doi}" if doi else ""),
        "abstract": re.sub(r"\s+", " ", abstract or "").strip(),
        "venue": venue or "",
        "source": source,
        "citations": citations,
    }


def _date_from_parts(parts) -> str:
    """Crossref date-parts [[2021, 5, 17]] -> '2021-05-17' (shorter if month/day missing)."""
    try:
        return "-".join(f"{int(p):02d}" if i else str(int(p)) for i, p in enumerate(parts[0]))
    except (TypeError, ValueError, IndexError):
        return ""


def _openalex_abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    words = {}
    for word, positions in inverted.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words[i] for i in sorted(words))


def _clamp(n: int) -> int:
    return max(1, min(int(n), 10))


# ---------------------------------------------------------------- API clients

def _arxiv(query: str, n: int) -> list[dict]:
    terms = [w for w in re.findall(r"[A-Za-z0-9\-]+", query)][:8]
    if not terms:
        return []
    resp = _http_get("arxiv", "https://export.arxiv.org/api/query", {
        "search_query": " AND ".join(f"all:{t}" for t in terms),
        "start": 0, "max_results": n, "sortBy": "relevance",
    })
    ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
    out = []
    for entry in ET.fromstring(resp.content).findall("a:entry", ns):
        g = lambda tag: (entry.findtext(f"a:{tag}", default="", namespaces=ns) or "").strip()  # noqa: E731
        out.append(_paper(
            g("title"), [a.findtext("a:name", default="", namespaces=ns) for a in entry.findall("a:author", ns)],
            g("published")[:10], entry.findtext("x:doi", default="", namespaces=ns), g("id"),
            g("summary"), "arXiv preprint", "arxiv"))
    return out


def _openalex(query: str, n: int) -> list[dict]:
    params = {"search": query, "per-page": n,
              "select": "id,doi,display_name,publication_date,authorships,primary_location,"
                        "abstract_inverted_index,cited_by_count"}
    if CONTACT:
        params["mailto"] = CONTACT
    results = _http_get("openalex", "https://api.openalex.org/works", params).json().get("results", [])
    out = []
    for w in results:
        loc = w.get("primary_location") or {}
        out.append(_paper(
            w.get("display_name"), [(a.get("author") or {}).get("display_name") for a in w.get("authorships", [])],
            w.get("publication_date"), w.get("doi"), loc.get("landing_page_url") or w.get("doi") or w.get("id"),
            _openalex_abstract(w.get("abstract_inverted_index")),
            (loc.get("source") or {}).get("display_name"), "openalex", w.get("cited_by_count")))
    return out


def _crossref_item(it: dict) -> dict:
    authors = [" ".join(x for x in (a.get("given"), a.get("family")) if x) or a.get("name", "")
               for a in it.get("author", [])]
    date = it.get("issued") or it.get("published-print") or it.get("published-online") or {}
    abstract = re.sub(r"<[^>]+>", " ", it.get("abstract", "") or "")  # abstracts come as JATS XML
    return _paper((it.get("title") or [""])[0], authors, _date_from_parts(date.get("date-parts")),
                  it.get("DOI"), it.get("URL"), abstract, (it.get("container-title") or [""])[0],
                  "crossref", it.get("is-referenced-by-count"))


def _crossref(query: str, n: int) -> list[dict]:
    params = {"query": query, "rows": n,
              "select": "DOI,title,author,issued,container-title,abstract,URL,is-referenced-by-count"}
    if CONTACT:
        params["mailto"] = CONTACT
    items = _http_get("crossref", "https://api.crossref.org/works", params).json()["message"].get("items", [])
    return [_crossref_item(i) for i in items]


def _semantic_scholar(query: str, n: int) -> list[dict]:
    fields = "title,abstract,year,publicationDate,authors,externalIds,url,venue,citationCount"
    headers = {"x-api-key": S2_KEY} if S2_KEY else {}
    data = _http_get("semantic_scholar", "https://api.semanticscholar.org/graph/v1/paper/search",
                     {"query": query, "limit": n, "fields": fields}, headers).json().get("data", [])
    return [_paper(p.get("title"), [a.get("name") for a in p.get("authors", [])],
                   p.get("publicationDate") or (str(p["year"]) if p.get("year") else ""),
                   (p.get("externalIds") or {}).get("DOI"), p.get("url"), p.get("abstract"),
                   p.get("venue"), "semantic_scholar", p.get("citationCount")) for p in data]


SOURCES = {"arxiv": _arxiv, "openalex": _openalex, "crossref": _crossref,
           "semantic_scholar": _semantic_scholar}


def _merge(papers: list[dict]) -> list[dict]:
    """De-duplicate by DOI (else normalised title); fill gaps in one record from its duplicates."""
    merged: dict[str, dict] = {}
    for p in papers:
        if not p["title"]:
            continue
        key = p["doi"] or re.sub(r"\W+", "", p["title"].lower())
        if key not in merged:
            merged[key] = dict(p, found_in=[p["source"]])
            continue
        base = merged[key]
        base["found_in"].append(p["source"])
        for field in ("abstract", "published", "venue", "doi", "url"):
            if not base[field] and p[field]:
                base[field] = p[field]
        if len(p["authors"]) > len(base["authors"]):
            base["authors"] = p["authors"]
    return list(merged.values())


# ------------------------------------------------------------------ MCP tools

@mcp.tool()
def search_papers(query: str, max_results: int = 6,
                  sources: str = "openalex,arxiv,semantic_scholar,crossref") -> dict:
    """Search scholarly papers across arXiv, OpenAlex, Crossref and Semantic Scholar.

    Returns {"papers": [...], "errors": {source: message}}. Sources that fail are reported
    in "errors" and the others still return results. Papers are de-duplicated by DOI/title.
    """
    n = _clamp(max_results)
    wanted = [s.strip() for s in sources.split(",") if s.strip() in SOURCES]
    errors: dict[str, str] = {}

    def run(name: str):
        try:
            return name, SOURCES[name](query, n), None
        except Exception as exc:  # noqa: BLE001 - one broken API must not break the others
            return name, [], str(exc)[:200]

    papers: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(wanted) or 1) as pool:
        for name, found, err in pool.map(run, wanted):
            papers += found
            if err:
                errors[name] = err
    merged = _merge(papers)
    merged.sort(key=lambda p: (not p["abstract"], -(p["citations"] or 0)))
    return {"papers": merged[: n + 2], "errors": errors}


def _single(name: str, query: str, max_results: int) -> dict:
    try:
        return {"papers": SOURCES[name](query, _clamp(max_results)), "errors": {}}
    except Exception as exc:  # noqa: BLE001
        return {"papers": [], "errors": {name: str(exc)[:200]}}


@mcp.tool()
def search_arxiv(query: str, max_results: int = 5) -> dict:
    """Search arXiv preprints."""
    return _single("arxiv", query, max_results)


@mcp.tool()
def search_openalex(query: str, max_results: int = 5) -> dict:
    """Search OpenAlex works (journal articles, books, preprints)."""
    return _single("openalex", query, max_results)


@mcp.tool()
def search_crossref(query: str, max_results: int = 5) -> dict:
    """Search Crossref DOI metadata."""
    return _single("crossref", query, max_results)


@mcp.tool()
def search_semantic_scholar(query: str, max_results: int = 5) -> dict:
    """Search Semantic Scholar (rate-limited without an API key)."""
    return _single("semantic_scholar", query, max_results)


@mcp.tool()
def get_paper_by_doi(doi: str) -> dict:
    """Look up one paper's metadata (authors, date, venue) on Crossref by DOI."""
    doi = doi.strip().replace("https://doi.org/", "").replace("http://dx.doi.org/", "")
    try:
        params = {"mailto": CONTACT} if CONTACT else None
        item = _http_get("crossref", f"https://api.crossref.org/works/{doi}", params).json()["message"]
        return {"paper": _crossref_item(item), "errors": {}}
    except Exception as exc:  # noqa: BLE001
        return {"paper": None, "errors": {"crossref": str(exc)[:200]}}


if __name__ == "__main__":
    mcp.run()  # stdio transport
