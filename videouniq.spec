# PyInstaller spec for a future onedir Windows build.
# Portable zip (embeddable CPython + ffmpeg) is the supported distribution today.

from PyInstaller.utils.hooks import collect_all
from pathlib import Path

datas, binaries, hiddenimports = collect_all("PySide6")

a = Analysis(
    ["src/videouniq/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["videouniq", "psutil"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoUniqPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="VideoUniqPro",
)
