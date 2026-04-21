from __future__ import annotations

from dataclasses import dataclass

from eoditdeora.storage.tokenize import kiwi_tokenize_for_query

_TANTIVY_SPECIALS = set(r'+-&|!(){}[]^"~*?:\/')
_SYNONYM_MAP = {
    "예산": ("예산안",),
    "예산안": ("예산",),
    "품의": ("기안",),
    "기안": ("품의",),
    "품의서": ("기안서",),
    "기안서": ("품의서",),
    "휴가": ("연차",),
    "연차": ("휴가",),
}


@dataclass(slots=True)
class ParsedQuery:
    positive_terms: list[str]
    phrases: list[str]
    negative_terms: list[str]
    negative_phrases: list[str]


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
        for synonym in _SYNONYM_MAP.get(norm, ()):
            if synonym not in seen:
                seen.add(synonym)
                expanded.append(synonym)
    return expanded


def _tokenize_terms(raw_terms: list[str], *, expand: bool) -> list[str]:
    seen: set[str] = set()
    tokenized: list[str] = []
    inputs = expand_search_terms(raw_terms) if expand else raw_terms
    for raw in inputs:
        for term in kiwi_tokenize_for_query(raw):
            if term not in seen:
                seen.add(term)
                tokenized.append(term)
    return tokenized


def parse_query(raw: str) -> ParsedQuery:
    positive_raw: list[str] = []
    negative_raw: list[str] = []
    phrases: list[str] = []
    negative_phrases: list[str] = []
    i = 0
    n = len(raw)

    while i < n:
        while i < n and raw[i].isspace():
            i += 1
        if i >= n:
            break

        is_negative = False
        if raw[i] == "-":
            j = i + 1
            while j < n and raw[j].isspace():
                j += 1
            if j < n:
                is_negative = True
                i = j

        if i < n and raw[i] == '"':
            i += 1
            start = i
            while i < n and raw[i] != '"':
                i += 1
            phrase = raw[start:i].strip()
            if phrase:
                if is_negative:
                    negative_phrases.append(phrase)
                else:
                    phrases.append(phrase)
            if i < n and raw[i] == '"':
                i += 1
            continue

        start = i
        while i < n and not raw[i].isspace():
            i += 1
        token = raw[start:i].strip()
        if not token:
            continue
        if is_negative:
            negative_raw.append(token)
        else:
            positive_raw.append(token)

    positive_terms = _tokenize_terms(positive_raw, expand=True)
    negative_terms = _tokenize_terms(negative_raw, expand=False)

    return ParsedQuery(
        positive_terms=positive_terms,
        phrases=phrases,
        negative_terms=negative_terms,
        negative_phrases=negative_phrases,
    )


def build_tantivy_query(parsed: ParsedQuery) -> str:
    parts: list[str] = []
    parts.extend(f'tokens:{_escape_term(term)}' for term in parsed.positive_terms)
    parts.extend(f'phrase_text:"{_escape_phrase(phrase)}"' for phrase in parsed.phrases)
    parts.extend(f'-tokens:{_escape_term(term)}' for term in parsed.negative_terms)
    parts.extend(f'-phrase_text:"{_escape_phrase(phrase)}"' for phrase in parsed.negative_phrases)
    return " ".join(parts)


def _escape_term(term: str) -> str:
    escaped: list[str] = []
    for ch in term:
        if ch in _TANTIVY_SPECIALS:
            escaped.append("\\")
        escaped.append(ch)
    return "".join(escaped)


def _escape_phrase(phrase: str) -> str:
    return phrase.replace("\\", "\\\\").replace('"', '\\"')
