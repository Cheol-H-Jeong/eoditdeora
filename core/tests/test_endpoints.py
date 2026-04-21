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
    """Swaps httpx.get / httpx.post so tests can script server responses
    without opening real sockets. Routes look up `(method, url)` so tests
    can independently configure the `/v1/models` and `/v1/chat/completions`
    arms that probe() now hits in sequence."""

    def __init__(self, responses: dict[tuple[str, str], httpx.Response]):
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, **_kw: Any) -> httpx.Response:
        key = ("GET", url)
        self.calls.append(key)
        if key in self.responses:
            return self.responses[key]
        raise httpx.ConnectError(f"no listener for {url}")

    def post(self, url: str, **_kw: Any) -> httpx.Response:
        key = ("POST", url)
        self.calls.append(key)
        if key in self.responses:
            return self.responses[key]
        # Default: pretend the chat endpoint exists so single-arm tests
        # that only script /models still pass the auth probe.
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})


@pytest.fixture
def patched_httpx(monkeypatch: pytest.MonkeyPatch):
    fake = _FakeHttpx({})

    def _installer(responses: dict[tuple[str, str], httpx.Response]) -> _FakeHttpx:
        fake.responses = responses
        return fake

    monkeypatch.setattr(ep_mod.httpx, "get", fake.get)
    monkeypatch.setattr(ep_mod.httpx, "post", fake.post)
    return _installer


def _resp(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=data)


