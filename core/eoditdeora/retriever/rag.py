"""Strict-provenance RAG answer generator.

Builds an [evidence] block from the top hits and prompts the LLM with
rules that forbid using any non-evidence knowledge. If the LLM outputs
the exact "근거 문서에 해당 정보가 없어..." sentinel, we surface that as
`{"answered": False, ...}` so the UI can distinguish "no answer"
from a bad LLM output.
"""

from __future__ import annotations

from typing import Any

from eoditdeora.runtime.clients import LlmClient
from eoditdeora.runtime.prompts import RAG_STRICT_SYSTEM, RAG_STRICT_USER
from eoditdeora.runtime.supervisor import RuntimeSupervisor
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_NO_ANSWER_SENTINEL = "근거 문서에 해당 정보가 없어"


def _build_evidence(hits: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    lines: list[str] = []
    citations: list[dict[str, Any]] = []
    for i, h in enumerate(hits, start=1):
        snippet = h.get("snippet", "").strip().replace("\n", " ")
        display = h.get("source_path_display") or h.get("source_path") or ""
        lines.append(f"[§{i}] {snippet}\n  (출처: {display})")
        citations.append(
            {
                "index": i,
                "doc_id": h.get("doc_id"),
                "chunk_id": h.get("chunk_id"),
                "source_path": h.get("source_path"),
                "source_path_display": display,
            }
        )
    return "\n\n".join(lines), citations


def answer_strict(question: str, hits: list[dict[str, Any]]) -> dict[str, Any]:
    if not hits:
        return {
            "answered": False,
            "answer": "근거 문서에 해당 정보가 없어 답변할 수 없습니다.",
            "citations": [],
        }

    sup = RuntimeSupervisor()
    if not sup.is_running("llm"):
        return {
            "answered": False,
            "answer": "LLM 런타임이 준비되지 않았습니다. 모델 다운로드 및 시작을 확인하세요.",
            "citations": [],
        }

    evidence, citations = _build_evidence(hits)
    user_prompt = RAG_STRICT_USER.format(question=question, evidence=evidence)

    client = LlmClient(sup.host, sup.port("llm"))
    try:
        text = client.chat(RAG_STRICT_SYSTEM, user_prompt, temperature=0.1, max_tokens=1024)
    finally:
        client.close()

    answered = _NO_ANSWER_SENTINEL not in text
    return {"answered": answered, "answer": text, "citations": citations}
