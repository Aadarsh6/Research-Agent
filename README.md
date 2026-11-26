# AI Research Agent (React + FastAPI + LangGraph + MCP)

Enter a topic -> the agent plans, searches, reads sources, draws charts/diagrams and writes a report
with **claim-level citations** and a reference list (authors, date, DOI, URL). Download it as PDF.

## Tools

| Tool | How | Free? | Needed? |
|---|---|---|---|
| Web search | **Tavily MCP**, automatic **DuckDuckGo** fallback | Tavily free tier (1,000 credits/month); DDG free | Tavily key optional |
| Page extraction | **Fetch MCP** | free, open source | installed by pip |
| Research files | **Filesystem MCP**, locked to `research/` | free | needs Node.js |
| Academic papers | **Custom FastMCP server**: arXiv, OpenAlex, Crossref, Semantic Scholar | free | works out of the box |
| JavaScript sites | **Playwright MCP** (only when Fetch fails) | free | optional, off by default |
| Wikipedia, charts | Wikipedia API, matplotlib | free | built in |

Anything optional that is missing is skipped; the app still works (even with only an LLM key).

## Windows PowerShell setup

**1. One-time prerequisites** (skip what you already have, then close and reopen PowerShell)

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id OpenJS.NodeJS.LTS
python --version; node --version; npx --version
```

**2. Backend**

```powershell
cd research_agent\backend
python -m venv venv
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned   # only if the next line is blocked
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

In `.env` set **one** LLM key (`GOOGLE_API_KEY` or `GROQ_API_KEY`, both have free tiers).
Optional: `TAVILY_API_KEY`, `CONTACT_EMAIL` (your email: faster OpenAlex/Crossref), `SEMANTIC_SCHOLAR_API_KEY`.

**3. (Optional) JavaScript-site browsing**: in `.env` set `ENABLE_PLAYWRIGHT_MCP=true`.
On Windows it uses the Microsoft Edge you already have, so nothing is downloaded.

**4. (Optional) Pre-download the npm MCP servers** so the first start is fast

```powershell
npm cache add tavily-mcp@latest @modelcontextprotocol/server-filesystem @playwright/mcp@latest
```

**5. Test the tools** (offline tests, then live checks of every tool)

```powershell
python -m unittest discover -s tests
python check_tools.py
```

`check_tools.py` prints PASS / FAIL / SKIP per tool, including a check that the Filesystem MCP
refuses to touch anything outside `research\`.

**6. Run** (two PowerShell windows)

```powershell
# window 1 - backend
cd research_agent\backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --port 8000

# window 2 - frontend
cd research_agent\frontend
npm install
npm run dev
```

Open http://localhost:5173. The "Tools" panel shows which MCP servers connected.

## How it behaves

- **Search:** Tavily MCP (basic depth = 1 credit; extract/crawl are never used). If the key is missing,
  rejected, or the free quota/rate limit is hit, DuckDuckGo is used (Tavily is paused for 1 hour after a quota error).
- **No duplicates:** identical queries are cached and never re-run; URLs/DOIs are de-duplicated; each page is
  extracted once and stored in `research\documents\` for later runs.
- **Reading pages:** thin search snippets are replaced with the full page via Fetch MCP; Playwright MCP is
  used only if Fetch fails or the page needs JavaScript.
- **Limits:** every call has a timeout and one retry; the academic server rate-limits each API
  (arXiv 1 req/3 s, Semantic Scholar ~1 req/s) and backs off on 429/5xx.
- **Citations:** the model writes `[n]` markers; code then **removes any statement without a valid source,
  or with a number that is not in the cited source**, renumbers the markers and builds the reference
  list only from retrieved sources. Titles, authors, dates and DOIs come from the tools, never from the LLM.
  If a source has no date/author it shows `n.d.` / nothing rather than a guess.
- **Output:** web report, PDF download, and copies saved to `research\reports\<id>_<topic>\`
  (`report.md`, `report.json`, `references.json`).

## What changed vs. the previous version

| File | Change |
|---|---|
| `backend/tools/mcp_client.py` | **new** - one MCP client layer (background loop, timeouts, retry, status) |
| `backend/mcp_servers/academic_server.py` | **new** - custom FastMCP server (4 scholarly APIs) |
| `backend/tools/web_search.py` | Tavily via MCP + DuckDuckGo fallback + cache |
| `backend/tools/page_fetch.py`, `academic_search.py`, `file_store.py`, `cache.py` | **new** wrappers |
| `backend/agent/citations.py` | **new** - claim-level citation validation |
| `backend/agent/reporter.py`, `graph.py` | numbered sources, cited report; academic search, page enrichment, query de-dup; redundant `summarize` LLM node removed (saves free-tier quota) |
| `backend/utils/references.py`, `markdown_export.py`, `pdf_generator.py` | reference metadata in PDF / Markdown |
| `backend/main.py` | starts/stops MCP servers, tool status in `/api/health`, saves reports |
| `frontend/src/components/ReportView.jsx`, `ToolStatus.jsx`, `App.jsx` | clickable citations, full references, tool panel |
| `backend/tests/`, `backend/check_tools.py` | offline tests and live smoke test |
| `backend/requirements.txt`, `.env.example` | `mcp`, `mcp-server-fetch` added; `tavily-python` removed |
