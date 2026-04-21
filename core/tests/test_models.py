"""Model download slot manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from eoditdeora.runtime import models


def test_all_status_returns_three_slots():
    st = models.all_status()
    keys = {s["key"] for s in st}
    assert keys == {"llm", "embed", "rerank"}


def test_download_requires_source(monkeypatch: pytest.MonkeyPatch):
    # No URL set → slot should fail gracefully.
    monkeypatch.delenv("EODITDEORA_LLM_GGUF_URL", raising=False)
    monkeypatch.setattr(models._SLOTS["llm"], "default_url", None)
    snap = models.start_download("llm")
    # Wait for background thread to flip finished.
    import time

    for _ in range(50):
        if models.status("llm")["finished"]:
            break
        time.sleep(0.05)
    final = models.status("llm")
    assert final["finished"] is True
    assert final["error"]
    assert "source_not_configured" in str(final["error"])


def test_cancel_before_running(monkeypatch: pytest.MonkeyPatch):
    snap = models.cancel_download("rerank")
    assert snap["cancelled"] is True


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        models.status("nope")
    with pytest.raises(ValueError):
        models.start_download("nope")
    with pytest.raises(ValueError):
        models.cancel_download("nope")


def test_download_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Feed a tiny HTTP response via a mock urlopen stand-in."""
    import io
    import time
    import urllib.request

    body = b"0123456789" * 10_000  # 100 KB

    class _FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def headers(self):
            return {"Content-Length": str(len(body))}

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *a, **k: _FakeResp(body),
    )
    # Point the "embed" slot at any URL — content irrelevant due to mock.
    monkeypatch.setenv("EODITDEORA_EMBED_GGUF_URL", "http://example.com/fake.gguf")
    # Ensure no leftover state from previous tests.
    slot = models._SLOTS["embed"]
    slot.finished = False
    slot.cancelled = False
    slot.downloaded_bytes = 0
    slot.total_bytes = 0
    slot.started_at = 0.0
    slot.error = None

    # Do not let the post-download supervisor spawn anything real.
    from eoditdeora.runtime import supervisor as sup_mod

    class _NoopSup:
        def ensure_running(self):
            return {"llm": False, "embed": False, "rerank": False}

    monkeypatch.setattr(sup_mod, "RuntimeSupervisor", lambda: _NoopSup())

    models.start_download("embed")
    for _ in range(100):
        st = models.status("embed")
        if st["finished"]:
            break
        time.sleep(0.05)
    final = models.status("embed")
    assert final["finished"] is True
    assert final["error"] is None
    assert final["percent"] == 100.0
    assert final["present"] is True
