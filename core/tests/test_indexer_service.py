from eoditdeora.indexer.daemon import _prune_disallowed_content
from eoditdeora.indexer.service import forget, index_summary
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
import pytest
import time


def _seed(meta: MetaStore, doc_id: str, path: str, *, root: str = "/tmp/root") -> None:
    meta.upsert_document(
        {
            "doc_id": doc_id,
            "root": root,
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


def test_prune_disallowed_content_removes_body_index_rows(tmp_path):
    meta = MetaStore(tmp_path / "meta.sqlite3")
    fts = FtsStore(tmp_path / "tantivy")
    vec = VectorStore(tmp_path / "lance")
    try:
        root = tmp_path / "root"
        root.mkdir()
        keep = root / "keep.txt"
        drop = root / "drop.md"
        _seed(meta, "sha256:" + "a" * 64, str(keep.resolve()), root=str(root.resolve()))
        _seed(meta, "sha256:" + "b" * 64, str(drop.resolve()), root=str(root.resolve()))
        removed = _prune_disallowed_content(
            root,
            {".txt"},
            meta=meta,
            fts=fts,
            vectors=vec,
        )
        assert removed == 1
        assert meta.get_document_by_path(str(keep.resolve())) is not None
        assert meta.get_document_by_path(str(drop.resolve())) is None
    finally:
        meta.close()
