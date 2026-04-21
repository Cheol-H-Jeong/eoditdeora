from eoditdeora.config import load_settings, save_settings


def test_default_settings_roundtrip():
    s = load_settings()
    assert s.search.strict_provenance is True
    assert s.privacy.telemetry is False
    # Endpoints default to unconfigured; the user selects a running server.
    assert s.model.llm.base_url == ""
    assert s.model.embed.base_url == ""
    assert s.model.rerank.base_url == ""
    assert s.model.llm_context_tokens == 32768

    s.index.roots.append("/tmp/example")
    s.model.llm.base_url = "http://127.0.0.1:8080"
    s.model.llm.model_id = "qwen3-70b"
    save_settings(s)

    s2 = load_settings()
    assert s2.index.roots == ["/tmp/example"]
    assert s2.model.llm.base_url == "http://127.0.0.1:8080"
    assert s2.model.llm.model_id == "qwen3-70b"
