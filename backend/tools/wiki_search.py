"""
TOOL 2 - Wikipedia lookup (free, no API key).

Uses the public MediaWiki API: one request searches and returns the intro
text of the best matching pages. Good for definitions, background and
statistics that web snippets often lack.
"""

import requests

API_URL = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "ResearchAgent/1.0 (student project)"}


def search_wikipedia(query: str, max_results: int = 2) -> list[dict]:
    """Return [{title, url, content}] for the best Wikipedia matches."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrlimit": max_results,
        "prop": "extracts|info",
        "inprop": "url",
        "exintro": 1,
        "explaintext": 1,
        "exsentences": 10,
        "exlimit": "max",
    }
    try:
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
    except Exception as exc:
        print(f"[wikipedia] Lookup failed for '{query}': {exc}")
        return []

    ordered = sorted(pages.values(), key=lambda p: p.get("index", 0))
    results = []
    for page in ordered:
        text = (page.get("extract") or "").strip()
        if not text:
            continue
        results.append(
            {
                "title": f"{page.get('title', 'Untitled')} - Wikipedia",
                "url": page.get("fullurl", ""),
                "content": text,
                "source_type": "wikipedia",
            }
        )
    return results
