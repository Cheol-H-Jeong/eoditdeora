"""Remote endpoint presets."""

from __future__ import annotations

from eoditdeora.runtime.presets import is_remote_url, list_presets


def test_is_remote_url_loopback_cases():
    for local in ("http://127.0.0.1:8080", "http://localhost:8080", "http://[::1]:8080"):
        assert is_remote_url(local) is False


def test_is_remote_url_external_cases():
    for remote in (
        "https://api.openai.com/v1",
        "http://home-server.local:8080",
        "http://192.168.1.10:8000",
        "http://my-vps.tailscale.net:8080",
    ):
        assert is_remote_url(remote) is True


def test_is_remote_url_handles_empty_and_garbage():
    assert is_remote_url("") is False
    assert is_remote_url("not a url") is False


def test_presets_include_the_key_providers():
    items = {p["key"]: p for p in list_presets()}
    assert "openai" in items
    assert "anthropic" in items
    assert "groq" in items
    assert "custom" in items
    # Remote providers must be flagged so the UI shows a warning badge.
    assert items["openai"]["remote"] is True
    assert items["custom"]["remote"] is False  # empty URL → not remote


def test_presets_require_api_key_where_applicable():
    by_key = {p["key"]: p for p in list_presets()}
    assert by_key["openai"]["requires_api_key"] is True
    assert by_key["anthropic"]["requires_api_key"] is True
    # Self-hosted remote servers do not require key by default.
    assert by_key["remote_llama_cpp"]["requires_api_key"] is False


def test_default_models_populated_where_catalog_is_missing():
    by_key = {p["key"]: p for p in list_presets()}
    # Anthropic has no /v1/models catalog — we bundle common ids.
    assert by_key["anthropic"]["default_models"]
