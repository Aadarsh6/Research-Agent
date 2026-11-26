"""
TOOL 1 - Web search.

Primary:  Tavily MCP  (free tier, needs TAVILY_API_KEY; only the cheapest "basic" search is used)
Fallback: DuckDuckGo  (free, no key) - used when Tavily is not configured, fails, or its free
          quota / rate limit is exhausted. Quota problems pause Tavily for an hour.

search_web(query) -> [{title, url, content, source_type, published}] ; never raises.
Identical queries are answered from a cache, so the same search is never paid for twice.
"""

import re
import time

from tools.cache import RateLimiter, TTLCache, normalize_query
from tools.mcp_client import MCPError, MCPUnavailable, mcp_manager

_cache = TTLCache(ttl=6 * 3600)
_tavily_limiter = RateLimiter(0.5)
_tavily = {"blocked_until": 0.0, "disabled": False}

_QUOTA = re.compile(r"usage limit|quota|plan.*limit|exceed|rate.?limit|too many|429|432|433", re.I)
_AUTH = re.compile(r"unauthori[sz]ed|invalid api key|401|403", re.I)


def parse_tavily_text(text: str) -> list[dict]:
    """Tavily MCP returns text blocks:  Title: ... / URL: ... / Content: ...  (JSON is also accepted)."""
    import json
    try:
        data = json.loads(text)
        items = data.get("results", data) if isinstance(data, dict) else data
        return [{"title": i.get("title", "Untitled"), "url": i.get("url", ""),
                 "content": i.get("content", ""), "source_type": "web",
                 "published": i.get("published_date", "")} for i in items if i.get("url")]
    except (ValueError, AttributeError):
        pass
    pattern = re.compile(r"Title:\s*(.*?)\s*\n\s*URL:\s*(\S+)\s*\n\s*Content:\s*(.*?)"
                         r"(?=\n\s*Title:|\n\s*Raw Content:|\n\s*Favicon:|\Z)", re.S)
    return [{"title": t.strip() or "Untitled", "url": u.strip(), "content": c.strip(),
             "source_type": "web", "published": ""} for t, u, c in pattern.findall(text)]


def _search_tavily(query: str, max_results: int) -> list[dict]:
    if _tavily["disabled"] or time.time() < _tavily["blocked_until"]:
        return []
    if not mcp_manager.is_ready("tavily"):
        return []
    _tavily_limiter.wait()
    try:
        out = mcp_manager.call("tavily", ["tavily-search", "tavily_search"],
                               {"query": query, "max_results": max_results, "search_depth": "basic"},
                               timeout=30)
    except MCPUnavailable:
        return []
    except MCPError as exc:
        msg = str(exc)
        if _AUTH.search(msg):
            _tavily["disabled"] = True
            print("[web_search] Tavily key rejected - using DuckDuckGo only.")
        elif _QUOTA.search(msg):
            _tavily["blocked_until"] = time.time() + 3600
            print("[web_search] Tavily free quota / rate limit reached - using DuckDuckGo for 1 hour.")
        else:
            print(f"[web_search] Tavily failed for '{query}': {msg}")
        return []
    return parse_tavily_text(out.text)[:max_results]


def _search_duckduckgo(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS  # new package name
    except ImportError:  # pragma: no cover
        from duckduckgo_search import DDGS  # old package name
    return [{"title": i.get("title", "Untitled"), "url": i.get("href", ""), "content": i.get("body") or "",
             "source_type": "web", "published": ""}
            for i in DDGS().text(query, max_results=max_results)]


def search_web(query: str, max_results: int = 4) -> list[dict]:
    key = normalize_query(query)
    cached = _cache.get(key)
    if cached is not None:
        return [dict(r) for r in cached]

    results = _search_tavily(query, max_results)
    if not results:
        try:
            results = _search_duckduckgo(query, max_results)
        except Exception as exc:  # noqa: BLE001
            print(f"[web_search] DuckDuckGo failed for '{query}': {exc}")
            return []
    results = [r for r in results if r.get("url")]
    if results:
        _cache.set(key, results)
    return [dict(r) for r in results]
