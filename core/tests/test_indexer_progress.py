"""Indexer daemon surfaces progress for the UI banner."""

from __future__ import annotations

import pytest

from eoditdeora.api.methods import _indexer_status
from eoditdeora.indexer.daemon import IndexerDaemon


def test_progress_on_fresh_daemon_reports_zero_queue() -> None:
    d = IndexerDaemon()
    p = d.progress()
    assert p["queue_size"] == 0
    assert p["last_file"] is None
    assert p["last_event_ts"] == 0.0
    assert p["running"] is False


@pytest.mark.asyncio
async def test_indexer_status_rpc_includes_progress_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``indexer.status`` must surface queue_size/last_file so the UI
    can render a progress banner without a second RPC call."""
    d = IndexerDaemon()
    # Inject a fake progress snapshot without starting real threads.
    d._last_file = "/tmp/whatever.pdf"
    d._last_event_ts = 1234.5
    d._stats["indexed"] = 7

    from eoditdeora.indexer import daemon as daemon_mod

    monkeypatch.setattr(daemon_mod, "get_daemon", lambda: d)
    out = await _indexer_status({})
    assert out["stats"]["indexed"] == 7
    assert out["last_file"] == "/tmp/whatever.pdf"
    assert out["last_event_ts"] == 1234.5
    assert "queue_size" in out
    assert out["running"] is False
