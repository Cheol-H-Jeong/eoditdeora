#!/usr/bin/env python3
"""End-to-end demo runner.

Walks a folder, indexes every file through the real pipeline (parsers →
SQLite + Tantivy + LanceDB), then runs a handful of natural-language
searches in BM25-only mode (no LLM required).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

# Isolated demo home so we never touch the user's real index.
os.environ["EODITDEORA_HOME"] = str(ROOT / ".demo-home")

from eoditdeora.collector.scanner import Scanner  # noqa: E402
from eoditdeora.indexer.pipeline import index_file  # noqa: E402
from eoditdeora.storage.fts import FtsStore  # noqa: E402
from eoditdeora.storage.meta import MetaStore  # noqa: E402
from eoditdeora.storage.vectors import VectorStore  # noqa: E402


def banner(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def index(root: Path) -> tuple[int, MetaStore]:
    meta = MetaStore()
    fts = FtsStore()
    vectors = VectorStore()
    count = 0
    for rec in Scanner(root).walk():
        result = index_file(rec, meta=meta, fts=fts, vectors=vectors)
        print(f"  • {rec.path.name:<40} → {result['status']}")
        if result["status"] == "indexed":
            count += 1
    return count, meta


def search(query: str, *, meta: MetaStore) -> None:
    from eoditdeora.storage.fts import FtsStore

    print(f"\n🔎  '{query}'")
    hits = FtsStore().search(query, top_k=5)
    if not hits:
        print("   (no results)")
        return
    for i, h in enumerate(hits, start=1):
        cur = meta._conn.execute(
            "SELECT source_path_display FROM documents WHERE doc_id = ?",
            (h["doc_id"],),
        )
        row = cur.fetchone()
        path = row["source_path_display"] if row else "?"
        snippet = (h["text"] or "").replace("\n", " ")[:120]
        print(f"  {i}. [{h['score']:.2f}] {path}")
        print(f"     {snippet}")


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: demo.py <folder-with-docs>\n"
            "  e.g. demo.py /tmp/eddr-demo/docs",
            file=sys.stderr,
        )
        return 2
    folder = Path(sys.argv[1]).resolve()
    if not folder.is_dir():
        print(f"not a directory: {folder}", file=sys.stderr)
        return 2

    banner("어딨더라 — live demo")
    print(f"EODITDEORA_HOME = {os.environ['EODITDEORA_HOME']}")
    print(f"watched folder  = {folder}")

    banner("1. indexing")
    count, meta = index(folder)
    print(f"\n   indexed {count} document(s). store: "
          f"{meta.path}")

    banner("2. natural language queries (BM25 only — no LLM required)")
    try:
        for q in [
            "예산 증액",
            "김철수 과장",
            "외주 평가 기준",
            "budget Q1",
            "회의 액션 아이템",
        ]:
            search(q, meta=meta)
    finally:
        meta.close()

    banner("3. store contents")
    meta2 = MetaStore()
    try:
        cur = meta2._conn.execute(
            "SELECT source_path_display, format, parser, fidelity FROM documents ORDER BY source_path_display"
        )
        for row in cur.fetchall():
            print(f"  · {row['format']:<5} fidelity={row['fidelity']} "
                  f"via {row['parser']:<20} {row['source_path_display']}")
    finally:
        meta2.close()

    banner("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
