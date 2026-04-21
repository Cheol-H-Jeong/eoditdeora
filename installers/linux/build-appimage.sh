#!/usr/bin/env bash
# Build Eoditdeora-*.AppImage on Linux x86_64.
#
# End product: installers/linux/out/Eoditdeora-<ver>-x86_64.AppImage
# Zero runtime system dependencies beyond glibc; everything (Python,
# Qt WebEngine, Svelte UI) is inside the image.
#
# Required tools (checked on entry):
#   - Python 3.11 venv at .venv (with PyInstaller + PyQt6 installed)
#   - pnpm + node for `pnpm --filter eoditdeora-ui build`
#   - appimagetool, patchelf, binutils, file, desktop-file-utils
#
# GitHub Actions provides all of these on ubuntu-22.04. Locally,
# installing `binutils patchelf file desktop-file-utils` unlocks it.

set -euo pipefail

VERSION="${1:-0.1.1}"
ARCH="x86_64"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/../.." && pwd)"
OUT="${HERE}/out"
APPDIR="${HERE}/AppDir"
DIST_NAME="Eoditdeora-${VERSION}-${ARCH}.AppImage"

say()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }
warn() { printf "\n\033[1;33m! %s\033[0m\n" "$*"; }
die()  { printf "\n\033[1;31m× %s\033[0m\n" "$*" >&2; exit 1; }

# --- preflight --------------------------------------------------------------
command -v pnpm          >/dev/null || die "pnpm is required"
command -v appimagetool  >/dev/null || warn "appimagetool not found — will download into ${HERE}/tools"
command -v patchelf      >/dev/null || die "patchelf is required (apt install patchelf)"
command -v objdump       >/dev/null || die "binutils is required (apt install binutils)"
test -x "${ROOT}/.venv/bin/python" || die ".venv not set up: run uv venv .venv first"

mkdir -p "${OUT}" "${HERE}/tools"

if ! command -v appimagetool >/dev/null; then
  say "Fetching appimagetool"
  curl -fsSL -o "${HERE}/tools/appimagetool" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "${HERE}/tools/appimagetool"
  APPIMAGETOOL="${HERE}/tools/appimagetool"
else
  APPIMAGETOOL="$(command -v appimagetool)"
fi

# --- 1. Svelte UI -----------------------------------------------------------
say "Building Svelte UI"
pushd "${ROOT}" >/dev/null
  pnpm install --silent
  pnpm --filter eoditdeora-ui build
popd >/dev/null

# --- 2. PyInstaller ---------------------------------------------------------
say "Freezing Python launcher with PyInstaller"
rm -rf "${HERE}/build"
rm -rf "${HERE}/dist"
"${ROOT}/.venv/bin/pyinstaller" \
  --clean --noconfirm \
  --distpath "${HERE}/dist" \
  --workpath "${HERE}/build" \
  "${HERE}/eoditdeora.spec"

# --- 3. AppDir assembly -----------------------------------------------------
say "Assembling AppDir"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
cp -r "${HERE}/dist/eoditdeora/." "${APPDIR}/usr/bin/"
cp "${HERE}/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"
cp "${HERE}/eoditdeora.desktop" "${APPDIR}/eoditdeora.desktop"
cp "${HERE}/icon.svg" "${APPDIR}/eoditdeora.svg"

# --- 4. Pack ----------------------------------------------------------------
say "Packing AppImage → ${DIST_NAME}"
rm -f "${OUT}/${DIST_NAME}"
ARCH="${ARCH}" "${APPIMAGETOOL}" --no-appstream "${APPDIR}" "${OUT}/${DIST_NAME}"
chmod +x "${OUT}/${DIST_NAME}"

say "Done"
ls -lh "${OUT}/${DIST_NAME}"
printf "\nDouble-click or run:\n  %s\n\n" "${OUT}/${DIST_NAME}"
