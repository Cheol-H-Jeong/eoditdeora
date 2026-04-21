"""CLI smoke tests using Click's CliRunner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from eoditdeora import cli as cli_mod


def test_version_flag():
    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, ["--version"])
    assert r.exit_code == 0
    assert "1.0.0" in r.output


def test_add_root(tmp_path: Path):
    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, ["add-root", str(tmp_path)])
    assert r.exit_code == 0
    assert '"ok": true' in r.output


def test_status_outputs_json(tmp_path: Path):
    runner = CliRunner()
    runner.invoke(cli_mod.cli, ["add-root", str(tmp_path)])
    r = runner.invoke(cli_mod.cli, ["status"])
    assert r.exit_code == 0
    assert '"roots"' in r.output


def test_search_command_formats_results(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    async def fake_search(query: str, top_k: int, mode: str):  # type: ignore[no-untyped-def]
        return {
            "query": query,
            "results": [
                {
                    "title": "요약-1",
                    "snippet": "예산 품의서 초안",
                    "source_path_display": "/tmp/a.pdf",
                }
            ],
        }

    # cli.search_cmd imports service inside function body
    from eoditdeora.retriever import service

    monkeypatch.setattr(service, "search", fake_search)

    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, ["search", "예산"])
    assert r.exit_code == 0
    assert "요약-1" in r.output
    assert "예산 품의서 초안" in r.output
    assert "/tmp/a.pdf" in r.output


def test_search_json_mode(monkeypatch: pytest.MonkeyPatch):
    import asyncio

    async def fake_search(query: str, top_k: int, mode: str):  # type: ignore[no-untyped-def]
        return {"query": query, "results": [{"snippet": "hit", "source_path_display": "/x"}]}

    from eoditdeora.retriever import service

    monkeypatch.setattr(service, "search", fake_search)
    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, ["search", "--json", "질의"])
    assert r.exit_code == 0
    assert '"results"' in r.output
