"""
The agent's brain — a LangGraph state machine.

Flow:

    plan -> search -> extract -> evaluate --(needs more info)--> search (max 2 rounds)
                                  |
                             (enough info)
                                  v
                          visualize -> report -> END

Tools used by the agent (most of them through MCP, see tools/mcp_client.py):
    web search   Tavily MCP, DuckDuckGo as fallback      (tools/web_search.py)
    academic     arXiv/OpenAlex/Crossref/Semantic Scholar (tools/academic_search.py, custom MCP server)
    page fetch   Fetch MCP, Playwright MCP for JS pages  (tools/page_fetch.py)
    filesystem   Filesystem MCP: page cache + saved reports in research/
    Wikipedia    free API                                (tools/wiki_search.py)
    charts       matplotlib                              (tools/chart_tool.py via agent/visualizer.py)

Each node is a small function that reads the shared state and returns only
the parts of the state it wants to update.
"""

from datetime import datetime
from typing import TypedDict

from langgraph.graph import StateGraph, START, END

from agent.planner import create_research_plan
from agent.researcher import decide_search_queries, extract_findings, check_sufficiency
from agent.reporter import generate_report
from agent.visualizer import build_visuals
from tools.academic_search import search_papers
from tools.cache import normalize_query, normalize_url
from tools.page_fetch import fetch_page
from tools.web_search import search_web
from tools.wiki_search import search_wikipedia

# MAX_SEARCH_ROUNDS = 2        # cap the refine loop so cost/time stays bounded
# ENRICH_BELOW_CHARS = 500     # web snippets shorter than this are replaced by the full page text
# MAX_PAGE_FETCHES_PER_ROUND = 4

MAX_SEARCH_ROUNDS = 2
ENRICH_BELOW_CHARS = 300
MAX_PAGE_FETCHES_PER_ROUND = 2

class ResearchState(TypedDict):
    """Everything the agent knows while working on one topic."""
    topic: str
    plan: dict
    search_queries: list[str]     # queries the agent wants to run next
    search_results: list[dict]    # every result collected so far
    findings: list[dict]          # extracted facts, each linked to a URL
    processed_urls: list[str]     # URLs already extracted (avoid re-processing)
    failed_queries: list[str]     # queries that returned nothing
    searched_queries: list[str]   # normalized queries already run (no duplicate searches)
    search_round: int
    visuals: list[dict]           # charts + diagram (PNG data URIs)
    report: dict
    error: str                    # non-empty if something went wrong


# ------------------------- nodes -------------------------

def plan_node(state: ResearchState) -> dict:
    """Step 1: understand the topic and plan the research."""
    try:
        plan = create_research_plan(state["topic"])
        plan_dict = plan.model_dump()
        # The agent itself decides which searches to run first.
        queries = decide_search_queries(plan_dict)
        return {"plan": plan_dict, "search_queries": queries, "search_round": 1}
    except Exception as exc:
        return {"error": f"Planning failed: {exc}"}


def _enrich_with_full_pages(results: list[dict]) -> None:
    """Replace thin web snippets by the full page text (Fetch MCP, Playwright MCP as fallback)."""
    from concurrent.futures import ThreadPoolExecutor

    todo = [r for r in results
            if r.get("source_type") == "web" and len(r.get("content", "")) < ENRICH_BELOW_CHARS
            and not r.get("fetched")][:MAX_PAGE_FETCHES_PER_ROUND]
    if not todo:
        return
    with ThreadPoolExecutor(max_workers=3) as pool:
        for r, page in zip(todo, pool.map(lambda r: fetch_page(r["url"]), todo)):
            if page:
                r["content"], r["fetched"] = page["text"], page["method"]


def search_node(state: ResearchState) -> dict:
    """Step 2: run the planned searches (web, Wikipedia, academic papers) and read thin pages."""
    if state.get("error"):
        return {}

    all_results = list(state.get("search_results", []))
    failed = list(state.get("failed_queries", []))
    searched = list(state.get("searched_queries", []))
    queries = state.get("search_queries", [])
    new_results: list[dict] = []

    for query in queries:
        norm = normalize_query(query)
        if norm in searched:                       # never repeat a search
            continue
        searched.append(norm)
        # Every tool below never raises; an empty list means "nothing found / tool unavailable".
        results = search_web(query) + search_wikipedia(query, max_results=1)
        if not results:
            failed.append(query)                   # remember it for the UI
        for r in results:
            r["query"] = query                     # remember which query found this
        new_results.extend(results)

    # One academic search per round: the research question first, follow-up topic later.
    if queries:
        academic_query = (state["plan"].get("research_question") if state.get("search_round", 1) <= 1
                          else queries[0]) or queries[0]
        if normalize_query("academic:" + academic_query) not in searched:
            searched.append(normalize_query("academic:" + academic_query))
            for r in search_papers(academic_query):
                r["query"] = academic_query
                new_results.append(r)

    # De-duplicate by URL / DOI so the same page or paper is never processed twice.
    seen_urls = {normalize_url(r["url"]) for r in all_results}
    seen_dois = {r["doi"] for r in all_results if r.get("doi")}
    fresh = []
    for r in new_results:
        key = normalize_url(r["url"])
        if not r["url"] or key in seen_urls or (r.get("doi") and r["doi"] in seen_dois):
            continue
        seen_urls.add(key)
        if r.get("doi"):
            seen_dois.add(r["doi"])
        fresh.append(r)

    _enrich_with_full_pages(fresh)
    all_results.extend(fresh)
    return {"search_results": all_results, "failed_queries": failed, "searched_queries": searched}


