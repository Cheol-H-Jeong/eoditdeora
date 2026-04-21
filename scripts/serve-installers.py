#!/usr/bin/env python3
"""Serve 어딨더라 installer files to other machines on the same LAN.

Why: the laptop is on the same wired network as the server. Rather than
pulling the 200 MB installer from GitHub (which needs auth on a private
repo) we stream it directly from this machine to the laptop's browser.

Usage:
    python scripts/serve-installers.py [--port 7118] [--from-release]

What it does:
    1. Looks under installers/**/out/ for a locally-built installer.
    2. If missing, downloads the latest matching asset from the most
       recent v* GitHub Release (requires GH_TOKEN with repo scope).
    3. Binds an HTTP server to 0.0.0.0:<port> and prints every LAN-
       reachable URL (IPv4 addresses of every up interface).
    4. GET /            → landing page with OS-specific download buttons.
       GET /<filename>  → attachment download with correct mime type.

The server terminates on Ctrl-C. It does not persist, does not log
request bodies, and binds only while you are running it — there is no
daemon component.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_DIRS = [
    ROOT / "installers" / "linux" / "out",
    ROOT / "installers" / "windows" / "out",
]
GH_REPO = "Cheol-H-Jeong/eoditdeora"

# File name → display label.
LABELS = {
    ".AppImage": ("Linux x64", "AppImage (더블클릭 실행)"),
    ".msi": ("Windows 10/11", "MSI 설치파일 (더블클릭 설치)"),
    ".exe": ("Windows 10/11", "EXE 설치파일 (더블클릭 설치)"),
    ".deb": ("Debian/Ubuntu", "deb 패키지"),
    ".rpm": ("Fedora/RHEL", "rpm 패키지"),
}


def find_local() -> list[Path]:
    files: list[Path] = []
    for d in INSTALLER_DIRS:
        if not d.exists():
            continue
        for suffix in LABELS:
            files.extend(sorted(d.glob(f"*{suffix}")))
    return files


def fetch_release_assets(target_dir: Path) -> list[Path]:
    """Download every installer asset attached to the latest release."""
    target_dir.mkdir(parents=True, exist_ok=True)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GH_TOKEN not set; cannot pull Release assets from a private repo."
        )
    headers = [
        ("Authorization", f"Bearer {token}"),
        ("Accept", "application/vnd.github+json"),
        ("X-GitHub-Api-Version", "2022-11-28"),
    ]
    api = f"https://api.github.com/repos/{GH_REPO}/releases/latest"
    req = urllib.request.Request(api, headers=dict(headers))
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assets = data.get("assets", [])
    if not assets:
        raise RuntimeError(
            "Latest release has no assets yet. CI probably still building; "
            "try again in a few minutes or use --wait."
        )
    downloaded: list[Path] = []
    for a in assets:
        name = a["name"]
        suffix = Path(name).suffix.lower()
        if suffix not in LABELS:
            continue
        url = a["url"]  # the asset API URL, not browser_download_url
        dest = target_dir / name
        if dest.exists() and dest.stat().st_size == a.get("size", -1):
            print(f"  ✓ already have {name}")
            downloaded.append(dest)
            continue
        print(f"  ↓ downloading {name} ({a.get('size', 0) / 1e6:.1f} MB) …")
        req2 = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/octet-stream",
            },
        )
        with urllib.request.urlopen(req2, timeout=600) as r, dest.open("wb") as fp:
            while chunk := r.read(1024 * 1024):
                fp.write(chunk)
        downloaded.append(dest)
    return downloaded


def pick_ip() -> str:
    """Best-effort: IP of the outbound interface toward the LAN."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return socket.gethostname()


def all_lan_ips() -> list[str]:
    """Enumerate every IPv4 address visible on this host."""
    out: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127."):
                out.add(ip)
    except socket.gaierror:
        pass
    out.add(pick_ip())
    return sorted(out)


