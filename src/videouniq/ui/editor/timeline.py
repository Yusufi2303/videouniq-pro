from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QScrollBar, QWidget

from videouniq.editor.ops import packed_starts, text_track_count, timeline_duration
from videouniq.editor.project import EditorProject, TextClip, VideoClip

VIDEO_H = 46
TEXT_H = 28
RULER = 22
GAP = 6
LEFT = 86
EDGE = 14
PAD_RIGHT = 64
BAR_H = 14
MIN_PX = 6.0
MAX_PX = 240.0


class TimelineWidget(QWidget):
    playhead_changed = Signal(float)
    selection_changed = Signal(str, str)  # kind, id
    project_changed = Signal()
    split_requested = Signal()
    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Timeline")
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setAcceptDrops(True)
        self.project: EditorProject | None = None
        self.playhead = 0.0
        self.px = 48.0
        self.scroll = 0.0
        self.selected = ("", "")
        self._drag = ""
        self._drag_id = ""
        self._origin_x = 0.0
        self._origin_val = 0.0
        self._origin_scroll = 0.0
        self._bar = QScrollBar(Qt.Orientation.Horizontal, self)
        self._bar.setObjectName("TimelineScroll")
        self._bar.valueChanged.connect(self._on_bar)
        self._bar.setVisible(False)

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self._clamp_scroll()
        self.update()

    def set_playhead(self, t: float) -> None:
        self.playhead = max(0.0, t)
        self.ensure_playhead_visible()
        self.update()

    def duration(self) -> float:
        return max(4.0, timeline_duration(self.project) if self.project else 0.0)

    def content_width(self) -> float:
        return self.duration() * self.px + PAD_RIGHT

    def usable_width(self) -> float:
        return max(80.0, float(self.width()) - LEFT - 8)

    def max_scroll(self) -> float:
        return max(0.0, self.content_width() - self.usable_width())

    def _x(self, t: float) -> float:
        return LEFT + t * self.px - self.scroll

    def _t(self, x: float) -> float:
        return max(0.0, (x - LEFT + self.scroll) / max(1.0, self.px))

    def _video_y(self) -> float:
        return RULER + 8

    def _text_y(self, track: int) -> float:
        return self._video_y() + VIDEO_H + 10 + track * (TEXT_H + GAP)

    def _bar_top(self) -> int:
        return max(0, self.height() - BAR_H)

    def _clamp_scroll(self) -> None:
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))
        self._sync_bar()

    def _sync_bar(self) -> None:
        mx = int(round(self.max_scroll()))
        self._bar.blockSignals(True)
        self._bar.setRange(0, mx)
        self._bar.setPageStep(max(20, int(self.usable_width())))
        self._bar.setSingleStep(max(8, int(self.px)))
        self._bar.setValue(int(round(self.scroll)))
        self._bar.setVisible(mx > 0)
        self._bar.blockSignals(False)
        self._layout_bar()

    def _layout_bar(self) -> None:
        y = self._bar_top()
        self._bar.setGeometry(LEFT, y, max(40, self.width() - LEFT), BAR_H)

    def _on_bar(self, value: int) -> None:
        self.scroll = float(value)
        self.update()

    def pan_by(self, pixels: float) -> None:
        self.scroll = max(0.0, min(self.max_scroll(), self.scroll + pixels))
        self._sync_bar()
        self.update()

    def ensure_playhead_visible(self, margin: float = 56.0) -> None:
        if self.width() <= LEFT + 40:
            return
        x = self._x(self.playhead)
        left = LEFT + 12
        right = self.width() - 20
        if x > right - margin:
            self.scroll = min(self.max_scroll(), self.scroll + (x - (right - margin)))
        elif x < left + 8:
            self.scroll = max(0.0, self.scroll - ((left + 8) - x))
        self._sync_bar()

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        tracks = text_track_count(self.project) if self.project else 2
        return QSize(800, int(self._text_y(tracks) + 20 + BAR_H))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._clamp_scroll()
        self.ensure_playhead_visible()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1B1E24"))
        p.setPen(QColor("#9CA3AF"))
        font = QFont()
        font.setPixelSize(11)
        p.setFont(font)
        dur = self.duration()
        t0 = max(0.0, self._t(LEFT))
        t1 = self._t(self.width()) + 1.0
        step = 1
        if self.px < 8:
            step = 30
        elif self.px < 14:
            step = 10
        elif self.px < 28:
            step = 5
        elif self.px < 44:
            step = 2
        sec0 = int(t0) - (int(t0) % step)
        for sec in range(sec0, int(t1) + step, step):
            x = self._x(sec)
            if x < LEFT - 2 or x > self.width():
                continue
            p.setPen(QColor("#2A2F3A"))
            p.drawLine(int(x), RULER, int(x), self.height())
            p.setPen(QColor("#9CA3AF"))
            p.drawText(int(x) + 2, 16, _ruler_label(sec))
        p.setPen(QColor("#9CA3AF"))
        p.drawText(8, int(self._video_y() + 28), "Видео")
        p.save()
        p.setClipRect(LEFT, 0, max(1, self.width() - LEFT), self.height())
        if self.project:
            starts = packed_starts(self.project.video_clips)
            for i, clip in enumerate(self.project.video_clips):
                x = self._x(starts[i])
                w = max(8, clip.duration() * self.px)
                rect = QRectF(x, self._video_y(), w, VIDEO_H)
                selected = self.selected == ("video", clip.clip_id)
                p.setBrush(QColor("#2563EB" if selected else "#1D4ED8"))
                p.setPen(QColor("#93C5FD") if selected else QColor("#1E3A8A"))
                p.drawRoundedRect(rect, 6, 6)
                if selected:
                    self._paint_edge_handles(p, rect)
                p.setPen(QColor("#F3F4F6"))
                name = Path(clip.source_path).name[-22:] if clip.source_path else "клип"
                p.drawText(rect.adjusted(8, 6, -8, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
                if clip.transition != "none" and i < len(self.project.video_clips) - 1:
                    p.setPen(QColor("#F59E0B"))
                    label = "×фэйд" if clip.transition == "crossfade" else "чёрн."
                    p.drawText(int(x + w - 40), int(self._video_y() + VIDEO_H - 6), label)
            tracks = text_track_count(self.project)
            for tr in range(tracks):
                p.setPen(QColor("#9CA3AF"))
                p.drawText(8, int(self._text_y(tr) + 18), f"Текст {tr + 1}")
            for clip in self.project.text_clips:
                x = self._x(clip.start)
                w = max(8, clip.duration * self.px)
                rect = QRectF(x, self._text_y(clip.track), w, TEXT_H)
                selected = self.selected == ("text", clip.clip_id)
                p.setBrush(QColor("#059669" if selected else "#065F46"))
                p.setPen(QColor("#6EE7B7") if selected else QColor("#064E3B"))
                p.drawRoundedRect(rect, 5, 5)
                if selected:
                    self._paint_edge_handles(p, rect)
                p.setPen(QColor("#F3F4F6"))
                p.drawText(rect.adjusted(8, 4, -6, -4), (clip.text or "Текст")[:24])
        ph = self._x(self.playhead)
        p.setPen(QPen(QColor("#EF4444"), 2))
        p.drawLine(int(ph), 0, int(ph), self.height())
        p.restore()
        p.fillRect(0, 0, LEFT, self.height(), QColor("#1B1E24"))
        p.setPen(QColor("#9CA3AF"))
        p.drawText(8, int(self._video_y() + 28), "Видео")
        if self.project:
            tracks = text_track_count(self.project)
            for tr in range(tracks):
                p.drawText(8, int(self._text_y(tr) + 18), f"Текст {tr + 1}")
        p.end()

    def _paint_edge_handles(self, p: QPainter, rect: QRectF) -> None:
        grip_w = 5.0
        p.setBrush(QColor("#F8FAFC"))
        p.setPen(QColor("#93C5FD"))
        left = QRectF(rect.left() + 2, rect.top() + 8, grip_w, max(12.0, rect.height() - 16))
        right = QRectF(rect.right() - grip_w - 2, rect.top() + 8, grip_w, max(12.0, rect.height() - 16))
        p.drawRoundedRect(left, 2, 2)
        p.drawRoundedRect(right, 2, 2)

    def _hit_video(self, x: float, y: float) -> tuple[VideoClip, str] | None:
        if self.project is None:
            return None
        if y < self._video_y() or y > self._video_y() + VIDEO_H:
            return None
        starts = packed_starts(self.project.video_clips)
        for i, clip in enumerate(self.project.video_clips):
            x0 = self._x(starts[i])
            x1 = x0 + clip.duration() * self.px
            if x0 - 2 <= x <= x1 + 2:
                # Short split pieces must stay grabable for reorder; keep trim to the rims.
                span = x1 - x0
                edge_px = 4.0 if span < 48 else min(float(EDGE), span * 0.12)
                if x - x0 <= edge_px:
                    return clip, "in"
                if x1 - x <= edge_px:
                    return clip, "out"
                return clip, "body"
        return None

    def _hit_text(self, x: float, y: float) -> tuple[TextClip, str] | None:
        if self.project is None:
            return None
        for clip in self.project.text_clips:
            x0 = self._x(clip.start)
            x1 = x0 + clip.duration * self.px
            y0 = self._text_y(clip.track)
            if x0 - 2 <= x <= x1 + 2 and y0 <= y <= y0 + TEXT_H:
                edge_px = EDGE if (x1 - x0) >= 28 else max(6.0, (x1 - x0) * 0.28)
                if x - x0 <= edge_px:
                    return clip, "in"
                if x1 - x <= edge_px:
                    return clip, "out"
                return clip, "body"
        return None

    def _edge_autoscroll(self, x: float) -> None:
        left = LEFT + 24
        right = self.width() - 24
        if x > right:
            self.pan_by(min(80.0, x - right))
        elif x < left:
            self.pan_by(-min(80.0, left - x))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        x, y = event.position().x(), event.position().y()
        if event.button() == Qt.MouseButton.MiddleButton:
            self._drag = "pan"
            self._origin_x = x
            self._origin_scroll = self.scroll
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._drag = "pan"
            self._origin_x = x
            self._origin_scroll = self.scroll
            return
        if y >= self._bar_top() - 2 and self._bar.isVisible():
            return
        if y <= RULER:
            self.playhead_changed.emit(self._t(x))
            self._drag = "playhead"
            return
        hit = self._hit_video(x, y)
        if hit:
            clip, edge = hit
            self.selected = ("video", clip.clip_id)
            self.selection_changed.emit("video", clip.clip_id)
            nclips = len(self.project.video_clips) if self.project else 0
            if edge in {"in", "out"}:
                self._drag = edge
            elif nclips > 1:
                self._drag = "move_video"
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            else:
                self._drag = "pan"
            self._drag_id = clip.clip_id
            self._origin_x = x
            self._origin_scroll = self.scroll
            self._origin_val = packed_starts(self.project.video_clips)[self.project.video_clips.index(clip)]
            self.update()
            return
        th = self._hit_text(x, y)
        if th:
            clip, edge = th
            self.selected = ("text", clip.clip_id)
            self.selection_changed.emit("text", clip.clip_id)
            self._drag = "trim_text_in" if edge == "in" else "trim_text_out" if edge == "out" else "move_text"
            self._drag_id = clip.clip_id
            self._origin_x = x
            self._origin_val = clip.start
            self.update()
            return
        self.playhead_changed.emit(self._t(x))
        self._drag = "playhead"

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        x = event.position().x()
        y = event.position().y()
        if not (event.buttons() & (Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton)):
            hit = self._hit_video(x, y) or self._hit_text(x, y)
            nclips = len(self.project.video_clips) if self.project else 0
            if hit and hit[1] in {"in", "out"}:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            elif hit and hit[1] == "body" and nclips > 1:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if self._drag == "pan":
            self.scroll = max(0.0, min(self.max_scroll(), self._origin_scroll - (x - self._origin_x)))
            self._sync_bar()
            self.update()
            return
        if self.project is None or not self._drag:
            return
        self._edge_autoscroll(x)
        if self._drag == "playhead":
            self.playhead_changed.emit(min(self.duration(), self._t(x)))
            self.ensure_playhead_visible()
            return
        clip_v = next((c for c in self.project.video_clips if c.clip_id == self._drag_id), None)
        clip_t = next((c for c in self.project.text_clips if c.clip_id == self._drag_id), None)
        dt = (x - self._origin_x) / self.px
        if clip_v and self._drag == "in":
            clip_v.in_point = clip_v.in_point + dt
            clip_v.clamped()
            self._origin_x = x
            self.project_changed.emit()
        elif clip_v and self._drag == "out":
            clip_v.out_point = clip_v.out_point + dt
            clip_v.clamped()
            self._origin_x = x
            self.project_changed.emit()
        elif clip_v and self._drag == "move_video":
            new_i = self._insert_index_at(x, clip_v.clip_id)
            idx = self.project.video_clips.index(clip_v)
            if new_i != idx:
                from videouniq.editor.ops import reorder_clip

                reorder_clip(self.project, clip_v.clip_id, new_i)
                self._origin_x = x
                self.project_changed.emit()
        elif clip_t and self._drag == "move_text":
            clip_t.start = max(0.0, self._origin_val + dt)
            tracks = text_track_count(self.project)
            for tr in range(tracks):
                y0 = self._text_y(tr)
                if y0 <= y <= y0 + TEXT_H + GAP:
                    clip_t.track = tr
            self.project_changed.emit()
        elif clip_t and self._drag == "trim_text_in":
            new_start = max(0.0, self._origin_val + dt)
            delta = new_start - clip_t.start
            if clip_t.duration - delta >= 0.2:
                clip_t.start = new_start
                clip_t.duration -= delta
                self._origin_val = clip_t.start
                self._origin_x = x
                self.project_changed.emit()
        elif clip_t and self._drag == "trim_text_out":
            clip_t.duration = max(0.2, clip_t.duration + dt)
            self._origin_x = x
            self.project_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag = ""
        self._drag_id = ""
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.12 if delta.y() > 0 else 1 / 1.12
            old = self.px
            self.px = max(MIN_PX, min(MAX_PX, self.px * factor))
            center_t = self._t(self.width() / 2)
            self.scroll = max(0.0, center_t * self.px - (self.usable_width() / 2))
            del old
            self._clamp_scroll()
            self.ensure_playhead_visible()
            event.accept()
            return
        dx = delta.x()
        dy = delta.y()
        pixels = -dx if abs(dx) > abs(dy) else -dy
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier and abs(dy) >= abs(dx):
            pixels = -dy
        self.pan_by(pixels)
        event.accept()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def _insert_index_at(self, x: float, exclude_id: str) -> int:
        if self.project is None or not self.project.video_clips:
            return 0
        clips = self.project.video_clips
        hit = self._hit_video(x, self._video_y() + 8)
        if hit is not None and hit[0].clip_id != exclude_id:
            return clips.index(hit[0])
        t = self._t(x)
        starts = packed_starts(clips)
        for i, clip in enumerate(clips):
            if t < starts[i] + clip.duration() / 2:
                return i
        return len(clips) - 1


def _ruler_label(sec: int) -> str:
    sec = max(0, int(sec))
    if sec < 60:
        return f"{sec}s"
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"
