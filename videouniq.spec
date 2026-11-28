# PyInstaller onefile Windows GUI build: VideoUniqPro.exe, icon, no console.
# Build on Windows x64:  pyinstaller --noconfirm videouniq.spec
# Linux CI ships the portable zip with a native VideoUniqPro.exe launcher.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = collect_all("PySide6")

root = Path(SPECPATH)
ff_win = root / "vendor" / "ffmpeg" / "win64"
if ff_win.is_dir():
    for item in ff_win.iterdir():
        if item.suffix.lower() in {".exe", ".dll"}:
            binaries.append((str(item), "ffmpeg"))

icon = root / "src" / "videouniq" / "resources" / "app.ico"
extra_datas = list(datas)
if icon.is_file():
    extra_datas.append((str(icon), "videouniq/resources"))

a = Analysis(
    ["src/videouniq/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=extra_datas,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="VideoUniqPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(icon) if icon.is_file() else None,
)
