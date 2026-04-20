from eoditdeora.indexer.chunker import chunk_parsed
from eoditdeora.parsers.base import Block, ParsedDoc


def _make_doc(blocks: list[Block]) -> ParsedDoc:
    return ParsedDoc(
        doc_id="sha256:" + "a" * 64,
        source_path="/tmp/x.txt",
        source_path_display="/tmp/x.txt",
        format="txt",
        parser="test",
        fidelity=5,
        blocks=blocks,
    )


def test_empty_doc_yields_no_chunks():
    doc = _make_doc([])
    assert chunk_parsed(doc) == []


def test_single_short_block_yields_single_chunk():
    doc = _make_doc([Block(type="paragraph", text="안녕하세요 어딨더라 테스트입니다.")])
    chunks = chunk_parsed(doc)
    assert len(chunks) == 1
    assert "어딨더라" in chunks[0].text


def test_long_text_is_windowed():
    # TARGET_CHARS defaults to 1000; we need well over that to force a split.
    body = ("문단 " + "데이터 " * 800).strip()
    assert len(body) > 1500
    doc = _make_doc([Block(type="paragraph", text=body)])
    chunks = chunk_parsed(doc)
    assert len(chunks) >= 2
    # Windows overlap: the next chunk begins before the previous one ends.
    assert chunks[0].char_end > chunks[1].char_start


def test_chunk_ordinals_are_monotonic():
    doc = _make_doc(
        [Block(type="paragraph", text=f"블록 {i} 내용입니다. " * 10) for i in range(5)]
    )
    chunks = chunk_parsed(doc)
    assert chunks == sorted(chunks, key=lambda c: c.ordinal)
