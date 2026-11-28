"""Qt text scene used by both the preview canvas and the FFmpeg overlay PNG.

Preview and final share this painter so custom fonts, rounded TikTok plates,
stroke and shadow match 1:1. drawtext is only a fallback when Qt cannot paint.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from videouniq.editor.project import TextClip
from videouniq.paths import cache_dir

SAFE_PCT = 0.05
WRAP_PCT = 0.82
PLATE_PAD_X = 18
PLATE_PAD_Y = 10
PLATE_RADIUS = 12

_paint_lock = threading.Lock()
_font_families: dict[str, str] = {}
_qapp = None


def ensure_qapp():
    """Create a QApplication if the process has none (tests / worker encode)."""
    global _qapp
    os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM") or "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        _qapp = QApplication(["videouniq-text"])
        app = _qapp
    return app


def text_fingerprint(clip: TextClip, dx: int = 0, dy: int = 0, width: int = 0, height: int = 0) -> str:
    payload = {
        "t": clip.text,
        "ff": clip.font_family,
        "file": clip.font_file,
        "sz": clip.font_size,
        "sc": round(clip.scale, 4),
        "c": clip.color,
        "st": clip.stroke_enabled,
        "sw": clip.stroke_width,
        "sc2": clip.stroke_color,
        "pl": clip.plate,
        "pc": clip.plate_color,
        "po": round(clip.plate_opacity, 4),
        "sh": clip.shadow,
        "sx": clip.shadow_x,
        "sy": clip.shadow_y,
        "shc": clip.shadow_color,
        "x": round(clip.x_norm, 5),
        "y": round(clip.y_norm, 5),
        "r": round(clip.rotation, 3),
        "dx": int(dx),
        "dy": int(dy),
        "w": int(width),
        "h": int(height),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _resolve_font(clip: TextClip, pixel_size: int):
    from PySide6.QtGui import QFont, QFontDatabase

    family = clip.font_family or "Segoe UI"
    path = clip.font_file or ""
    if path and Path(path).is_file():
        key = str(Path(path).resolve())
        with _paint_lock:
            fam = _font_families.get(key)
            if fam is None:
                fid = QFontDatabase.addApplicationFont(key)
                fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
                fam = fams[0] if fams else family
                _font_families[key] = fam
        family = fam
    font = QFont(family)
    font.setPixelSize(max(8, int(pixel_size)))
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def wrap_text(text: str, metrics, max_width: int) -> list[str]:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for para in text.split("\n") or [""]:
        if not para:
            lines.append("")
            continue
        words = para.split(" ")
        cur = ""
        for word in words:
            trial = word if not cur else f"{cur} {word}"
            if metrics.horizontalAdvance(trial) <= max_width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        if cur or not lines:
            lines.append(cur)
    return lines or [""]


@dataclass
class TextLayout:
    lines: list[str]
    pixel_size: int
    center_x: float
    center_y: float
    box_w: float
    box_h: float
    line_h: float
    text_w: float
    text_h: float
    aabb: tuple[float, float, float, float]


def measure_text(clip: TextClip, width: int, height: int, dx: int = 0, dy: int = 0) -> TextLayout:
    ensure_qapp()
    from PySide6.QtGui import QFontMetrics

    size = max(8, int(round(clip.font_size * clip.scale)))
    font = _resolve_font(clip, size)
    metrics = QFontMetrics(font)
    max_w = max(32, int(width * WRAP_PCT))
    lines = wrap_text(clip.text, metrics, max_w)
    line_h = max(1.0, float(metrics.lineSpacing()))
    text_w = max((metrics.horizontalAdvance(line) for line in lines), default=0)
    text_h = line_h * len(lines)
    box_w = text_w + 2 * PLATE_PAD_X
    box_h = text_h + 2 * PLATE_PAD_Y
    cx = float(clip.x_norm) * width + int(dx)
    cy = float(clip.y_norm) * height + int(dy)
    aabb = _rotated_aabb(cx, cy, box_w, box_h, clip.rotation)
    return TextLayout(
        lines=lines,
        pixel_size=size,
        center_x=cx,
        center_y=cy,
        box_w=box_w,
        box_h=box_h,
        line_h=line_h,
        text_w=text_w,
        text_h=text_h,
        aabb=aabb,
    )


def _rotated_aabb(cx: float, cy: float, w: float, h: float, angle_deg: float) -> tuple[float, float, float, float]:
    import math

    rad = math.radians(angle_deg)
    cos_a, sin_a = math.cos(rad), math.sin(rad)
    hw, hh = w / 2.0, h / 2.0
    xs: list[float] = []
    ys: list[float] = []
    for x, y in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        xs.append(cx + x * cos_a - y * sin_a)
        ys.append(cy + x * sin_a + y * cos_a)
    return min(xs), min(ys), max(xs), max(ys)


def clamp_text_shift(clip: TextClip, width: int, height: int, dx: int, dy: int) -> tuple[int, int]:
    """Keep ±15 px jitter inside the title-safe margin (5% each edge)."""
    mx = max(8.0, width * SAFE_PCT)
    my = max(8.0, height * SAFE_PCT)
    dx, dy = int(dx), int(dy)

    def _ok(jx: int, jy: int) -> bool:
        x0, y0, x1, y1 = measure_text(clip, width, height, jx, jy).aabb
        return x0 >= mx - 0.5 and y0 >= my - 0.5 and x1 <= width - mx + 0.5 and y1 <= height - my + 0.5

    if _ok(dx, dy):
        return dx, dy

    x0, y0, x1, y1 = measure_text(clip, width, height, dx, dy).aabb
    nx = ny = 0.0
    if x0 < mx:
        nx += mx - x0
    if x1 + nx > width - mx:
        nx = (width - mx) - x1
    if y0 < my:
        ny += my - y0
    if y1 + ny > height - my:
        ny = (height - my) - y1
    jx, jy = int(round(dx + nx)), int(round(dy + ny))
    if _ok(jx, jy):
        return jx, jy
    if _ok(0, 0):
        for t in (0.8, 0.6, 0.4, 0.2, 0.0):
            ax, ay = int(round(dx * t)), int(round(dy * t))
            if _ok(ax, ay):
                return ax, ay
        return 0, 0
    return jx, jy


def paint_text_clip(painter, clip: TextClip, width: int, height: int, dx: int = 0, dy: int = 0) -> TextLayout:
    """Paint one text layer in video-pixel coordinates onto ``painter``."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

    layout = measure_text(clip, width, height, dx, dy)
    font = _resolve_font(clip, layout.pixel_size)
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    painter.translate(layout.center_x, layout.center_y)
    painter.rotate(clip.rotation)
    painter.setFont(font)

    box = QRectF(-layout.box_w / 2.0, -layout.box_h / 2.0, layout.box_w, layout.box_h)
    if clip.plate:
        col = QColor(clip.plate_color)
        col.setAlphaF(max(0.0, min(1.0, float(clip.plate_opacity))))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(col)
        painter.drawRoundedRect(box, PLATE_RADIUS, PLATE_RADIUS)

    def _line_path(ox: float, oy: float) -> QPainterPath:
        path = QPainterPath()
        y0 = -layout.text_h / 2.0 + layout.line_h * 0.8
        for i, line in enumerate(layout.lines):
            tw = painter.fontMetrics().horizontalAdvance(line)
            path.addText(ox - tw / 2.0, oy + y0 + i * layout.line_h, font, line)
        return path

    if clip.shadow:
        sh = _line_path(float(clip.shadow_x), float(clip.shadow_y))
        painter.fillPath(sh, QColor(clip.shadow_color))
    body = _line_path(0.0, 0.0)
    if clip.stroke_enabled and clip.stroke_width > 0:
        pen = QPen(QColor(clip.stroke_color))
        pen.setWidth(max(1, int(clip.stroke_width)))
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.strokePath(body, pen)
    painter.fillPath(body, QColor(clip.color))
    painter.restore()
    return layout


def render_text_image(clip: TextClip, width: int, height: int, dx: int = 0, dy: int = 0):
    ensure_qapp()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    w, h = max(2, int(width)), max(2, int(height))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    with _paint_lock:
        p = QPainter(img)
        paint_text_clip(p, clip, w, h, dx, dy)
        p.end()
    return img


def render_text_png(clip: TextClip, width: int, height: int, dx: int = 0, dy: int = 0) -> Path:
    ensure_qapp()
    key = text_fingerprint(clip, dx, dy, width, height)
    dest = cache_dir() / "text" / f"{key}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 32:
        return dest
    img = render_text_image(clip, width, height, dx, dy)
    if not img.save(str(dest), "PNG"):
        raise RuntimeError("не удалось сохранить PNG текста")
    return dest
