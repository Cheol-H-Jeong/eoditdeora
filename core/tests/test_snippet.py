"""Match-aware snippet rendering."""

from __future__ import annotations

from eoditdeora.retriever.snippet import make_snippet


def test_empty_text_returns_pair_of_empty_strings() -> None:
    plain, html_out = make_snippet("", "query")
    assert plain == ""
    assert html_out == ""


def test_korean_token_gets_marked() -> None:
    plain, html_out = make_snippet(
        "2026 상반기 예산 품의서 초안. 부서: 총무과.",
        "예산 품의서",
    )
    assert "예산" in plain
    assert "<mark>예산</mark>" in html_out
    assert "<mark>품의서</mark>" in html_out


def test_html_is_escaped_before_marking() -> None:
    """Raw HTML in the doc text must never reach the browser as tags."""
    plain, html_out = make_snippet(
        "<script>alert(1)</script> 예산 보고",
        "예산",
    )
    # Doc content escaped; the only unescaped tags are our own <mark>.
    assert "&lt;script&gt;" in html_out
    assert "<script>" not in html_out
    assert "<mark>예산</mark>" in html_out
    # Plain snippet leaves the original characters — it's for text
    # contexts that already escape.
    assert "<script>" in plain


def test_window_centers_on_first_match() -> None:
    text = ("before " * 40) + "TARGET" + (" after" * 40)
    plain, html_out = make_snippet(text, "TARGET")
    assert "TARGET" in plain
    assert "<mark>TARGET</mark>" in html_out
    # Since match is deep inside, the left side should be clipped.
    assert plain.startswith("…")


def test_no_match_falls_back_to_head_window() -> None:
    text = "a b c d " * 50  # 400 chars, no match
    plain, html_out = make_snippet(text, "zzz")
    # No mark tags when nothing matches.
    assert "<mark>" not in html_out
    # Head window; should not start with ellipsis.
    assert not plain.startswith("…")


def test_longer_terms_win_over_shorter() -> None:
    # "예산" is a substring of "예산안"; we want "예산안" to be wrapped,
    # not "예산" followed by a bare "안".
    plain, html_out = make_snippet("2026년 예산안 제출", "예산안")
    assert "<mark>예산안</mark>" in html_out
    assert "<mark>예산</mark>안" not in html_out


def test_case_insensitive_english() -> None:
    plain, html_out = make_snippet("Check the README file", "readme")
    assert "<mark>README</mark>" in html_out


def test_mark_tags_can_be_consumed_as_html_safely() -> None:
    """Contract: the html output can be fed to ``{@html}`` — nothing
    other than ``<mark>`` / ``</mark>`` appears as a raw tag."""
    _, html_out = make_snippet(
        'quotes " and < and > and & in text, find "quotes"',
        "quotes",
    )
    # Doc special chars escaped.
    assert "&quot;" in html_out or "\"" in html_out  # html.escape doesn't escape " by default (quote=False is not our case; we call html.escape(text))
    assert "&amp;" in html_out
    assert "&lt;" in html_out
    # Marks around matches.
    assert "<mark>quotes</mark>" in html_out
