from __future__ import annotations

_OFFICE_SYNONYM_MAP = {
    "예산": ("예산안",),
    "예산안": ("예산",),
    "품의": ("기안",),
    "기안": ("품의",),
    "품의서": ("기안서",),
    "기안서": ("품의서",),
    "휴가": ("연차",),
    "연차": ("휴가",),
}


def expand_search_terms(terms: list[str]) -> list[str]:
    """Add conservative office-document synonyms while preserving order."""
    expanded: list[str] = []
    seen: set[str] = set()
    for term in terms:
        norm = term.strip()
        if not norm:
            continue
        if norm not in seen:
            seen.add(norm)
            expanded.append(norm)
        for synonym in _OFFICE_SYNONYM_MAP.get(norm, ()):
            if synonym not in seen:
                seen.add(synonym)
                expanded.append(synonym)
    return expanded
