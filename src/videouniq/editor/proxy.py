"""Editor player proxies for sources heavier than 1080p."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from videouniq.paths import cache_dir, ffmpeg_bin

PROXY_MAX_EDGE = 1080


def is_heavy_source(width: int, height: int) -> bool:
    """Proxy only above 1080p. 1080×1920 (9:16 phone) is not heavy."""
    return max(int(width), int(height)) > 1920


def proxy_cache_path(src: str | Path) -> Path:
    p = Path(src)
    try:
        stamp = int(p.stat().st_mtime)
        size = int(p.stat().st_size)
    except OSError:
        stamp, size = 0, 0
    key = hashlib.sha1(f"{p.resolve()}|{stamp}|{size}|p1080max".encode()).hexdigest()[:20]
    return cache_dir() / "proxies" / f"{key}.mp4"


def ensure_proxy(src: str | Path, width: int = 0, height: int = 0, timeout: float = 180.0) -> str:
    """Return a ≤1080p proxy path for heavy files, else the original."""
    src = Path(src)
    if not src.is_file():
        return str(src)
    if width <= 0 or height <= 0:
        try:
            from videouniq.core.probe import probe_media

            info = probe_media(src)
            width, height = info.width, info.height
        except Exception:
            return str(src)
    if not is_heavy_source(width, height):
        return str(src)
    dest = proxy_cache_path(src)
    if dest.is_file() and dest.stat().st_size > 1000:
        try:
            if dest.stat().st_mtime >= src.stat().st_mtime:
                return str(dest)
        except OSError:
            return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale='if(gte(iw,ih),{PROXY_MAX_EDGE},-2)':'if(gte(iw,ih),-2,{PROXY_MAX_EDGE})'"
        ":flags=fast_bilinear,format=yuv420p"
    )
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-fflags",
        "+genpts+discardcorrupt",
        "-ignore_editlist",
        "1",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0 or not dest.is_file() or dest.stat().st_size < 1000:
        dest.unlink(missing_ok=True)
        cmd = [c for c in cmd if c not in {"-hwaccel", "auto"}]
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if dest.is_file() and dest.stat().st_size > 1000:
        return str(dest)
    return str(src)
