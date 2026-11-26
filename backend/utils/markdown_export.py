"""Plain Markdown version of a report (saved to research/reports/ through the Filesystem MCP)."""

from utils.references import format_reference


def _bullets(items) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "_No items._"


def report_to_markdown(report: dict) -> str:
    meta = report.get("meta", {})
    out = [f"# {report.get('title', 'Research Report')}", ""]
    if meta:
        out += [f"*Generated {meta.get('generated_at', '')} - {meta.get('num_findings', 0)} facts, "
                f"{meta.get('num_sources', 0)} sources*", ""]
        if meta.get("research_question"):
            out += [f"**Research question:** {meta['research_question']}", ""]
    sections = [
        ("Executive Summary", report.get("executive_summary")),
        ("Introduction", report.get("introduction")),
        ("Research Questions", _bullets(report.get("research_questions"))),
        ("Key Findings", _bullets(report.get("key_findings"))),
    ]
    visuals = report.get("visuals") or []
    if visuals:
        sections.append(("Figures", "\n".join(f"- Figure {i}: {v['title']}. {v['caption']}"
                                              for i, v in enumerate(visuals, 1))))
    sections += [
        ("Detailed Analysis", report.get("detailed_analysis")),
        ("Advantages & Opportunities", _bullets(report.get("advantages"))),
        ("Challenges & Limitations", _bullets(report.get("challenges"))),
        ("Conclusion", report.get("conclusion")),
    ]
    n = 0
    for title, body in sections:
        if body:
            n += 1
            out += [f"## {n}. {title}", "", str(body), ""]
    refs = report.get("references") or []
    out += [f"## {n + 1}. References", ""]
    for i, ref in enumerate(refs, 1):
        link = f"https://doi.org/{ref['doi']}" if ref.get("doi") else ref.get("url", "")
        out.append(f"[{i}] {format_reference(ref)} <{link}>")
    return "\n".join(out) + "\n"
