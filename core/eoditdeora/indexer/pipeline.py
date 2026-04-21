"""End-to-end pipeline: CollectedFile → ParsedDoc → chunks → storage."""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from pathlib import Path

from eoditdeora.collector.model import ChangeKind, CollectedFile
from eoditdeora.config import load_settings
from eoditdeora.indexer.chunker import chunk_parsed
from eoditdeora.parsers.base import ParsedDoc
from eoditdeora.parsers.registry import parse_file, resolve_parser
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
from eoditdeora.utils.hashing import sha256_file
from eoditdeora.utils.logging import get_logger
from eoditdeora.utils.paths_util import display_path

log = get_logger(__name__)


def _content_doc_id_for(path: Path) -> str:
    return f"sha256:{sha256_file(path)}"


def _duplicate_doc_id_for(content_doc_id: str, path: Path) -> str:
    path_digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    return f"{content_doc_id}#{path_digest}"


def _skipped_doc_id_for(reason: str, path: Path) -> str:
    path_digest = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()
    return f"skip:{reason}:{path_digest}"


def _doc_id_for(
    path: Path,
    *,
    meta: MetaStore | None = None,
    existing_doc_id: str | None = None,
) -> str:
    content_doc_id = _content_doc_id_for(path)
    if existing_doc_id:
        if existing_doc_id == content_doc_id or existing_doc_id.startswith(f"{content_doc_id}#"):
            return existing_doc_id

    if meta is None:
        return content_doc_id

    current = meta.get_document(content_doc_id)
    if current is None or current["source_path"] == str(path):
        return content_doc_id
    return _duplicate_doc_id_for(content_doc_id, path)


