from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(QSize(42, 24))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.setEnabled(True)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(42, 24)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool, emit: bool = True) -> None:
        checked = bool(checked)
        if checked == self._checked:
            return
        self._checked = checked
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        if emit:
            self.toggled.emit(checked)
        self.update()

    def get_knob(self) -> float:
        return self._pos

    def set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = Property(float, get_knob, set_knob)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        on = QColor("#3B82F6")
        off = QColor("#2A2F3A")
        if not self.isEnabled():
            on = QColor("#374151")
            off = QColor("#1F2937")
        bg = QColor(off)
        bg.setRed(int(off.red() + (on.red() - off.red()) * self._pos))
        bg.setGreen(int(off.green() + (on.green() - off.green()) * self._pos))
        bg.setBlue(int(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        knob_d = h - 6
        x = 3 + self._pos * (w - knob_d - 6)
        p.setBrush(QColor("#F3F4F6"))
        p.drawEllipse(int(x), 3, knob_d, knob_d)
        p.end()
