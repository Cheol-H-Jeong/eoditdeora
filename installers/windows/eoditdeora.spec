# PyInstaller spec for Eoditdeora on Windows.
# Mirrors installers/linux/eoditdeora.spec but keeps Windows-only paths
# so pnpm / build tooling does not trip on POSIX separators.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = Path(SPECPATH).resolve()
ROOT = SPEC_DIR.parent.parent

hiddenimports = []
for pkg in (
    "eoditdeora",
    "eoditdeora.api",
    "eoditdeora.api.methods",
    "eoditdeora.collector",
    "eoditdeora.config",
    "eoditdeora.indexer",
    "eoditdeora.parsers",
    "eoditdeora.retriever",
    "eoditdeora.runtime",
    "eoditdeora.storage",
    "eoditdeora.understanders",
    "eoditdeora.utils",
):
    hiddenimports += collect_submodules(pkg)

hiddenimports += collect_submodules("kiwipiepy")
hiddenimports += collect_submodules("tantivy")
hiddenimports += collect_submodules("lancedb")
hiddenimports += collect_submodules("pyarrow")
hiddenimports += collect_submodules("pdfplumber")
hiddenimports += collect_submodules("pypdfium2")
hiddenimports += collect_submodules("hwp5")
hiddenimports += collect_submodules("PyQt6")
hiddenimports += collect_submodules("webview")

datas = []
datas += collect_data_files("kiwipiepy")
datas += collect_data_files("pypdfium2")
datas += collect_data_files("webview")
datas += [(str(ROOT / "apps" / "ui" / "build"), "apps/ui/build")]
datas += [(str(ROOT / "scripts" / "dev-server.py"), "scripts")]

a = Analysis(
    [str(ROOT / "apps" / "launcher" / "eoditdeora_launcher.py")],
    pathex=[str(ROOT / "core")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="eoditdeora",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=str(SPEC_DIR / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="eoditdeora",
)
