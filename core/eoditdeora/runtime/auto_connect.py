"""First-run auto-connection to already-serving local endpoints.

When Eoditdeora launches for the first time (or whenever any role is
still unconfigured), this module probes well-known localhost ports,
enumerates each server's `/v1/models` list, and heuristically assigns
one model to each of the three roles (LLM, embedding, reranker). The
user never has to open Settings unless they want to override.

Role assignment heuristic:
  * **embedding**  — model id contains any of: bge-m3, bge-small, bge-base,
                     bge-large, nomic-embed, e5-, gte-, jina-embed, text-embedding
  * **reranker**   — model id contains any of: reranker, rerank, bge-reranker, ms-marco
  * **llm**        — anything else. Prefer larger / newer when multiple candidates exist.

We only assign roles that are *currently empty*. An explicit user choice
is never overwritten.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from eoditdeora.config import load_settings, save_settings
from eoditdeora.config.settings import EndpointConfig
from eoditdeora.runtime.endpoints import (
    WELL_KNOWN_CANDIDATES,
    Probe,
    discover_local,
)
from eoditdeora.utils.logging import get_logger

log = get_logger(__name__)


_EMBED_HINTS = (
    "bge-m3", "bge-small", "bge-base", "bge-large",
    "nomic-embed", "text-embedding", "e5-", "gte-",
    "jina-embed", "multilingual-e5", "snowflake-arctic-embed",
)
_RERANK_HINTS = (
    "reranker", "rerank", "bge-reranker", "ms-marco", "cross-encoder",
)


@dataclass(frozen=True)
class Candidate:
    base_url: str
    api_kind: str
    model_id: str


def classify_role(model_id: str) -> str:
    low = model_id.lower()
    for h in _RERANK_HINTS:
        if h in low:
            return "rerank"
    for h in _EMBED_HINTS:
        if h in low:
            return "embed"
    return "llm"


def _size_heuristic(model_id: str) -> float:
    """Extract a numeric 'size' hint from model ids like `gpt-oss-120b`,
    `qwen3-72b-instruct`, `llama-3.1-70b-q8`. Used to break ties when
    multiple LLM candidates compete for the role."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB]\b", model_id)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    # Fall back to raw digit count as a weak tiebreaker.
    digits = sum(c.isdigit() for c in model_id)
    return float(digits)


def _candidates_from_probes(probes: Iterable[Probe]) -> list[Candidate]:
    """Only fully-usable probes become auto-connect candidates.

    A probe that lists models but failed the chat auth check
    (`error == "auth_required"`) is *not* a candidate — assigning it
    would persist a broken endpoint into settings.toml and the very
    next query would 401. The user must supply an API key through
    Settings before we treat it as usable.
    """
    out: list[Candidate] = []
    for p in probes:
        if not p.reachable:
            continue
        for m in p.models:
            if not m:
                continue
            out.append(Candidate(base_url=p.base_url, api_kind=p.api_kind, model_id=m))
    return out


def _pick(
    candidates: list[Candidate],
    *,
    role: str,
) -> Candidate | None:
    matching = [c for c in candidates if classify_role(c.model_id) == role]
    if not matching:
        return None
    if role == "llm":
        matching.sort(key=lambda c: _size_heuristic(c.model_id), reverse=True)
    return matching[0]


def auto_connect(force: bool = False) -> dict[str, object]:
    """Scan localhost and assign any unconfigured role.

    * `force=False` (default) → only empty roles are filled.
    * `force=True`            → re-assign every role regardless of state.

    Returns a summary dict suitable for logging and for the UI to show
    what happened.
    """
    settings = load_settings()
    before = {
        "llm": bool(settings.model.llm.base_url),
        "embed": bool(settings.model.embed.base_url),
        "rerank": bool(settings.model.rerank.base_url),
    }

    need = {role for role in ("llm", "embed", "rerank") if force or not before[role]}
    if not need:
        return {"actions": [], "assigned": {}, "probed": 0}

    probes = discover_local(timeout=1.5)
    candidates = _candidates_from_probes(probes)
    actions: list[str] = []
    assigned: dict[str, dict[str, str]] = {}

    for p in probes:
        if p.error == "auth_required":
            actions.append(f"skipped:auth_required@{p.base_url}")

    for role in ("llm", "embed", "rerank"):
        if role not in need:
            continue
        pick = _pick(candidates, role=role)
        if pick is None:
            continue
        endpoint = EndpointConfig(
            base_url=pick.base_url,
            model_id=pick.model_id,
            api_kind=pick.api_kind,
        )
        setattr(settings.model, role, endpoint)
        actions.append(f"auto_connected:{role}:{pick.model_id}@{pick.base_url}")
        assigned[role] = {
            "base_url": pick.base_url,
            "model_id": pick.model_id,
            "api_kind": pick.api_kind,
        }

    if actions:
        save_settings(settings)
    log.info(
        "auto_connect_done",
        probed_candidates=len(candidates),
        probed_servers=len([p for p in probes if p.reachable]),
        assigned=list(assigned.keys()),
    )
    return {
        "actions": actions,
        "assigned": assigned,
        "probed": len(candidates),
        "well_known_scanned": len(WELL_KNOWN_CANDIDATES),
    }
