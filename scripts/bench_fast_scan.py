from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from eoditdeora.config.paths import get_paths
from eoditdeora.indexer.fast_scan import scan_root


def _make_files(root: Path, count: int) -> None:
    for idx in range(count):
        subdir = root / f"dir_{idx % 128:03d}"
        subdir.mkdir(parents=True, exist_ok=True)
        (subdir / f"bench_{idx:06d}.txt").touch()


def _bench_once(count: int) -> None:
    with tempfile.TemporaryDirectory(prefix="bench-fast-scan-") as tmp:
        base = Path(tmp)
        os.environ["EODITDEORA_HOME"] = str(base / "app")
        get_paths.cache_clear()
        root = base / "docs"
        root.mkdir()
        _make_files(root, count)
        started = time.perf_counter()
        seen, upserted = scan_root(root, {".txt"}, 0)
        elapsed = time.perf_counter() - started
        print(f"N={count} seen={seen} upserted={upserted} seconds={elapsed:.3f}")


if __name__ == "__main__":
    for size in (1000, 10000, 50000):
        _bench_once(size)