def test_probe_parses_openai_models_response(patched_httpx):
    patched_httpx(
        {
            ("GET", "http://127.0.0.1:8080/v1/models"): _resp({
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
        ("GET", "http://127.0.0.1:8000/v1/models"): _resp({"data": [{"id": "model-a"}]})
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
        ("GET", "http://127.0.0.1:8080/v1/models"): httpx.Response(404, text="no")
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
        ("GET", "http://127.0.0.1:11434/api/tags"): _resp({
            "models": [{"name": "llama3:8b"}, {"name": "qwen2.5:14b"}]
        })
    })
    p = ep_mod.probe("http://127.0.0.1:11434", api_kind="ollama")
    assert p.models == ["llama3:8b", "qwen2.5:14b"]
    # Ollama native probe does not do a chat auth round-trip.
    assert p.reachable is True


def test_probe_detects_auth_required_on_chat(patched_httpx):
    # llama-server with --api-key pattern: models listing is anonymous
    # but chat is 401. The fix elevates this from a silent false-positive
    # "healthy" badge to reachable=False error="auth_required".
    patched_httpx({
        ("GET", "http://127.0.0.1:8081/v1/models"): _resp({
            "data": [{"id": "qwen3.6-35b-a3b"}]
        }),
        ("POST", "http://127.0.0.1:8081/v1/chat/completions"): httpx.Response(
            401, json={"error": {"message": "Invalid API Key"}}
        ),
    })
    p = ep_mod.probe("http://127.0.0.1:8081/v1")
    assert p.reachable is False
    assert p.error == "auth_required"
    assert p.models == ["qwen3.6-35b-a3b"]  # catalog kept so UI can show which model needs auth


def test_probe_marks_endpoint_not_found_when_both_routes_404(patched_httpx):
    # Only mark endpoint_not_found when *both* chat and embeddings
    # are missing. A chat-only 404 could still be a valid embed server
    # and is covered by test_probe_accepts_embeddings_only_server.
    patched_httpx({
        ("GET", "http://127.0.0.1:8080/v1/models"): _resp({
            "data": [{"id": "only"}]
        }),
        ("POST", "http://127.0.0.1:8080/v1/chat/completions"): httpx.Response(404, text="no"),
        ("POST", "http://127.0.0.1:8080/v1/embeddings"): httpx.Response(404, text="no"),
    })
    p = ep_mod.probe("http://127.0.0.1:8080")
    assert p.reachable is False
    assert p.error == "endpoint_not_found"


def test_probe_treats_chat_read_timeout_as_reachable(patched_httpx, monkeypatch):
    # Cold 120B-parameter servers frequently exceed the probe deadline
    # on the first-token reply even when max_tokens=1. The server is
    # authenticated and healthy — it's just slow. Flagging those as
    # unreachable would make discovery useless on heavy backends.
    import httpx as _httpx

    patched_httpx({
        ("GET", "http://127.0.0.1:8080/v1/models"): _resp({"data": [{"id": "m"}]}),
    })

    def raise_timeout(*_a: Any, **_k: Any) -> _httpx.Response:
        raise _httpx.ReadTimeout("deadline exceeded")

    monkeypatch.setattr(ep_mod.httpx, "post", raise_timeout)
    p = ep_mod.probe("http://127.0.0.1:8080")
    assert p.reachable is True
    assert p.error is None


def test_probe_ollama_kind_skips_chat_post(patched_httpx):
    # For api_kind="ollama" the native /api/tags listing is enough;
    # we must NOT hit /v1/chat/completions (Ollama accepts it but
    # sending a POST here would wake the default model on some builds).
    fake = patched_httpx({
        ("GET", "http://127.0.0.1:11434/api/tags"): _resp({
            "models": [{"name": "llama3:8b"}]
        }),
    })
    p = ep_mod.probe("http://127.0.0.1:11434", api_kind="ollama")
    assert p.reachable is True
    assert all(method != "POST" for method, _ in fake.calls), fake.calls


def test_probe_accepts_embeddings_only_server(patched_httpx):
    # TEI / llama-server --embeddings do not implement /chat/completions
    # and return 404 there, but the /v1/embeddings arm works. The probe
    # must fall through to embeddings rather than declaring the whole
    # URL unreachable.
    patched_httpx({
        ("GET", "http://127.0.0.1:8082/v1/models"): _resp({
            "data": [{"id": "bge-m3"}]
        }),
        ("POST", "http://127.0.0.1:8082/v1/chat/completions"): httpx.Response(
            404, json={"error": "not found"}
        ),
        ("POST", "http://127.0.0.1:8082/v1/embeddings"): httpx.Response(
            200, json={"data": [{"embedding": [0.1]}]}
        ),
    })
    p = ep_mod.probe("http://127.0.0.1:8082/v1")
    assert p.reachable is True
    assert p.error is None


def test_probe_reports_auth_required_even_for_embed_only(patched_httpx):
    # Auth classification must beat endpoint_not_found when either arm
    # reports 401 — a locked embed-only server needs the "API 키 필요"
    # message, not "엔드포인트 경로를 찾을 수 없음".
    patched_httpx({
        ("GET", "http://127.0.0.1:8082/v1/models"): _resp({"data": [{"id": "tei"}]}),
        ("POST", "http://127.0.0.1:8082/v1/chat/completions"): httpx.Response(404),
        ("POST", "http://127.0.0.1:8082/v1/embeddings"): httpx.Response(401),
    })
    p = ep_mod.probe("http://127.0.0.1:8082/v1")
    assert p.reachable is False
    assert p.error == "auth_required"


def test_probe_accepts_400_bad_body_on_chat(patched_httpx):
    # A 400 on the auth probe means "the server saw our request, auth
    # passed, but the body was malformed" — the endpoint is usable.
    patched_httpx({
        ("GET", "http://127.0.0.1:8080/v1/models"): _resp({"data": [{"id": "m"}]}),
        ("POST", "http://127.0.0.1:8080/v1/chat/completions"): httpx.Response(
            400, json={"error": "bad request"}
        ),
    })
    p = ep_mod.probe("http://127.0.0.1:8080")
    assert p.reachable is True
    assert p.error is None


def test_probe_200_non_json_is_not_reachable(patched_httpx):
    patched_httpx({
        ("GET", "http://127.0.0.1:8080/v1/models"): httpx.Response(200, text="<html>login</html>")
    })
    p = ep_mod.probe("http://127.0.0.1:8080")
    # Pre-fix this was reachable=True error="non_json_body" — a false
    # positive that would show an HTML login page as a healthy endpoint.
    assert p.reachable is False
    assert p.error == "non_json_body"


def test_discover_local_returns_only_hits(patched_httpx, monkeypatch):
    patched_httpx({
        ("GET", "http://127.0.0.1:8080/v1/models"): _resp({"data": [{"id": "m"}]}),
    })
    # Narrow the candidate list so the test is stable across refactors.
    monkeypatch.setattr(ep_mod, "WELL_KNOWN_CANDIDATES", (
        ("http://127.0.0.1:8080", "openai"),
        ("http://127.0.0.1:1", "openai"),
    ))
    results = ep_mod.discover_local(timeout=0.1)
    assert [r.base_url for r in results] == ["http://127.0.0.1:8080"]


def test_discover_local_includes_auth_required(patched_httpx, monkeypatch):
    # Endpoints that list models but fail the auth probe must still
    # appear in discovery so the UI can prompt the user for a key.
    patched_httpx({
        ("GET", "http://127.0.0.1:8081/v1/models"): _resp({"data": [{"id": "locked"}]}),
        ("POST", "http://127.0.0.1:8081/v1/chat/completions"): httpx.Response(401),
    })
    monkeypatch.setattr(ep_mod, "WELL_KNOWN_CANDIDATES", (
        ("http://127.0.0.1:8081/v1", "openai"),
    ))
    results = ep_mod.discover_local(timeout=0.1)
    assert len(results) == 1
    assert results[0].error == "auth_required"
    assert results[0].models == ["locked"]


def test_health_for_not_configured():
    h = ep_mod.health_for(EndpointConfig(base_url=""))
    assert h == {"configured": False, "reachable": False, "error": "not_configured", "models": []}


def test_health_for_configured(patched_httpx):
    patched_httpx({
        ("GET", "http://host:1/v1/models"): _resp({"data": [{"id": "only"}]})
    })
    h = ep_mod.health_for(EndpointConfig(base_url="http://host:1", model_id=""))
    assert h["reachable"] is True
    assert h["active_model"] == "only"


def test_runtime_supervisor_is_running_follows_config(patched_httpx):
    patched_httpx({
        ("GET", "http://host:7/v1/models"): _resp({"data": [{"id": "m"}]})
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
