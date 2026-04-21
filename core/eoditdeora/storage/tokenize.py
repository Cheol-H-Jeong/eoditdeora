"""Kiwi-based Korean tokenization used by both BM25 indexing and query
planning.

Why Kiwi:
  * mature Korean morphological analyzer with stable pip install
  * returns POS tags, so we can filter out particles/endings from the
    BM25 term stream (this improves recall dramatically vs whitespace
    tokenization for Korean documents)

Kept intentionally functional — no class, no state — so it's safe to
call from worker threads without locking.
"""

from __future__ import annotations

from functools import lru_cache

# POS tags we drop before indexing to reduce noise.
# JKS/JKC/JKG/JKO/JKB/JKV/JKQ/JX/JC = particles (조사)
# EP/EF/EC/ETN/ETM           = endings (어미)
# SP/SS/SE/SO/SW/SH          = punctuation/special
# XSN/XSV/XSA                = suffix morphemes that rarely carry meaning
_DROP_TAGS = frozenset(
    {
        "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC",
        "EP", "EF", "EC", "ETN", "ETM",
        "SP", "SS", "SE", "SO", "SW", "SH",
        "XSN", "XSV", "XSA",
    }
)

# Query-time only stopwords. Index-time tokens stay intact so stored text
# and highlight behaviour are unaffected.
_STOPWORDS = frozenset(
    {
        "의", "을", "를", "은", "는", "이", "가", "에", "에서", "에게",
        "께", "도", "와", "과", "로", "으로", "만", "이나", "나", "부터",
        "까지", "보다", "처럼", "같이", "마다", "조차", "마저", "뿐", "밖에",
        "하고", "이며", "이며", "이고", "이다", "인", "the", "a", "an",
        "and", "or", "but", "if", "then", "else", "for", "to", "of",
        "in", "on", "at", "by", "with", "from", "as", "is", "are",
        "was", "were", "be", "been", "being", "this", "that", "these",
        "those", "it", "its", "into", "about", "over", "under",
    }
)


@lru_cache(maxsize=1)
def _get_kiwi():  # type: ignore[no-untyped-def]
    # Lazily constructed so import time stays cheap and so tests can
    # monkeypatch the module without triggering the big native load.
    from kiwipiepy import Kiwi  # type: ignore[import-not-found]

    return Kiwi()


def kiwi_tokenize(text: str) -> list[str]:
    """Return a list of surface forms with noise POS removed.

    Keeps proper-noun / compound-noun / verb-stem / English-word tokens.
    """
    if not text:
        return []
    kiwi = _get_kiwi()
    tokens: list[str] = []
    for tok in kiwi.tokenize(text):
        if tok.tag in _DROP_TAGS:
            continue
        form = tok.form.strip()
        if len(form) < 1:
            continue
        tokens.append(form)
    return tokens


def kiwi_tokenize_for_query(text: str) -> list[str]:
    """Same as kiwi_tokenize but we keep English as-is even if POS
    tagging mislabels it."""
    return [tok for tok in kiwi_tokenize(text) if tok.lower() not in _STOPWORDS]
