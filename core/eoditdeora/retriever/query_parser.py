from __future__ import annotations

from dataclasses import dataclass

from eoditdeora.storage.tokenize import kiwi_tokenize_for_query

_TANTIVY_SPECIALS = set(r'+-&|!(){}[]^"~*?:\/')


@dataclass(slots=True)
class ParsedQuery:
    positive_terms: list[str]
    phrases: list[str]
    negative_terms: list[str]
    negative_phrases: list[str]


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

        is_negative = raw[i] == "-" and i + 1 < n and not raw[i + 1].isspace()
        if is_negative:
            i += 1

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

    positive_terms: list[str] = []
    for token in positive_raw:
        positive_terms.extend(kiwi_tokenize_for_query(token))

    negative_terms: list[str] = []
    for token in negative_raw:
        negative_terms.extend(kiwi_tokenize_for_query(token))

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
