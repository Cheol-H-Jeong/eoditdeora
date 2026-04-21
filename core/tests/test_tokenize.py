from eoditdeora.storage.tokenize import kiwi_tokenize, kiwi_tokenize_for_query


def test_kiwi_tokenize_drops_particles():
    tokens = kiwi_tokenize("나는 오늘 예산을 신청했습니다.")
    # "는", "을" (particles) should be filtered; meaningful stems remain.
    assert "나" in tokens or "오늘" in tokens
    for t in tokens:
        assert t not in {"는", "을"}


def test_kiwi_tokenize_handles_empty():
    assert kiwi_tokenize("") == []


def test_kiwi_tokenize_preserves_english():
    tokens = kiwi_tokenize("예산 report 제출")
    assert any("report" in t.lower() for t in tokens)


def test_kiwi_tokenize_numbers():
    tokens = kiwi_tokenize("금액은 12000원")
    text = " ".join(tokens)
    assert "12000" in text or "12" in tokens or "12000" in tokens


def test_query_tokenizer_only_removes_query_stopwords():
    sentence = "김철수 과장이 예산 품의를 제출"
    assert kiwi_tokenize(sentence) == ["김철수", "과장", "예산", "품", "르", "제출"]
    assert kiwi_tokenize_for_query(sentence) == ["김철수", "과장", "예산", "품", "르", "제출"]
