"""
Page extraction: Fetch MCP first, Playwright MCP only when Fetch fails or the page needs JavaScript.

  fetch_page(url) -> {"text": str, "method": "fetch" | "playwright" | "cache"} | None

Each URL is extracted at most once: results (and failures) are remembered in memory, and
successful extractions are stored in research/documents/ through the Filesystem MCP so
later runs reuse them.
"""

import json
import re

from tools import file_store
from tools.cache import TTLCache, normalize_url
from tools.mcp_client import MCPError, mcp_manager

MAX_CHARS = 4000
MIN_USEFUL_CHARS = 200
_memory = TTLCache(ttl=6 * 3600)   # url -> result dict, or {} for a known failure

_JS_HINTS = ("enable javascript", "javascript is required", "javascript is disabled",
             "turn on javascript", "requires javascript", "please enable js")


def _needs_browser(text: str | None) -> bool:
    return not text or len(text) < MIN_USEFUL_CHARS or any(h in text.lower() for h in _JS_HINTS)


def _fetch_with_fetch_mcp(url: str) -> str | None:
    try:
        out = mcp_manager.call("fetch", ["fetch"],
                               {"url": url, "max_length": MAX_CHARS, "raw": False}, timeout=40)
    except MCPError as exc:
        print(f"[page_fetch] fetch failed for {url}: {exc}")
        return None
    text = re.sub(r"^Contents of [^\n]*:\n", "", out.text.strip())
    return text[:MAX_CHARS] or None


def _parse_playwright_result(text: str) -> str:
    """browser_evaluate answers '### Result\\n"...json string..."\\n### Ran Playwright code...'."""
    m = re.search(r"### Result\s*\n(.*?)(?=\n### |\Z)", text, re.S)
    body = (m.group(1) if m else text).strip()
    try:
        value = json.loads(body)
        return value if isinstance(value, str) else body
    except ValueError:
        return body


def _fetch_with_playwright(url: str) -> str | None:
    if not mcp_manager.is_ready("playwright"):
        return None
    try:
        try:
            mcp_manager.call("playwright", ["browser_navigate"], {"url": url}, timeout=60)
        except MCPError as exc:
            if re.search(r"install|executable doesn't exist|not found", str(exc), re.I):
                # Playwright MCP can download its own browser; try once, then navigate again.
                mcp_manager.call("playwright", ["browser_install"], {}, timeout=300, retries=0)
                mcp_manager.call("playwright", ["browser_navigate"], {"url": url}, timeout=60)
            else:
                raise
        try:
            out = mcp_manager.call("playwright", ["browser_evaluate"],
                                   {"function": "() => document.body.innerText"}, timeout=30)
            text = _parse_playwright_result(out.text)
        except MCPError:
            text = mcp_manager.call("playwright", ["browser_snapshot"], {}, timeout=30).text
    except MCPError as exc:
        print(f"[page_fetch] playwright failed for {url}: {exc}")
        return None
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_CHARS] or None


def fetch_page(url: str) -> dict | None:
    key = normalize_url(url)
    known = _memory.get(key)
    if known is not None:
        return known or None               # {} means "already failed - don't retry"

    cached = file_store.load_document(url) if mcp_manager.is_ready("filesystem", wait=False) else None
    if cached:
        _memory.set(key, cached)
        return cached

    text, method = _fetch_with_fetch_mcp(url), "fetch"
    if _needs_browser(text):
        browser_text = _fetch_with_playwright(url)
        if browser_text and len(browser_text) >= MIN_USEFUL_CHARS:
            text, method = browser_text, "playwright"

    if not text or len(text) < MIN_USEFUL_CHARS:
        _memory.set(key, {})
        return None

    result = {"text": text, "method": method}
    _memory.set(key, result)
    if mcp_manager.is_ready("filesystem", wait=False):
        file_store.save_document(url, text, method)
    return result
