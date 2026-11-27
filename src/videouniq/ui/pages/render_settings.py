from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videouniq.core.hardware import ENCODER_LABELS
from videouniq.ui.widgets.toggle import ToggleSwitch


class RenderSettingsPage(QWidget):
    changed = Signal()
    theme_changed = Signal(bool)
    cache_clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        title = QLabel("Настройки рендера")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)
        sub = QLabel("Аппаратный энкодер определяется автоматически. При ошибке GPU используется CPU.")
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(sub)

        layout.addWidget(self._cap("Энкодер"))
        self.encoder = QComboBox()
        for key, label in ENCODER_LABELS.items():
            self.encoder.addItem(label, key)
        self.encoder.currentIndexChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.encoder)

        self.hw_info = QLabel("Проверка энкодеров…")
        self.hw_info.setWordWrap(True)
        self.hw_info.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(self.hw_info)

        row = QHBoxLayout()
        col1 = QVBoxLayout()
        col1.addWidget(self._cap("Потоки"))
        self.threads = QComboBox()
        self.threads.addItem("2 потока", 2)
        self.threads.addItem("4 потока", 4)
        self.threads.currentIndexChanged.connect(lambda _: self.changed.emit())
        col1.addWidget(self.threads)
        col2 = QVBoxLayout()
        col2.addWidget(self._cap("CRF (CPU)"))
        self.crf = QSpinBox()
        self.crf.setRange(14, 23)
        self.crf.setValue(17)
        self.crf.valueChanged.connect(lambda _: self.changed.emit())
        col2.addWidget(self.crf)
        col3 = QVBoxLayout()
        col3.addWidget(self._cap("CQ (NVENC)"))
        self.cq = QSpinBox()
        self.cq.setRange(16, 24)
        self.cq.setValue(19)
        self.cq.valueChanged.connect(lambda _: self.changed.emit())
        col3.addWidget(self.cq)
        row.addLayout(col1)
        row.addLayout(col2)
        row.addLayout(col3)
        layout.addLayout(row)

        layout.addWidget(self._cap("Пресет CPU"))
        self.cpu_preset = QComboBox()
        for name in ("slow", "medium", "fast"):
            self.cpu_preset.addItem(name, name)
        self.cpu_preset.currentIndexChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.cpu_preset)

        layout.addWidget(self._cap("Пресет NVIDIA"))
        self.nv_preset = QComboBox()
        for name in ("p6", "p7", "p5"):
            self.nv_preset.addItem(name, name)
        self.nv_preset.currentIndexChanged.connect(lambda _: self.changed.emit())
        layout.addWidget(self.nv_preset)

        theme_row = QHBoxLayout()
        theme_lab = QLabel("Тёмная тема")
        self.dark_toggle = ToggleSwitch(True)
        self.dark_toggle.toggled.connect(self.theme_changed.emit)
        theme_row.addWidget(theme_lab)
        theme_row.addStretch(1)
        theme_row.addWidget(self.dark_toggle)
        layout.addLayout(theme_row)

        note = QLabel("Цвет: yuv420p, матрицы исходника (по умолчанию BT.709). Звук AAC 320 кбит/с, 48 кГц.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(note)

        layout.addWidget(self._cap("Кэш"))
        cache_row = QHBoxLayout()
        self.cache_btn = QPushButton("Очистить кэш превью и временных файлов")
        self.cache_btn.setObjectName("GhostButton")
        self.cache_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cache_btn.clicked.connect(self.cache_clear_requested.emit)
        cache_row.addWidget(self.cache_btn)
        cache_row.addStretch(1)
        layout.addLayout(cache_row)
        cache_hint = QLabel("Удаляет кадры превью и кэш FFmpeg. Проекты .vup не трогает.")
        cache_hint.setWordWrap(True)
        cache_hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(cache_hint)
        layout.addStretch(1)

    def _cap(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        return lab

    def encoder_key(self) -> str:
        return str(self.encoder.currentData())

    def thread_count(self) -> int:
        return int(self.threads.currentData())

    def set_hardware_info(self, text: str) -> None:
        self.hw_info.setText(text)