def extract_node(state: ResearchState) -> dict:
    """Step 3: extract facts from results we haven't processed yet."""
    if state.get("error"):
        return {}

    topic = state["topic"]
    processed = set(state.get("processed_urls", []))
    findings = list(state.get("findings", []))
    seen_texts = {f["finding"].lower() for f in findings}

    # Group only NEW results by the query that found them.
    by_query = {}
    for r in state.get("search_results", []):
        if r["url"] not in processed:
            by_query.setdefault(r.get("query", ""), []).append(r)

    for query, results in by_query.items():
        for f in extract_findings(query, results, topic):
            if f["finding"].lower() not in seen_texts:   # skip duplicate facts
                findings.append(f)
                seen_texts.add(f["finding"].lower())
        processed.update(r["url"] for r in results)

    return {"findings": findings, "processed_urls": list(processed)}


def evaluate_node(state: ResearchState) -> dict:
    if state.get("error"):
        return {}

    findings = state.get("findings", [])
    sources = {f["source_url"] for f in findings}

    current_round = state.get("search_round", 1)
    searched = set(state.get("searched_queries", []))

    sufficient = len(findings) >= 8 and len(sources) >= 3

    check = check_sufficiency(state["plan"], findings)

    if sufficient and check["enough_information"]:
        return {"search_queries": []}

    if current_round >= MAX_SEARCH_ROUNDS:
        return {"search_queries": []}

    queries = check["follow_up_queries"]

    if not sufficient or not queries:
        topic = state["topic"]
        queries = queries + [
            f"{topic} statistics research data",
            f"{topic} recent trends challenges evidence",
        ]

    queries = [
        q for q in queries
        if normalize_query(q) not in searched
    ]

    return {
        "search_queries": queries[:3],
        "search_round": current_round + 1,
    }


def visualize_node(state: ResearchState) -> dict:
    """Step 5: the agent decides which charts / diagram to draw (never fatal)."""
    if state.get("error"):
        return {}
    try:
        visuals = build_visuals(state["topic"], state.get("plan", {}), state.get("findings", []))
    except Exception as exc:
        print(f"[graph] Visualization skipped: {exc}")
        visuals = []
    return {"visuals": visuals}


def report_node(state: ResearchState) -> dict:
    """Step 6: generate the final structured report."""
    if state.get("error"):
        return {}
    try:
        report = generate_report(
            state["topic"],
            state["plan"],
            state.get("findings", []),
            state.get("search_results", []),
        )
        # Attach everything the web page and the PDF need.
        report["visuals"] = state.get("visuals", [])
        report["meta"] = {
            "topic": state["topic"],
            "research_question": state["plan"].get("research_question", ""),
            "num_sources": len(report.get("references", [])),
            "num_findings": len(state.get("findings", [])),
            "citation_stats": report.get("citation_stats", {}),
            "search_rounds": state.get("search_round", 1),
            "generated_at": datetime.now().strftime("%d %B %Y, %H:%M"),
        }
        return {"report": report}
    except Exception as exc:
        return {"error": f"Report generation failed: {exc}"}


# ------------------------- routing -------------------------

def route_after_evaluate(state: ResearchState) -> str:
    """Decide: search again, or start writing?"""
    if state.get("error"):
        return END
    if state.get("search_queries"):
        return "search"          # loop back for one more round
    return "visualize"


def build_graph():
    """Build and compile the agent's workflow graph."""
    builder = StateGraph(ResearchState)

    builder.add_node("plan", plan_node)
    builder.add_node("search", search_node)
    builder.add_node("extract", extract_node)
    builder.add_node("evaluate", evaluate_node)
    builder.add_node("visualize", visualize_node)
    builder.add_node("report", report_node)

    builder.add_edge(START, "plan")
    builder.add_edge("plan", "search")
    builder.add_edge("search", "extract")
    builder.add_edge("extract", "evaluate")
    builder.add_conditional_edges(
        "evaluate",
        route_after_evaluate,
        {"search": "search", "visualize": "visualize", END: END},
    )
    builder.add_edge("visualize", "report")
    builder.add_edge("report", END)

    return builder.compile()
