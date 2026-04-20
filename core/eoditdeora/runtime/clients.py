"""HTTP clients for the three llama-server backends.

Each client talks to 127.0.0.1 only — there is no remote option per D4.
llama.cpp's server exposes OpenAI-compatible endpoints which we use:

  * /v1/chat/completions   (LlmClient)
  * /v1/embeddings         (EmbedClient)
  * /v1/rerank             (RerankClient)  — llama.cpp reranker mode
"""

from __future__ import annotations

from typing import Any

import httpx

from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


class _Base:
    def __init__(self, host: str, port: int, timeout: float = 60.0) -> None:
        self._base = f"http://{host}:{port}"
        self._client = httpx.Client(base_url=self._base, timeout=timeout)

    def close(self) -> None:
        self._client.close()


class LlmClient(_Base):
    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 1024,
        stop: list[str] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stop:
            body["stop"] = stop
        if response_format:
            body["response_format"] = response_format
        r = self._client.post("/v1/chat/completions", json=body)
        r.raise_for_status()
        data = r.json()
        return str(data["choices"][0]["message"]["content"])


class EmbedClient(_Base):
    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        r = self._client.post("/v1/embeddings", json={"input": texts})
        r.raise_for_status()
        data = r.json()
        return [item["embedding"] for item in data["data"]]


class RerankClient(_Base):
    def rerank(self, query: str, docs: list[str], top_k: int | None = None) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "documents": docs}
        if top_k is not None:
            body["top_n"] = top_k
        r = self._client.post("/v1/rerank", json=body)
        r.raise_for_status()
        data = r.json()
        # llama.cpp rerank response format: {"results": [{"index": i, "relevance_score": s}, ...]}
        return [
            {"index": int(x["index"]), "score": float(x["relevance_score"])}
            for x in data.get("results", [])
        ]
