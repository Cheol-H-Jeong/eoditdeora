#!/usr/bin/env python3
"""Fail CI if code introduces non-whitelisted literal network egress."""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "core"
if str(CORE_ROOT) not in sys.path:
    sys.path.insert(0, str(CORE_ROOT))

from eoditdeora.config.settings import PrivacySettings

ALLOWED_HOSTS: set[str] = {
    "huggingface.co",
    "cdn-lfs.huggingface.co",
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
}
EXCLUDED_DIRS: set[str] = {
    "core/tests",
    "scripts",
    ".venv",
    "node_modules",
    "apps/ui",
}
PYTHON_SUFFIXES = {".py"}
TEXT_SUFFIXES = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
}
URL_SCHEMES = {"http", "https", "ws", "wss"}
FETCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""\bfetch\(\s*["'](?P<url>https?://[^"'`]+)["']"""),
    re.compile(r"""\b(?:new\s+)?WebSocket\(\s*["'](?P<url>wss?://[^"'`]+)["']"""),
)


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    host: str
    url: str


def allowed_hosts() -> set[str]:
    return set(PrivacySettings().egress_allowed_hosts) | set(ALLOWED_HOSTS)


def should_skip(path: Path, root: Path) -> bool:
    rel = path.relative_to(root).as_posix()
    return any(rel == prefix or rel.startswith(f"{prefix}/") for prefix in EXCLUDED_DIRS)


def iter_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if should_skip(path, root):
            continue
        if path.suffix.lower() not in PYTHON_SUFFIXES | TEXT_SUFFIXES:
            continue
        out.append(path)
    return out


def is_env_lookup(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if isinstance(node.func, ast.Attribute):
        if node.func.attr in {"getenv", "get"}:
            owner = node.func.value
            if isinstance(owner, ast.Name) and owner.id == "os" and node.func.attr == "getenv":
                return True
            if (
                isinstance(owner, ast.Attribute)
                and owner.attr == "environ"
                and isinstance(owner.value, ast.Name)
                and owner.value.id == "os"
            ):
                return True
    return False


def literal_url_from_call(node: ast.Call) -> str | None:
    candidates: list[ast.AST] = []
    if node.args:
        candidates.append(node.args[0])
    for keyword in node.keywords:
        if keyword.arg == "url":
            candidates.append(keyword.value)
    for candidate in candidates:
        if is_env_lookup(candidate):
            return None
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
    return None


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = call_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def is_network_call(node: ast.Call) -> bool:
    name = call_name(node.func)
    return name in {
        "httpx.get",
        "httpx.post",
        "httpx.put",
        "httpx.patch",
        "httpx.delete",
        "httpx.request",
        "requests.get",
        "requests.post",
        "requests.put",
        "requests.patch",
        "requests.delete",
        "requests.request",
        "urllib.request.urlopen",
        "urlopen",
    }


def parse_host(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in URL_SCHEMES:
        return None
    return parsed.hostname


def scan_python_file(path: Path, allowed: set[str]) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="ignore")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not is_network_call(node):
            continue
        url = literal_url_from_call(node)
        if not url:
            continue
        host = parse_host(url)
        if host is None or host in allowed:
            continue
        violations.append(Violation(path=path, line=node.lineno, host=host, url=url))
    return violations


def scan_text_file(path: Path, allowed: set[str]) -> list[Violation]:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="ignore")

    violations: list[Violation] = []
    for pattern in FETCH_PATTERNS:
        for match in pattern.finditer(source):
            url = match.group("url")
            host = parse_host(url)
            if host is None or host in allowed:
                continue
            line = source.count("\n", 0, match.start()) + 1
            violations.append(Violation(path=path, line=line, host=host, url=url))
    return violations


def scan_tree(root: Path) -> list[Violation]:
    allowed = allowed_hosts()
    violations: list[Violation] = []
    for path in iter_files(root):
        if path.suffix.lower() in PYTHON_SUFFIXES:
            violations.extend(scan_python_file(path, allowed))
        else:
            violations.extend(scan_text_file(path, allowed))
    return sorted(violations, key=lambda item: (str(item.path), item.line, item.url))


def main(argv: list[str]) -> int:
    target = Path(argv[1]).resolve() if len(argv) > 1 else REPO_ROOT
    violations = scan_tree(target)
    if not violations:
        print(f"check_egress: ok ({target})")
        return 0

    print("check_egress: found literal egress to non-whitelisted hosts", file=sys.stderr)
    for item in violations:
        rel = item.path.relative_to(target)
        print(f"{rel}:{item.line}: host={item.host} url={item.url}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
