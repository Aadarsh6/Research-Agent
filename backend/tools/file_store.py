"""
Filesystem MCP wrapper - reads/writes ONLY inside the project's research/ folder.

    research/
      reports/    one folder per finished report  (report.md, report.json, references.json)
      documents/  extracted web pages (cache, one .md per URL, reused on later runs)

The Filesystem MCP server is started with the research folder as its only allowed directory,
so it cannot touch anything else. If the server is unavailable every function degrades
quietly (returns None / False) and the agent carries on.
"""

import hashlib
import json
import re
from datetime import datetime, timedelta

from tools.mcp_client import MCPError, mcp_manager, research_dir

READ_TOOLS = ["read_text_file", "read_file"]   # name differs between server versions
CACHE_DAYS = 30


def _path(*parts: str) -> str:
    return str(research_dir().joinpath(*parts))


def ensure_folders():
    for sub in ("reports", "documents"):
        try:
            mcp_manager.call("filesystem", ["create_directory"], {"path": _path(sub)}, timeout=20)
        except MCPError as exc:
            print(f"[file_store] Could not create '{sub}': {exc}")
            return


def write_file(path: str, content: str) -> bool:
    try:
        mcp_manager.call("filesystem", ["write_file"], {"path": path, "content": content}, timeout=30)
        return True
    except MCPError as exc:
        print(f"[file_store] Write failed: {exc}")
        return False


def read_file(path: str) -> str | None:
    try:
        return mcp_manager.call("filesystem", READ_TOOLS, {"path": path}, timeout=20, retries=0).text
    except MCPError:
        return None  # missing file or server down -> treated as "not cached"


# ------------------------------------------------------------ document cache

def _doc_path(url: str) -> str:
    return _path("documents", hashlib.sha1(url.encode()).hexdigest()[:16] + ".md")


def load_document(url: str) -> dict | None:
    """Return {'text', 'method'} for a previously extracted page, or None."""
    raw = read_file(_doc_path(url))
    if not raw or "\n---\n" not in raw:
        return None
    header, text = raw.split("\n---\n", 1)
    meta = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
    try:
        age = datetime.now() - datetime.fromisoformat(meta.get("fetched", "1970-01-01"))
        if age > timedelta(days=CACHE_DAYS):
            return None
    except ValueError:
        return None
    return {"text": text.strip(), "method": meta.get("method", "cache")}


def save_document(url: str, text: str, method: str) -> None:
    header = f"source: {url}\nfetched: {datetime.now().isoformat(timespec='seconds')}\nmethod: {method}"
    write_file(_doc_path(url), f"{header}\n---\n{text}")


# ------------------------------------------------------------------- reports

def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "report"


def save_report(run_id: int, topic: str, report: dict) -> str | None:
    """Write the finished report as Markdown + JSON. Returns the folder path, or None on failure."""
    from utils.markdown_export import report_to_markdown

    if not mcp_manager.is_ready("filesystem", wait=False):
        return None
    folder = _path("reports", f"{run_id:04d}_{_slug(topic)}")
    light = {k: v for k, v in report.items() if k != "visuals"}  # images are not stored as text
    light["figures"] = [{"title": v["title"], "caption": v["caption"]} for v in report.get("visuals", [])]
    try:
        mcp_manager.call("filesystem", ["create_directory"], {"path": folder}, timeout=20)
    except MCPError as exc:
        print(f"[file_store] Could not create report folder: {exc}")
        return None
    ok = write_file(f"{folder}/report.md", report_to_markdown(report))
    ok &= write_file(f"{folder}/report.json", json.dumps(light, indent=2, ensure_ascii=False))
    ok &= write_file(f"{folder}/references.json",
                     json.dumps(report.get("references", []), indent=2, ensure_ascii=False))
    return folder if ok else None
