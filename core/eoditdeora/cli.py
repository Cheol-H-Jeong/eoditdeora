"""`eddr` command-line tool.

Keeps parity with the RPC API so power users can script the same operations
the UI performs. Also useful for smoke-testing from a terminal without
spinning up the Tauri shell.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from eoditdeora import __app_display__, __version__
from eoditdeora.utils.logging import configure_logging


@click.group(help=f"{__app_display__} (eddr) — local document knowledge base CLI")
@click.version_option(__version__)
def cli() -> None:
    configure_logging()


@cli.command("search", help="Run a natural-language search against the index.")
@click.argument("query", nargs=-1, required=True)
@click.option("--ask", is_flag=True, help="Ask mode: return RAG answer with citations.")
@click.option("--top", default=10, show_default=True, help="Number of results.")
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def search_cmd(query: tuple[str, ...], ask: bool, top: int, as_json: bool) -> None:
    from eoditdeora.retriever.service import search

    q = " ".join(query)
    mode = "ask" if ask else "search"
    result = asyncio.run(search(query=q, top_k=top, mode=mode))
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    for i, r in enumerate(result.get("results", []), start=1):
        click.echo(f"{i}. {r.get('title') or r.get('source_path_display')}")
        if snippet := r.get("snippet"):
            click.echo(f"   {snippet}")
        click.echo(f"   {r.get('source_path_display')}")


@cli.command("add-root", help="Register a folder for watching and indexing.")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
def add_root_cmd(path: Path) -> None:
    from eoditdeora.collector.service import add_root

    result = asyncio.run(add_root(str(path)))
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command("status", help="Show indexer status.")
def status_cmd() -> None:
    from eoditdeora.collector.service import status

    result = asyncio.run(status())
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@cli.command("serve", help="Run the JSON-RPC sidecar over stdio (used by the UI shell).")
def serve_cmd() -> None:
    from eoditdeora.api.rpc_server import main as rpc_main

    rpc_main()


def main() -> None:
    cli(prog_name="eddr")


if __name__ == "__main__":
    sys.exit(main())
