"""Resolve FFmpeg binaries, config, and resource locations for frozen and source runs."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_ID = "VideoUniqPro"


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def meipass() -> Path | None:
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else None


def vendor_ffmpeg_dir() -> Path:
    root = app_root()
    if sys.platform == "win32":
        return root / "vendor" / "ffmpeg" / "win64"
    return root / "vendor" / "ffmpeg" / "linux64"


def _candidate_bins(name: str) -> list[Path]:
    exe = f"{name}.exe" if sys.platform == "win32" else name
    out: list[Path] = []
    mp = meipass()
    if mp:
        out.append(mp / exe)
        out.append(mp / "ffmpeg" / exe)
    out.append(vendor_ffmpeg_dir() / exe)
    out.append(app_root() / "vendor" / "ffmpeg" / exe)
    which = _which(exe)
    if which:
        out.append(which)
    return out


def _which(name: str) -> Path | None:
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder:
            continue
        candidate = Path(folder) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def ffmpeg_bin() -> str:
    for path in _candidate_bins("ffmpeg"):
        if path.is_file():
            return str(path)
    return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


def ffprobe_bin() -> str:
    for path in _candidate_bins("ffprobe"):
        if path.is_file():
            return str(path)
    return "ffprobe.exe" if sys.platform == "win32" else "ffprobe"


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        path = base / APP_ID / "Cache"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        path = base / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def presets_path() -> Path:
    return config_dir() / "presets.json"


def settings_ini_path() -> Path:
    return config_dir() / "settings.ini"
