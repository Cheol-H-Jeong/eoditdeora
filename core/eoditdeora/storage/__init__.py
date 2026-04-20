"""Storage backends for Eoditdeora.

- `meta`: SQLite — the canonical record of every document, chunk, entity,
  and relation. This is the source of truth; the vector store and FTS
  index are rebuildable from it.
- `vectors`: LanceDB — dense embeddings per chunk.
- `fts`: Tantivy — keyword index over chunk text, Kiwi-tokenized.
- `tokenize`: shared Kiwi wrapper used by indexer + retriever.
"""

from eoditdeora.storage.meta import MetaStore
from eoditdeora.storage.tokenize import kiwi_tokenize

__all__ = ["MetaStore", "kiwi_tokenize"]
