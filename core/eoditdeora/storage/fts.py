"""Tantivy full-text index keyed on Kiwi-tokenized chunk text.

We pre-tokenize with Kiwi before handing text to Tantivy, then use the
'raw' tokenizer on the Tantivy side so it doesn't re-tokenize. This is
the standard trick for languages where Tantivy's built-in tokenizers are
inadequate.
"""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

import tantivy  # type: ignore[import-not-found]

from eoditdeora.config.paths import get_paths
from eoditdeora.storage.schema_version import CURRENT_SCHEMA_VERSION, ensure_version
from eoditdeora.storage.tokenize import kiwi_tokenize, kiwi_tokenize_for_query
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


_WRITER_HEAP = 50_000_000  # tantivy requires >= 15 MB per thread


def _schema() -> tantivy.Schema:
    b = tantivy.SchemaBuilder()
    # `raw` keeps a single-token field for exact-match delete by id.
    b.add_text_field("chunk_id", stored=True, tokenizer_name="raw")
    b.add_text_field("doc_id", stored=True, tokenizer_name="raw", fast=True)
    # Stored verbatim for snippet return but not searched (raw = exact whole-string).
    b.add_text_field("text", stored=True, tokenizer_name="raw")
    # `default` splits on unicode whitespace + lowercases. We feed it Kiwi-
    # tokenized input so the effective index is Korean-morpheme aware while
    # still riding the mature English-default tokenizer path.
    b.add_text_field("tokens", tokenizer_name="default")
    return b.build()


class FtsStore:
    def __init__(self, index_dir: Path | None = None) -> None:
        self._dir = index_dir or (get_paths().index / "tantivy")
        self._dir.mkdir(parents=True, exist_ok=True)
        self._schema = _schema()
        self._index: tantivy.Index | None = None
        ensure_version(
            self._dir.parent,
            "fts",
            CURRENT_SCHEMA_VERSION,
            self._rebuild_index,
        )

    def _open(self) -> tantivy.Index:
        if self._index is not None:
            return self._index
        try:
            self._index = tantivy.Index.open(str(self._dir))
        except Exception:
            self._index = tantivy.Index(self._schema, path=str(self._dir))
        return self._index

    def _rebuild_index(self) -> None:
        self._index = None
        shutil.rmtree(self._dir, ignore_errors=True)
        self._dir.mkdir(parents=True, exist_ok=True)
        tantivy.Index(self._schema, path=str(self._dir))

    def upsert(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        index = self._open()
        writer = index.writer(_WRITER_HEAP)
        # Delete existing chunk_ids to make upsert truly upsert-y.
        for r in records:
            writer.delete_documents("chunk_id", r["chunk_id"])
        for r in records:
            tokens = " ".join(kiwi_tokenize(r["text"]))
            doc = tantivy.Document()
            doc.add_text("chunk_id", r["chunk_id"])
            doc.add_text("doc_id", r["doc_id"])
            doc.add_text("text", r["text"])
            doc.add_text("tokens", tokens)
            writer.add_document(doc)
        writer.commit()

    def delete_doc(self, doc_id: str) -> None:
        index = self._open()
        writer = index.writer(_WRITER_HEAP)
        writer.delete_documents("doc_id", doc_id)
        writer.commit()

    def search(self, query_text: str, top_k: int = 50) -> list[dict[str, Any]]:
        index = self._open()
        index.reload()
        tokens = kiwi_tokenize_for_query(query_text)
        if not tokens:
            return []
        q_str = " ".join(tokens)
        searcher = index.searcher()
        query = index.parse_query(q_str, ["tokens"])
        results: list[dict[str, Any]] = []
        for score, address in searcher.search(query, top_k).hits:
            doc = searcher.doc(address)
            results.append(
                {
                    "chunk_id": doc.get_first("chunk_id"),
                    "doc_id": doc.get_first("doc_id"),
                    "text": doc.get_first("text"),
                    "score": float(score),
                }
            )
        return results