def _upsert_parsed_doc(
    *,
    cf: CollectedFile,
    meta: MetaStore,
    doc: ParsedDoc,
    path: Path,
    indexed_at: int,
    size_bytes: int | None = None,
    mtime_ns: int | None = None,
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
            "size_bytes": cf.size if size_bytes is None else size_bytes,
            "mtime_ns": cf.mtime_ns if mtime_ns is None else mtime_ns,
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


def _delete_existing_doc(
    *,
    doc_id: str,
    meta: MetaStore,
    fts: FtsStore,
    vectors: VectorStore,
) -> None:
    meta.delete_document(doc_id)
    fts.delete_doc(doc_id)
    vectors.delete_doc(doc_id)


def _clear_indexed_payload(
    *,
    doc_id: str,
    meta: MetaStore,
    fts: FtsStore,
    vectors: VectorStore,
) -> None:
    meta.replace_chunks(doc_id, [])
    fts.delete_doc(doc_id)
    vectors.delete_doc(doc_id)


def _can_reuse_existing_parse(record: dict[str, object] | None) -> bool:
    if not record:
        return False
    try:
        payload = json.loads(str(record.get("warnings_json") or "{}"))
    except json.JSONDecodeError:
        return False
    return payload.get("status") == "indexed"


def _clone_chunks_for_doc(
    *,
    source_doc_id: str,
    target_doc_id: str,
    meta: MetaStore,
) -> list[dict[str, object]]:
    source_chunks = meta.get_chunks_for_doc(source_doc_id)
    cloned: list[dict[str, object]] = []
    for row in source_chunks:
        ordinal = int(row["ordinal"])
        cloned.append(
            {
                "chunk_id": f"{target_doc_id}:{ordinal}",
                "doc_id": target_doc_id,
                "ordinal": ordinal,
                "block_type": row["block_type"],
                "page": row["page"],
                "sheet": row["sheet"],
                "text": row["text"],
                "char_start": row["char_start"],
                "char_end": row["char_end"],
                "token_count": row["token_count"],
            }
        )
    return cloned


def _reuse_duplicate_parse(
    *,
    cf: CollectedFile,
    path: Path,
    doc_id: str,
    canonical_doc: dict[str, object],
    meta: MetaStore,
    fts: FtsStore,
    current_size: int,
    current_mtime_ns: int,
) -> dict[str, int | str]:
    now_ns = time.time_ns()
    meta.upsert_document(
        {
            "doc_id": doc_id,
            "root": str(cf.root),
            "source_path": str(path),
            "source_path_display": display_path(path),
            "format": canonical_doc["format"],
            "parser": canonical_doc["parser"],
            "fidelity": canonical_doc["fidelity"],
            "size_bytes": current_size,
            "mtime_ns": current_mtime_ns,
            "indexed_at": now_ns,
            "classification": canonical_doc["classification"],
            "summary_oneline": canonical_doc["summary_oneline"],
            "summary_paragraph": canonical_doc["summary_paragraph"],
            "summary_detailed": canonical_doc["summary_detailed"],
            "language": canonical_doc["language"],
            "warnings_json": canonical_doc["warnings_json"],
            "metadata_json": canonical_doc["metadata_json"],
        }
    )
    chunk_rows = _clone_chunks_for_doc(
        source_doc_id=str(canonical_doc["doc_id"]),
        target_doc_id=doc_id,
        meta=meta,
    )
    meta.replace_chunks(doc_id, chunk_rows)
    fts.upsert(
        [
            {"chunk_id": str(r["chunk_id"]), "doc_id": str(r["doc_id"]), "text": str(r["text"])}
            for r in chunk_rows
        ]
    )
    meta.enqueue_job(
        "embed",
        json.dumps({"doc_id": doc_id, "chunk_ids": [str(r["chunk_id"]) for r in chunk_rows]}),
        priority=50,
    )
    meta.enqueue_job(
        "understand",
        json.dumps({"doc_id": doc_id}),
        priority=80,
    )
    log.info(
        "indexed_duplicate_reused_parse",
        path=str(path),
        doc_id=doc_id,
        canonical_doc_id=str(canonical_doc["doc_id"]),
        chunks=len(chunk_rows),
    )
    return {"status": "indexed", "path": str(path), "chunks": len(chunk_rows)}


def _parse_with_timeout(path: Path, *, doc_id: str, timeout_sec: int):
    done = threading.Event()
    result_queue: "queue.Queue[tuple[str, object]]" = queue.Queue(maxsize=1)
    parser = resolve_parser(path)

    def _worker() -> None:
        try:
            result_queue.put(("result", parse_file(path, doc_id=doc_id)))
        except Exception as e:  # noqa: BLE001
            result_queue.put(("error", e))
        finally:
            done.set()

    started = time.monotonic()
    threading.Thread(target=_worker, name=f"parse:{path.name}", daemon=True).start()
    if not done.wait(timeout=timeout_sec):
        elapsed = time.monotonic() - started
        log.warning(
            "parser_timeout",
            path=str(path),
            parser=parser.name if parser is not None else "unknown",
            elapsed=round(elapsed, 3),
            timeout_sec=timeout_sec,
        )
        return ParsedDoc(
            doc_id=doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format=(path.suffix.lower().lstrip(".") or "unknown"),
            parser="timeout_guard",
            fidelity=1,
            parse_status="parser_timeout",
            warnings=[f"exceeded {timeout_sec}s"],
            parse_ms=int(elapsed * 1000),
        )

    kind, payload = result_queue.get()
    if kind == "error":
        raise payload
    return payload


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
        move_result = meta.replace_path(
            str(cf.previous_path),
            str(path),
            new_root=str(cf.root),
        )
        if move_result is not None:
            moved_doc_id, displaced_doc_id = move_result
            if displaced_doc_id:
                fts.delete_doc(displaced_doc_id)
                vectors.delete_doc(displaced_doc_id)
        if move_result is not None and path.exists() and path.is_file():
            current_doc_id = _doc_id_for(path, meta=meta, existing_doc_id=moved_doc_id)
            if current_doc_id == moved_doc_id:
                existing = meta.get_document_by_path(str(path))
                if existing and existing["mtime_ns"] == cf.mtime_ns:
                    return {"status": "moved", "path": str(path), "previous_path": str(cf.previous_path)}

    if not path.exists() or not path.is_file():
        return {"status": "skipped", "reason": "file_missing", "path": str(path)}

    existing = meta.get_document_by_path(str(path))
    settings = load_settings()

    try:
        current_stat = path.stat()
    except OSError as e:
        log.warning("index_stat_failed", path=str(path), error=str(e))
        return {"status": "skipped", "reason": "file_missing", "path": str(path)}

    current_size = current_stat.st_size
    max_file_bytes = max(1, int(settings.index.max_file_bytes))

    if current_size > max_file_bytes:
        too_large_doc_id = existing["doc_id"] if existing else _skipped_doc_id_for("too_large", path)
        doc = ParsedDoc(
            doc_id=too_large_doc_id,
            source_path=str(path),
            source_path_display=display_path(path),
            format=(path.suffix.lower().lstrip(".") or "unknown"),
            parser="preflight",
            fidelity=1,
            parse_status="too_large",
            warnings=[f"file_too_large: {current_size}_bytes > {max_file_bytes}_bytes"],
        )
        now_ns = time.time_ns()
        _upsert_parsed_doc(
            cf=cf,
            meta=meta,
            doc=doc,
            path=path,
            indexed_at=now_ns,
            size_bytes=current_size,
            mtime_ns=current_stat.st_mtime_ns,
        )
        _clear_indexed_payload(
            doc_id=doc.doc_id,
            meta=meta,
            fts=fts,
            vectors=vectors,
        )
        log.warning(
            "parser_file_too_large",
            path=str(path),
            size_bytes=current_size,
            max_file_bytes=max_file_bytes,
        )
        return {"status": "skipped", "reason": "too_large", "path": str(path)}

    if current_size == 0:
        empty_doc_id = _doc_id_for(
            path,
            meta=meta,
            existing_doc_id=existing["doc_id"] if existing else None,
        )
        if existing and existing["doc_id"] != empty_doc_id:
            _delete_existing_doc(
                doc_id=existing["doc_id"],
                meta=meta,
                fts=fts,
                vectors=vectors,
            )
        doc = ParsedDoc(
            doc_id=empty_doc_id,
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

    if (
        existing
        and existing["mtime_ns"] == current_stat.st_mtime_ns
        and existing["size_bytes"] == current_size
    ):
        return {"status": "unchanged", "path": str(path)}

    doc_id = _doc_id_for(
        path,
        meta=meta,
        existing_doc_id=existing["doc_id"] if existing else None,
    )
    if existing and existing["doc_id"] == doc_id and existing["mtime_ns"] == current_stat.st_mtime_ns:
        return {"status": "unchanged", "path": str(path)}
    # If the same source_path had a previous doc_id (content changed), drop
    # the old rows from every store so the new content fully replaces it.
    if existing and existing["doc_id"] != doc_id:
        _delete_existing_doc(
            doc_id=existing["doc_id"],
            meta=meta,
            fts=fts,
            vectors=vectors,
        )

    canonical_doc = None
    if "#" in doc_id:
        content_doc_id = doc_id.split("#", 1)[0]
        maybe_canonical = meta.get_document(content_doc_id)
        if _can_reuse_existing_parse(maybe_canonical):
            canonical_doc = maybe_canonical

    if canonical_doc is not None:
        return _reuse_duplicate_parse(
            cf=cf,
            path=path,
            doc_id=doc_id,
            canonical_doc=canonical_doc,
            meta=meta,
            fts=fts,
            current_size=current_size,
            current_mtime_ns=current_stat.st_mtime_ns,
        )

    timeout_sec = max(1, int(settings.index.parser_timeout_sec))

    try:
        result = _parse_with_timeout(path, doc_id=doc_id, timeout_sec=timeout_sec)
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
    doc = result if isinstance(result, ParsedDoc) else result.doc
    now_ns = time.time_ns()
    _upsert_parsed_doc(cf=cf, meta=meta, doc=doc, path=path, indexed_at=now_ns)

    if doc.parse_status != "ok":
        _clear_indexed_payload(
            doc_id=doc.doc_id,
            meta=meta,
            fts=fts,
            vectors=vectors,
        )
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
