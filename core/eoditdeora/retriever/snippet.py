"""Match-aware snippet rendering.

Both the lexical ("내용" tab) and hybrid ("AI" tab) retrievers hand back
chunk text that the UI needs to display as a ~240-char window centred on
the first match, with every query token wrapped in ``<mark>``. Doing
this server-side keeps the renderer dumb and lets non-UI clients (CLI,
future APIs) reuse the same highlighted output.

The output is safe to feed into Svelte's ``{@html}``: every chunk text
character is escaped before ``<mark>`` tags are interpolated, so doc
content cannot inject tags even if it contains literal ``<script>``.
"""

from __future__ import annotations

import html
import re
from typing import Iterable

from eoditdeora.retriever.query_parser import parse_query

SNIPPET_WINDOW = 240
BEFORE_MATCH = 60


def _raw_positive_terms(query: str) -> list[str]:
    terms: list[str] = []
    i = 0
    n = len(query)

    while i < n:
        while i < n and query[i].isspace():
            i += 1
        if i >= n:
            break

        is_negative = False
        if query[i] == "-":
            j = i + 1
            while j < n and query[j].isspace():
                j += 1
            if j < n:
                is_negative = True
                i = j

        if i < n and query[i] == '"':
            i += 1
            start = i
            while i < n and query[i] != '"':
                i += 1
            phrase = query[start:i].strip()
            if phrase and not is_negative:
                terms.append(phrase)
            if i < n and query[i] == '"':
                i += 1
            continue

        start = i
        while i < n and not query[i].isspace():
            i += 1
        token = query[start:i].strip()
        if token and not is_negative:
            terms.append(token)

    return terms


def _query_terms(query: str) -> list[str]:
    """Tokens we'll try to highlight.

    This mirrors the actual search parser rather than re-tokenizing the
    raw string ad hoc. That keeps snippet centering / highlighting in
    sync with user-visible search semantics:

      * negative terms do not get highlighted
      * quoted phrases stay intact
      * conservative synonym expansion matches the retriever
    """
    parsed = parse_query(query)
    candidates = [*_raw_positive_terms(query), *parsed.phrases, *parsed.positive_terms]
    seen: set[str] = set()
    terms: list[str] = []
    for raw in candidates:
        term = raw.strip()
        if not term:
            continue
        lowered = term.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        terms.append(term)
    return terms


def _first_match(text: str, terms: Iterable[str]) -> int:
    low = text.lower()
    best = -1
    for t in terms:
        if not t:
            continue
        pos = low.find(t.lower())
        if pos >= 0 and (best < 0 or pos < best):
            best = pos
    return best


def _window(text: str, center: int) -> tuple[str, bool, bool]:
    """Return (slice, clipped_left, clipped_right)."""
    if center < 0:
        sl = text[:SNIPPET_WINDOW]
        return sl, False, len(text) > SNIPPET_WINDOW
    start = max(0, center - BEFORE_MATCH)
    end = start + SNIPPET_WINDOW
    if end > len(text):
        end = len(text)
        start = max(0, end - SNIPPET_WINDOW)
    return text[start:end], start > 0, end < len(text)


def _mark_html(escaped_text: str, terms: Iterable[str]) -> str:
    """Wrap every case-insensitive occurrence of ``terms`` in <mark>.

    Uses a single alternation regex built from escape-sorted terms so
    longest tokens win over their prefixes (e.g., "예산안" beats "예산").
    """
    candidates = [t for t in terms if t]
    if not candidates:
        return escaped_text
    candidates.sort(key=len, reverse=True)
    escaped_terms = [re.escape(html.escape(t)) for t in candidates]
    pattern = re.compile("|".join(escaped_terms), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group(0)}</mark>", escaped_text)


def make_snippet(text: str, query: str) -> tuple[str, str]:
    """Produce (plain, html) snippets for a chunk.

    The plain snippet is the same character window; the html snippet is
    the same content escaped and with query tokens wrapped in ``<mark>``.
    If ``text`` is empty the pair (``""``, ``""``) is returned so
    callers can serialise to JSON without special-casing.
    """
    if not text:
        return "", ""
    terms = _query_terms(query)
    center = _first_match(text, terms) if terms else -1
    window, clip_l, clip_r = _window(text, center)
    plain = window
    if clip_l:
        plain = "…" + plain
    if clip_r:
        plain = plain + "…"
    escaped = html.escape(window)
    marked = _mark_html(escaped, terms)
    html_out = marked
    if clip_l:
        html_out = "…" + html_out
    if clip_r:
        html_out = html_out + "…"
    return plain, html_out
