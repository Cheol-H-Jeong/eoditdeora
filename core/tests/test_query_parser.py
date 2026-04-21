from eoditdeora.retriever.query_parser import ParsedQuery, build_tantivy_query, parse_query
from eoditdeora.storage.tokenize import kiwi_tokenize_for_query


def test_parse_query_splits_positive_phrase_and_negative():
    parsed = parse_query('예산 "품의서 초안" -취소')
    assert parsed == ParsedQuery(
        positive_terms=["예산", "예산안"],
        phrases=["품의서 초안"],
        negative_terms=["취소"],
        negative_phrases=[],
    )


def test_parse_query_preserves_negative_phrase_as_phrase() -> None:
    parsed = parse_query('예산 -"품의서 초안"')
    assert parsed == ParsedQuery(
        positive_terms=["예산", "예산안"],
        phrases=[],
        negative_terms=[],
        negative_phrases=["품의서 초안"],
    )


def test_parse_query_allows_whitespace_after_negative_marker() -> None:
    parsed = parse_query('예산 - "품의서 초안" - 취소')
    assert parsed == ParsedQuery(
        positive_terms=["예산", "예산안"],
        phrases=[],
        negative_terms=["취소"],
        negative_phrases=["품의서 초안"],
    )


def test_parse_query_expands_office_synonyms_for_positive_terms() -> None:
    parsed = parse_query("예산안")
    assert parsed.positive_terms == ["예산안", "예산"]


def test_query_tokenizer_drops_stopwords_only_for_query():
    assert kiwi_tokenize_for_query("예산을 의 품의") == ["예산", "품"]


def test_build_tantivy_query_mixes_terms_phrases_and_negatives():
    parsed = ParsedQuery(
        positive_terms=["예산"],
        phrases=["품의서 초안"],
        negative_terms=["취소"],
        negative_phrases=[],
    )
    assert build_tantivy_query(parsed) == 'tokens:예산 phrase_text:"품의서 초안" -tokens:취소'


def test_build_tantivy_query_includes_negative_phrases() -> None:
    parsed = ParsedQuery(
        positive_terms=["예산"],
        phrases=[],
        negative_terms=[],
        negative_phrases=["품의서 초안"],
    )
    assert build_tantivy_query(parsed) == 'tokens:예산 -phrase_text:"품의서 초안"'
