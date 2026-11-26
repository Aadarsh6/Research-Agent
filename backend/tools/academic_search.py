"""Client for the custom Academic Research MCP server (arXiv, OpenAlex, Crossref, Semantic Scholar)."""

from tools.cache import TTLCache, normalize_query
from tools.mcp_client import MCPError, mcp_manager

_cache = TTLCache(ttl=24 * 3600)
MIN_ABSTRACT_CHARS = 80  # a title alone cannot support any claim, so such papers are skipped


def search_papers(query: str, max_results: int = 6) -> list[dict]:
    """Return search-result dicts (title, url, content=abstract + authors/published/doi/venue)."""
    key = normalize_query(query)
    cached = _cache.get(key)
    if cached is not None:
        return [dict(r) for r in cached]

    try:
        out = mcp_manager.call("academic", ["search_papers"],
                               {"query": query, "max_results": max_results}, timeout=60)
    except MCPError as exc:
        print(f"[academic] search failed: {exc}")
        return []

    data = out.structured or {}
    if "papers" not in data:  # older SDKs only return JSON text
        import json
        try:
            data = json.loads(out.text)
        except ValueError:
            return []
    for source, err in (data.get("errors") or {}).items():
        print(f"[academic] {source}: {err}")

    results = []
    for p in data.get("papers", []):
        if len(p.get("abstract", "")) < MIN_ABSTRACT_CHARS or not p.get("url"):
            continue
        results.append({
            "title": p["title"], "url": p["url"], "content": p["abstract"],
            "source_type": "academic", "authors": p.get("authors", []),
            "published": p.get("published", ""), "doi": p.get("doi", ""), "venue": p.get("venue", ""),
        })
    if results:
        _cache.set(key, results)
    return results
