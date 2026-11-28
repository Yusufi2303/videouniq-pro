from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from videouniq.core.probe import probe_media
from videouniq.editor.export import autosave_path
from videouniq.editor.ops import close_gaps, split_clip
from videouniq.editor.presets import load_text_presets
from videouniq.editor.project import EditorProject, TextClip, VideoClip
from videouniq.ui.editor.inspector import InspectorPanel
from videouniq.ui.editor.media_bin import MediaBin
from videouniq.ui.editor.player import PreviewPlayer
from videouniq.ui.editor.timeline import TimelineWidget


class EditorPage(QWidget):
    send_to_uniquizer = Signal(object)
    export_clean = Signal(object)
    zip_requested = Signal()
    log_line = Signal(str)
    dirty_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.project = EditorProject()
        self.project.text_presets = load_text_presets()
        self.dirty = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self.title = QLabel("Без названия")
        self.title.setProperty("heading", True)
        bar.addWidget(self.title)
        bar.addStretch(1)
        self.open_btn = QPushButton("Открыть")
        self.save_btn = QPushButton("Сохранить")
        self.save_as_btn = QPushButton("Сохранить как")
        self.split_btn = QPushButton("Разрезать")
        self.split_btn.setToolTip("Разрезать клип по красной метке (Ctrl+B)")
        self.delete_btn = QPushButton("Удалить")
        self.join_btn = QPushButton("Склеить")
        self.export_btn = QPushButton("Экспорт")
        self.send_btn = QPushButton("В уникализатор (5)")
        self.send_btn.setObjectName("CtaButton")
        self.zip_btn = QPushButton("ZIP копий")
        for b in (
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.split_btn,
            self.delete_btn,
            self.join_btn,
            self.export_btn,
            self.zip_btn,
        ):
            b.setObjectName("GhostButton")
        self.open_btn.clicked.connect(self.open_project_dialog)
        self.save_btn.clicked.connect(lambda: self.save_project(False))
        self.save_as_btn.clicked.connect(lambda: self.save_project(True))
        self.split_btn.clicked.connect(self.split_at_playhead)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.join_btn.clicked.connect(self._join_selected)
        self.export_btn.clicked.connect(lambda: self.export_clean.emit(self.project))
        self.send_btn.clicked.connect(self._send)
        self.zip_btn.clicked.connect(self.zip_requested.emit)
        for w in (
            self.open_btn,
            self.save_btn,
            self.save_as_btn,
            self.split_btn,
            self.delete_btn,
            self.join_btn,
            self.export_btn,
            self.send_btn,
            self.zip_btn,
        ):
            bar.addWidget(w)
        root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Vertical)
        top = QSplitter(Qt.Orientation.Horizontal)
        self.bin = MediaBin()
        self.player = PreviewPlayer()
        self.inspector = InspectorPanel()
        top.addWidget(self.bin)
        top.addWidget(self.player)
        top.addWidget(self.inspector)
        top.setStretchFactor(0, 0)
        top.setStretchFactor(1, 1)
        top.setStretchFactor(2, 0)
        top.setSizes([240, 640, 300])
        self.timeline = TimelineWidget()
        split.addWidget(top)
        split.addWidget(self.timeline)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([480, 200])
        root.addWidget(split, 1)

        self.bin.import_requested.connect(self.import_media)
        self.bin.add_clip_requested.connect(self.add_media)
        self.bin.add_text_requested.connect(self.add_text)
        self.player.playhead_changed.connect(self._on_playhead)
        self.player.selection_changed.connect(lambda i: self._select("text", i))
        self.player.project_changed.connect(lambda: self._touch(rebind=False))
        self.timeline.playhead_changed.connect(self.player.set_playhead)
        self.timeline.selection_changed.connect(self._select)
        self.timeline.project_changed.connect(lambda: self._touch(rebind=False))
        self.timeline.files_dropped.connect(self._append_files)
        self.inspector.changed.connect(lambda: self._touch(rebind=False))

        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.split_at_playhead)
        QShortcut(QKeySequence("Ctrl+S"), self, activated=lambda: self.save_project(False))
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self.save_project(True))
        QShortcut(QKeySequence("Space"), self, activated=self.player.toggle)
        QShortcut(QKeySequence("Left"), self, activated=lambda: self.player.step(-1))
        QShortcut(QKeySequence("Right"), self, activated=lambda: self.player.step(1))
        for seq in ("Delete", "Backspace"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(self._delete_selected)

        self._text_guard = QTimer(self)
        self._text_guard.setSingleShot(True)
        self._text_guard.setInterval(350)
        self._pending_text: TextClip | None = None

        self._auto = QTimer(self)
        self._auto.setInterval(60_000)
        self._auto.timeout.connect(self._autosave)
        self._auto.start()
        self.bind()

    def bind(self) -> None:
        name = self.project.name or "Без названия"
        mark = " •" if self.dirty else ""
        self.title.setText(name + mark)
        self.bin.set_project(self.project)
        self.player.set_project(self.project)
        self.inspector.set_project(self.project)
        self.timeline.set_project(self.project)

    def load_project(self, project: EditorProject) -> None:
        self.project = project
        if not self.project.text_presets:
            self.project.text_presets = load_text_presets()
        self.dirty = False
        self.bind()
        self.log_line.emit(f"Открыт проект: {project.path or project.name}")

    def open_project_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Открыть проект", str(Path.home()), "Проект VideoUniq (*.vup);;JSON (*.json)")
        if not path:
            return
        try:
            self.load_project(EditorProject.load(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Проект", f"Не удалось открыть:\n{exc}")

    def save_project(self, save_as: bool) -> Path | None:
        path = self.project.path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Сохранить проект", str(Path.home() / f"{self.project.name}.vup"), "Проект VideoUniq (*.vup)"
            )
            if not path:
                return None
        try:
            dest = self.project.save(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Проект", f"Не удалось сохранить:\n{exc}")
            return None
        self.dirty = False
        self.bind()
        self.log_line.emit(f"Сохранено: {dest}")
        return dest

    def _autosave(self) -> None:
        if not self.dirty:
            return
        try:
            dest = autosave_path()
            payload = self.project.to_dict()
            Path(dest).write_text(self.project.to_json(), encoding="utf-8")
            self.log_line.emit(f"Автосохранение: {dest}")
            del payload
        except Exception as exc:  # noqa: BLE001
            self.log_line.emit(f"Автосохранение не удалось: {exc}")

    def import_media(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Добавить видео на дорожку", str(Path.home()), "Видео (*.mp4 *.mov *.avi *.mkv *.webm);;Все файлы (*)"
        )
        self._append_files(files)

    def _append_files(self, files: list[str]) -> None:
        for f in files:
            if f:
                self.add_media(f)

    def add_media(self, path: str) -> None:
        try:
            info = probe_media(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Медиа", str(exc))
            return
        self.project.add_media_path(info.path)
        clip = VideoClip(
            source_path=info.path,
            in_point=0.0,
            out_point=info.duration,
            source_duration=info.duration,
            source_width=info.width,
            source_height=info.height,
            source_fps=info.fps,
            has_audio=info.has_audio,
        )
        self.project.video_clips.append(clip.clamped())
        close_gaps(self.project)
        self.project.sync_canvas()
        self._select("video", clip.clip_id)
        self._touch()
        self.log_line.emit(f"Клип в конец дорожки: {info.name}")

    def add_text(self, clip: TextClip) -> None:
        self._pending_text = clip
        if self._text_guard.isActive():
            return
        self._text_guard.start()
        self._commit_text()

    def _commit_text(self) -> None:
        clip = self._pending_text
        self._pending_text = None
        if clip is None:
            return
        clip.start = self.player.playhead
        if not clip.duration:
            clip.duration = 3.0
        self.project.text_clips.append(clip.clamped())
        self._select("text", clip.clip_id)
        self._touch()

    def split_at_playhead(self) -> None:
        right = split_clip(self.project, self.player.playhead)
        if right is None:
            QMessageBox.information(self, "Разрезать", "Поставьте красную метку внутрь клипа и нажмите «Разрезать».")
            return
        self._select("video", right.clip_id)
        self._touch()
        self.log_line.emit("Клип разрезан — куски можно перетащить и удалить по одному")

    def _delete_selected(self) -> None:
        from PySide6.QtWidgets import QLineEdit

        from videouniq.editor.ops import delete_clip

        focus = self.focusWidget()
        if isinstance(focus, QLineEdit) and self.timeline.selected[0] == "text":
            return
        kind, cid = self.timeline.selected
        if not cid:
            cid = self.player.canvas.selected_id
            kind = "text" if cid else kind
        if not cid:
            return
        if delete_clip(self.project, cid):
            self.timeline.selected = ("", "")
            self.player.canvas.selected_id = ""
            self.inspector.show_clip("", "")
            self._touch()
            self.log_line.emit("Клип удалён")

    def _join_selected(self) -> None:
        from videouniq.editor.ops import join_clip_with_next

        kind, cid = self.timeline.selected
        if kind != "video" or not cid:
            if self.project.video_clips:
                cid = self.project.video_clips[0].clip_id
            else:
                return
        if join_clip_with_next(self.project, cid):
            self._touch()
            self.log_line.emit("Клипы склеены")

    def _select(self, kind: str, clip_id: str) -> None:
        self.timeline.selected = (kind, clip_id)
        self.player.canvas.selected_id = clip_id if kind == "text" else ""
        self.inspector.show_clip(kind, clip_id)
        self.timeline.update()
        self.player.canvas.update()
        if kind == "video" and clip_id:
            self.timeline.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_playhead(self, t: float) -> None:
        self.timeline.set_playhead(t)

    def _touch(self, rebind: bool = True) -> None:
        self.dirty = True
        close_gaps(self.project)
        if rebind:
            self.bind()
        else:
            name = self.project.name or "Без названия"
            self.title.setText(name + " •")
            self.timeline.update()
            self.player.canvas.update()
        self.dirty_changed.emit(True)

    def _send(self) -> None:
        if not self.project.video_clips:
            QMessageBox.information(self, "Редактор", "Добавьте хотя бы один видеоклип.")
            return
        if not self.project.path:
            saved = self.save_project(True)
            if saved is None:
                return
        self.send_to_uniquizer.emit(self.project)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_selected()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self.player.toggle()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Left:
            self.player.step(-1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Right:
            self.player.step(1)
            event.accept()
            return
        super().keyPressEvent(event)
