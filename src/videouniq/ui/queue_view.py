from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videouniq.queue.models import FileItem
from videouniq.ui.file_card import FileCard


class DropZone(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(False)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Перетащите видео или папку")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        sub = QLabel("MP4, MOV, AVI, MKV, WEBM  ·  или нажмите, чтобы выбрать")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #9CA3AF; font-size: 13px;")
        layout.addWidget(title)
        layout.addWidget(sub)


class QueueView(QWidget):
    files_dropped = Signal(list)
    remove_requested = Signal(str)
    open_requested = Signal(str)
    browse_requested = Signal()
    return_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._cards: dict[str, FileCard] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QLabel("Очередь")
        header.setProperty("heading", True)
        layout.addWidget(header)

        self.empty = DropZone()
        self.empty.setMinimumHeight(280)
        layout.addWidget(self.empty, 1)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 2, 0)
        self.list_layout.setSpacing(10)
        self.list_layout.addStretch(1)
        self.scroll.setWidget(self.list_host)
        self.scroll.hide()
        layout.addWidget(self.scroll, 1)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.empty.isVisible() and event.button() == Qt.MouseButton.LeftButton:
            self.browse_requested.emit()
        super().mousePressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.empty.setProperty("active", True)
            self.empty.style().unpolish(self.empty)
            self.empty.style().polish(self.empty)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.empty.setProperty("active", False)
        self.empty.style().unpolish(self.empty)
        self.empty.style().polish(self.empty)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.empty.setProperty("active", False)
        self.empty.style().unpolish(self.empty)
        self.empty.style().polish(self.empty)
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.toLocalFile()]
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()

    def set_items(self, items: list[FileItem]) -> None:
        if not items:
            self.scroll.hide()
            self.empty.show()
            for card in list(self._cards.values()):
                card.setParent(None)
            self._cards.clear()
            return
        self.empty.hide()
        self.scroll.show()
        seen = {it.item_id for it in items}
        for key in list(self._cards):
            if key not in seen:
                self._cards[key].setParent(None)
                del self._cards[key]
        stretch = self.list_layout.takeAt(self.list_layout.count() - 1)
        for item in items:
            card = self._cards.get(item.item_id)
            if card is None:
                card = FileCard(item)
                card.remove_requested.connect(self.remove_requested)
                card.open_requested.connect(self.open_requested)
                card.return_requested.connect(self.return_requested)
                self._cards[item.item_id] = card
                self.list_layout.addWidget(card)
            else:
                card.bind(item)
        if stretch:
            self.list_layout.addItem(stretch)
        else:
            self.list_layout.addStretch(1)

    def update_item(self, item: FileItem) -> None:
        card = self._cards.get(item.item_id)
        if card:
            card.bind(item)
