"""Pure-lexical body search.

The contract: typing a keyword into the "내용" tab must feel like
Everything — instant, deterministic, works with zero AI infrastructure.
No embed calls, no reranker calls, no model loading. Just Tantivy BM25
over whatever the ingest daemon has already parsed.

Semantic / hybrid retrieval lives behind the AI tab
(`retriever.hybrid.hybrid_search`).
"""

from __future__ import annotations

from typing import Any

from eoditdeora.retriever.snippet import make_snippet
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


def _load_documents_by_id(
    meta: MetaStore | None,
    doc_ids: list[str],
    *,
    log_event: str,
) -> dict[str, dict[str, Any]]:
    if meta is None:
        return {}
    try:
        return meta.get_documents(doc_ids)
    except Exception as e:  # noqa: BLE001
        log.debug(log_event, doc_ids=len(doc_ids), error=str(e))
        return {}


def lexical_search(query: str, *, top_k: int = 20) -> list[dict[str, Any]]:
    """BM25-only body search.

    Each hit is enriched with the document's display path / title from
    the meta store so the UI card has something to render. Every store
    open and lookup is defensively wrapped: an unreachable Tantivy dir
    or a corrupt SQLite row degrades to an empty result rather than
    taking the RPC loop down.
    """
    query = (query or "").strip()
    if not query or top_k <= 0:
        return []

    try:
        fts: FtsStore | None = FtsStore()
    except Exception as e:  # noqa: BLE001
        log.warning("lexical_fts_open_failed", error=str(e))
        return []

    try:
        try:
            rows = fts.search(query, top_k=top_k)
        except Exception as e:  # noqa: BLE001
            log.exception("lexical_fts_search_failed", error=str(e))
            raise
        if not rows:
            return []

        try:
            meta: MetaStore | None = MetaStore()
        except Exception as e:  # noqa: BLE001
            log.warning("lexical_meta_open_failed", error=str(e))
            meta = None

        try:
            docs_by_id = _load_documents_by_id(
                meta,
                [str(r.get("doc_id", "") or "") for r in rows],
                log_event="lexical_meta_batch_lookup_failed",
            )
            results: list[dict[str, Any]] = []
            for r in rows:
                doc_id = r.get("doc_id", "")
                doc_row = docs_by_id.get(str(doc_id))
                text = r.get("text", "") or ""
                plain, marked = make_snippet(text, query)
                results.append(
                    {
                        "chunk_id": r.get("chunk_id", ""),
                        "doc_id": doc_id,
                        "snippet": plain,
                        "snippet_html": marked,
                        "score": float(r.get("score", 0.0)),
                        "fusion_score": None,
                        "source_path": doc_row["source_path"] if doc_row else "",
                        "source_path_display": doc_row["source_path_display"] if doc_row else "",
                        "format": doc_row["format"] if doc_row else "",
                        "title": doc_row["summary_oneline"] if doc_row else "",
                        "classification": doc_row["classification"] if doc_row else None,
                    }
                )
            return results
        finally:
            if meta is not None:
                try:
                    meta.close()
                except Exception:  # noqa: BLE001
                    pass
    finally:
        try:
            # FtsStore has no close() — Tantivy index handle is GC'd.
            pass
        except Exception:  # noqa: BLE001
            pass
