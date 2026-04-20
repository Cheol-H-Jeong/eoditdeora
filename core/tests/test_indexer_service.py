import pytest

from eoditdeora.indexer.service import forget, index_summary
from eoditdeora.storage.meta import MetaStore
import time


def _seed(meta: MetaStore, doc_id: str, path: str) -> None:
    meta.upsert_document(
        {
            "doc_id": doc_id,
            "root": "/tmp/root",
            "source_path": path,
            "source_path_display": path,
            "format": "txt",
            "parser": "txt_plain",
            "fidelity": 5,
            "size_bytes": 1,
            "mtime_ns": time.time_ns(),
            "indexed_at": time.time_ns(),
            "classification": None,
            "summary_oneline": None,
            "summary_paragraph": None,
            "summary_detailed": None,
            "language": None,
            "warnings_json": "[]",
            "metadata_json": "{}",
        }
    )


@pytest.mark.asyncio
async def test_index_summary_reports_count():
    m = MetaStore()
    try:
        _seed(m, "sha256:" + "a" * 64, "/tmp/a.txt")
        _seed(m, "sha256:" + "b" * 64, "/tmp/b.txt")
    finally:
        m.close()
    summary = await index_summary()
    assert summary["doc_count"] == 2


@pytest.mark.asyncio
async def test_forget_by_doc_id():
    m = MetaStore()
    try:
        _seed(m, "sha256:" + "a" * 64, "/tmp/a.txt")
        _seed(m, "sha256:" + "b" * 64, "/tmp/b.txt")
        assert m.count_documents() == 2
    finally:
        m.close()

    result = await forget(
        doc_ids=["sha256:" + "a" * 64],
        paths=[],
        entities=[],
    )
    assert result["ok"] is True
    assert result["removed"] == 1
    m2 = MetaStore()
    try:
        assert m2.count_documents() == 1
    finally:
        m2.close()


@pytest.mark.asyncio
async def test_forget_by_path():
    m = MetaStore()
    try:
        _seed(m, "sha256:" + "a" * 64, "/tmp/a.txt")
    finally:
        m.close()
    result = await forget(doc_ids=[], paths=["/tmp/a.txt"], entities=[])
    assert result["removed"] == 1


@pytest.mark.asyncio
async def test_forget_unknown_path_is_noop():
    m = MetaStore()
    m.close()
    result = await forget(doc_ids=[], paths=["/does/not/exist"], entities=[])
    assert result["removed"] == 0
