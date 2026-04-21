"""First-run auto-connection to already-serving endpoints."""

from __future__ import annotations

import pytest

from eoditdeora.config import load_settings, save_settings
from eoditdeora.config.settings import EndpointConfig
from eoditdeora.runtime import auto_connect as ac_mod
from eoditdeora.runtime.auto_connect import auto_connect, classify_role
from eoditdeora.runtime.endpoints import Probe


def test_classify_role_matrix():
    assert classify_role("bge-m3") == "embed"
    assert classify_role("BAAI/bge-m3") == "embed"
    assert classify_role("nomic-embed-text-v1.5") == "embed"
    assert classify_role("bge-reranker-v2-m3") == "rerank"
    assert classify_role("cross-encoder/ms-marco-MiniLM") == "rerank"
    assert classify_role("gpt-oss-120b") == "llm"
    assert classify_role("Qwen3-72B-Instruct") == "llm"
    assert classify_role("meta-llama-3.1-70b") == "llm"


def test_auto_connect_assigns_empty_roles(monkeypatch: pytest.MonkeyPatch):
    # Reset settings to empty.
    s = load_settings()
    s.model.llm = EndpointConfig()
    s.model.embed = EndpointConfig()
    s.model.rerank = EndpointConfig()
    save_settings(s)

    monkeypatch.setattr(
        ac_mod,
        "discover_local",
        lambda timeout=1.5: [
            Probe(
                base_url="http://127.0.0.1:8080",
                api_kind="openai",
                reachable=True,
                models=["gpt-oss-120b", "qwen3-72b", "bge-m3", "bge-reranker-v2-m3"],
            )
        ],
    )

    result = auto_connect()
    assigned = result["assigned"]
    assert set(assigned.keys()) == {"llm", "embed", "rerank"}
    # LLM prefers the largest numeric size tag.
    assert assigned["llm"]["model_id"] == "gpt-oss-120b"
    assert assigned["embed"]["model_id"] == "bge-m3"
    assert assigned["rerank"]["model_id"] == "bge-reranker-v2-m3"
    # Persisted.
    s2 = load_settings()
    assert s2.model.llm.base_url == "http://127.0.0.1:8080"
    assert s2.model.llm.model_id == "gpt-oss-120b"
    assert s2.model.embed.model_id == "bge-m3"


def test_auto_connect_does_not_overwrite_user_choice(monkeypatch: pytest.MonkeyPatch):
    s = load_settings()
    s.model.llm = EndpointConfig(base_url="http://user:1", model_id="manual-llm")
    s.model.embed = EndpointConfig()
    s.model.rerank = EndpointConfig()
    save_settings(s)

    monkeypatch.setattr(
        ac_mod,
        "discover_local",
        lambda timeout=1.5: [
            Probe(
                base_url="http://127.0.0.1:8080",
                api_kind="openai",
                reachable=True,
                models=["other-llm", "bge-m3"],
            )
        ],
    )

    result = auto_connect()
    # LLM stays untouched; only embed was assigned.
    assert "llm" not in result["assigned"]
    assert "embed" in result["assigned"]
    s2 = load_settings()
    assert s2.model.llm.model_id == "manual-llm"


def test_auto_connect_force_reassigns_every_role(monkeypatch: pytest.MonkeyPatch):
    s = load_settings()
    s.model.llm = EndpointConfig(base_url="http://user:1", model_id="manual-llm")
    save_settings(s)

    monkeypatch.setattr(
        ac_mod,
        "discover_local",
        lambda timeout=1.5: [
            Probe(
                base_url="http://127.0.0.1:8080",
                api_kind="openai",
                reachable=True,
                models=["fresh-llm", "bge-m3"],
            )
        ],
    )

    auto_connect(force=True)
    s2 = load_settings()
    assert s2.model.llm.model_id == "fresh-llm"
    assert s2.model.embed.model_id == "bge-m3"


def test_auto_connect_no_servers_leaves_settings_alone(monkeypatch: pytest.MonkeyPatch):
    s = load_settings()
    s.model.llm = EndpointConfig()
    s.model.embed = EndpointConfig()
    s.model.rerank = EndpointConfig()
    save_settings(s)
    monkeypatch.setattr(ac_mod, "discover_local", lambda timeout=1.5: [])

    result = auto_connect()
    assert result["actions"] == []
    assert result["assigned"] == {}
    s2 = load_settings()
    assert s2.model.llm.base_url == ""


def test_auto_connect_skips_auth_required_server(monkeypatch: pytest.MonkeyPatch):
    # A server whose /v1/models is open but /v1/chat/completions is
    # 401 must NOT be auto-assigned — the resulting settings.toml would
    # persist a guaranteed-to-fail endpoint. The user has to enter the
    # API key manually first.
    s = load_settings()
    s.model.llm = EndpointConfig()
    s.model.embed = EndpointConfig()
    s.model.rerank = EndpointConfig()
    save_settings(s)

    monkeypatch.setattr(
        ac_mod,
        "discover_local",
        lambda timeout=1.5: [
            Probe(
                base_url="http://127.0.0.1:8081/v1",
                api_kind="openai",
                reachable=False,
                models=["qwen3.6-35b-a3b"],
                error="auth_required",
            )
        ],
    )

    result = auto_connect()
    assert result["assigned"] == {}
    assert any("skipped:auth_required" in a for a in result["actions"])
    s2 = load_settings()
    assert s2.model.llm.base_url == ""


def test_llm_size_tiebreaker(monkeypatch: pytest.MonkeyPatch):
    s = load_settings()
    s.model.llm = EndpointConfig()
    save_settings(s)
    monkeypatch.setattr(
        ac_mod,
        "discover_local",
        lambda timeout=1.5: [
            Probe(
                base_url="http://h:1",
                api_kind="openai",
                reachable=True,
                models=["small-7b", "medium-34b", "big-120b"],
            )
        ],
    )
    result = auto_connect()
    assert result["assigned"]["llm"]["model_id"] == "big-120b"
