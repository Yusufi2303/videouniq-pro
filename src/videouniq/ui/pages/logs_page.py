from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class LogsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Логи")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        clear = QPushButton("Очистить")
        clear.setObjectName("GhostButton")
        header.addWidget(clear)
        layout.addLayout(header)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        layout.addWidget(self.view, 1)
        clear.clicked.connect(self.clear)

    def append(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.view.appendPlainText(f"[{stamp}] {text}")
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        self.view.clear()
