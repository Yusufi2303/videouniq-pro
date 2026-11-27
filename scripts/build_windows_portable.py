#!/usr/bin/env python3
"""Assemble a portable Windows x64 folder: embeddable CPython + wheels + FFmpeg + app.

Rebuild after the V2 visual editor add-on so the zip matches src/videouniq.
The previous shipped artifact is v2.0.0; next zip is v2.0.1.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build" / "win-portable"
APP_NAME = "VideoUniqPro"
ZIP_NAME = "VideoUniqPro-windows-x64.zip"

PY_VER = "3.12.10"
PY_URL = f"https://www.python.org/ftp/python/{PY_VER}/python-{PY_VER}-embed-amd64.zip"
GET_PIP = "https://bootstrap.pypa.io/get-pip.py"
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        print("reuse", dest)
        return dest
    print("download", url)
    req = urllib.request.Request(url, headers={"User-Agent": "VideoUniqProBuilder/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, dest.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    print("saved", dest, dest.stat().st_size)
    return dest


def unzip(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        zf.extractall(dest)


def copy_app(dest: Path) -> None:
    src_out = dest / "src" / "videouniq"
    if src_out.exists():
        shutil.rmtree(src_out)
    shutil.copytree(
        ROOT / "src" / "videouniq",
        src_out,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "run.py", dest / "run.py")
    shutil.copy2(ROOT / "requirements.txt", dest / "requirements.txt")
    shutil.copy2(ROOT / "README.md", dest / "README.md")
    shutil.copy2(ROOT / "scripts" / "VideoUniqPro.bat", dest / "VideoUniqPro.bat")
    (dest / "ЧИТАЙ.txt").write_text(
        "VideoUniq Pro — портативная сборка для Windows 10/11 x64.\r\n"
        "1. Распакуйте папку на рабочий стол.\r\n"
        "2. Запустите VideoUniqPro.bat\r\n"
        "FFmpeg и Python уже внутри. Интернет не нужен.\r\n",
        encoding="utf-8",
    )


def patch_pth(python_dir: Path) -> None:
    pth = next(python_dir.glob("python*._pth"))
    text = pth.read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    extras = ["Lib/site-packages", "import site"]
    for extra in extras:
        if extra not in lines:
            lines.append(extra)
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_wheels(python_dir: Path, wheel_dir: Path) -> None:
    pip_py = python_dir / "get-pip.py"
    # Use host pip to download Windows wheels, then unpack into embeddable site-packages.
    wheel_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "PySide6_Essentials==6.12.0",
        "shiboken6==6.12.0",
        "psutil==7.2.2",
        "--python-version",
        "3.12",
        "--platform",
        "win_amd64",
        "--only-binary=:all:",
        "-d",
        str(wheel_dir),
    ]
    print("pip download", cmd)
    subprocess.run(cmd, check=True)
    site = python_dir / "Lib" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    for wheel in sorted(wheel_dir.glob("*.whl")):
        print("extract", wheel.name)
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(site)


def place_ffmpeg(bundle: Path, zpath: Path) -> None:
    extract_to = WORK / "ffmpeg-src"
    if extract_to.exists():
        shutil.rmtree(extract_to)
    unzip(zpath, extract_to)
    bins = list(extract_to.rglob("ffmpeg.exe"))
    if not bins:
        raise RuntimeError("ffmpeg.exe not in archive")
    bin_dir = bins[0].parent
    target = bundle / "vendor" / "ffmpeg" / "win64"
    target.mkdir(parents=True, exist_ok=True)
    skip = {"ffplay.exe"}
    copied = 0
    for src in bin_dir.iterdir():
        if not src.is_file():
            continue
        if src.name in skip:
            continue
        if src.suffix.lower() not in {".exe", ".dll"}:
            continue
        shutil.copy2(src, target / src.name)
        copied += src.stat().st_size
    if not (target / "ffmpeg.exe").is_file() or not (target / "ffprobe.exe").is_file():
        raise RuntimeError("ffmpeg.exe/ffprobe.exe missing after copy")
    print(f"ffmpeg win64 {copied/1e6:.1f} MB")
    _upx_dir(target)


def slim_pyside(pyside: Path) -> None:
    if not pyside.is_dir():
        return
    drop_globs = [
        "Qt6Quick*.dll",
        "Qt6Qml*.dll",
        "Qt6Designer*.dll",
        "Qt6Labs*.dll",
        "Qt6QuickControls*.dll",
        "Qt6QuickDialogs*.dll",
        "Qt6QuickLayouts.dll",
        "Qt6QuickTemplates2.dll",
        "Qt6QuickWidgets.dll",
        "Qt6Quick3D*.dll",
        "Qt6ShaderTools.dll",
        "QtQuick*.pyd",
        "QtQml*.pyd",
        "QtDesigner*.pyd",
        "QtOpenGLWidgets.pyd",
        "Qt6OpenGLWidgets.dll",
        "qmlls.exe",
        "qml*.exe",
        "pyside6-*.exe",
        "assistant.exe",
        "designer.exe",
        "linguist.exe",
        "lrelease.exe",
        "lupdate.exe",
        "rcc.exe",
        "uic.exe",
        "QtOpenGL.pyd",
        "QtOpenGL.pyi",
        "resources/icudtl.dat",
        "plugins/sqldrivers/*",
        "translations/*.qm",
        "qml/**",
        "metatypes/**",
    ]
    removed = 0
    for pattern in drop_globs:
        for path in pyside.glob(pattern):
            if path.is_file():
                removed += path.stat().st_size
                path.unlink()
            elif path.is_dir():
                removed += sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
                shutil.rmtree(path)
    print(f"slimmed PySide6 by {removed/1e6:.1f} MB")
    _upx_dir(pyside)
    _upx_dir(pyside / "plugins")


def _upx_dir(folder: Path) -> None:
    upx = shutil.which("upx")
    if not upx or not folder.is_dir():
        return
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in {".dll", ".exe", ".pyd"}:
            continue
        if path.stat().st_size < 800_000:
            continue
        proc = subprocess.run(
            [upx, "-q", "-9", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and "AlreadyPackedException" not in (proc.stderr or ""):
            print("upx skip", path.name, (proc.stderr or proc.stdout or "")[:80])


def zip_bundle(bundle: Path, dest_zip: Path) -> Path:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    if dest_zip.exists():
        dest_zip.unlink()
    with zipfile.ZipFile(
        dest_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True
    ) as zf:
        for file in bundle.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(bundle.parent).as_posix())
    print("zip", dest_zip, dest_zip.stat().st_size)
    return dest_zip


def main() -> int:
    bundle = WORK / APP_NAME
    if WORK.exists():
        shutil.rmtree(WORK)
    bundle.mkdir(parents=True)
    cache = ROOT / "build" / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    py_zip = download(PY_URL, cache / f"python-{PY_VER}-embed-amd64.zip")
    shared = cache / "ffmpeg-win64-gpl-shared.zip"
    if shared.is_file() and shared.stat().st_size > 1_000_000:
        ff_zip = shared
    else:
        ff_zip = download(FFMPEG_URL, cache / "ffmpeg-release-essentials.zip")

    python_dir = bundle / "python"
    unzip(py_zip, python_dir)
    patch_pth(python_dir)
    install_wheels(python_dir, cache / "wheels-win")
    place_ffmpeg(bundle, ff_zip)
    copy_app(bundle)
    slim_pyside(bundle / "python" / "Lib" / "site-packages" / "PySide6")

    dest = DIST / ZIP_NAME
    zip_bundle(bundle, dest)
    print("OK", dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
