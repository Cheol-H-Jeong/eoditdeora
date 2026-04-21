#!/usr/bin/env python3
"""End-to-end smoke test for the sidecar.

Drives the JSON-RPC sidecar over stdio through the full read path:
ping → add root → rescan → files.search → body search → history.top.
Returns non-zero exit if any step regresses. Designed for CI and for
local v*.*.0 release gates.

The script isolates all state under temp dirs via the environment so
it never touches the user's real index:
  EODITDEORA_HOME → $tmp/home
  XDG_CONFIG_HOME → $tmp/config
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _frame(msg: dict[str, Any]) -> bytes:
    body = json.dumps(msg).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


def _read_msg(stream) -> dict[str, Any] | None:
    headers = b""
    while b"\r\n\r\n" not in headers:
        ch = stream.read(1)
        if not ch:
            return None
        headers += ch
    head, _, rest = headers.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n"):
        k, _, v = line.partition(b":")
        if k.strip().lower() == b"content-length":
            length = int(v.strip())
    body = rest
    while len(body) < length:
        more = stream.read(length - len(body))
        if not more:
            return None
        body += more
    return json.loads(body.decode("utf-8"))


class Sidecar:
    def __init__(self, tmp: Path) -> None:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONPATH": str(ROOT / "core"),
            "EODITDEORA_HOME": str(tmp / "home"),
            "XDG_CONFIG_HOME": str(tmp / "config"),
        }
        (tmp / "home").mkdir(parents=True)
        (tmp / "config").mkdir(parents=True)
        python = ROOT / ".venv" / "bin" / "python"
        if not python.exists():
            python = Path(sys.executable)
        self._proc = subprocess.Popen(
            [str(python), "-m", "eoditdeora.cli", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            env=env,
        )
        self._resp: dict[int, dict[str, Any]] = {}
        self._next_id = 0
        self._stderr_tail: list[str] = []
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._err_reader, daemon=True).start()

    def _reader(self) -> None:
        while True:
            m = _read_msg(self._proc.stdout)
            if m is None:
                return
            if "id" in m:
                self._resp[m["id"]] = m

    def _err_reader(self) -> None:
        while True:
            line = self._proc.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", "replace"))

    def call(self, method: str, params: dict[str, Any] | None = None, timeout: float = 60.0) -> dict[str, Any]:
        self._next_id += 1
        i = self._next_id
        self._proc.stdin.write(_frame({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}))
        self._proc.stdin.flush()
        t0 = time.time()
        while time.time() - t0 < timeout:
            if i in self._resp:
                r = self._resp.pop(i)
                if "error" in r:
                    raise RuntimeError(f"{method} error: {r['error']}")
                return r["result"]
            time.sleep(0.02)
        raise TimeoutError(f"{method} after {timeout}s")

    def shutdown(self) -> None:
        self._proc.terminate()
        try:
            self._proc.wait(timeout=3)
        except Exception:
            self._proc.kill()


def _seed_corpus(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for name, body in [
        ("예산_품의서_2026.txt", "2026 상반기 예산 품의서 초안. 부서: 총무과. 지출: 사무실 리모델링 12,000,000원."),
        ("회의록_2026_04_18.md", "# 2026-04-18 회의록\n- 주제: 시스템 점검 일정\n- 결정사항: 5월 2주차 점검"),
        ("민원_응대_매뉴얼.md", "민원 응대 기본 원칙: 경청, 공감, 정확한 안내."),
        ("휴가신청서_홍길동.txt", "휴가신청서\n성명: 홍길동\n기간: 2026-05-03 ~ 2026-05-05"),
    ]:
        (root / name).write_text(body, encoding="utf-8")


def _require(cond: bool, label: str) -> None:
    if cond:
        print(f"  ✓ {label}")
        return
    print(f"  ✗ {label}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="eoditdeora-smoke-"))
    print(f"[smoke] scratch = {tmp}")
    sidecar = Sidecar(tmp)
    try:
        time.sleep(0.3)
        p = sidecar.call("ping")
        _require(bool(p.get("ok")), f"ping ok, version={p.get('version')}")

        corpus = tmp / "corpus"
        _seed_corpus(corpus)
        sidecar.call("index.add_root", {"path": str(corpus)})
        rescan = sidecar.call("index.rescan", timeout=120)
        _require(rescan["totals"]["upserted"] >= 4, f"rescan upserted {rescan['totals']['upserted']} files")

        stats = sidecar.call("files.stats")
        _require(stats["total"] >= 4, f"files.stats total={stats['total']}")

        name_hit = sidecar.call("files.search", {"query": "예산"})
        _require(len(name_hit["results"]) >= 1, "files.search '예산' returns a hit")

        # Body ingest runs async; wait up to 45s.
        deadline = time.time() + 45
        while time.time() < deadline:
            st = sidecar.call("indexer.status")
            if st["stats"]["indexed"] >= 4:
                break
            time.sleep(0.5)
        else:
            _require(False, "body ingest did not reach 4 docs in 45s")

        body_hit = sidecar.call("search", {"query": "예산 품의서", "top_k": 5, "mode": "search"})
        _require(len(body_hit["results"]) >= 1, "body search '예산 품의서' returns a hit")
        top = body_hit["results"][0]
        _require("snippet_html" in top and "<mark>" in (top.get("snippet_html") or ""), "first hit has highlighted snippet_html")

        miss = sidecar.call("search", {"query": "zzzz_nonexistent_abc", "top_k": 5, "mode": "search"})
        _require(miss.get("warning") == "no_results", "miss query returns no_results warning")

        hist = sidecar.call("history.top", {"kinds": ["queries"], "limit_query": 10})
        recorded = [q["query"] for q in hist.get("queries", [])]
        _require(any("예산" in q for q in recorded), f"history recorded the search, got {recorded[:3]}")

        print("[smoke] all checks passed")
        return 0
    finally:
        sidecar.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