def render_index(files: list[Path], host: str, port: int) -> bytes:
    rows = []
    for f in files:
        suffix = f.suffix.lower()
        os_label, desc = LABELS.get(suffix, ("파일", ""))
        size = f.stat().st_size / 1e6
        url = f"/{quote(f.name)}"
        rows.append(
            f"""
            <a class="card" href="{url}" download>
              <div class="os">{os_label}</div>
              <div class="name">{f.name}</div>
              <div class="desc">{desc}</div>
              <div class="size">{size:.1f} MB</div>
            </a>"""
        )
    body = "\n".join(rows) if rows else (
        '<p class="empty">아직 준비된 설치파일이 없습니다. '
        "<code>scripts/serve-installers.py --from-release</code> 로 다운로드하거나 "
        "<code>installers/linux/build-appimage.sh</code> 로 빌드하세요.</p>"
    )
    html = f"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>어딨더라 · 설치파일 다운로드</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Pretendard",
      "Apple SD Gothic Neo", "Noto Sans CJK KR", sans-serif;
    margin: 0; padding: 40px 20px; background: #0b0d11; color: #e8e8ea;
    display: flex; flex-direction: column; align-items: center;
  }}
  h1 {{ margin: 0 0 6px; font-size: 28px; font-weight: 700; }}
  .sub {{ color: #8a94a3; margin-bottom: 32px; font-size: 13px; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px; max-width: 820px; width: 100%;
  }}
  .card {{
    background: #141822; border: 1px solid #1e2230; border-radius: 10px;
    padding: 18px; color: #e8e8ea; text-decoration: none;
    transition: border-color 80ms ease, transform 80ms ease;
  }}
  .card:hover {{ border-color: #4b7bff; transform: translateY(-1px); }}
  .os {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: #8ab4ff; }}
  .name {{ margin: 6px 0 2px; font-weight: 600; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }}
  .desc {{ font-size: 12px; color: #c7cbd3; }}
  .size {{ margin-top: 8px; font-size: 11px; color: #6b7280; }}
  .empty {{ color: #8a94a3; font-size: 14px; }}
  code {{ background: #141822; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
  footer {{ margin-top: 40px; color: #4b5563; font-size: 11px; }}
</style>
</head><body>
  <h1>어딨더라</h1>
  <p class="sub">운영체제에 맞는 파일을 받아 더블클릭하면 설치됩니다.</p>
  <div class="grid">{body}</div>
  <footer>서버: {host}:{port}</footer>
</body></html>"""
    return html.encode("utf-8")


class Handler(http.server.SimpleHTTPRequestHandler):
    """Serve files from a fixed set of directories with a landing page."""

    files: list[Path] = []
    host: str = ""
    port: int = 0

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        sys.stderr.write(f"[serve] {self.address_string()} {fmt % args}\n")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].lstrip("/")
        if not path:
            body = render_index(self.files, self.host, self.port)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
            return
        target = next((f for f in self.files if f.name == path), None)
        if target is None:
            self.send_error(404, "unknown file")
            return
        size = target.stat().st_size
        mime = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{target.name}"'
        )
        self.end_headers()
        with target.open("rb") as fp:
            while chunk := fp.read(1024 * 1024):
                self.wfile.write(chunk)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve installer files on LAN")
    parser.add_argument("--port", type=int, default=7118)
    parser.add_argument(
        "--from-release",
        action="store_true",
        help="Download the latest v* Release assets first (private repo OK via GH_TOKEN).",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        help="Extra directory of files to serve (e.g. an external drive).",
    )
    args = parser.parse_args()

    if args.dir:
        INSTALLER_DIRS.append(args.dir.resolve())

    files = find_local()
    if args.from_release or not files:
        try:
            print("Fetching latest Release assets…")
            cache_dir = ROOT / "installers" / "_release-cache"
            new_files = fetch_release_assets(cache_dir)
            if new_files:
                INSTALLER_DIRS.append(cache_dir)
                files = find_local()
        except Exception as e:  # noqa: BLE001
            print(f"! release fetch failed: {e}", file=sys.stderr)
    if not files:
        print(
            "No installer files found. Either build one with\n"
            "  installers/linux/build-appimage.sh   (Linux AppImage)\n"
            "  installers/windows/build-installer.ps1  (Windows EXE)\n"
            "or wait for CI to finish and rerun with --from-release.",
            file=sys.stderr,
        )
        return 2

    Handler.files = files
    Handler.host = pick_ip()
    Handler.port = args.port
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), Handler)

    print()
    print("어딨더라 installer server running.")
    print(f"  port: {args.port}")
    print("  LAN URLs:")
    for ip in all_lan_ips():
        print(f"    http://{ip}:{args.port}/")
    print(f"\nServing {len(files)} file(s):")
    for f in files:
        print(f"  · {f.name}  ({f.stat().st_size / 1e6:.1f} MB)")
    print("\nOn the laptop: open one of the LAN URLs in a browser and click a card.")
    print("Ctrl-C to stop.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
