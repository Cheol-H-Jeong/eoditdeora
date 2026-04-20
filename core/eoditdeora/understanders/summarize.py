"""3-length summary via LLM."""

from __future__ import annotations

import json
from typing import Any

from eoditdeora.parsers.base import ParsedDoc
from eoditdeora.runtime.clients import LlmClient
from eoditdeora.runtime.prompts import SUMMARIZE_SYSTEM, SUMMARIZE_USER
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


def _body_text(doc: ParsedDoc, limit: int = 12000) -> str:
    buf: list[str] = []
    total = 0
    for block in doc.blocks:
        buf.append(block.text)
        total += len(block.text)
        if total >= limit:
            break
    return "\n".join(buf)[:limit]


def summarize_document(doc: ParsedDoc, llm: LlmClient) -> dict[str, Any]:
    prompt = SUMMARIZE_USER.format(body=_body_text(doc))
    raw = llm.chat(
        SUMMARIZE_SYSTEM, prompt,
        temperature=0.1, max_tokens=1024,
        response_format={"type": "json_object"},
    )
    try:
        parsed = json.loads(raw)
        return {
            "oneline": str(parsed.get("oneline", ""))[:120],
            "paragraph": str(parsed.get("paragraph", "")),
            "detailed": str(parsed.get("detailed", "")),
        }
    except json.JSONDecodeError:
        log.warning("summarize_parse_failed", raw=raw[:200])
        return {"oneline": "", "paragraph": "", "detailed": ""}
