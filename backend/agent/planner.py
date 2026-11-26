"""
Step 1 — Research Planner.

Turns the user's topic into one clear research question plus 3-5 sub-questions.
"""

from pydantic import BaseModel, Field

from agent.llm import get_llm, get_structured_llm


class ResearchPlan(BaseModel):
    research_question: str = Field(description="One clear main research question")
    sub_questions: list[str] = Field(description="3 to 5 smaller research points")


PLANNER_PROMPT = """You are a research planner.

Research topic: "{topic}"

1. Rewrite the topic as ONE clear main research question.
2. Break it into 3 to 5 specific sub-questions that together cover the topic
   (e.g. current state, benefits, challenges, future outlook)."""


def create_research_plan(topic: str) -> ResearchPlan:
    """Ask the LLM for a structured research plan."""
    chain = get_structured_llm(ResearchPlan)
    plan = chain.invoke(PLANNER_PROMPT.format(topic=topic))
    # Safety: keep between 3 and 5 clean sub-questions.
    plan.sub_questions = [q.strip() for q in plan.sub_questions if q.strip()][:5]
    if not plan.sub_questions:
        plan.sub_questions = [plan.research_question or topic]
    return plan
