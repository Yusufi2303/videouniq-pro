from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from videouniq.paths import ffprobe_bin

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


@dataclass(frozen=True)
class MediaInfo:
    path: str
    width: int
    height: int
    fps: float
    duration: float
    size_bytes: int
    has_video: bool
    has_audio: bool
    codec_video: str
    codec_audio: str
    pix_fmt: str
    color_space: str
    color_primaries: str
    color_trc: str
    color_range: str
    audio_rate: int
    audio_channels: int

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def resolution_label(self) -> str:
        return f"{self.width}×{self.height}"

    @property
    def fps_label(self) -> str:
        if self.fps <= 0:
            return "—"
        if abs(self.fps - round(self.fps)) < 0.03:
            return f"{int(round(self.fps))} FPS"
        return f"{self.fps:.2f} FPS"

    @property
    def duration_label(self) -> str:
        total = max(0, int(self.duration))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @property
    def size_label(self) -> str:
        n = float(self.size_bytes)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if n < 1024 or unit == "ГБ":
                if unit == "Б":
                    return f"{int(n)} {unit}"
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{self.size_bytes} Б"


def _parse_fps(rate: str) -> float:
    if not rate or rate in {"0/0", "N/A"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _sane_fps(avg: float, raw: float) -> float:
    """Phone MP4s often report avg_frame_rate like 100/1 or 90k/900. Keep 1–60."""
    candidates = [x for x in (avg, raw) if x and 1.0 < x <= 60.5]
    if candidates:
        if avg in candidates:
            return avg
        return candidates[0]
    if raw > 60.5 and 1.0 < raw / 2 <= 60.5:
        return raw / 2
    return 30.0


def _rotation_deg(video: dict) -> float:
    tags = video.get("tags") or {}
    try:
        rot = float(tags.get("rotate") or 0)
    except (TypeError, ValueError):
        rot = 0.0
    for item in video.get("side_data_list") or []:
        if not isinstance(item, dict):
            continue
        if "rotation" in item:
            try:
                rot = float(item.get("rotation") or rot)
            except (TypeError, ValueError):
                continue
    return rot


def _color(value: str, fallback: str) -> str:
    if not value or value in {"unknown", "unspecified", "N/A"}:
        return fallback
    return value


def probe_media(path: str | Path, timeout: float = 30.0) -> MediaInfo:
    src = Path(path)
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(src),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffprobe failed").strip()
        raise RuntimeError(err.splitlines()[-1] if err else "ffprobe failed")

    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise RuntimeError("В файле нет видеопотока")

    duration = 0.0
    for candidate in (fmt.get("duration"), video.get("duration"), audio.get("duration") if audio else None):
        if candidate:
            try:
                duration = float(candidate)
                break
            except (TypeError, ValueError):
                continue

    size_bytes = 0
    try:
        size_bytes = int(fmt.get("size") or src.stat().st_size)
    except OSError:
        size_bytes = int(fmt.get("size") or 0)

    avg = _parse_fps(video.get("avg_frame_rate") or "")
    raw = _parse_fps(video.get("r_frame_rate") or "")
    fps = _sane_fps(avg, raw)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rot = _rotation_deg(video)
    if abs(rot) % 180.0 >= 45.0:
        width, height = height, width
    if width <= 0 or height <= 0:
        raise RuntimeError("Не удалось определить разрешение")

    return MediaInfo(
        path=str(src.resolve()),
        width=width,
        height=height,
        fps=fps,
        duration=duration,
        size_bytes=size_bytes,
        has_video=True,
        has_audio=audio is not None,
        codec_video=str(video.get("codec_name") or ""),
        codec_audio=str((audio or {}).get("codec_name") or ""),
        pix_fmt=str(video.get("pix_fmt") or "yuv420p"),
        color_space=_color(str(video.get("color_space") or ""), "bt709"),
        color_primaries=_color(str(video.get("color_primaries") or ""), "bt709"),
        color_trc=_color(str(video.get("color_transfer") or ""), "bt709"),
        color_range=_color(str(video.get("color_range") or ""), "tv"),
        audio_rate=int((audio or {}).get("sample_rate") or 48000),
        audio_channels=int((audio or {}).get("channels") or 2),
    )


def is_video_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def collect_videos(paths: list[str | Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        candidates: list[Path] = []
        if p.is_dir():
            for child in sorted(p.rglob("*")):
                if child.is_file() and is_video_file(child) and not child.name.startswith("."):
                    candidates.append(child)
        elif p.is_file() and is_video_file(p):
            candidates.append(p)
        for item in candidates:
            key = str(item.resolve())
            if key not in seen:
                seen.add(key)
                found.append(item)
    return found
