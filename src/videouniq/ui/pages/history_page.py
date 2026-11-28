from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from videouniq.editor.history import clear_history, load_history
from videouniq.ui.file_card import open_path


class HistoryPage(QWidget):
    open_folder_requested = Signal(str)
    report_requested = Signal(str, str)  # source, output_dir

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("История и загрузки")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("GhostButton")
        refresh.clicked.connect(self.reload)
        clear = QPushButton("Очистить список")
        clear.setObjectName("GhostButton")
        clear.clicked.connect(self._clear)
        header.addWidget(refresh)
        header.addWidget(clear)
        layout.addLayout(header)
        sub = QLabel("Экспорты редактора, уникализированные копии и ZIP-архивы.")
        sub.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(sub)

        self.empty = QLabel("Пока пусто — экспортируйте проект или запустите уникализатор.")
        self.empty.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(self.empty)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.host = QWidget()
        self.list_l = QVBoxLayout(self.host)
        self.list_l.setContentsMargins(0, 0, 0, 0)
        self.list_l.setSpacing(8)
        self.list_l.addStretch(1)
        self.scroll.setWidget(self.host)
        layout.addWidget(self.scroll, 1)
        self.reload()

    def _clear(self) -> None:
        clear_history()
        self.reload()

    def reload(self) -> None:
        items = load_history()
        self.empty.setVisible(not items)
        self.scroll.setVisible(bool(items))
        while self.list_l.count() > 1:
            item = self.list_l.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
        for rec in items:
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(10, 8, 10, 8)
            kind = {"export": "Чистый экспорт", "uniquize": "Уникализация", "zip": "ZIP", "project": "Проект"}.get(
                str(rec.get("kind") or ""), str(rec.get("kind") or "")
            )
            text = QLabel(f"{rec.get('ts', '')}\n{kind} · {rec.get('name', '')}\n{rec.get('path', '')}")
            text.setWordWrap(True)
            hl.addWidget(text, 1)
            btn = QPushButton("Папка")
            btn.setObjectName("GhostButton")
            path = str(rec.get("path") or "")
            source = str(rec.get("source") or rec.get("name") or "")
            btn.clicked.connect(lambda _=False, p=path: open_path(p) if p else None)
            btn.setEnabled(bool(path) and Path(path).exists())
            hl.addWidget(btn)
            report_btn = QPushButton("Отчёт")
            report_btn.setObjectName("GhostButton")
            folder = path if Path(path).is_dir() else str(Path(path).parent) if path else ""
            report_btn.clicked.connect(
                lambda _=False, src=source, p=folder: self.report_requested.emit(src, p)
            )
            report_btn.setEnabled(
                str(rec.get("kind") or "") in {"uniquize", "project"} and bool(folder) and Path(folder).exists()
            )
            hl.addWidget(report_btn)
            self.list_l.insertWidget(self.list_l.count() - 1, row)
