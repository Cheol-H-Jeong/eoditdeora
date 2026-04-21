"""Endpoint discovery, health probing, and runtime facade."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from eoditdeora.config import load_settings, save_settings
from eoditdeora.config.settings import EndpointConfig
from eoditdeora.runtime import endpoints as ep_mod
from eoditdeora.runtime.supervisor import RuntimeSupervisor


class _FakeHttpx:
    """Swaps httpx.get so tests can script server responses without a
    real socket being opened anywhere."""

    def __init__(self, responses: dict[str, httpx.Response]):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **_kw: Any) -> httpx.Response:
        self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        # Default: not reachable.
        raise httpx.ConnectError(f"no listener for {url}")


@pytest.fixture
def patched_httpx(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeHttpx({})

    def _installer(responses: dict[str, httpx.Response]) -> _FakeHttpx:
        fake.responses = responses
        return fake

    monkeypatch.setattr(ep_mod.httpx, "get", fake.get)
    return _installer


def _resp(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def test_probe_parses_openai_models_response(patched_httpx):
    patched_httpx(
        {
            "http://127.0.0.1:8080/v1/models": _resp({
                "data": [{"id": "gpt-oss-120b"}, {"id": "qwen3-70b"}]
            })
        }
    )
    p = ep_mod.probe("http://127.0.0.1:8080")
    assert p.reachable is True
    assert p.models == ["gpt-oss-120b", "qwen3-70b"]
    assert p.error is None


def test_probe_handles_v1_in_base_url(patched_httpx):
    patched_httpx({
        "http://127.0.0.1:8000/v1/models": _resp({"data": [{"id": "model-a"}]})
    })
    p = ep_mod.probe("http://127.0.0.1:8000/v1")
    assert p.models == ["model-a"]


def test_probe_unreachable_endpoint(patched_httpx):
    patched_httpx({})  # nothing registered
    p = ep_mod.probe("http://127.0.0.1:9999")
    assert p.reachable is False
    assert p.error is not None


def test_probe_non_200_returns_error(patched_httpx):
    patched_httpx({
        "http://127.0.0.1:8080/v1/models": httpx.Response(404, text="no")
    })
    p = ep_mod.probe("http://127.0.0.1:8080")
    assert p.reachable is False
    assert p.error == "http_404"


def test_probe_empty_url_returns_error():
    p = ep_mod.probe("")
    assert p.reachable is False
    assert p.error == "empty_url"


def test_probe_ollama_native_path(patched_httpx):
    patched_httpx({
        "http://127.0.0.1:11434/api/tags": _resp({
            "models": [{"name": "llama3:8b"}, {"name": "qwen2.5:14b"}]
        })
    })
    p = ep_mod.probe("http://127.0.0.1:11434", api_kind="ollama")
    assert p.models == ["llama3:8b", "qwen2.5:14b"]


def test_discover_local_returns_only_hits(patched_httpx, monkeypatch):
    patched_httpx({
        "http://127.0.0.1:8080/v1/models": _resp({"data": [{"id": "m"}]}),
    })
    # Narrow the candidate list so the test is stable across refactors.
    monkeypatch.setattr(ep_mod, "WELL_KNOWN_CANDIDATES", (
        ("http://127.0.0.1:8080", "openai"),
        ("http://127.0.0.1:1", "openai"),
    ))
    results = ep_mod.discover_local(timeout=0.1)
    assert [r.base_url for r in results] == ["http://127.0.0.1:8080"]


def test_health_for_not_configured():
    h = ep_mod.health_for(EndpointConfig(base_url=""))
    assert h == {"configured": False, "reachable": False, "error": "not_configured", "models": []}


def test_health_for_configured(patched_httpx):
    patched_httpx({
        "http://host:1/v1/models": _resp({"data": [{"id": "only"}]})
    })
    h = ep_mod.health_for(EndpointConfig(base_url="http://host:1", model_id=""))
    assert h["reachable"] is True
    assert h["active_model"] == "only"


def test_runtime_supervisor_is_running_follows_config(patched_httpx):
    patched_httpx({
        "http://host:7/v1/models": _resp({"data": [{"id": "m"}]})
    })
    s = load_settings()
    s.model.llm = EndpointConfig(base_url="http://host:7", model_id="m")
    save_settings(s)

    sup = RuntimeSupervisor()
    assert sup.is_running("llm") is True
    assert sup.is_running("embed") is False  # unset
    assert sup.port("llm") == 7
    assert sup.ensure_running() == {"llm": True, "embed": False, "rerank": False}


def test_url_resolvers_handle_trailing_v1():
    from eoditdeora.runtime.endpoints import (
        resolve_chat_url,
        resolve_embeddings_url,
        resolve_rerank_url,
    )

    e1 = EndpointConfig(base_url="http://h:1")
    e2 = EndpointConfig(base_url="http://h:1/v1")
    assert resolve_chat_url(e1).endswith("/v1/chat/completions")
    assert resolve_chat_url(e2).endswith("/v1/chat/completions")
    assert resolve_embeddings_url(e1).endswith("/v1/embeddings")
    assert resolve_embeddings_url(e2).endswith("/v1/embeddings")
    assert resolve_rerank_url(e1).endswith("/v1/rerank")
    assert resolve_rerank_url(e2).endswith("/v1/rerank")
