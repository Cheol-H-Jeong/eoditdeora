from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_egress.py"


def _run_check(target: Path) -> subprocess.CompletedProcess[str]:
    env = {"PYTHONPATH": str(REPO_ROOT / "core")}
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_egress_guard_rejects_unapproved_host(tmp_path: Path):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "bad.py").write_text('import httpx\nhttpx.get("https://evil.example/")\n', encoding="utf-8")

    result = _run_check(tmp_path)

    assert result.returncode != 0
    assert "evil.example" in result.stderr
    assert "pkg/bad.py:2" in result.stderr


def test_egress_guard_allows_huggingface_host(tmp_path: Path):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "ok.py").write_text(
        'import httpx\nhttpx.get("https://huggingface.co/openai/gpt-oss-20b")\n',
        encoding="utf-8",
    )

    result = _run_check(tmp_path)

    assert result.returncode == 0


def test_egress_guard_allows_localhost(tmp_path: Path):
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "local.py").write_text('import httpx\nhttpx.get("http://localhost:8080/v1/models")\n', encoding="utf-8")

    result = _run_check(tmp_path)

    assert result.returncode == 0
