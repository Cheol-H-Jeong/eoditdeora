from __future__ import annotations

import time
from pathlib import Path

from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.config.settings import Settings
from eoditdeora.indexer.daemon import IndexerDaemon
from eoditdeora.indexer.pipeline import index_file
from eoditdeora.parsers.base import ParsedDoc, ParseResult
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore


def _make_cf(path: Path) -> CollectedFile:
    st = path.stat()
    return CollectedFile(
        path=path.resolve(),
        root=path.parent.resolve(),
        size=st.st_size,
        mtime_ns=st.st_mtime_ns,
        change=ChangeKind.CREATED,
    )


def _stores(tmp_path: Path):
    meta = MetaStore(tmp_path / "meta.sqlite3")
    fts = FtsStore(tmp_path / "tantivy")
    vectors = VectorStore(tmp_path / "lance")
    return meta, fts, vectors


def test_index_file_returns_parser_timeout_without_waiting_full_parse(
    tmp_path: Path, monkeypatch
) -> None:
    src = tmp_path / "slow.pdf"
    src.write_text("slow parser payload", encoding="utf-8")
    meta, fts, vectors = _stores(tmp_path)
    try:
        settings = Settings()
        settings.index.parser_timeout_sec = 1
        monkeypatch.setattr("eoditdeora.indexer.pipeline.load_settings", lambda: settings)

        def slow_parser(path: Path, *, doc_id: str) -> ParseResult:
            time.sleep(5)
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=str(path),
                    format="pdf",
                    parser="slow_parser",
                    fidelity=2,
                    blocks=[],
                )
            )

        monkeypatch.setattr("eoditdeora.indexer.pipeline.parse_file", slow_parser)

        started = time.monotonic()
        result = index_file(_make_cf(src), meta=meta, fts=fts, vectors=vectors)
        elapsed = time.monotonic() - started

        assert result["status"] == "skipped"
        assert result["reason"] == "parser_timeout"
        assert elapsed < 5
        assert meta.get_document_by_path(str(src.resolve()))["warnings_json"]
    finally:
        meta.close()


def test_index_file_allows_normal_parser_completion(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "ok.txt"
    src.write_text("normal parser payload", encoding="utf-8")
    meta, fts, vectors = _stores(tmp_path)
    try:
        settings = Settings()
        settings.index.parser_timeout_sec = 1
        monkeypatch.setattr("eoditdeora.indexer.pipeline.load_settings", lambda: settings)

        def ok_parser(path: Path, *, doc_id: str) -> ParseResult:
            return ParseResult(
                doc=ParsedDoc(
                    doc_id=doc_id,
                    source_path=str(path),
                    source_path_display=str(path),
                    format="txt",
                    parser="ok_parser",
                    fidelity=2,
                    blocks=[],
                )
            )

        monkeypatch.setattr("eoditdeora.indexer.pipeline.parse_file", ok_parser)

        result = index_file(_make_cf(src), meta=meta, fts=fts, vectors=vectors)

        assert result["status"] == "indexed"
        stored = meta.get_document_by_path(str(src.resolve()))
        assert stored is not None
    finally:
        meta.close()


def test_indexer_daemon_counts_parser_timeout_as_error(tmp_path: Path, monkeypatch) -> None:
    class _DummyStore:
        def close(self) -> None:
            return

    class _DummyFastIndex(_DummyStore):
        def delete(self, path: Path) -> None:
            return

        def upsert(self, path: Path, *, size: int, mtime: float) -> None:
            return

    src = tmp_path / "slow.pdf"
    src.write_text("slow parser payload", encoding="utf-8")
    item = _make_cf(src)
    daemon = IndexerDaemon()
    daemon._running = True
    daemon._queue.put(item)
    daemon._queue.put(None)

    monkeypatch.setattr("eoditdeora.indexer.daemon.MetaStore", _DummyStore)
    monkeypatch.setattr("eoditdeora.indexer.daemon.FtsStore", _DummyStore)
    monkeypatch.setattr("eoditdeora.indexer.daemon.VectorStore", _DummyStore)
    monkeypatch.setattr("eoditdeora.indexer.daemon.FastIndex", _DummyFastIndex)
    monkeypatch.setattr(
        "eoditdeora.indexer.daemon.index_file",
        lambda item, *, meta, fts, vectors: {
            "status": "skipped",
            "reason": "parser_timeout",
            "path": str(item.path),
        },
    )

    daemon._run_worker()

    assert daemon.stats()["errors"] == 1
    assert daemon.stats()["skipped"] == 0
