"""End-to-end pipeline: CollectedFile → ParsedDoc → chunks → storage."""

from __future__ import annotations

import json
import time
from pathlib import Path

from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.indexer.chunker import chunk_parsed
from eoditdeora.parsers.base import ParsedDoc
from eoditdeora.parsers.registry import parse_file
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
from eoditdeora.utils.hashing import sha256_file
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import display_path

log = get_logger(__name__)


def _doc_id_for(path: Path) -> str:
    return f"sha256:{sha256_file(path)}"


def _upsert_parsed_doc(
    *,
    cf: CollectedFile,
    meta: MetaStore,
    doc: ParsedDoc,
    path: Path,
    indexed_at: int,
) -> None:
    meta.upsert_document(
        {
            "doc_id": doc.doc_id,
            "root": str(cf.root),
            "source_path": str(path),
            "source_path_display": display_path(path),
            "format": doc.format,
            "parser": doc.parser,
            "fidelity": doc.fidelity,
            "size_bytes": cf.size,
            "mtime_ns": cf.mtime_ns,
            "indexed_at": indexed_at,
            "classification": None,
            "summary_oneline": None,
            "summary_paragraph": None,
            "summary_detailed": None,
            "language": None,
            "warnings_json": json.dumps(
                {
                    "status": "indexed" if doc.parse_status == "ok" else "skipped",
                    "reason": doc.parse_status,
                    "warnings": doc.warnings,
                },
                ensure_ascii=False,
            ),
            "metadata_json": json.dumps(doc.metadata, ensure_ascii=False, default=str),
        }
    )


def index_file(
    cf: CollectedFile,
    *,
    meta: MetaStore,
    fts: FtsStore,
    vectors: VectorStore,
) -> dict[str, int | str]:
    """Synchronously handle one collector event.

    Returns a small summary dict so the caller can log/telemetry.
    LLM work (embed/understand) is queued; it does not block this call.
    MOVED events apply `previous_path` via `meta.replace_path` so renames
    keep the existing doc_id when content is unchanged.
    """
    path = cf.path

    if cf.change is ChangeKind.DELETED:
        existing = meta.get_document_by_path(str(path))
        if existing:
            doc_id = existing["doc_id"]
            meta.delete_document(doc_id)
            fts.delete_doc(doc_id)
            vectors.delete_doc(doc_id)
            log.info("indexed_delete", path=str(path))
        return {"status": "deleted", "path": str(path)}

    if cf.change is ChangeKind.MOVED and cf.previous_path is not None:
        moved_doc_id = meta.replace_path(str(cf.previous_path), str(path))
        if moved_doc_id and path.exists() and path.is_file():
            current_doc_id = _doc_id_for(path)
            if current_doc_id == moved_doc_id:
                existing = meta.get_document_by_path(str(path))
                if existing and existing["mtime_ns"] == cf.mtime_ns:
                    return {"status": "moved", "path": str(path), "previous_path": str(cf.previous_path)}

    if not path.exists() or not path.is_file():
        return {"status": "skipped", "reason": "file_missing", "path": str(path)}

    if path.stat().st_size == 0:
        doc = ParsedDoc(
            doc_id=_doc_id_for(path),
            source_path=str(path),
            source_path_display=display_path(path),
            format=(path.suffix.lower().lstrip(".") or "unknown"),
            parser="preflight",
            fidelity=1,
            parse_status="empty",
            warnings=["empty_file"],
        )
        now_ns = time.time_ns()
        _upsert_parsed_doc(cf=cf, meta=meta, doc=doc, path=path, indexed_at=now_ns)
        log.warning("parser_empty_file", path=str(path))
        return {"status": "skipped", "reason": "empty", "path": str(path)}

    doc_id = _doc_id_for(path)
    existing = meta.get_document_by_path(str(path))
    if existing and existing["doc_id"] == doc_id and existing["mtime_ns"] == cf.mtime_ns:
        return {"status": "unchanged", "path": str(path)}
    # If the same source_path had a previous doc_id (content changed), drop
    # the old rows from every store so the new content fully replaces it.
    if existing and existing["doc_id"] != doc_id:
        old_id = existing["doc_id"]
        meta.delete_document(old_id)
        fts.delete_doc(old_id)
        vectors.delete_doc(old_id)

    try:
        result = parse_file(path, doc_id=doc_id)
    except Exception as e:  # noqa: BLE001
        result = type("ParseResultShim", (), {})()
        result.doc = ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format=(path.suffix.lower().lstrip(".") or "unknown"),
            parser="pipeline_guard",
            fidelity=1,
            parse_status="parser_error",
            warnings=[str(e)],
        )
    doc = result.doc
    now_ns = time.time_ns()
    _upsert_parsed_doc(cf=cf, meta=meta, doc=doc, path=path, indexed_at=now_ns)

    if doc.parse_status != "ok":
        log.warning(
            "parser_failed",
            path=str(path),
            parser_name=doc.parser,
            parse_status=doc.parse_status,
            reason="; ".join(doc.warnings) if doc.warnings else doc.parse_status,
        )
        return {"status": "skipped", "reason": doc.parse_status, "path": str(path)}

    chunks = chunk_parsed(doc)
    chunk_rows = [
        {
            "chunk_id": f"{doc.doc_id}:{c.ordinal}",
            "doc_id": doc.doc_id,
            "ordinal": c.ordinal,
            "block_type": c.block_type,
            "page": c.page,
            "sheet": c.sheet,
            "text": c.text,
            "char_start": c.char_start,
            "char_end": c.char_end,
            "token_count": c.token_count,
        }
        for c in chunks
    ]
    meta.replace_chunks(doc.doc_id, chunk_rows)
    fts.upsert(
        [
            {"chunk_id": r["chunk_id"], "doc_id": r["doc_id"], "text": r["text"]}
            for r in chunk_rows
        ]
    )

    # Queue deferred work
    meta.enqueue_job(
        "embed",
        json.dumps({"doc_id": doc.doc_id, "chunk_ids": [r["chunk_id"] for r in chunk_rows]}),
        priority=50,
    )
    meta.enqueue_job(
        "understand",
        json.dumps({"doc_id": doc.doc_id}),
        priority=80,
    )

    log.info(
        "indexed_upsert",
        path=str(path),
        doc_id=doc.doc_id,
        parser=doc.parser,
        chunks=len(chunk_rows),
    )
    return {"status": "indexed", "path": str(path), "chunks": len(chunk_rows)}
