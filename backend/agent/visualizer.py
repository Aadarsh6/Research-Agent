"""
Visual planner - the agent decides which charts / diagram the report needs.

The LLM only proposes *specs* (labels, numbers, node names). The drawing is
done by tools/chart_tool.py. To avoid invented statistics, every chart value
must actually appear as a number in the collected facts; charts that fail this
check are dropped. If no data chart survives, the agent falls back to a chart
built from its own research data (facts per source).
"""

from urllib.parse import urlparse

from pydantic import BaseModel, Field

from agent.citations import numbers_in
from agent.llm import get_llm, get_structured_llm
from tools.chart_tool import render_chart, render_diagram, to_data_uri

MAX_FACTS_IN_PROMPT = 40


class ChartSpec(BaseModel):
    chart_type: str = Field(description="One of: bar, line, pie")
    title: str
    x_label: str = Field(default="", description="X axis label (empty for pie)")
    y_label: str = Field(default="", description="Y axis label with unit (empty for pie)")
    labels: list[str] = Field(description="Category / time labels, 3 to 8 items")
    values: list[float] = Field(description="Numbers copied from the facts, same length as labels")
    caption: str = Field(description="One sentence explaining what the chart shows")


class DiagramSpec(BaseModel):
    kind: str = Field(description="'flow' for a process / sequence, 'concept_map' for a topic with related parts")
    title: str
    nodes: list[str] = Field(description="3 to 7 SHORT labels (max 4 words each). For concept_map the first is the central idea.")
    caption: str = Field(description="One sentence explaining the diagram")


class VisualPlan(BaseModel):
    charts: list[ChartSpec] = Field(description="0 to 2 charts. Empty list if the facts contain no usable numbers.")
    diagram: list[DiagramSpec] = Field(description="Exactly 1 diagram (list with one item)")


VISUAL_PROMPT = """You are designing figures for a research report.

Topic: "{topic}"

Facts collected from the web (the ONLY data you may use):
{findings}

Create:
1. Up to 2 charts, ONLY from numbers that are explicitly written in the facts
   (statistics, percentages, years with values, market sizes...). Copy the
   numbers exactly. Never estimate or invent a number. Compare values of the
   same unit only. If the facts have no usable numbers, return an empty charts list.
2. Exactly 1 diagram that explains the topic: a 'flow' (steps of a process) or
   a 'concept_map' (central idea with 4-6 related parts). Labels must be short.
"""


# ------------------------------------------------------------------ helpers

def _chart_is_grounded(spec: ChartSpec, known: set[float]) -> bool:
    """At least 2/3 of the chart values must appear as numbers in the facts."""
    values = [round(v, 4) for v in spec.values]
    hits = sum(1 for v in values if v in known)
    return len(values) >= 2 and hits / len(values) >= 2 / 3


def _facts_text(findings: list[dict]) -> str:
    return "\n".join(f"- {f['finding']}" for f in findings[:MAX_FACTS_IN_PROMPT]) or "(none)"


def _short(text: str, n: int = 38) -> str:
    text = text.strip().rstrip("?.")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _source_fallback_chart(findings: list[dict]) -> dict | None:
    """Chart built from the agent's own data: number of facts per website."""
    counts: dict[str, int] = {}
    for f in findings:
        host = urlparse(f["source_url"]).netloc.replace("www.", "") or "unknown"
        counts[host] = counts.get(host, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:6]
    if len(top) < 2:
        return None
    title = "Evidence collected per source"
    png = render_chart("bar", title, [t[0] for t in top], [float(t[1]) for t in top],
                       "Source website", "Facts extracted")
    return {
        "type": "chart",
        "title": title,
        "caption": "Number of facts the agent extracted from each of the most-used sources.",
        "image": to_data_uri(png),
    }


# ------------------------------------------------------------------- main

def build_visuals(topic: str, plan: dict, findings: list[dict]) -> list[dict]:
    """Return a list of figures: [{type, title, caption, image(data URI)}]."""
    visuals: list[dict] = []
    if not findings:
        return visuals

    specs = None
    try:
        chain = get_structured_llm(VisualPlan)
        specs = chain.invoke(VISUAL_PROMPT.format(topic=topic, findings=_facts_text(findings)))
    except Exception as exc:
        print(f"[visualizer] Visual planning failed: {exc}")

    # ---- data charts (validated) ----
    if specs:
        known = numbers_in(" ".join(f["finding"] for f in findings))
        for spec in specs.charts[:2]:
            try:
                ctype = spec.chart_type.lower().strip()
                if ctype not in ("bar", "line", "pie"):
                    ctype = "bar"
                if not _chart_is_grounded(spec, known):
                    print(f"[visualizer] Dropped ungrounded chart: {spec.title}")
                    continue
                png = render_chart(ctype, spec.title, spec.labels, spec.values,
                                   spec.x_label, spec.y_label)
                visuals.append({"type": "chart", "title": spec.title,
                                "caption": spec.caption, "image": to_data_uri(png)})
            except Exception as exc:
                print(f"[visualizer] Chart failed: {exc}")

    if not visuals:
        try:
            fb = _source_fallback_chart(findings)
            if fb:
                visuals.append(fb)
        except Exception as exc:
            print(f"[visualizer] Fallback chart failed: {exc}")

    # ---- diagram ----
    try:
        if specs and specs.diagram:
            d = specs.diagram[0]
            kind = d.kind if d.kind in ("flow", "concept_map") else "concept_map"
            png = render_diagram(kind, d.title, d.nodes)
            visuals.append({"type": "diagram", "title": d.title,
                            "caption": d.caption, "image": to_data_uri(png)})
    except Exception as exc:
        print(f"[visualizer] Diagram failed: {exc}")

    if not any(v["type"] == "diagram" for v in visuals):
        try:  # fallback diagram straight from the plan
            nodes = [_short(topic, 30)] + [_short(q) for q in plan.get("sub_questions", [])[:5]]
            if len(nodes) >= 3:
                png = render_diagram("concept_map", "Research structure", nodes)
                visuals.append({"type": "diagram", "title": "Research structure",
                                "caption": "The main topic and the sub-questions the agent investigated.",
                                "image": to_data_uri(png)})
        except Exception as exc:
            print(f"[visualizer] Fallback diagram failed: {exc}")

    return visuals
