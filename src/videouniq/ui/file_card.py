from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from videouniq.queue.models import FileItem, FileStatus


def open_path(path: str) -> None:
    target = path if Path(path).is_dir() else str(Path(path).parent)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target])


class FileCard(QFrame):
    remove_requested = Signal(str)
    open_requested = Signal(str)
    return_requested = Signal(str)
    report_requested = Signal(str)

    def __init__(self, item: FileItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FileCard")
        self.item_id = item.item_id
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(12)

        self.preview = QLabel()
        self.preview.setFixedSize(64, 64)
        self.preview.setStyleSheet("background: #111318; border-radius: 8px;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setScaledContents(True)
        root.addWidget(self.preview)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 600;")
        self.badge = QLabel("Проект")
        self.badge.setObjectName("ProjectBadge")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.hide()
        title_row.addWidget(self.name, 1)
        title_row.addWidget(self.badge)
        self.meta = QLabel()
        self.meta.setProperty("muted", True)
        self.meta.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self.status = QLabel()
        self.status.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self.bar = QProgressBar()
        self.bar.setFixedHeight(6)
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        mid.addLayout(title_row)
        mid.addWidget(self.meta)
        mid.addWidget(self.bar)
        mid.addWidget(self.status)
        root.addLayout(mid, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)
        self.open_btn = QPushButton("Папка")
        self.open_btn.setObjectName("GhostButton")
        self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.item_id))
        self.report_btn = QPushButton("Отчёт уникальности")
        self.report_btn.setObjectName("GhostButton")
        self.report_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.report_btn.clicked.connect(lambda: self.report_requested.emit(self.item_id))
        self.report_btn.hide()
        self.return_btn = QPushButton("В редактор")
        self.return_btn.setObjectName("GhostButton")
        self.return_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.return_btn.clicked.connect(lambda: self.return_requested.emit(self.item_id))
        self.return_btn.hide()
        self.del_btn = QPushButton("Удалить")
        self.del_btn.setObjectName("GhostButton")
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.del_btn.clicked.connect(lambda: self.remove_requested.emit(self.item_id))
        actions.addWidget(self.open_btn)
        actions.addWidget(self.report_btn)
        actions.addWidget(self.return_btn)
        actions.addWidget(self.del_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        self.bind(item)

    def bind(self, item: FileItem) -> None:
        info = item.info
        is_project = item.kind == "project"
        self.badge.setVisible(is_project)
        self.return_btn.setVisible(is_project)
        self.name.setText(info.name if info and not is_project else Path(item.path).name)
        if info:
            self.meta.setText(
                f"{info.resolution_label}  ·  {info.fps_label}  ·  {info.duration_label}  ·  {info.size_label}"
            )
        else:
            self.meta.setText(item.error or "чтение метаданных…")
        if item.preview_path and Path(item.preview_path).is_file():
            pix = QPixmap(item.preview_path)
            if not pix.isNull():
                self.preview.setPixmap(
                    pix.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
                )
        self.bar.setValue(int(item.progress * 1000))
        state = "idle"
        if item.status == FileStatus.DONE:
            state = "done"
            self.status.setText(f"Готово · {item.copies_done} копий")
            self.status.setStyleSheet("color: #10B981; font-size: 12px;")
        elif item.status == FileStatus.ERROR:
            state = "error"
            self.status.setText(item.error or "Ошибка")
            self.status.setStyleSheet("color: #EF4444; font-size: 12px;")
        elif item.status == FileStatus.RENDERING:
            state = "progress"
            pct = int(item.progress * 100)
            self.status.setText(item.message or f"Рендер {item.copies_done}/{item.copies_total} · {pct}%")
            self.status.setStyleSheet("color: #F59E0B; font-size: 12px;")
        elif item.status == FileStatus.CANCELLED:
            self.status.setText("Остановлено")
            self.status.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        else:
            self.status.setText("В очереди")
            self.status.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self.bar.setProperty("state", state)
        self.bar.style().unpolish(self.bar)
        self.bar.style().polish(self.bar)
        self.open_btn.setEnabled(bool(item.output_dir) and Path(item.output_dir).exists())
        done = item.status == FileStatus.DONE and bool(item.output_dir) and Path(item.output_dir).exists()
        self.report_btn.setVisible(done)
        self.report_btn.setEnabled(done)
        self.del_btn.setEnabled(item.status not in {FileStatus.RENDERING})
