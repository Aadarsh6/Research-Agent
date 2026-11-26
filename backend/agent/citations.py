"""
Claim-level citations - enforced in CODE, not trusted to the LLM.

The LLM sees facts as  "[n] fact text"  where n identifies a real retrieved source, and must end
every statement with the matching marker(s), e.g. "Adaptive tools personalise pace [2][5]."

This module then checks every statement:
  1. markers must point to a source that was really given to the model  (invalid ones are removed)
  2. a statement without any valid marker is DROPPED
  3. a statement containing a number (2+ digits) that does not appear in the cited source's
     facts / title is DROPPED (catches invented statistics)
Finally the surviving markers are renumbered 1..k in order of first use, and the reference list
is rebuilt from exactly the sources that are cited - so the report can never cite something
that was not retrieved, and never lists something it does not cite.
"""

import re

MARK = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_TRAIL = re.compile(r"([.!?])\s*((?:\[\d+(?:\s*,\s*\d+)*\]\s*)+)")      # "claim. [1]" -> "claim [1]."
_ABBREV = re.compile(r"(?:e\.g|i\.e|vs|etc|Dr|Mr|Ms|U\.S|al|Fig|No|approx)\.$")
_NUM = re.compile(r"\d[\d,]*\.?\d*")


def numbers_in(text: str) -> set[float]:
    found = set()
    for m in _NUM.findall(MARK.sub(" ", text)):
        try:
            found.add(round(float(m.replace(",", "").rstrip(".")), 4))
        except ValueError:
            pass
    return found


def _marks(text: str) -> list[int]:
    return [int(n) for group in MARK.findall(text) for n in re.split(r"\s*,\s*", group)]


def _sentences(paragraph: str) -> list[str]:
    paragraph = re.sub(r"[ \t]+", " ", _TRAIL.sub(lambda m: f" {m.group(2).strip()}{m.group(1)} ", paragraph)).strip()
    pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", paragraph)
    merged: list[str] = []
    for piece in pieces:
        if merged and _ABBREV.search(merged[-1]):
            merged[-1] += " " + piece
        else:
            merged.append(piece)
    return [s for s in merged if s.strip()]


def _check(sentence: str, allowed_numbers: dict[int, set[float]]) -> str | None:
    """Return the cleaned sentence, or None if it is not properly supported."""
    marks = [n for n in _marks(sentence) if n in allowed_numbers]
    if not marks:
        return None
    support = set().union(*(allowed_numbers[n] for n in marks))
    for value in numbers_in(sentence):
        if len(f"{value:g}".replace(".", "")) >= 2 and value not in support:
            return None

    def keep_valid(m):
        nums = [int(x) for x in re.split(r"\s*,\s*", m.group(1)) if int(x) in allowed_numbers]
        return f"[{', '.join(map(str, nums))}]" if nums else ""

    cleaned = MARK.sub(keep_valid, sentence)
    return re.sub(r"\s+([.!?,;])", r"\1", re.sub(r"[ \t]{2,}", " ", cleaned)).strip()


def validate_text(text: str, allowed_numbers: dict[int, set[float]], stats: dict) -> str:
    """Keep only supported statements; paragraphs (blank-line separated) are preserved."""
    paragraphs = []
    for para in re.split(r"\n\s*\n", str(text or "")):
        kept = []
        for sentence in _sentences(para):
            ok = _check(sentence, allowed_numbers)
            stats["kept" if ok else "removed"] += 1
            if ok:
                kept.append(ok)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs)


def _renumber(text: str, mapping: dict[int, int]) -> str:
    def fix(m):
        nums = sorted({mapping[int(x)] for x in re.split(r"\s*,\s*", m.group(1)) if int(x) in mapping})
        return f"[{', '.join(map(str, nums))}]" if nums else ""
    return MARK.sub(fix, text)


# Order = the order a reader meets the sections, which decides the final numbering.
PROSE = ("executive_summary", "detailed_analysis", "conclusion")
LISTS = ("key_findings", "advantages", "challenges")


def apply_citations(report: dict, facts: list[tuple[int, str]], refs: dict[int, dict]) -> dict:
    """
    report : dict from the LLM (text still contains [n] markers)
    facts  : [(ref_number, fact_text)] that were shown to the LLM
    refs   : {ref_number: reference metadata}
    Returns the report with validated text, renumbered markers, `references` and `meta` stats.
    """
    allowed: dict[int, set[float]] = {}
    for n, text in facts:
        allowed.setdefault(n, set()).update(numbers_in(text))
    for n, ref in refs.items():  # title / publication date numbers are legitimate too
        allowed.setdefault(n, set()).update(numbers_in(f"{ref.get('title', '')} {ref.get('published', '')}"))

    stats = {"kept": 0, "removed": 0}

    # Introduction is framing: invalid markers are stripped but uncited sentences stay.
    intro = report.get("introduction", "")
    report["introduction"] = _renumber_valid_only(intro, allowed)

    for key in PROSE:
        report[key] = validate_text(report.get(key, ""), allowed, stats)
    for key in LISTS:
        items = [validate_text(i, allowed, stats) for i in report.get(key, [])]
        report[key] = [i for i in items if i]

    # Safety net: if the model produced no usable findings, build them straight from the facts.
    if not report["key_findings"]:
        seen, fallback = set(), []
        for n, text in facts:
            if text not in seen and n in allowed:
                seen.add(text)
                fallback.append(f"{text.rstrip('.')} [{n}].")
            if len(fallback) == 6:
                break
        report["key_findings"] = fallback

    # Renumber in reading order and keep only the sources that are actually cited.
    order: list[int] = []
    for key in ("executive_summary", "introduction", "key_findings", "detailed_analysis",
                "advantages", "challenges", "conclusion"):
        value = report[key]
        for text in (value if isinstance(value, list) else [value]):
            for n in _marks(text):
                if n in refs and n not in order:
                    order.append(n)
    mapping = {old: new for new, old in enumerate(order, start=1)}

    for key in ("executive_summary", "introduction", "detailed_analysis", "conclusion"):
        report[key] = _renumber(report[key], mapping)
    for key in LISTS:
        report[key] = [_renumber(i, mapping) for i in report[key]]

    report["references"] = [dict(refs[old], n=new) for old, new in mapping.items()]
    report["citation_stats"] = {"statements_cited": stats["kept"], "statements_removed": stats["removed"]}
    return report


def _renumber_valid_only(text: str, allowed: dict) -> str:
    def fix(m):
        nums = [x for x in re.split(r"\s*,\s*", m.group(1)) if int(x) in allowed]
        return f"[{', '.join(nums)}]" if nums else ""
    return MARK.sub(fix, str(text or ""))
