"""
AI Research Agent - FastAPI backend.

Run (from the backend folder):
    uvicorn main:app --reload --port 8000

API
    GET    /api/health               -> which keys / tools are configured
    POST   /api/research             -> start a research job  {topic}  -> {job_id}
    GET    /api/jobs/{job_id}        -> live progress (steps, status, result_id)
    GET    /api/research             -> history list
    GET    /api/research/{id}        -> one saved report
    GET    /api/research/{id}/pdf    -> download the report as PDF
    DELETE /api/research/{id}        -> remove from history
"""

import os
import re
import threading
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load keys from backend/.env BEFORE importing modules that read them.
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.graph import build_graph
from agent.llm import llm_provider
from database import db
from tools import file_store
from tools.mcp_client import mcp_manager
from utils.pdf_generator import generate_pdf


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Start the MCP servers in the background (the API is usable immediately) and stop them on exit."""
    mcp_manager.start()

    def _prepare_folders():
        if mcp_manager.is_ready("filesystem"):
            file_store.ensure_folders()

    threading.Thread(target=_prepare_folders, daemon=True).start()
    yield
    mcp_manager.stop()


app = FastAPI(title="AI Research Agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db.init_db()

STEP_LABELS = {
    "plan": "Planning the research",
    "search": "Searching web, Wikipedia & academic sources",
    "extract": "Extracting key facts",
    "evaluate": "Checking if more research is needed",
    "visualize": "Creating charts & diagrams",
    "report": "Writing the final report",
}

# In-memory job table: {job_id: {...}}. Finished reports live in SQLite.
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ------------------------------------------------------------------ models

class ResearchRequest(BaseModel):
    topic: str = Field(min_length=5, max_length=300)


# ------------------------------------------------------------------ helpers

def _step_detail(node: str, state: dict) -> str:
    if node == "plan":
        n_q = len(state.get("plan", {}).get("sub_questions", []))
        return f"{n_q} sub-questions, {len(state.get('search_queries', []))} searches planned"
    if node == "search":
        return f"{len(state.get('search_results', []))} unique pages collected so far"
    if node == "extract":
        return f"{len(state.get('findings', []))} facts extracted so far"
    if node == "evaluate":
        if state.get("search_queries"):
            return "Not enough information - running follow-up searches"
        return "Enough information gathered"
    if node == "visualize":
        return f"{len(state.get('visuals', []))} figure(s) created"
    return ""


def _run_job(job_id: str, topic: str):
    """Runs in a background thread: executes the agent and records each step."""
    job = JOBS[job_id]
    state = {
        "topic": topic, "plan": {}, "search_queries": [], "search_results": [],
        "findings": [], "processed_urls": [], "failed_queries": [], "searched_queries": [],
        "search_round": 0, "visuals": [], "report": {}, "error": "",
    }
    try:
        graph = build_graph()
        for update in graph.stream(state, stream_mode="updates"):
            for node, output in update.items():
                if isinstance(output, dict):
                    state.update(output)
                with JOBS_LOCK:
                    job["steps"].append({
                        "node": node,
                        "label": STEP_LABELS.get(node, node),
                        "detail": _step_detail(node, state),
                        "time": round(time.time() - job["started"], 1),
                    })

        if state.get("error"):
            raise RuntimeError(state["error"])
        report = state.get("report")
        if not report:
            raise RuntimeError("The agent finished but did not produce a report.")

        result_id = db.save_research(topic, report, report.get("references", []))
        saved_to = None
        try:  # copy to research/reports/ through the Filesystem MCP (optional, never fatal)
            saved_to = file_store.save_report(result_id, topic, report)
        except Exception as exc:  # noqa: BLE001
            print(f"[main] Could not save report files: {exc}")
        with JOBS_LOCK:
            job.update(status="done", result_id=result_id, saved_to=saved_to)
    except Exception as exc:  # any failure is reported to the UI, never crashes the server
        with JOBS_LOCK:
            job.update(status="error", error=str(exc))


def _safe_filename(topic: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", topic)
    return "_".join(safe.split())[:50] or "research_report"


# ------------------------------------------------------------------ routes

@app.get("/api/health")
def health():
    provider = llm_provider()
    labels = {
        "tavily": "Tavily web search (MCP)", "fetch": "Fetch pages (MCP)",
        "filesystem": "Research files (MCP)", "academic": "Academic papers (MCP)",
        "playwright": "Playwright browser (MCP)",
    }
    tools = [{"name": labels[n], "state": st["state"], "detail": st["detail"]}
             for n, st in mcp_manager.status().items()]
    tools.append({"name": "DuckDuckGo (fallback search)", "state": "ready", "detail": "no key needed"})
    tools.append({"name": "Wikipedia", "state": "ready", "detail": "no key needed"})
    return {"llm_ready": provider is not None, "llm_provider": provider, "tools": tools}


@app.post("/api/research", status_code=202)
def start_research(req: ResearchRequest):
    if llm_provider() is None:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key configured. Add GOOGLE_API_KEY or GROQ_API_KEY to backend/.env and restart.",
        )
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "steps": [], "error": "", "result_id": None, "saved_to": None,
                    "topic": req.topic.strip(), "started": time.time()}
    threading.Thread(target=_run_job, args=(job_id, req.topic.strip()), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    with JOBS_LOCK:
        return {k: job[k] for k in ("status", "steps", "error", "result_id", "topic", "saved_to")}


@app.get("/api/research")
def list_research():
    return db.get_all_research()


@app.get("/api/research/{run_id}")
def get_research(run_id: int):
    record = db.get_research(run_id)
    if record is None:
        raise HTTPException(404, "Research not found")
    return record


@app.get("/api/research/{run_id}/pdf")
def download_pdf(run_id: int):
    record = db.get_research(run_id)
    if record is None:
        raise HTTPException(404, "Research not found")
    try:
        pdf_bytes = generate_pdf(record["report"])
    except Exception as exc:
        raise HTTPException(500, f"Could not generate the PDF: {exc}")
    filename = _safe_filename(record["topic"]) + ".pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/research/{run_id}")
def delete_research(run_id: int):
    db.delete_research(run_id)
    return {"deleted": run_id}


# Optional: after `npm run build`, the backend also serves the frontend (single process).
DIST = BASE_DIR.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
