"""Indexer orchestration.

The indexer is the glue between Collector output and Storage. For each
file change it:

  1. hashes the file → doc_id,
  2. picks a parser via the registry,
  3. chunks the parsed blocks with an embedding-friendly window,
  4. persists to SQLite (meta + chunks),
  5. enqueues embed + understand jobs.

Heavy LLM work (embedding, classify, summarize, entities) is deferred
to the job queue workers so the user's filesystem changes never block
on the GPU.
"""

from eoditdeora.indexer.chunker import chunk_parsed

__all__ = ["chunk_parsed"]
