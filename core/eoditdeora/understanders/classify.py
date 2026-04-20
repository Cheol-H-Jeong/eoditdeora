"""Document classification via LLM."""

from __future__ import annotations

import json
from typing import Any

from eoditdeora.parsers.base import ParsedDoc
from eoditdeora.runtime.clients import LlmClient
from eoditdeora.runtime.prompts import CLASSIFY_SYSTEM, CLASSIFY_USER
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


def _head_text(doc: ParsedDoc, limit: int = 2000) -> str:
    buf: list[str] = []
    total = 0
    for block in doc.blocks:
        buf.append(block.text)
        total += len(block.text)
        if total >= limit:
            break
    return "\n".join(buf)[:limit]


def classify_document(doc: ParsedDoc, llm: LlmClient) -> dict[str, Any]:
    title = doc.metadata.get("title") or doc.source_path_display
    prompt = CLASSIFY_USER.format(title=title, head=_head_text(doc))
    raw = llm.chat(
        CLASSIFY_SYSTEM, prompt,
        temperature=0.0, max_tokens=128,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("classify_json_parse_failed", raw=raw[:200], error=str(e))
        return {"classification": "기타", "confidence": 0.0}
