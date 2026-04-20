"""Entity extraction via LLM."""

from __future__ import annotations

import json

from eoditdeora.parsers.base import ParsedDoc
from eoditdeora.runtime.clients import LlmClient
from eoditdeora.runtime.prompts import ENTITY_SYSTEM, ENTITY_USER
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)

_VALID_KINDS = {"person", "org", "project", "money", "date", "place", "phone", "account"}


def extract_entities(doc: ParsedDoc, llm: LlmClient, body_limit: int = 8000) -> list[dict[str, str]]:
    buf: list[str] = []
    total = 0
    for block in doc.blocks:
        buf.append(block.text)
        total += len(block.text)
        if total >= body_limit:
            break
    body = "\n".join(buf)[:body_limit]
    raw = llm.chat(
        ENTITY_SYSTEM,
        ENTITY_USER.format(body=body),
        temperature=0.0, max_tokens=1024,
        response_format={"type": "json_object"},
    )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("entity_parse_failed", raw=raw[:200])
        return []
    out: list[dict[str, str]] = []
    for ent in data.get("entities", []):
        kind = str(ent.get("kind", "")).lower()
        value = str(ent.get("value", "")).strip()
        if kind not in _VALID_KINDS or not value:
            continue
        out.append({
            "kind": kind,
            "value": value,
            "normalized": ent.get("normalized") or value,
        })
    return out
