#!/usr/bin/env python3
"""Fetch GGUF weights into `AppPaths.models`.

Usage:
    python scripts/download-models.py [--skip-llm] [--skip-embed] [--skip-rerank]

This is the only network operation the app performs by default. It is
deliberately a separate script rather than an auto-run on first launch
so air-gapped 공무원 environments can deliver weights on USB and never
talk to the internet.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

# Paths imports are local to avoid forcing the full runtime to resolve
# `platformdirs` when users hit `--help`.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "core"))
    from eoditdeora.config.paths import get_paths
except ImportError:  # pragma: no cover
    get_paths = None  # type: ignore[assignment]

MODELS = {
    "llm": {
        "file_name": "gemma-4-26b-a4b-it.Q8_0.gguf",
        # TODO: finalize HF repo + revision once the official GGUF conversion is
        # published. This placeholder URL is resolved at download time.
        "url_env": "EODITDEORA_LLM_GGUF_URL",
    },
    "embed": {
        "file_name": "bge-m3.Q8_0.gguf",
        "url_env": "EODITDEORA_EMBED_GGUF_URL",
    },
    "rerank": {
        "file_name": "bge-reranker-v2-m3.Q8_0.gguf",
        "url_env": "EODITDEORA_RERANK_GGUF_URL",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Download Eoditdeora GGUF weights")
    ap.add_argument("--skip-llm", action="store_true")
    ap.add_argument("--skip-embed", action="store_true")
    ap.add_argument("--skip-rerank", action="store_true")
    args = ap.parse_args()

    import os

    if get_paths is None:
        print("error: cannot import eoditdeora.config.paths; run from repo root", file=sys.stderr)
        return 2

    models_dir = get_paths().models
    models_dir.mkdir(parents=True, exist_ok=True)

    todo = []
    if not args.skip_llm:
        todo.append("llm")
    if not args.skip_embed:
        todo.append("embed")
    if not args.skip_rerank:
        todo.append("rerank")

    for key in todo:
        spec = MODELS[key]
        target = models_dir / spec["file_name"]
        if target.exists():
            print(f"✓ {key}: {target.name} already present ({target.stat().st_size / 1e9:.2f} GB)")
            continue
        url = os.environ.get(spec["url_env"])
        if not url:
            print(
                f"× {key}: set {spec['url_env']} to the GGUF download URL "
                f"(e.g. a Hugging Face LFS link). Skipping.",
                file=sys.stderr,
            )
            continue
        print(f"↓ {key}: fetching {url} → {target}")
        _download(url, target)
        print(f"✓ {key}: done ({target.stat().st_size / 1e9:.2f} GB)")
    return 0


def _download(url: str, target: Path) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    sha = hashlib.sha256()
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as fp:
        while chunk := resp.read(1024 * 1024):
            fp.write(chunk)
            sha.update(chunk)
    tmp.rename(target)
    print(f"   sha256: {sha.hexdigest()[:16]}…")


if __name__ == "__main__":
    sys.exit(main())
