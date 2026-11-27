from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videouniq.core.params import (
    ManualRanges,
    ModuleFlags,
    PresetName,
    flags_for_preset,
    ranges_for_preset,
)
from videouniq.ui.widgets.toggle import ToggleSwitch

MODULE_ROWS = [
    ("metadata", "Метаданные"),
    ("trim", "Обрезка краёв таймлайна"),
    ("tempo", "Микро-скорость"),
    ("crop", "Кроп / зум"),
    ("rotate", "Поворот"),
    ("shift", "Сдвиг X/Y"),
    ("color", "Яркость / контраст"),
    ("fps", "Микро-FPS"),
    ("grain", "Зерно"),
    ("overlay", "Оверлей по кадрам"),
    ("pitch", "Высота тона"),
    ("audio_filters", "HP / LP фильтры"),
    ("audio_noise", "Аудио-шум −50 дБ"),
    ("mirror", "Зеркало (опционально)"),
]


class ChipRow(QWidget):
    changed = Signal(int)

    def __init__(self, values: list[int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._buttons: dict[int, QPushButton] = {}
        for value in values:
            btn = QPushButton(str(value))
            btn.setObjectName("Chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, v=value: self.changed.emit(v))
            self._group.addButton(btn)
            self._buttons[value] = btn
            layout.addWidget(btn)
        layout.addStretch(1)

    def set_value(self, value: int) -> None:
        for v, btn in self._buttons.items():
            btn.setProperty("active", v == value)
            btn.setChecked(v == value)
            btn.style().unpolish(btn)
            btn.style().polish(btn)


class PresetRow(QWidget):
    changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}
        labels = [
            ("light", "Лайт"),
            ("optimal", "Оптимальный"),
            ("hard", "Жёсткий"),
            ("manual", "Ручной"),
        ]
        for i, (key, title) in enumerate(labels):
            btn = QPushButton(title)
            btn.setObjectName("Chip")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip("Рекомендуемый" if key == "optimal" else "")
            btn.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
            self._buttons[key] = btn
            layout.addWidget(btn, i // 2, i % 2)

    def set_value(self, key: str) -> None:
        for k, btn in self._buttons.items():
            btn.setProperty("active", k == key)
            btn.style().unpolish(btn)
            btn.style().polish(btn)


class FlagRow(QWidget):
    changed = Signal(str, bool)

    def __init__(self, key: str, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.key = key
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        label = QLabel(title)
        label.setStyleSheet("font-size: 13px;")
        self.toggle = ToggleSwitch()
        self.toggle.toggled.connect(lambda v: self.changed.emit(self.key, v))
        layout.addWidget(label, 1)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)


class RangeRow(QWidget):
    def __init__(self, title: str, minimum: float, maximum: float, step: float, decimals: int = 2, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title))
        row = QHBoxLayout()
        self.min_spin = QDoubleSpinBox()
        self.max_spin = QDoubleSpinBox()
        for spin in (self.min_spin, self.max_spin):
            spin.setRange(minimum, maximum)
            spin.setSingleStep(step)
            spin.setDecimals(decimals)
        row.addWidget(self.min_spin)
        dash = QLabel("—")
        dash.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(dash)
        row.addWidget(self.max_spin)
        layout.addLayout(row)


class RightPanel(QFrame):
    start_requested = Signal()
    stop_requested = Signal()
    copies_changed = Signal(int)
    preset_changed = Signal(str)
    flags_changed = Signal()
    output_changed = Signal(str)
    save_preset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RightPanel")
        self.setFixedWidth(320)
        self._preset: PresetName = "optimal"
        self._file_count = 0
        self._copy_count = 5
        self._running = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(12)

        h = QLabel("Параметры")
        h.setProperty("heading", True)
        layout.addWidget(h)

        layout.addWidget(self._label("Число копий"))
        copies_row = QHBoxLayout()
        self.copies_spin = QSpinBox()
        self.copies_spin.setRange(1, 50)
        self.copies_spin.setValue(5)
        self.copies_spin.valueChanged.connect(self._on_copies)
        copies_row.addWidget(self.copies_spin, 1)
        layout.addLayout(copies_row)
        self.chips = ChipRow([3, 5, 10, 20])
        self.chips.changed.connect(self.copies_spin.setValue)
        self.chips.set_value(5)
        layout.addWidget(self.chips)

        layout.addWidget(self._label("Режим"))
        self.presets = PresetRow()
        self.presets.changed.connect(self._on_preset)
        self.presets.set_value("optimal")
        layout.addWidget(self.presets)
        hint = QLabel("Оптимальный — безопасные лимиты, картинка без видимых артефактов.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(hint)

        layout.addWidget(self._label("Модули"))
        self.flag_rows: dict[str, FlagRow] = {}
        for key, title in MODULE_ROWS:
            row = FlagRow(key, title)
            row.changed.connect(self._on_flag)
            self.flag_rows[key] = row
            layout.addWidget(row)

        self.manual_box = QWidget()
        man = QVBoxLayout(self.manual_box)
        man.setContentsMargins(0, 8, 0, 0)
        man.setSpacing(6)
        man_title = QLabel("Диапазоны (ручной)")
        man_title.setStyleSheet("font-weight: 600;")
        man.addWidget(man_title)
        self.r_crop = RangeRow("Кроп, %", 0.5, 2.5, 0.1)
        self.r_rotate = RangeRow("Поворот, ° (0…макс)", 0.0, 0.4, 0.05)
        self.r_rotate.min_spin.hide()
        self.r_trim = RangeRow("Trim, с", 0.03, 0.15, 0.01, 3)
        self.r_tempo = RangeRow("Δ скорости", 0.0, 0.015, 0.001, 3)
        self.r_tempo.min_spin.hide()
        self.r_bright = RangeRow("Δ яркости", 0.0, 0.02, 0.001, 3)
        self.r_bright.min_spin.hide()
        for w in (self.r_crop, self.r_rotate, self.r_trim, self.r_tempo, self.r_bright):
            man.addWidget(w)
        save_btn = QPushButton("Сохранить свой пресет")
        save_btn.setObjectName("GhostButton")
        save_btn.clicked.connect(self.save_preset_requested.emit)
        man.addWidget(save_btn)
        layout.addWidget(self.manual_box)
        self.manual_box.hide()

        layout.addWidget(self._label("Папка сохранения"))
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("Output_[дата_время] рядом с исходником")
        self.out_edit.editingFinished.connect(lambda: self.output_changed.emit(self.out_edit.text().strip()))
        browse = QPushButton("…")
        browse.setFixedWidth(36)
        browse.clicked.connect(self._browse_out)
        out_row.addWidget(self.out_edit, 1)
        out_row.addWidget(browse)
        layout.addLayout(out_row)
        note = QLabel("По умолчанию: Output_[Дата_Время], подпапка на каждый исходник, video_1.mp4 …")
        note.setWordWrap(True)
        note.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        layout.addWidget(note)

        layout.addStretch(1)
        self._scroll.setWidget(host)
        outer.addWidget(self._scroll, 1)

        cta_wrap = QWidget()
        cta_l = QVBoxLayout(cta_wrap)
        cta_l.setContentsMargins(14, 8, 14, 14)
        self.cta = QPushButton("Уникализировать")
        self.cta.setObjectName("CtaButton")
        self.cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cta.clicked.connect(self._on_cta)
        self.stop_btn = QPushButton("Остановить")
        self.stop_btn.setObjectName("StopButton")
        self.stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.hide()
        self.cta_sub = QLabel("")
        self.cta_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cta_sub.setStyleSheet("color: #9CA3AF; font-size: 11px;")
        cta_l.addWidget(self.cta)
        cta_l.addWidget(self.stop_btn)
        cta_l.addWidget(self.cta_sub)
        outer.addWidget(cta_wrap)

        self.apply_preset("optimal", emit=False)
        self.set_file_count(0)

    def _label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        return lab

    def _on_copies(self, value: int) -> None:
        self._copy_count = value
        self.chips.set_value(value if value in {3, 5, 10, 20} else -1)
        self.copies_changed.emit(value)
        self._refresh_cta()

    def _on_preset(self, key: str) -> None:
        self.apply_preset(key)  # type: ignore[arg-type]
        self.preset_changed.emit(key)

    def _on_flag(self, key: str, value: bool) -> None:
        if self._preset != "manual":
            self._preset = "manual"
            self.presets.set_value("manual")
            self.manual_box.setVisible(True)
        self.flags_changed.emit()

    def _on_cta(self) -> None:
        if self._running:
            return
        self.start_requested.emit()

    def _browse_out(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка сохранения", self.out_edit.text() or str(Path.home()))
        if folder:
            self.out_edit.setText(folder)
            self.output_changed.emit(folder)

    def apply_preset(self, key: PresetName, emit: bool = True) -> None:
        self._preset = key
        self.presets.set_value(key)
        flags = flags_for_preset("optimal" if key == "manual" else key)
        if key == "manual":
            flags = self.flags()
        else:
            for name, row in self.flag_rows.items():
                row.toggle.setChecked(getattr(flags, name), emit=False)
        ranges = ranges_for_preset("optimal" if key == "manual" else key)
        self._fill_ranges(ranges)
        self.manual_box.setVisible(key == "manual")
        if key == "manual":
            QTimer.singleShot(0, lambda: self._scroll.ensureWidgetVisible(self.manual_box))
        for row in self.flag_rows.values():
            row.toggle.setEnabled(key == "manual" or True)
        if emit:
            self.flags_changed.emit()

    def _fill_ranges(self, ranges: ManualRanges) -> None:
        self.r_crop.min_spin.setValue(ranges.crop_min)
        self.r_crop.max_spin.setValue(ranges.crop_max)
        self.r_rotate.max_spin.setValue(ranges.rotate_max)
        self.r_trim.min_spin.setValue(ranges.trim_min)
        self.r_trim.max_spin.setValue(ranges.trim_max)
        self.r_tempo.max_spin.setValue(ranges.tempo_delta)
        self.r_bright.max_spin.setValue(ranges.brightness)

    def flags(self) -> ModuleFlags:
        kwargs = {key: row.toggle.isChecked() for key, row in self.flag_rows.items()}
        return ModuleFlags(**kwargs)

    def ranges(self) -> ManualRanges:
        r = ranges_for_preset("optimal")
        r.crop_min = self.r_crop.min_spin.value()
        r.crop_max = self.r_crop.max_spin.value()
        r.rotate_max = self.r_rotate.max_spin.value()
        r.trim_min = self.r_trim.min_spin.value()
        r.trim_max = self.r_trim.max_spin.value()
        r.tempo_delta = self.r_tempo.max_spin.value()
        r.brightness = self.r_bright.max_spin.value()
        r.contrast = self.r_bright.max_spin.value()
        return r.clamp()

    def preset(self) -> PresetName:
        return self._preset

    def copy_count(self) -> int:
        return int(self.copies_spin.value())

    def output_dir(self) -> str:
        return self.out_edit.text().strip()

    def set_output_dir(self, path: str) -> None:
        self.out_edit.setText(path)

    def set_file_count(self, n: int) -> None:
        self._file_count = n
        self._refresh_cta()

    def set_running(self, running: bool) -> None:
        self._running = running
        self.cta.setVisible(not running)
        self.stop_btn.setVisible(running)
        self._refresh_cta()

    def _refresh_cta(self) -> None:
        n = self._file_count
        copies = self.copy_count()
        if n <= 0:
            self.cta.setText("Уникализировать")
            self.cta.setEnabled(False)
            self.cta_sub.setText("Добавьте видео в очередь")
        else:
            total = n * copies
            self.cta.setText(f"Уникализировать ({n} видео)")
            self.cta.setEnabled(not self._running)
            self.cta_sub.setText(f"{copies} копий × {n} = {total} файлов")
        if self._running:
            self.cta_sub.setText("Идёт рендер…")
