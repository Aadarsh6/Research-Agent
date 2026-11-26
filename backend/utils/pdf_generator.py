"""
Builds the final research report as a formatted PDF (reportlab).

Layout: title block, summary box, numbered sections, figures with captions,
numbered references with clickable links, and a footer with page numbers.
"""

import base64
import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from utils.references import format_reference
from reportlab.platypus import (HRFlowable, Image, KeepTogether, ListFlowable, ListItem,
                                Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

NAVY = colors.HexColor("#1e3a5f")
GREY = colors.HexColor("#475569")
LIGHT = colors.HexColor("#f1f5f9")
LINK = "#1d4ed8"


def _clean(text) -> str:
    """Escape for reportlab markup and drop characters the base font can't draw."""
    text = str(text or "")
    text = text.encode("cp1252", "replace").decode("cp1252")
    return escape(text)


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontName="Helvetica-Bold",
                                fontSize=22, leading=27, textColor=NAVY, alignment=0, spaceAfter=6),
        "meta": ParagraphStyle("m", parent=base["Normal"], fontSize=9, textColor=GREY, leading=13),
        "h1": ParagraphStyle("h1", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=14, leading=18, textColor=NAVY, spaceBefore=14, spaceAfter=6,
                             keepWithNext=1),
        "body": ParagraphStyle("b", parent=base["Normal"], fontName="Helvetica", fontSize=10.5,
                               leading=15.5, alignment=TA_JUSTIFY, spaceAfter=6),
        "bullet": ParagraphStyle("bl", parent=base["Normal"], fontSize=10.5, leading=15, spaceAfter=3),
        "caption": ParagraphStyle("c", parent=base["Normal"], fontName="Helvetica-Oblique",
                                  fontSize=9, leading=12, textColor=GREY, alignment=1, spaceAfter=10),
        "ref": ParagraphStyle("r", parent=base["Normal"], fontSize=9, leading=12.5,
                              leftIndent=18, firstLineIndent=-18, spaceAfter=4),
    }


def _paragraphs(text: str, style) -> list:
    """Split text on blank lines so long analysis becomes real paragraphs."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", str(text or "")) if p.strip()]
    return [Paragraph(_clean(p).replace("\n", " "), style) for p in parts] or [Paragraph("-", style)]


def _bullets(items: list, style) -> list:
    items = [i for i in (items or []) if str(i).strip()]
    if not items:
        return [Paragraph("No items available.", style)]
    return [ListFlowable([ListItem(Paragraph(_clean(i), style), leftIndent=14) for i in items],
                         bulletType="bullet", start="\u2022", leftIndent=14, bulletFontSize=9)]


def _image(data_uri: str, max_w: float = 15.5 * cm):
    raw = base64.b64decode(data_uri.split(",", 1)[1])
    w, h = ImageReader(io.BytesIO(raw)).getSize()
    scale = max_w / w
    return Image(io.BytesIO(raw), width=w * scale, height=h * scale)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#cbd5e1"))
    canvas.line(2 * cm, 1.6 * cm, A4[0] - 2 * cm, 1.6 * cm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.1 * cm, "AI Research Agent")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def generate_pdf(report: dict) -> bytes:
    """Return the report as PDF bytes."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=2 * cm, bottomMargin=2.2 * cm,
                            title=report.get("title", "Research Report"),
                            author="AI Research Agent")
    meta = report.get("meta", {})
    story = []

    # ---- title block ----
    story.append(Paragraph(_clean(report.get("title", "Research Report")), st["title"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=8))
    info = [
        ["Research question", Paragraph(_clean(meta.get("research_question", "-")), st["meta"])],
        ["Generated", Paragraph(_clean(meta.get("generated_at", "-")), st["meta"])],
        ["Evidence", Paragraph(_clean(f"{meta.get('num_findings', 0)} facts from "
                                      f"{meta.get('num_sources', 0)} sources"), st["meta"])],
    ]
    table = Table(info, colWidths=[3.6 * cm, 13.4 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (0, -1), 9), ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [table, Spacer(1, 6)]

    n = 0

    def section(title):
        nonlocal n
        n += 1
        story.append(Paragraph(f"{n}. {_clean(title)}", st["h1"]))

    # ---- sections ----
    if report.get("executive_summary"):
        section("Executive Summary")
        story += _paragraphs(report["executive_summary"], st["body"])

    section("Introduction")
    story += _paragraphs(report.get("introduction"), st["body"])

    section("Research Questions")
    story += _bullets(report.get("research_questions"), st["bullet"])

    section("Key Findings")
    story += _bullets(report.get("key_findings"), st["bullet"])

    visuals = report.get("visuals") or []
    if visuals:
        section("Data & Diagrams")
        for i, v in enumerate(visuals, start=1):
            try:
                story.append(KeepTogether([
                    _image(v["image"]),
                    Paragraph(_clean(f"Figure {i}: {v.get('title', '')}. {v.get('caption', '')}"),
                              st["caption"]),
                ]))
            except Exception as exc:
                print(f"[pdf] Skipped a figure: {exc}")

    section("Detailed Analysis")
    story += _paragraphs(report.get("detailed_analysis"), st["body"])

    section("Advantages & Opportunities")
    story += _bullets(report.get("advantages"), st["bullet"])

    section("Challenges & Limitations")
    story += _bullets(report.get("challenges"), st["bullet"])

    section("Conclusion")
    story += _paragraphs(report.get("conclusion"), st["body"])

    section("References")
    refs = report.get("references") or []
    if not refs:
        story.append(Paragraph("No sources were available for this report.", st["body"]))
    for i, ref in enumerate(refs, start=1):
        url = ref.get("doi") and f"https://doi.org/{ref['doi']}" or ref.get("url", "")
        story.append(Paragraph(
            f"[{i}] {_clean(format_reference(ref))}<br/>"
            f"<link href=\"{escape(url, {chr(34): '&quot;'})}\" color=\"{LINK}\">{_clean(url)}</link>",
            st["ref"]))

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()
