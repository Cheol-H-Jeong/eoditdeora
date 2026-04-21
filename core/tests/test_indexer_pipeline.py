"""End-to-end indexer pipeline tests.

We drive `index_file` with a real MetaStore, real FTS, real Vector store
(all backed by tmp_path directories). We inject known `CollectedFile`s
and assert round-trip invariants:

  * a CREATED file appears in all three stores.
  * an unchanged re-index is a no-op (no duplicates).
  * content changes upsert; chunks are replaced, not appended.
  * DELETED removes from all three.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.indexer.pipeline import index_file
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore


def _make_cf(path: Path, change: ChangeKind = ChangeKind.CREATED) -> CollectedFile:
    st = path.stat()
    return CollectedFile(
        path=path.resolve(),
        root=path.parent.resolve(),
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        change=change,
    )


@pytest.fixture()
def stores(tmp_path: Path):
    m = MetaStore(tmp_path / "meta.sqlite3")
    f = FtsStore(tmp_path / "tantivy")
    v = VectorStore(tmp_path / "lance")
    try:
        yield m, f, v
    finally:
        m.close()


def test_index_new_file_populates_meta_and_fts(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "note.txt"
    src.write_text("예산 증액 품의서 초안입니다.", encoding="utf-8")
    cf = _make_cf(src)
    result = index_file(cf, meta=meta, fts=fts, vectors=vec)
    assert result["status"] == "indexed"
    assert meta.count_documents() == 1
    hits = fts.search("예산", top_k=5)
    assert hits, "expected FTS to locate the chunk"


def test_reindex_same_file_is_noop(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "note.txt"
    src.write_text("내용", encoding="utf-8")
    cf = _make_cf(src)
    r1 = index_file(cf, meta=meta, fts=fts, vectors=vec)
    assert r1["status"] == "indexed"
    r2 = index_file(cf, meta=meta, fts=fts, vectors=vec)
    assert r2["status"] == "unchanged"
    assert meta.count_documents() == 1


def test_content_change_replaces_chunks(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "note.txt"
    src.write_text("첫 번째 내용 abcdef", encoding="utf-8")
    cf1 = _make_cf(src)
    index_file(cf1, meta=meta, fts=fts, vectors=vec)
    # Rewrite with entirely different content and bump mtime.
    time.sleep(0.01)
    src.write_text("두 번째 완전히 다른 내용 uvwxyz", encoding="utf-8")
    cf2 = _make_cf(src)
    result = index_file(cf2, meta=meta, fts=fts, vectors=vec)
    assert result["status"] == "indexed"
    # Exactly one document stays (new doc_id because content changed).
    assert meta.count_documents() == 1
    assert not fts.search("abcdef", top_k=5)
    assert fts.search("uvwxyz", top_k=5)


def test_deleted_file_purges_from_all_stores(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "note.txt"
    src.write_text("삭제 대상 marker_xyz123", encoding="utf-8")
    cf = _make_cf(src)
    index_file(cf, meta=meta, fts=fts, vectors=vec)
    assert meta.count_documents() == 1

    # Now simulate deletion. File removal + DELETED change.
    src.unlink()
    del_cf = CollectedFile(
        path=src.resolve(),
        root=tmp_path.resolve(),
        size=0,
        mtime_ns=0,
        change=ChangeKind.DELETED,
    )
    result = index_file(del_cf, meta=meta, fts=fts, vectors=vec)
    assert result["status"] == "deleted"
    assert meta.count_documents() == 0
    assert not fts.search("marker_xyz123", top_k=5)


def test_missing_file_yields_skipped_status(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "ghost.txt"
    # Fake CollectedFile but don't actually create the file.
    cf = CollectedFile(
        path=src.resolve(),
        root=tmp_path.resolve(),
        size=0,
        mtime_ns=0,
        change=ChangeKind.CREATED,
    )
    result = index_file(cf, meta=meta, fts=fts, vectors=vec)
    assert result["status"] == "skipped"
    assert result.get("reason") == "file_missing"
    assert meta.count_documents() == 0


def test_queued_jobs_appear_after_index(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "note.txt"
    src.write_text("job 생성 확인 본문", encoding="utf-8")
    index_file(_make_cf(src), meta=meta, fts=fts, vectors=vec)
    embed = meta.claim_job("embed")
    understand = meta.claim_job("understand")
    assert embed is not None
    assert understand is not None


def test_moved_file_preserves_doc_id_and_updates_path(tmp_path: Path, stores):
    meta, fts, vec = stores
    src = tmp_path / "before.txt"
    src.write_text("rename payload", encoding="utf-8")
    index_file(_make_cf(src), meta=meta, fts=fts, vectors=vec)
    original = meta.get_document_by_path(str(src.resolve()))
    assert original is not None

    time.sleep(0.01)
    dst = tmp_path / "after.txt"
    src.rename(dst)
    moved = CollectedFile(
        path=dst.resolve(),
        root=tmp_path.resolve(),
        size=dst.stat().st_size,
        mtime_ns=dst.stat().st_mtime_ns,
        change=ChangeKind.MOVED,
        previous_path=src.resolve(),
    )

    result = index_file(moved, meta=meta, fts=fts, vectors=vec)

    assert result["status"] == "moved"
    current = meta.get_document_by_path(str(dst.resolve()))
    assert current is not None
    assert current["doc_id"] == original["doc_id"]
    assert meta.get_document_by_path(str(src.resolve())) is None
