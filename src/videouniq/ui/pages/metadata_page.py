from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

from videouniq.core.metadata import DEVICE_LABELS
from videouniq.core.params import DEVICE_PRESETS


class MetadataPage(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(10)
        title = QLabel("Пресеты метаданных")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)
        sub = QLabel(
            "Исходные теги удаляются (−map_metadata −1). Для каждой копии случайно "
            "выбирается одно из включённых устройств. creation_time — в пределах последних 1–7 дней."
        )
        sub.setWordWrap(True)
        sub.setStyleSheet("color: #9CA3AF;")
        layout.addWidget(sub)

        self.boxes: dict[str, QCheckBox] = {}
        for key in DEVICE_PRESETS:
            box = QCheckBox(DEVICE_LABELS.get(key, key))
            box.setChecked(True)
            box.toggled.connect(lambda _: self.changed.emit())
            self.boxes[key] = box
            layout.addWidget(box)

        extra = QLabel("Дополнительно: +faststart и случайные байты в конце файла (уникальный MD5).")
        extra.setWordWrap(True)
        extra.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(extra)
        layout.addStretch(1)

    def enabled_devices(self) -> list[str]:
        keys = [k for k, b in self.boxes.items() if b.isChecked()]
        return keys or list(DEVICE_PRESETS)
