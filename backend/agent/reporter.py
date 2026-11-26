"""
Final report generation with claim-level citations.

Sources get numbers [1], [2]... in order of first use. The LLM writes statements ending in those
markers; agent/citations.py then verifies every statement and rebuilds the reference list from
real retrieved sources only (title, authors, date, DOI and URL come from the tools, never the LLM).
"""

from datetime import date

from pydantic import BaseModel, Field, field_validator

from agent.citations import apply_citations
from agent.llm import get_llm, get_structured_llm

MAX_FACTS_IN_PROMPT = 20  # safety cap so the prompt never gets too long


class ResearchReport(BaseModel):
    """The final report structure."""

    title: str
    executive_summary: str = Field(
        description="A single string paragraph of 3-4 cited sentences, not a list"
    )
    introduction: str = Field(
        description="Short framing paragraph, no statistics"
    )
    research_questions: list[str]
    key_findings: list[str]
    detailed_analysis: str
    advantages: list[str]
    challenges: list[str]
    conclusion: str

    @field_validator(
        "executive_summary",
        "introduction",
        "detailed_analysis",
        "conclusion",
        mode="before"
    )
    @classmethod
    def normalize_text(cls, value):
        if isinstance(value, list) and all(
            isinstance(item, str) for item in value
        ):
            return " ".join(item.strip() for item in value if item.strip())
        return value


REPORT_PROMPT = """You are writing the final report of an AI research agent.

Research topic: "{topic}"
Main research question: {question}
Sub-questions:
{sub_questions}

SOURCES (the number identifies the source):
{sources}

FACTS - the ONLY information you may use. The number in brackets is the source of each fact:
{findings}

Write the report. Strict rules:
1. Use ONLY the facts above. No outside knowledge, no guessing.
2. CITATIONS: every statement (every sentence in the executive summary, key findings, analysis,
   advantages, challenges and conclusion) must end with the number(s) of the supporting
   source(s) in square brackets before the full stop, copied from the facts, e.g.
   "Adaptive tools let students learn at their own pace [2]." or "... reduces workload [1][4]."
   A statement that no fact supports must NOT be written.
3. Never invent numbers, dates, names or sources. Copy figures exactly as written in the facts.
4. If information is limited, say so honestly (and cite what you do have).
5. Do not write URLs. The reference list is added by the system.
6. executive_summary, introduction, detailed_analysis and conclusion MUST be strings, not arrays or lists.
7. research_questions, key_findings, advantages and challenges MUST be arrays of strings.

OUTPUT LENGTH:
- Keep the entire report within 500 words.
- Executive summary: maximum 3 sentences.
- Introduction: maximum 2 sentences.
- Key findings: maximum 6 items.
- Detailed analysis: maximum 3 concise paragraphs.
- Advantages: maximum 4 items.
- Challenges: maximum 4 items.
- Conclusion: maximum 3 sentences.
- Avoid repeating the same facts across sections.
- Return a complete and valid JSON document.

"""


def _build_tables(findings: list[dict], sources: list[dict]):
    """Number the sources in order of first use and collect their real metadata."""
    by_url = {s["url"]: s for s in sources if s.get("url")}
    number_of: dict[str, int] = {}
    facts: list[tuple[int, str]] = []
    refs: dict[int, dict] = {}
    today = date.today().strftime("%d %b %Y")

    for f in findings[:MAX_FACTS_IN_PROMPT]:
        url = f["source_url"]
        src = by_url.get(url)
        if src is None:                       # a fact must trace back to a retrieved source
            continue
        if url not in number_of:
            n = number_of[url] = len(number_of) + 1
            refs[n] = {
                "title": src.get("title") or "Untitled", "url": url,
                "authors": src.get("authors", []), "published": src.get("published", ""),
                "doi": src.get("doi", ""), "venue": src.get("venue", ""),
                "source_type": src.get("source_type", "web"), "accessed": today,
            }
        facts.append((number_of[url], f["finding"]))
    return facts, refs


def generate_report(topic: str, plan: dict, findings: list[dict], sources: list[dict]) -> dict:
    """Produce the final structured, citation-checked report as a dict."""
    facts, refs = _build_tables(findings, sources)

    # Graceful handling when nothing was retrieved.
    if not facts:
        return {
            "title": f"Research Report: {topic}",
            "executive_summary": "",
            "introduction": (
                "This report could not be completed because the agent was unable to collect "
                "information from the web. The search services may have been unreachable, or "
                "no results were found."
            ),
            "research_questions": plan.get("sub_questions", []),
            "key_findings": [], "detailed_analysis": "", "advantages": [], "challenges": [],
            "conclusion": "Please check your internet connection and try again.",
            "references": [], "citation_stats": {"statements_cited": 0, "statements_removed": 0},
        }

    prompt = REPORT_PROMPT.format(
        topic=topic,
        question=plan.get("research_question", topic),
        sub_questions="\n".join(f"- {q}" for q in plan.get("sub_questions", [])),
        sources="\n".join(
            f"[{n}] {r['title']} ({r['published'] or 'n.d.'}, {r['source_type']})" for n, r in refs.items()),
        findings="\n".join(f"[{n}] {text}" for n, text in facts),
    )
    report = get_structured_llm(
    ResearchReport,
    max_tokens=3000
).invoke(prompt).model_dump()
    return apply_citations(report, facts, refs)
