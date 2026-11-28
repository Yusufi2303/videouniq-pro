"""Preview player: libmpv if present, else Qt Multimedia, else FFmpeg frames."""

from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
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
from videouniq.editor.proxy import ensure_proxy, is_heavy_source
from videouniq.editor.text_paint import render_text_image, text_fingerprint
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


class GrabBridge(QObject):
    done = Signal(object, str, float, int, int)


class GrabTask(QRunnable):
    def __init__(self, src: str, seconds: float, size: tuple[int, int], bridge: GrabBridge) -> None:
        super().__init__()
        self.src = src
        self.seconds = seconds
        self.size = size
        self.bridge = bridge

    def run(self) -> None:
        pix = grab_frame(self.src, self.seconds, self.size)
        self.bridge.done.emit(pix, self.src, self.seconds, self.size[0], self.size[1])


def grab_frame(
    src: str,
    seconds: float,
    size: tuple[int, int],
    hwaccel: bool = True,
) -> QPixmap | None:
    if not src or not Path(src).is_file():
        return None
    w, h = size

    def _once(use_hw: bool) -> QPixmap | None:
        cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error"]
        if use_hw:
            cmd += ["-hwaccel", "auto"]
        cmd += [
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
        proc = subprocess.run(cmd, capture_output=True, timeout=12, check=False)
        if proc.returncode != 0 or not proc.stdout:
            return None
        img = QImage.fromData(proc.stdout, "JPG")
        if img.isNull():
            return None
        return QPixmap.fromImage(img)

    pix = _once(hwaccel)
    if pix is None and hwaccel:
        pix = _once(False)
    return pix


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
        self._press = QPointF()
        self.loading = False
        self._img_cache: dict[str, tuple[str, QImage]] = {}

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
            img = self._text_image(clip)
            if img is not None and not img.isNull():
                p.drawImage(rect, img)
            if clip.clip_id == self.selected_id:
                self._paint_handles(p, rect, clip)
        if self.loading:
            badge = QRectF(rect.right() - 168, rect.top() + 10, 156, 28)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(17, 19, 24, 200))
            p.drawRoundedRect(badge, 8, 8)
            p.setPen(QColor("#E5E7EB"))
            p.drawText(badge, int(Qt.AlignmentFlag.AlignCenter), "Загрузка кадра…")
        p.end()

    def _text_image(self, clip: TextClip) -> QImage | None:
        if self.project is None:
            return None
        w, h = self.project.canvas_width, self.project.canvas_height
        key = text_fingerprint(clip, 0, 0, w, h)
        hit = self._img_cache.get(clip.clip_id)
        if hit and hit[0] == key:
            return hit[1]
        try:
            img = render_text_image(clip, w, h, 0, 0)
        except Exception:
            return None
        self._img_cache[clip.clip_id] = (key, img)
        return img

    def _paint_handles(self, p: QPainter, rect: QRectF, clip: TextClip) -> None:
        p.save()
        cx = rect.left() + clip.x_norm * rect.width()
        cy = rect.top() + clip.y_norm * rect.height()
        p.translate(cx, cy)
        p.rotate(clip.rotation)
        scale = rect.height() / max(1.0, float(self.project.canvas_height if self.project else 1080))
        bw = max(48.0, (clip.font_size * clip.scale * 0.6 + 36) * scale)
        bh = max(28.0, (clip.font_size * clip.scale + 20) * scale)
        box = QRectF(-bw / 2, -bh / 2, bw, bh)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#3B82F6"), 1, Qt.PenStyle.DashLine))
        p.drawRect(box)
        p.setBrush(QColor("#3B82F6"))
        p.drawEllipse(QRectF(-5, box.top() - 18, 10, 10))
        p.drawRect(QRectF(box.right() - 6, box.bottom() - 6, 10, 10))
        p.restore()

    def clip_center(self, clip: TextClip) -> QPointF:
        rect = self.canvas_rect()
        return QPointF(rect.left() + clip.x_norm * rect.width(), rect.top() + clip.y_norm * rect.height())

    def _hit(self, pos) -> TextClip | None:
        pt = QPointF(pos)
        rect = self.canvas_rect()
        if not rect.contains(pt):
            return None
        best = None
        best_d = 1e9
        for clip in reversed(self.visible_texts()):
            c = self.clip_center(clip)
            d = abs(c.x() - pt.x()) + abs(c.y() - pt.y())
            # Generous hit box so a real mouse can grab the overlay.
            if d < max(48.0, 0.12 * min(rect.width(), rect.height())) and d < best_d:
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
        self._last = QPointF(event.position())
        self._press = QPointF(event.position())
        self._start_norm = (clip.x_norm, clip.y_norm)
        self._start_scale = clip.scale
        self._start_rot = clip.rotation
        c = self.clip_center(clip)
        dx = event.position().x() - c.x()
        dy = event.position().y() - c.y()
        if dy < -20 and abs(dx) < 22:
            self._drag = "rotate"
        elif dx > 10 and dy > 2:
            self._drag = "scale"
        else:
            self._drag = "move"
        self._guides = self._drag == "move"
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        clip = self._clip_by_id(self.selected_id)
        if not clip or not self._drag:
            return
        rect = self.canvas_rect()
        pos = QPointF(event.position())
        if self._drag == "move":
            delta = pos - self._last
            clip.x_norm = max(0.0, min(1.0, clip.x_norm + delta.x() / max(1.0, rect.width())))
            clip.y_norm = max(0.0, min(1.0, clip.y_norm + delta.y() / max(1.0, rect.height())))
            self._guides = True
        elif self._drag == "scale":
            clip.scale = max(0.2, min(4.0, self._start_scale + (pos.x() - self._press.x()) / 120.0))
        elif self._drag == "rotate":
            clip.rotation = max(-180.0, min(180.0, self._start_rot + (pos.x() - self._press.x()) * 0.4))
        self._last = pos
        self._img_cache.pop(clip.clip_id, None)
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
        self._img_cache.pop(clip.clip_id, None)
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
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self._last_grab_t = -1.0
        self._last_grab_src = ""
        self._grabbing = False
        self._grab_bridge = GrabBridge(self)
        self._grab_bridge.done.connect(self._on_grab)
        self._frame_cache: dict[tuple, QPixmap] = {}
        self._proxy_of: dict[str, str] = {}
        self._proxy_pending: set[str] = set()
        self._seeking = False
        self.seek.sliderPressed.connect(self._seek_start)
        self.seek.sliderReleased.connect(self._seek_end)
        self._init_backend()

    def _backend_label(self) -> str:
        base = {"mpv": "libmpv", "qt": "Qt Multimedia", "ffmpeg": "FFmpeg / Qt"}.get(self.backend, self.backend)
        return f"{base} · прокси>1080p"

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
        self._prepare_proxies(project)

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

    def _prepare_proxies(self, project: EditorProject) -> None:
        for clip in project.video_clips:
            if not clip.source_path or not is_heavy_source(clip.source_width, clip.source_height):
                continue
            if clip.source_path in self._proxy_of or clip.source_path in self._proxy_pending:
                continue
            src = clip.source_path
            self._proxy_pending.add(src)
            w, h = clip.source_width, clip.source_height

            class _ProxyTask(QRunnable):
                def __init__(self, path: str, width: int, height: int, bridge: GrabBridge) -> None:
                    super().__init__()
                    self.path, self.width, self.height, self.bridge = path, width, height, bridge

                def run(self) -> None:
                    try:
                        proxy = ensure_proxy(self.path, self.width, self.height)
                    except Exception:
                        proxy = self.path
                    self.bridge.done.emit(None, f"proxy:{self.path}|{proxy}", 0.0, 0, 0)

            QThreadPool.globalInstance().start(_ProxyTask(src, w, h, self._grab_bridge))

    def _seek_start(self) -> None:
        self._seeking = True
        self._set_loading(True)

    def _seek_end(self) -> None:
        self._seeking = False
        self._set_loading(self._grabbing)

    def _set_loading(self, on: bool) -> None:
        self.canvas.loading = bool(on)
        self.canvas.update()

    def _play_src(self, clip) -> str:
        return self._proxy_of.get(clip.source_path) or clip.source_path

    def refresh_frame(self) -> None:
        if self.project is None:
            self.canvas.set_frame(None)
            return
        hit = clip_at_time(self.project, self.playhead)
        rect = self.canvas.canvas_rect()
        size = (max(160, int(rect.width())), max(160, int(rect.height())))
        if hit is None:
            self.canvas.set_frame(None)
            self._set_loading(False)
            return
        _, clip, local = hit
        src = self._play_src(clip)
        cache_key = (src, round(local, 2), size[0], size[1])
        cached = self._frame_cache.get(cache_key)
        if cached is not None:
            self.canvas.set_frame(cached)
            self._set_loading(False)
            return
        if clip.source_path == self._last_grab_src and abs(local - self._last_grab_t) < 0.08:
            self.canvas.update()
            return
        if self._grabbing:
            self._set_loading(True)
            self.canvas.update()
            return
        self._grabbing = True
        self._set_loading(True)
        self._last_grab_t = local
        self._last_grab_src = src
        QThreadPool.globalInstance().start(GrabTask(src, local, size, self._grab_bridge))
        if self._qt_player is not None and src != self._src:
            self._src = src
            self._qt_player.setSource(QUrl.fromLocalFile(src))
        if self._mpv is not None and src:
            try:
                self._mpv.command("seek", local, "absolute")
            except Exception:
                pass

    def _on_grab(self, pix, src: str, seconds: float, _w: int, _h: int) -> None:
        if isinstance(src, str) and src.startswith("proxy:"):
            raw, proxy = src[6:].split("|", 1)
            self._proxy_of[raw] = proxy
            self._proxy_pending.discard(raw)
            self.refresh_frame()
            return
        self._grabbing = False
        if not self._seeking:
            self._set_loading(False)
        if src == self._last_grab_src:
            frame = pix if pix is not None else QPixmap()
            self.canvas.set_frame(frame)
            if pix is not None:
                key = (src, round(seconds, 2), _w, _h)
                self._frame_cache[key] = pix
                if len(self._frame_cache) > 36:
                    first = next(iter(self._frame_cache))
                    self._frame_cache.pop(first, None)


def _fmt(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"
