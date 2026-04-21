#!/usr/bin/env python3
"""Spawn the JSON-RPC sidecar exactly as the Tauri shell would, then
drive it over stdio to confirm the contract.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _frame(payload: dict) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    return header + body


def _read_response(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    header_lines: list[bytes] = []
    while True:
        line = proc.stdout.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        header_lines.append(line)
    length = 0
    for h in header_lines:
        if h.lower().startswith(b"content-length:"):
            length = int(h.split(b":", 1)[1].strip())
    body = proc.stdout.read(length)
    return json.loads(body)


def call(proc: subprocess.Popen, method: str, params: dict | None = None, request_id: int = 1) -> dict:
    msg = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    assert proc.stdin is not None
    proc.stdin.write(_frame(msg))
    proc.stdin.flush()
    return _read_response(proc)


def main() -> int:
    env = os.environ.copy()
    env["EODITDEORA_HOME"] = str(ROOT / ".demo-home")
    env["PYTHONPATH"] = str(ROOT / "core")
    proc = subprocess.Popen(
        [str(ROOT / ".venv/bin/python"), "-u", "-m", "eoditdeora.api.rpc_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        cwd=str(ROOT),
    )
    try:
        print("── ping ──────────────────────────────────────────────")
        print(json.dumps(call(proc, "ping", request_id=1)["result"], ensure_ascii=False, indent=2))

        print("\n── settings.get (first few keys) ─────────────────────")
        s = call(proc, "settings.get", request_id=2)["result"]
        print(f"  llm_model_id      = {s['model']['llm_model_id']}")
        print(f"  embedding_model_id= {s['model']['embedding_model_id']}")
        print(f"  strict_provenance = {s['search']['strict_provenance']}")
        print(f"  roots             = {s['index']['roots']}")

        print("\n── index.status ──────────────────────────────────────")
        print(json.dumps(call(proc, "index.status", request_id=3)["result"], ensure_ascii=False, indent=2))

        print("\n── search('예산 증액') ──────────────────────────────")
        result = call(proc, "search", {"query": "예산 증액", "top_k": 3}, request_id=4)["result"]
        for i, r in enumerate(result["results"], start=1):
            print(f"  {i}. [{r['score']:.2f}] {r['source_path_display']}")
            print(f"     {r['snippet'][:100]}")

        print("\n── search('회의 액션 아이템') ────────────────────────")
        result = call(proc, "search", {"query": "회의 액션 아이템", "top_k": 2}, request_id=5)["result"]
        for i, r in enumerate(result["results"], start=1):
            print(f"  {i}. [{r['score']:.2f}] {r['source_path_display']}")

        print("\n── search(mode='ask') — LLM offline, strict rejects ──")
        result = call(
            proc, "search", {"query": "예산은 얼마인가?", "mode": "ask", "top_k": 3}, request_id=6
        )["result"]
        if "answer" in result:
            print(f"  answered: {result['answer']['answered']}")
            print(f"  answer  : {result['answer']['answer'][:120]}")

        print("\n── unknown method returns -32601 ─────────────────────")
        bad = call(proc, "no.such.method", request_id=7)
        print(f"  error: {bad['error']['code']} — {bad['error']['message']}")

        print("\n──────────────────────────────────────────────────────")
        print("✓ sidecar speaks JSON-RPC correctly.")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
