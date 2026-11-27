from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from videouniq import __version__

NAV = [
    ("uniquize", "Уникализация"),
    ("render", "Настройки рендера"),
    ("meta", "Пресеты метаданных"),
    ("logs", "Логи"),
]


class LogoMark(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#3B82F6"))
        p.drawRoundedRect(0, 0, 36, 36, 9, 9)
        p.setPen(QColor("#FFFFFF"))
        font = QFont("Inter", 11)
        font.setWeight(QFont.Weight.DemiBold)
        p.setFont(font)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "VU")
        p.end()


class Sidebar(QFrame):
    page_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)
        self._buttons: dict[str, QPushButton] = {}
        self._page = "uniquize"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 14)
        layout.setSpacing(6)

        brand = QWidget()
        brand_l = QVBoxLayout(brand)
        brand_l.setContentsMargins(2, 0, 2, 10)
        brand_l.setSpacing(8)
        row = QWidget()
        from PySide6.QtWidgets import QHBoxLayout

        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.setSpacing(10)
        row_l.addWidget(LogoMark())
        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(0)
        name = QLabel("VideoUniq Pro")
        name.setProperty("heading", True)
        name.setStyleSheet("font-size: 15px; font-weight: 600;")
        sub = QLabel("без нейросетей")
        sub.setProperty("muted", True)
        sub.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        title_box.addWidget(name)
        title_box.addWidget(sub)
        row_l.addLayout(title_box)
        brand_l.addWidget(row)
        layout.addWidget(brand)

        for key, label in NAV:
            btn = QPushButton(label)
            btn.setObjectName("NavBtn")
            btn.setCheckable(False)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _=False, k=key: self.set_page(k))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch(1)

        self.hw_label = QLabel("GPU: определение…")
        self.hw_label.setWordWrap(True)
        self.hw_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        self.load_label = QLabel("CPU 0%  ·  RAM 0%")
        self.load_label.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        ver = QLabel(f"v{__version__}")
        ver.setStyleSheet("color: #6B7280; font-size: 11px;")
        layout.addWidget(self.hw_label)
        layout.addWidget(self.load_label)
        layout.addWidget(ver)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_load)
        self._timer.start(1000)
        self._tick_load()
        self.set_page("uniquize", emit=False)

    def set_page(self, key: str, emit: bool = True) -> None:
        self._page = key
        for k, btn in self._buttons.items():
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if emit:
            self.page_changed.emit(key)

    def set_hardware(self, text: str) -> None:
        self.hw_label.setText(text)

    def _tick_load(self) -> None:
        cpu = ram = 0.0
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except Exception:
            pass
        gpu = "—"
        try:
            import shutil
            import subprocess

            if shutil.which("nvidia-smi"):
                proc = subprocess.run(
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                )
                line = (proc.stdout or "").strip().splitlines()
                if line:
                    gpu = f"{line[0].strip()}%"
        except Exception:
            gpu = "—"
        self.load_label.setText(f"CPU {cpu:.0f}%  ·  RAM {ram:.0f}%  ·  GPU {gpu}")
