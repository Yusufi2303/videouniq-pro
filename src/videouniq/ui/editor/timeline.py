from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from videouniq.editor.ops import packed_starts, text_track_count, timeline_duration
from videouniq.editor.project import EditorProject, TextClip, VideoClip

VIDEO_H = 46
TEXT_H = 28
RULER = 22
GAP = 6
LEFT = 86


class TimelineWidget(QWidget):
    playhead_changed = Signal(float)
    selection_changed = Signal(str, str)  # kind, id
    project_changed = Signal()
    split_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Timeline")
        self.setMinimumHeight(160)
        self.setMouseTracking(True)
        self.project: EditorProject | None = None
        self.playhead = 0.0
        self.px = 72.0
        self.selected = ("", "")
        self._drag = ""
        self._drag_id = ""
        self._origin_x = 0.0
        self._origin_val = 0.0

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self.update()

    def set_playhead(self, t: float) -> None:
        self.playhead = max(0.0, t)
        self.update()

    def duration(self) -> float:
        return max(4.0, timeline_duration(self.project) if self.project else 0.0)

    def _x(self, t: float) -> float:
        return LEFT + t * self.px

    def _t(self, x: float) -> float:
        return max(0.0, (x - LEFT) / max(1.0, self.px))

    def _video_y(self) -> float:
        return RULER + 8

    def _text_y(self, track: int) -> float:
        return self._video_y() + VIDEO_H + 10 + track * (TEXT_H + GAP)

    def sizeHint(self):  # noqa: N802
        from PySide6.QtCore import QSize

        tracks = text_track_count(self.project) if self.project else 2
        return QSize(800, int(self._text_y(tracks) + 16))

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1B1E24"))
        p.setPen(QColor("#9CA3AF"))
        font = QFont()
        font.setPixelSize(11)
        p.setFont(font)
        dur = self.duration()
        for sec in range(0, int(dur) + 2):
            x = self._x(sec)
            p.setPen(QColor("#2A2F3A"))
            p.drawLine(int(x), RULER, int(x), self.height())
            p.setPen(QColor("#9CA3AF"))
            p.drawText(int(x) + 2, 16, f"{sec}s")
        p.setPen(QColor("#9CA3AF"))
        p.drawText(8, int(self._video_y() + 28), "Видео")
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
                p.setPen(QColor("#F3F4F6"))
                name = clip.source_path.rsplit("/", 1)[-1][-18:]
                p.drawText(rect.adjusted(6, 6, -6, -6), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, name)
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
                p.setPen(QColor("#F3F4F6"))
                p.drawText(rect.adjusted(6, 4, -4, -4), clip.text[:24])
        ph = self._x(self.playhead)
        p.setPen(QPen(QColor("#EF4444"), 2))
        p.drawLine(int(ph), 0, int(ph), self.height())
        p.end()

    def _hit_video(self, x: float, y: float) -> tuple[VideoClip, str] | None:
        if self.project is None:
            return None
        if y < self._video_y() or y > self._video_y() + VIDEO_H:
            return None
        starts = packed_starts(self.project.video_clips)
        for i, clip in enumerate(self.project.video_clips):
            x0 = self._x(starts[i])
            x1 = x0 + clip.duration() * self.px
            if x0 <= x <= x1:
                wide = (x1 - x0) >= 24
                edge = "in" if wide and x - x0 < 8 else "out" if wide and x1 - x < 8 else "body"
                return clip, edge
        return None

    def _hit_text(self, x: float, y: float) -> tuple[TextClip, str] | None:
        if self.project is None:
            return None
        for clip in self.project.text_clips:
            x0 = self._x(clip.start)
            x1 = x0 + clip.duration * self.px
            y0 = self._text_y(clip.track)
            if x0 <= x <= x1 and y0 <= y <= y0 + TEXT_H:
                edge = "in" if x - x0 < 8 else "out" if x1 - x < 8 else "body"
                return clip, edge
        return None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if y <= RULER:
            self.playhead_changed.emit(self._t(x))
            self._drag = "playhead"
            return
        hit = self._hit_video(x, y)
        if hit:
            clip, edge = hit
            self.selected = ("video", clip.clip_id)
            self.selection_changed.emit("video", clip.clip_id)
            self._drag = edge if edge != "body" else "move_video"
            self._drag_id = clip.clip_id
            self._origin_x = x
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
        if self.project is None or not self._drag:
            return
        x = event.position().x()
        if self._drag == "playhead":
            self.playhead_changed.emit(self._t(x))
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
            starts = packed_starts(self.project.video_clips)
            idx = self.project.video_clips.index(clip_v)
            target_t = max(0.0, starts[idx] + dt)
            new_i = 0
            for i, c in enumerate(self.project.video_clips):
                mid = starts[i] + c.duration() / 2
                if target_t >= mid:
                    new_i = i
            if new_i != idx:
                from videouniq.editor.ops import reorder_clip

                reorder_clip(self.project, clip_v.clip_id, new_i)
                self._origin_x = x
                self.project_changed.emit()
        elif clip_t and self._drag == "move_text":
            clip_t.start = max(0.0, self._origin_val + dt)
            y = event.position().y()
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
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
            self.px = max(24.0, min(240.0, self.px * factor))
            self.update()
            event.accept()
            return
        super().wheelEvent(event)
