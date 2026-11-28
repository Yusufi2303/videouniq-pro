from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from videouniq.core.probe import collect_videos
from videouniq.editor.project import EditorProject, TextClip


class MediaBin(QWidget):
    import_requested = Signal()
    add_clip_requested = Signal(str)
    add_text_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EditorZone")
        self.setAcceptDrops(True)
        self.project: EditorProject | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        title = QLabel("Медиа и текст")
        title.setProperty("heading", True)
        layout.addWidget(title)
        row = QHBoxLayout()
        self.imp = QPushButton("Импорт")
        self.imp.setObjectName("GhostButton")
        self.imp.clicked.connect(self.import_requested.emit)
        row.addWidget(self.imp)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._add_selected)
        layout.addWidget(self.list, 1)
        hint = QLabel("Импорт или перетаскивание добавляет ролик в конец дорожки. Двойной клик — ещё один кусок.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(hint)

        tlab = QLabel("Текст")
        tlab.setStyleSheet("font-weight: 600;")
        layout.addWidget(tlab)
        self.plain_btn = QPushButton("Добавить текст")
        self.plain_btn.clicked.connect(lambda: self.add_text_requested.emit(self._plain()))
        self.tiktok_btn = QPushButton("Плашка TikTok")
        self.tiktok_btn.clicked.connect(lambda: self.add_text_requested.emit(self._tiktok()))
        layout.addWidget(self.plain_btn)
        layout.addWidget(self.tiktok_btn)

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self.reload()

    def reload(self) -> None:
        self.list.clear()
        if self.project is None:
            return
        for path in self.project.media_bin:
            item = QListWidgetItem(Path(path).name)
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            self.list.addItem(item)

    def _add_selected(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self.add_clip_requested.emit(str(path))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        videos = collect_videos(paths) if paths else []
        seen: set[str] = set()
        for p in videos:
            key = str(Path(p).resolve())
            if key in seen:
                continue
            seen.add(key)
            self.add_clip_requested.emit(str(p))
        event.acceptProposedAction()

    def _plain(self) -> TextClip:
        return TextClip(text="Текст", plate=False, stroke_enabled=True, shadow=True)

    def _tiktok(self) -> TextClip:
        return TextClip(
            text="Текст на плашке",
            plate=True,
            plate_color="#000000",
            plate_opacity=0.62,
            stroke_enabled=False,
            shadow=False,
            font_size=52,
            y_norm=0.82,
        )
