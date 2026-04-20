from eoditdeora.config import load_settings, save_settings


def test_default_settings_roundtrip():
    s = load_settings()
    assert s.search.strict_provenance is True
    assert s.privacy.telemetry is False
    assert s.model.llm_model_id == "gemma-4-26b-a4b-it"
    assert s.model.embedding_model_id == "bge-m3"
    assert s.model.reranker_model_id == "bge-reranker-v2-m3"

    s.index.roots.append("/tmp/example")
    save_settings(s)

    s2 = load_settings()
    assert s2.index.roots == ["/tmp/example"]
