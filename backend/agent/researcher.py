"""
The researcher — the most "agentic" module.

It contains three abilities:

  1. decide_search_queries() - the agent decides WHICH searches to run
     based on its plan (not a fixed number of searches).
  2. extract_findings()      - pulls facts out of search results and tags
     every fact with the exact result it came from.
  3. check_sufficiency()     - the agent looks at its own notes and decides
     whether it has enough information or should search again.
"""

from pydantic import BaseModel, Field

from agent.llm import get_llm, get_structured_llm


# ---------- LLM output structures (enforced by LangChain) ----------

class SearchQueries(BaseModel):
    queries: list[str] = Field(description="Search engine queries to run")


class Finding(BaseModel):
    text: str = Field(description="One factual finding, one or two sentences")
    result_number: int = Field(description="The [number] of the search result the fact came from")


class ExtractedFindings(BaseModel):
    findings: list[Finding]


class SufficiencyCheck(BaseModel):
    enough_information: bool = Field(description="True if the notes cover all sub-questions")
    follow_up_queries: list[str] = Field(description="New queries for missing info (empty if enough)")


# ---------- Prompts ----------

QUERY_PLANNER_PROMPT = """You are planning web searches for a research task.

Main research question: {question}
Sub-questions to investigate:
{sub_questions}

Write 3 to 5 short, effective search queries (the kind you would type into
a search engine) that together cover the sub-questions."""

EXTRACTION_PROMPT = """You are a careful research assistant.

A web search was run for the query: "{query}"
Research topic: "{topic}"

Below are the search results. Extract factual statements useful for the topic.

Rules:
- Use ONLY facts that appear in the results. Never invent anything.
- For each fact, set result_number to the [number] of the result it came from.
- Ignore ads, menus, and irrelevant results.
- At most 5 relevant facts per search result.
- Prioritize statistics, percentages and measurable outcomes.
- Preserve exact numbers, units, years and context.
- Avoid generic statements and duplicate information.
- Never invent statistics when none are available.

Search results:
{results}"""

SUFFICIENCY_PROMPT = """You are evaluating research progress for a research agent.

Main research question: {question}
Sub-questions:
{sub_questions}

Facts collected so far:
{notes}

Decide whether these facts are enough to answer every sub-question.
- If yes: set enough_information to true and return an empty list.
- If a whole sub-question has no relevant facts: return up to 3 new search
  queries targeting exactly the missing information.
  
  Prioritize queries that retrieve:
- Quantitative statistics and measurable outcomes.
- Recent government reports and official datasets.
- Peer-reviewed research and authoritative sources.

Include at least one query specifically targeting
numerical data relevant to the research topic.
Avoid overly broad or generic searches.

  """


# ---------- Agent abilities ----------

def decide_search_queries(plan: dict, max_queries: int = 3) -> list[str]:
    """The agent decides what searches it needs based on its plan."""
    llm = get_llm()
    chain = get_structured_llm(SearchQueries)

    sub_questions = "\n".join(f"- {q}" for q in plan["sub_questions"])
    result = chain.invoke(QUERY_PLANNER_PROMPT.format(
        question=plan["research_question"],
        sub_questions=sub_questions,
    ))

    # Clean up: strip whitespace, drop empties, cap the count.
    queries = [q.strip() for q in result.queries if q.strip()]
    return queries[:max_queries]


def extract_findings(query: str, results: list[dict], topic: str) -> list[dict]:
    """Extract facts from the search results of ONE query."""
    if not results:
        return []

    llm = get_llm()
    chain = get_structured_llm(ExtractedFindings)

    # Number each result so the LLM can reference them safely.
    blocks = []
    for i, r in enumerate(results, start=1):
        blocks.append(
            f"[{i}] Title: {r['title']}\nURL: {r['url']}\nContent: {r['content'][:3000]}"
        )
    results_text = "\n\n".join(blocks)

    try:
        extracted = chain.invoke(EXTRACTION_PROMPT.format(
            query=query, topic=topic, results=results_text
        ))
    except Exception as exc:
        print(f"[researcher] Extraction failed for '{query}': {exc}")
        return []

    # Map result numbers back to URLs OURSELVES. The LLM never writes a URL,
    # so a hallucinated citation is impossible.
    number_to_url = {i: r["url"] for i, r in enumerate(results, start=1)}

    findings = []
    for f in extracted.findings:
        url = number_to_url.get(f.result_number)
        if url and f.text.strip():
            findings.append({"finding": f.text.strip(), "source_url": url})
    return findings


def check_sufficiency(plan: dict, findings: list[dict]) -> dict:
    """The agent decides whether the collected notes are enough."""
    if not findings:
        # Nothing collected: definitely not enough, ask the LLM for follow-ups.
        enough = False
    else:
        enough = None  # will be decided by the LLM below

    llm = get_llm()
    chain = get_structured_llm(ExtractedFindings)

    notes = "\n".join(f"- {f['finding']}" for f in findings) or "(no findings yet)"
    sub_questions = "\n".join(f"- {q}" for q in plan["sub_questions"])

    try:
        check = chain.invoke(SUFFICIENCY_PROMPT.format(
            question=plan["research_question"],
            sub_questions=sub_questions,
            notes=notes,
        ))
        return {
            "enough_information": check.enough_information if enough is None else enough,
            "follow_up_queries": [q.strip() for q in check.follow_up_queries if q.strip()][:3],
        }
    except Exception as exc:
        print(f"[researcher] Sufficiency check failed: {exc}")
        # If the check itself fails, assume we have enough and move on.
        return {"enough_information": True, "follow_up_queries": []}
