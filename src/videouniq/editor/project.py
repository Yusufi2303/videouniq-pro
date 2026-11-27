"""VideoUniq Pro project (.vup) JSON model."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Literal

FORMAT = "videouniq-project"
VERSION = 2

AspectName = Literal["9:16", "16:9", "1:1", "original"]
TransitionName = Literal["none", "crossfade", "fade_black"]

ASPECTS: dict[str, tuple[int, int] | None] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "original": None,
}
TRANSITIONS: tuple[str, ...] = ("none", "crossfade", "fade_black")


def _id() -> str:
    return uuid.uuid4().hex[:10]


def _clip_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    valid = {f.name for f in fields(cls)}
    return {k: v for k, v in data.items() if k in valid}


@dataclass
class VideoClip:
    clip_id: str = field(default_factory=_id)
    source_path: str = ""
    in_point: float = 0.0
    out_point: float = 0.0
    volume: float = 1.0
    muted: bool = False
    transition: str = "none"
    transition_duration: float = 0.5
    source_duration: float = 0.0
    source_width: int = 0
    source_height: int = 0
    source_fps: float = 30.0
    has_audio: bool = True

    def duration(self) -> float:
        return max(0.04, float(self.out_point) - float(self.in_point))

    def clamped(self) -> VideoClip:
        src = self.source_duration if self.source_duration > 0 else max(self.out_point, 0.04)
        self.in_point = max(0.0, min(float(self.in_point), max(0.0, src - 0.04)))
        self.out_point = max(self.in_point + 0.04, min(float(self.out_point), src if src > 0 else self.out_point))
        self.volume = max(0.0, min(2.0, float(self.volume)))
        if self.transition not in TRANSITIONS:
            self.transition = "none"
        self.transition_duration = max(0.2, min(1.5, float(self.transition_duration)))
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> VideoClip:
        raw = dict(data or {})
        if "clip_id" not in raw and "id" in raw:
            raw["clip_id"] = raw["id"]
        return cls(**_clip_fields(cls, raw)).clamped()


@dataclass
class TextClip:
    clip_id: str = field(default_factory=_id)
    text: str = "Текст"
    track: int = 0
    start: float = 0.0
    duration: float = 3.0
    font_family: str = "Segoe UI"
    font_file: str = ""
    font_size: int = 48
    color: str = "#FFFFFF"
    stroke_enabled: bool = True
    stroke_width: int = 3
    stroke_color: str = "#000000"
    plate: bool = False
    plate_color: str = "#000000"
    plate_opacity: float = 0.55
    shadow: bool = True
    shadow_x: int = 2
    shadow_y: int = 2
    shadow_color: str = "#000000"
    x_norm: float = 0.5
    y_norm: float = 0.78
    scale: float = 1.0
    rotation: float = 0.0

    def end(self) -> float:
        return max(0.0, float(self.start) + max(0.04, float(self.duration)))

    def clamped(self) -> TextClip:
        self.track = max(0, int(self.track))
        self.start = max(0.0, float(self.start))
        self.duration = max(0.04, float(self.duration))
        self.font_size = max(8, min(240, int(self.font_size)))
        self.stroke_width = max(0, min(20, int(self.stroke_width)))
        self.plate_opacity = max(0.0, min(1.0, float(self.plate_opacity)))
        self.x_norm = max(0.0, min(1.0, float(self.x_norm)))
        self.y_norm = max(0.0, min(1.0, float(self.y_norm)))
        self.scale = max(0.2, min(4.0, float(self.scale)))
        self.rotation = max(-180.0, min(180.0, float(self.rotation)))
        if not self.color.startswith("#"):
            self.color = "#FFFFFF"
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TextClip:
        raw = dict(data or {})
        if "clip_id" not in raw and "id" in raw:
            raw["clip_id"] = raw["id"]
        return cls(**_clip_fields(cls, raw)).clamped()


@dataclass
class TextStylePreset:
    name: str = "Стиль"
    font_family: str = "Segoe UI"
    font_file: str = ""
    font_size: int = 48
    color: str = "#FFFFFF"
    stroke_enabled: bool = True
    stroke_width: int = 3
    stroke_color: str = "#000000"
    plate: bool = False
    plate_color: str = "#000000"
    plate_opacity: float = 0.55
    shadow: bool = True
    shadow_x: int = 2
    shadow_y: int = 2
    shadow_color: str = "#000000"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TextStylePreset:
        return cls(**_clip_fields(cls, dict(data or {})))

    def apply_to(self, clip: TextClip) -> None:
        clip.font_family = self.font_family
        clip.font_file = self.font_file
        clip.font_size = self.font_size
        clip.color = self.color
        clip.stroke_enabled = self.stroke_enabled
        clip.stroke_width = self.stroke_width
        clip.stroke_color = self.stroke_color
        clip.plate = self.plate
        clip.plate_color = self.plate_color
        clip.plate_opacity = self.plate_opacity
        clip.shadow = self.shadow
        clip.shadow_x = self.shadow_x
        clip.shadow_y = self.shadow_y
        clip.shadow_color = self.shadow_color


DEFAULT_PRESETS = [
    TextStylePreset(name="Белый", color="#FFFFFF", stroke_enabled=True, plate=False),
    TextStylePreset(name="ТикТок", color="#FFFFFF", plate=True, plate_color="#000000", plate_opacity=0.62, stroke_enabled=False, shadow=False, font_size=52),
    TextStylePreset(name="Жёлтый", color="#FDE047", stroke_enabled=True, stroke_color="#111827", plate=False),
]


@dataclass
class EditorProject:
    name: str = "Без названия"
    aspect: str = "9:16"
    fps: float = 30.0
    canvas_width: int = 1080
    canvas_height: int = 1920
    shift_text_on_uniquize: bool = True
    video_clips: list[VideoClip] = field(default_factory=list)
    text_clips: list[TextClip] = field(default_factory=list)
    text_presets: list[TextStylePreset] = field(default_factory=lambda: [p for p in DEFAULT_PRESETS])
    media_bin: list[str] = field(default_factory=list)
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "version": VERSION,
            "name": self.name,
            "aspect": self.aspect,
            "fps": self.fps,
            "canvas_width": self.canvas_width,
            "canvas_height": self.canvas_height,
            "shift_text_on_uniquize": self.shift_text_on_uniquize,
            "video_clips": [c.to_dict() for c in self.video_clips],
            "text_clips": [c.to_dict() for c in self.text_clips],
            "text_presets": [p.to_dict() for p in self.text_presets],
            "media_bin": list(self.media_bin),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> EditorProject:
        raw = data or {}
        aspect = str(raw.get("aspect") or "9:16")
        if aspect not in ASPECTS:
            aspect = "9:16"
        proj = cls(
            name=str(raw.get("name") or "Без названия"),
            aspect=aspect,
            fps=float(raw.get("fps") or 30.0),
            canvas_width=int(raw.get("canvas_width") or 1080),
            canvas_height=int(raw.get("canvas_height") or 1920),
            shift_text_on_uniquize=bool(raw.get("shift_text_on_uniquize", True)),
            video_clips=[VideoClip.from_dict(x) for x in (raw.get("video_clips") or [])],
            text_clips=[TextClip.from_dict(x) for x in (raw.get("text_clips") or [])],
            text_presets=[TextStylePreset.from_dict(x) for x in (raw.get("text_presets") or DEFAULT_PRESETS)],
            media_bin=[str(p) for p in (raw.get("media_bin") or [])],
            path=str(raw.get("path") or ""),
        )
        if not proj.text_presets:
            proj.text_presets = [p for p in DEFAULT_PRESETS]
        proj.sync_canvas()
        return proj

    @classmethod
    def from_json(cls, text: str) -> EditorProject:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("Некорректный проект")
        fmt = str(data.get("format") or "")
        if fmt and fmt != FORMAT:
            raise ValueError(f"Неизвестный формат: {fmt}")
        return cls.from_dict(data)

    @classmethod
    def load(cls, path: str | Path) -> EditorProject:
        p = Path(path)
        proj = cls.from_json(p.read_text(encoding="utf-8"))
        proj.path = str(p.resolve())
        if proj.name in {"", "Без названия"}:
            proj.name = p.stem
        return proj

    def save(self, path: str | Path | None = None) -> Path:
        dest = Path(path or self.path)
        if not dest.suffix:
            dest = dest.with_suffix(".vup")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.to_json(), encoding="utf-8")
        self.path = str(dest.resolve())
        return dest

    def sync_canvas(self) -> tuple[int, int]:
        from videouniq.core.filters import even

        size = ASPECTS.get(self.aspect)
        if size is None:
            first = next((c for c in self.video_clips if c.source_width and c.source_height), None)
            if first:
                w, h = even(first.source_width), even(first.source_height)
            else:
                w, h = 1080, 1920
        else:
            w, h = size
        self.canvas_width, self.canvas_height = even(w), even(h)
        if self.fps <= 1:
            fps = next((c.source_fps for c in self.video_clips if c.source_fps > 1), 30.0)
            self.fps = fps or 30.0
        return self.canvas_width, self.canvas_height

    def add_media_path(self, path: str) -> None:
        key = str(Path(path).resolve()) if path else path
        if key and key not in self.media_bin:
            self.media_bin.append(key)

    def missing_sources(self) -> list[str]:
        missing = []
        for clip in self.video_clips:
            if clip.source_path and not Path(clip.source_path).is_file():
                missing.append(clip.source_path)
        return missing
