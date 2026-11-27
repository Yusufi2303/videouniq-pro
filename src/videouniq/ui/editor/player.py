"""Preview player: libmpv if present, else Qt Multimedia, else FFmpeg frames."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from videouniq.editor.ops import clip_at_time, timeline_duration
from videouniq.editor.project import ASPECTS, EditorProject, TextClip
from videouniq.paths import ffmpeg_bin


def player_backend() -> str:
    try:
        import mpv  # noqa: F401

        return "mpv"
    except Exception:
        pass
    try:
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
        from PySide6.QtMultimediaWidgets import QVideoWidget  # noqa: F401

        return "qt"
    except Exception:
        return "ffmpeg"


def grab_frame(src: str, seconds: float, size: tuple[int, int]) -> QPixmap | None:
    if not src or not Path(src).is_file():
        return None
    w, h = size
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, seconds):.4f}",
        "-i",
        src,
        "-frames:v",
        "1",
        "-vf",
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=8, check=False)
    if proc.returncode != 0 or not proc.stdout:
        return None
    img = QImage.fromData(proc.stdout, "JPG")
    if img.isNull():
        return None
    return QPixmap.fromImage(img)


class CanvasWidget(QWidget):
    text_changed = Signal()
    selection_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CanvasHost")
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.project: EditorProject | None = None
        self.playhead = 0.0
        self.frame = QPixmap()
        self.selected_id = ""
        self._drag = ""
        self._last = QPointF()
        self._guides = False
        self._start_norm = (0.5, 0.5)
        self._start_scale = 1.0
        self._start_rot = 0.0

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self.update()

    def set_frame(self, pix: QPixmap | None) -> None:
        self.frame = pix or QPixmap()
        self.update()

    def canvas_rect(self) -> QRectF:
        if self.project is None:
            return QRectF(self.rect())
        aw, ah = self.project.canvas_width, self.project.canvas_height
        if aw <= 0 or ah <= 0:
            return QRectF(self.rect())
        wr, hr = self.width(), self.height()
        scale = min(wr / aw, hr / ah)
        w, h = aw * scale, ah * scale
        return QRectF((wr - w) / 2, (hr - h) / 2, w, h)

    def visible_texts(self) -> list[TextClip]:
        if self.project is None:
            return []
        t = self.playhead
        return [c for c in self.project.text_clips if c.start <= t <= c.end()]

    def _clip_by_id(self, clip_id: str) -> TextClip | None:
        if self.project is None:
            return None
        return next((c for c in self.project.text_clips if c.clip_id == clip_id), None)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#0B0D10"))
        rect = self.canvas_rect()
        p.fillRect(rect, QColor("#111318"))
        if not self.frame.isNull():
            p.drawPixmap(rect.toRect(), self.frame)
        if self._guides:
            pen = QPen(QColor("#3B82F6"))
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
            p.drawLine(rect.left(), rect.center().y(), rect.right(), rect.center().y())
        for clip in self.visible_texts():
            self._paint_text(p, rect, clip, clip.clip_id == self.selected_id)
        p.end()

    def _paint_text(self, p: QPainter, rect: QRectF, clip: TextClip, selected: bool) -> None:
        font = QFont(clip.font_family)
        if clip.font_file and Path(clip.font_file).is_file():
            fid = QFontDatabase.addApplicationFont(clip.font_file)
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                font = QFont(fams[0])
        font.setPixelSize(max(8, int(clip.font_size * clip.scale * (rect.height() / max(1, self.project.canvas_height if self.project else 1080)))))
        p.save()
        cx = rect.left() + clip.x_norm * rect.width()
        cy = rect.top() + clip.y_norm * rect.height()
        p.translate(cx, cy)
        p.rotate(clip.rotation)
        p.setFont(font)
        metrics = p.fontMetrics()
        box = metrics.boundingRect(clip.text)
        box.adjust(-14, -8, 14, 8)
        box.moveCenter(QPoint(0, 0))
        if clip.plate:
            col = QColor(clip.plate_color)
            col.setAlphaF(clip.plate_opacity)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(box, 8, 8)
        if clip.shadow:
            p.setPen(QColor(clip.shadow_color))
            p.drawText(clip.shadow_x, metrics.ascent() // 2 + clip.shadow_y, clip.text)
        if clip.stroke_enabled and clip.stroke_width > 0:
            pen = QPen(QColor(clip.stroke_color))
            pen.setWidth(max(1, int(clip.stroke_width)))
            p.setPen(pen)
            p.drawText(-metrics.horizontalAdvance(clip.text) // 2, metrics.ascent() // 2, clip.text)
        p.setPen(QColor(clip.color))
        tw = metrics.horizontalAdvance(clip.text)
        p.drawText(-tw // 2, metrics.ascent() // 2, clip.text)
        if selected:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#3B82F6"), 1, Qt.PenStyle.DashLine))
            p.drawRect(box)
            handle = QRectF(-5, box.top() - 18, 10, 10)
            p.setBrush(QColor("#3B82F6"))
            p.drawEllipse(handle)
            corner = QRectF(box.right() - 6, box.bottom() - 6, 10, 10)
            p.drawRect(corner)
        p.restore()

    def _hit(self, pos) -> TextClip | None:
        rect = self.canvas_rect()
        if not rect.contains(pos):
            return None
        nx = (pos.x() - rect.left()) / max(1, rect.width())
        ny = (pos.y() - rect.top()) / max(1, rect.height())
        best = None
        best_d = 0.08
        for clip in reversed(self.visible_texts()):
            d = abs(clip.x_norm - nx) + abs(clip.y_norm - ny)
            if d < best_d:
                best, best_d = clip, d
        return best

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        clip = self._hit(event.position())
        if clip is None:
            self.selected_id = ""
            self.selection_changed.emit("")
            self.update()
            return
        self.selected_id = clip.clip_id
        self.selection_changed.emit(clip.clip_id)
        self._last = event.position()
        self._start_norm = (clip.x_norm, clip.y_norm)
        self._start_scale = clip.scale
        self._start_rot = clip.rotation
        rect = self.canvas_rect()
        cx = rect.left() + clip.x_norm * rect.width()
        cy = rect.top() + clip.y_norm * rect.height()
        # rotate handle roughly above center
        if abs(event.position().y() - (cy - 36)) < 14 and abs(event.position().x() - cx) < 14:
            self._drag = "rotate"
        elif event.position().x() > cx + 20 and event.position().y() > cy + 8:
            self._drag = "scale"
        else:
            self._drag = "move"
        self._guides = self._drag == "move"
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        clip = self._clip_by_id(self.selected_id)
        if not clip or not self._drag:
            return
        rect = self.canvas_rect()
        delta = event.position() - self._last
        if self._drag == "move":
            clip.x_norm = max(0.0, min(1.0, clip.x_norm + delta.x() / max(1, rect.width())))
            clip.y_norm = max(0.0, min(1.0, clip.y_norm + delta.y() / max(1, rect.height())))
            self._guides = True
        elif self._drag == "scale":
            clip.scale = max(0.2, min(4.0, self._start_scale + delta.x() / 120.0))
        elif self._drag == "rotate":
            clip.rotation = max(-180.0, min(180.0, self._start_rot + delta.x() * 0.4))
        self._last = event.position()
        self.text_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag = ""
        self._guides = False
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        clip = self._clip_by_id(self.selected_id)
        if clip is None:
            return
        clip.scale = max(0.2, min(4.0, clip.scale + (0.08 if event.angleDelta().y() > 0 else -0.08)))
        self.text_changed.emit()
        self.update()


class PreviewPlayer(QWidget):
    playhead_changed = Signal(float)
    selection_changed = Signal(str)
    project_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.backend = player_backend()
        self.project: EditorProject | None = None
        self.playhead = 0.0
        self.playing = False
        self._qt_player = None
        self._mpv = None
        self._src = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        cap = QLabel("Плеер")
        cap.setProperty("heading", True)
        top.addWidget(cap)
        top.addStretch(1)
        self.backend_lab = QLabel(self._backend_label())
        self.backend_lab.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        top.addWidget(self.backend_lab)
        self.aspect = QComboBox()
        for key in ASPECTS:
            self.aspect.addItem(key, key)
        self.aspect.currentIndexChanged.connect(self._on_aspect)
        top.addWidget(QLabel("Кадр"))
        top.addWidget(self.aspect)
        layout.addLayout(top)

        self.canvas = CanvasWidget()
        self.canvas.selection_changed.connect(self.selection_changed.emit)
        self.canvas.text_changed.connect(self.project_changed.emit)
        layout.addWidget(self.canvas, 1)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle)
        self.prev_btn = QPushButton("⟨")
        self.prev_btn.setFixedWidth(36)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn = QPushButton("⟩")
        self.next_btn.setFixedWidth(36)
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderMoved.connect(self._seek_frac)
        self.time_lab = QLabel("0:00 / 0:00")
        self.time_lab.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.time_lab)
        layout.addLayout(controls)

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        self._last_grab_t = -1.0
        self._last_grab_src = ""
        self._init_backend()

    def _backend_label(self) -> str:
        return {"mpv": "libmpv", "qt": "Qt Multimedia", "ffmpeg": "FFmpeg / Qt"}.get(self.backend, self.backend)

    def _init_backend(self) -> None:
        if self.backend == "mpv":
            try:
                import mpv

                self._mpv = mpv.MPV(vo="null", pause=True, idle=True)
            except Exception:
                self.backend = "ffmpeg"
                self._mpv = None
        if self.backend == "qt":
            try:
                from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

                self._qt_player = QMediaPlayer(self)
                audio = QAudioOutput(self)
                audio.setVolume(0.0)
                self._qt_player.setAudioOutput(audio)
            except Exception:
                self.backend = "qt_fail"
                self._qt_player = None
                self.backend = "ffmpeg"
        self.backend_lab.setText(self._backend_label())

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self.canvas.set_project(project)
        idx = self.aspect.findData(project.aspect)
        if idx >= 0:
            self.aspect.blockSignals(True)
            self.aspect.setCurrentIndex(idx)
            self.aspect.blockSignals(False)
        self.set_playhead(min(self.playhead, timeline_duration(project)))

    def _on_aspect(self) -> None:
        if self.project is None:
            return
        self.project.aspect = str(self.aspect.currentData() or "9:16")
        self.project.sync_canvas()
        self.project_changed.emit()
        self.refresh_frame()

    def duration(self) -> float:
        return timeline_duration(self.project) if self.project else 0.0

    def fps(self) -> float:
        if self.project and self.project.fps > 1:
            return self.project.fps
        return 30.0

    def toggle(self) -> None:
        if self.playing:
            self.pause()
        else:
            self.play()

    def play(self) -> None:
        if self.duration() <= 0:
            return
        self.playing = True
        self.play_btn.setText("❚❚")
        self._timer.start()

    def pause(self) -> None:
        self.playing = False
        self.play_btn.setText("▶")
        self._timer.stop()
        if self._qt_player is not None:
            self._qt_player.pause()

    def step(self, frames: int) -> None:
        self.pause()
        self.set_playhead(self.playhead + frames / self.fps())

    def set_playhead(self, t: float) -> None:
        dur = self.duration()
        self.playhead = max(0.0, min(t, max(0.0, dur)))
        self.canvas.playhead = self.playhead
        if dur > 0:
            self.seek.blockSignals(True)
            self.seek.setValue(int(self.playhead / dur * 1000))
            self.seek.blockSignals(False)
        self.time_lab.setText(f"{_fmt(self.playhead)} / {_fmt(dur)}")
        self.playhead_changed.emit(self.playhead)
        self.refresh_frame()

    def _seek_frac(self, value: int) -> None:
        dur = self.duration()
        self.set_playhead(dur * value / 1000.0)

    def _tick(self) -> None:
        nxt = self.playhead + self._timer.interval() / 1000.0
        if nxt >= self.duration():
            self.set_playhead(self.duration())
            self.pause()
            return
        self.set_playhead(nxt)

    def refresh_frame(self) -> None:
        if self.project is None:
            self.canvas.set_frame(None)
            return
        hit = clip_at_time(self.project, self.playhead)
        rect = self.canvas.canvas_rect()
        size = (max(160, int(rect.width())), max(160, int(rect.height())))
        if hit is None:
            self.canvas.set_frame(None)
            return
        _, clip, local = hit
        if self.playing and clip.source_path == self._last_grab_src and abs(local - self._last_grab_t) < 0.12:
            self.canvas.update()
            return
        pix = grab_frame(clip.source_path, local, size)
        self._last_grab_t = local
        self._last_grab_src = clip.source_path
        self.canvas.set_frame(pix)
        if self._qt_player is not None and clip.source_path != self._src:
            self._src = clip.source_path
            self._qt_player.setSource(QUrl.fromLocalFile(clip.source_path))
        if self._mpv is not None and clip.source_path:
            try:
                self._mpv.command("seek", local, "absolute")
            except Exception:
                pass


def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"
