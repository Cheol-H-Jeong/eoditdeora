"""LLM runtime management.

Three long-lived local HTTP services backed by `llama-server` binaries:

  * LLM      (gemma-4 26B A4B it, Q8_0) — classification, summarization,
               entity extraction, strict-provenance RAG answers.
  * Embedder (bge-m3, Q8_0) — dense chunk vectors.
  * Reranker (bge-reranker-v2-m3, Q8_0) — cross-encoder re-scoring.

All three share the same supervisor (spawn + health + stop) but have
different ports and clients. `RuntimeSupervisor.start_all()` brings them
up on demand; the RPC server starts it lazily when the first request
that needs LLM compute arrives.
"""

from eoditdeora.runtime.clients import EmbedClient, LlmClient, RerankClient
from eoditdeora.runtime.supervisor import RuntimeSupervisor

__all__ = ["EmbedClient", "LlmClient", "RerankClient", "RuntimeSupervisor"]
