# Build Eoditdeora-*-setup.exe on Windows x64.
#
# Prerequisites (CI-provided; local builds need these):
#   - Python 3.11 + .venv with production deps + pyinstaller + pyqt6 + pywebview
#   - pnpm + node
#   - Inno Setup 6 (`iscc.exe` on PATH or passed via -IsccPath)
#
# Usage:
#   .\installers\windows\build-installer.ps1 -Version 0.1.0

param(
    [string]$Version = "1.0.0",
    [string]$IsccPath = ""
)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Definition
$Root = Resolve-Path (Join-Path $Here "..\..")

function Say($msg) { Write-Host "▶ $msg" -ForegroundColor Cyan }
function Die($msg) { Write-Host "× $msg" -ForegroundColor Red; exit 1 }

if (-not (Test-Path "$Root\.venv\Scripts\python.exe")) {
    Die "Python venv missing at $Root\.venv. Create with: python -m venv .venv"
}

Say "Building Svelte UI"
Push-Location $Root
pnpm install --silent
pnpm --filter eoditdeora-ui build
if ($LASTEXITCODE -ne 0) { Pop-Location; Die "UI build failed" }
Pop-Location

Say "Freezing Python launcher with PyInstaller"
Remove-Item -Recurse -Force "$Here\build" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$Here\dist"  -ErrorAction SilentlyContinue
& "$Root\.venv\Scripts\pyinstaller.exe" `
    --clean --noconfirm `
    --distpath "$Here\dist" `
    --workpath "$Here\build" `
    "$Here\eoditdeora.spec"
if ($LASTEXITCODE -ne 0) { Die "PyInstaller failed" }

Say "Running Inno Setup compiler"
$Iscc = $IsccPath
if (-not $Iscc) {
    $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
if (-not (Test-Path $Iscc)) {
    Die "Inno Setup compiler not found at $Iscc. Install Inno Setup 6 or pass -IsccPath."
}
New-Item -ItemType Directory -Force -Path "$Here\out" | Out-Null
& $Iscc /DAppVersion=$Version "$Here\eoditdeora.iss"
if ($LASTEXITCODE -ne 0) { Die "Inno Setup failed" }

Say "Done"
Get-ChildItem "$Here\out\Eoditdeora-$Version-setup.exe" | Format-List FullName,Length
