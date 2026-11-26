"""One place that formats a reference's metadata (used by the PDF and the Markdown export)."""


def format_authors(authors: list[str]) -> str:
    authors = [a for a in (authors or []) if a]
    if not authors:
        return ""
    return ", ".join(authors) if len(authors) <= 3 else f"{', '.join(authors[:3])} et al."


def format_reference(ref: dict) -> str:
    """'Authors (date). Title. Venue. DOI: x. Accessed d.'  - only parts that really exist are shown."""
    parts = []
    authors = format_authors(ref.get("authors", []))
    date = ref.get("published") or "n.d."
    parts.append(f"{authors} ({date})." if authors else f"({date}).")
    parts.append(f"{ref.get('title', 'Untitled').rstrip('.')}.")
    if ref.get("venue"):
        parts.append(f"{ref['venue'].rstrip('.')}.")
    if ref.get("doi"):
        parts.append(f"DOI: {ref['doi']}.")
    if ref.get("accessed"):
        parts.append(f"Accessed {ref['accessed']}.")
    return " ".join(parts)
