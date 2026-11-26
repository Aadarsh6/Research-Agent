"""
Live smoke test of every tool. Run from backend/ after setup:

    python check_tools.py

Prints PASS / FAIL / SKIP per tool (SKIP = optional tool not configured). Uses a few free API calls.
"""

import sys
import tempfile
from pathlib import Path
import json

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from tools import academic_search, file_store, page_fetch, web_search, wiki_search  # noqa: E402
from tools.mcp_client import MCPError, mcp_manager, research_dir  # noqa: E402

results: list[tuple[str, str, str]] = []


def record(name, status, detail=""):
    results.append((name, status, detail))
    print(f"[{status:4}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def check(name, server, fn):
    """Run fn() if the MCP server is up; fn returns a detail string or raises."""
    if not mcp_manager.is_ready(server):
        status = mcp_manager.status().get(server, {})
        record(name, "SKIP", status.get("detail", "not configured"))
        return
    try:
        record(name, "PASS", fn())
    except Exception as exc:  # noqa: BLE001
        record(name, "FAIL", f"{type(exc).__name__}: {exc}"[:200])


def t_tavily():
    out = mcp_manager.call("tavily", ["tavily-search", "tavily_search"],
                           {"query": "what is the model context protocol", "max_results": 3,
                            "search_depth": "basic"}, timeout=40)
    parsed = web_search.parse_tavily_text(out.text)
    if not parsed:
        raise RuntimeError(f"could not parse Tavily output: {out.text[:150]!r}")
    return f"{len(parsed)} results, first: {parsed[0]['url']}"


def t_fetch():
    out = mcp_manager.call(
        "fetch",
        ["fetch"],
        {
            "url": "https://example.com",
            "max_length": 500
        },
        timeout=40
    )

    text = out.text.lower()

    if not any(phrase in text for phrase in (
        "example domain",
        "documentation examples"
    )):
        raise RuntimeError(
            f"unexpected content: {out.text[:100]!r}"
        )

    return "example.com extracted"


def t_filesystem():
    root = research_dir()
    probe = str(root / "documents" / "_check.txt")
    file_store.ensure_folders()
    if not file_store.write_file(probe, "ok"):
        raise RuntimeError("write failed")
    if (file_store.read_file(probe) or "").strip() != "ok":
        raise RuntimeError("read-back failed")
    outside = str(Path(tempfile.gettempdir()) / "outside_research_folder.txt")
    try:
        mcp_manager.call("filesystem", ["write_file"], {"path": outside, "content": "x"}, retries=0)
        raise RuntimeError("SECURITY: server wrote outside the research folder!")
    except MCPError:
        pass  # expected: access denied
    return f"read/write OK in {root}; access outside it is refused"


def t_academic():
    papers = academic_search.search_papers("transformer neural network attention", max_results=4)
    if not papers:
        raise RuntimeError("no papers returned (see [academic] messages above for per-source errors)")
    p = papers[0]
    out = mcp_manager.call("academic", ["get_paper_by_doi"], {"doi": "10.1038/nature14539"}, timeout=40)
    data = out.structured or {}

    if "paper" not in data:
        data = json.loads(out.text)

    paper = data.get("paper")
    if not paper:
        raise RuntimeError(f"DOI lookup failed: {out.text[:150]}")
    return f"{len(papers)} papers; first: '{p['title'][:50]}' ({p['published']}, DOI {p['doi'] or 'n/a'}); DOI lookup: {paper['title'][:40]}"


def t_playwright():
    page = page_fetch._fetch_with_playwright("https://example.com")
    if not page or "Example Domain" not in page:
        raise RuntimeError(f"unexpected content: {(page or '')[:100]!r}")
    return "browser rendered example.com"


def main():
    print("Starting MCP servers (the first run downloads npm packages - this can take a minute)...\n")
    mcp_manager.start()
    check("Tavily MCP        (web search)", "tavily", t_tavily)
    check("Fetch MCP         (page -> text)", "fetch", t_fetch)
    check("Filesystem MCP    (research/ only)", "filesystem", t_filesystem)
    check("Academic MCP      (4 scholarly APIs)", "academic", t_academic)
    check("Playwright MCP    (JS pages)", "playwright", t_playwright)

    try:
        n = len(web_search._search_duckduckgo("open source research agent", 3))
        record("DuckDuckGo       (fallback)", "PASS" if n else "FAIL", f"{n} results")
    except Exception as exc:  # noqa: BLE001
        record("DuckDuckGo       (fallback)", "FAIL", str(exc)[:150])
    n = len(wiki_search.search_wikipedia("Model Context Protocol", 1))
    record("Wikipedia", "PASS" if n else "FAIL", f"{n} result(s)")

    mcp_manager.stop()
    failed = [r for r in results if r[1] == "FAIL"]
    print(f"\n{sum(r[1] == 'PASS' for r in results)} passed, {len(failed)} failed, "
          f"{sum(r[1] == 'SKIP' for r in results)} skipped")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
