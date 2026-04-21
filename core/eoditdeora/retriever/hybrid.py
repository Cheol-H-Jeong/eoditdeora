"""Hybrid BM25 + dense retrieval with cross-encoder rerank.

Fusion strategy: Reciprocal Rank Fusion (RRF) with k=60. This avoids
having to normalize BM25 vs cosine-similarity scores, which have
incompatible scales. After RRF we keep top (top_k * 3) candidates and
let the reranker produce the final ordering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from eoditdeora.config import load_settings
from eoditdeora.runtime.clients import EmbedClient, RerankClient, get_embed_client, get_rerank_client
from eoditdeora.storage.fts import FtsStore
from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.vectors import VectorStore
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

RRF_K = 60


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    text: str
    score: float
    rank_bm25: int | None = None
    rank_dense: int | None = None
    rerank_score: float | None = None


def _rrf_merge(bm25: list[dict[str, Any]], dense: list[dict[str, Any]]) -> list[Hit]:
    by_chunk: dict[str, Hit] = {}
    for rank, r in enumerate(bm25):
        cid = r["chunk_id"]
        hit = by_chunk.setdefault(
            cid, Hit(chunk_id=cid, doc_id=r["doc_id"], text=r["text"], score=0.0)
        )
        hit.rank_bm25 = rank
        hit.score += 1.0 / (RRF_K + rank + 1)
    for rank, r in enumerate(dense):
        cid = r["chunk_id"]
        hit = by_chunk.setdefault(
            cid, Hit(chunk_id=cid, doc_id=r["doc_id"], text=r["text"], score=0.0)
        )
        hit.rank_dense = rank
        hit.score += 1.0 / (RRF_K + rank + 1)
    return sorted(by_chunk.values(), key=lambda h: -h.score)


def hybrid_search(query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
    settings = load_settings()
    meta = MetaStore()
    fts = FtsStore()
    vectors = VectorStore()
    try:
        bm25_rows = fts.search(query, top_k=settings.search.bm25_top_k)

        dense_rows: list[dict[str, Any]] = []
        embed_client = get_embed_client()
        if embed_client is not None:
            try:
                qvec = embed_client.embed([query])[0]
                dense_rows = vectors.search(qvec, top_k=settings.search.dense_top_k)
            except Exception as e:  # noqa: BLE001
                log.info("embed_endpoint_failed_bm25_only", error=str(e))
            finally:
                embed_client.close()
        else:
            log.info("embed_endpoint_unconfigured_bm25_only")

        fused = _rrf_merge(bm25_rows, dense_rows)
        candidates = fused[: max(top_k * 3, 30)]

        rerank_client = get_rerank_client()
        if rerank_client is not None and candidates:
            try:
                ranked = rerank_client.rerank(
                    query, [h.text for h in candidates], top_k=top_k
                )
                reranked: list[Hit] = []
                for item in ranked:
                    idx = item["index"]
                    if 0 <= idx < len(candidates):
                        cand = candidates[idx]
                        cand.rerank_score = item["score"]
                        reranked.append(cand)
                if reranked:
                    candidates = reranked
            except Exception as e:  # noqa: BLE001
                log.info("rerank_endpoint_failed_fusion_only", error=str(e))
            finally:
                rerank_client.close()

        results: list[dict[str, Any]] = []
        for h in candidates[:top_k]:
            cur = meta._conn.execute(  # type: ignore[attr-defined]
                "SELECT source_path, source_path_display, format, summary_oneline, classification "
                "FROM documents WHERE doc_id = ?",
                (h.doc_id,),
            )
            row = cur.fetchone()
            results.append(
                {
                    "chunk_id": h.chunk_id,
                    "doc_id": h.doc_id,
                    "snippet": h.text[:400],
                    "score": h.rerank_score if h.rerank_score is not None else h.score,
                    "fusion_score": h.score,
                    "source_path": row["source_path"] if row else "",
                    "source_path_display": row["source_path_display"] if row else "",
                    "format": row["format"] if row else "",
                    "title": row["summary_oneline"] if row else "",
                    "classification": row["classification"] if row else None,
                }
            )
        return results
    finally:
        meta.close()
