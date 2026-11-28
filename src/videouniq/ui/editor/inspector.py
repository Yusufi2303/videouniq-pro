from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from videouniq.editor.presets import load_text_presets, save_text_presets, upsert_preset
from videouniq.editor.project import TRANSITIONS, EditorProject, TextClip, TextStylePreset, VideoClip


class InspectorPanel(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EditorZone")
        self.project: EditorProject | None = None
        self.kind = ""
        self.clip_id = ""
        self._lock = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Инспектор")
        title.setProperty("heading", True)
        layout.addWidget(title)
        self.hint = QLabel("Выберите клип на таймлайне или текст на холсте.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        layout.addWidget(self.hint)

        self.video_box = QWidget()
        vf = QFormLayout(self.video_box)
        vf.setContentsMargins(0, 0, 0, 0)
        self.in_spin = QDoubleSpinBox()
        self.in_spin.setRange(0, 86400)
        self.in_spin.setDecimals(3)
        self.in_spin.setSuffix(" с")
        self.out_spin = QDoubleSpinBox()
        self.out_spin.setRange(0.04, 86400)
        self.out_spin.setDecimals(3)
        self.out_spin.setSuffix(" с")
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setValue(100)
        self.vol.setObjectName("VolumeSlider")
        self.vol_lab = QLabel("100%")
        vol_row = QHBoxLayout()
        vol_row.addWidget(self.vol, 1)
        vol_row.addWidget(self.vol_lab)
        vol_w = QWidget()
        vol_w.setLayout(vol_row)
        self.mute = QCheckBox("Без звука")
        self.trans = QComboBox()
        self.trans.addItem("Нет", "none")
        self.trans.addItem("Кроссфейд", "crossfade")
        self.trans.addItem("Уход в чёрный", "fade_black")
        self.tdur = QDoubleSpinBox()
        self.tdur.setRange(0.2, 1.5)
        self.tdur.setSingleStep(0.1)
        self.tdur.setValue(0.5)
        self.tdur.setSuffix(" с")
        vf.addRow("Начало", self.in_spin)
        vf.addRow("Конец", self.out_spin)
        vf.addRow("Громкость", vol_w)
        vf.addRow("", self.mute)
        vf.addRow("Переход", self.trans)
        vf.addRow("Длительность", self.tdur)
        layout.addWidget(self.video_box)

        self.text_box = QWidget()
        tf = QFormLayout(self.text_box)
        tf.setContentsMargins(0, 0, 0, 0)
        self.text_edit = QLineEdit()
        self.font = QFontComboBox()
        self.font_btn = QPushButton("Свой шрифт…")
        self.size = QSpinBox()
        self.size.setRange(8, 240)
        self.size.setValue(48)
        self.color_btn = QPushButton("Цвет")
        self.stroke = QCheckBox("Обводка")
        self.stroke.setChecked(True)
        self.stroke_w = QSpinBox()
        self.stroke_w.setRange(0, 20)
        self.stroke_w.setValue(3)
        self.plate = QCheckBox("Плашка как в TikTok")
        self.shadow = QCheckBox("Тень")
        self.shadow.setChecked(True)
        self.t_start = QDoubleSpinBox()
        self.t_start.setRange(0, 86400)
        self.t_start.setDecimals(2)
        self.t_start.setSuffix(" с")
        self.t_dur = QDoubleSpinBox()
        self.t_dur.setRange(0.04, 86400)
        self.t_dur.setDecimals(2)
        self.t_dur.setValue(3)
        self.t_dur.setSuffix(" с")
        self.rot = QDoubleSpinBox()
        self.rot.setRange(-180, 180)
        self.rot.setSuffix(" °")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.2, 4.0)
        self.scale.setSingleStep(0.05)
        self.scale.setValue(1.0)
        self.preset_box = QComboBox()
        self.save_preset_btn = QPushButton("Сохранить стиль")
        tf.addRow("Текст", self.text_edit)
        tf.addRow("Шрифт", self.font)
        tf.addRow("", self.font_btn)
        tf.addRow("Кегль", self.size)
        tf.addRow("", self.color_btn)
        tf.addRow("", self.stroke)
        tf.addRow("Толщина", self.stroke_w)
        tf.addRow("", self.plate)
        tf.addRow("", self.shadow)
        tf.addRow("Старт", self.t_start)
        tf.addRow("Длительность", self.t_dur)
        tf.addRow("Поворот", self.rot)
        tf.addRow("Масштаб", self.scale)
        tf.addRow("Пресет", self.preset_box)
        tf.addRow("", self.save_preset_btn)
        layout.addWidget(self.text_box)

        self.shift_box = QCheckBox("Слегка сдвигать текст на уникализированных копиях (±15 px)")
        self.shift_box.setChecked(True)
        self.shift_box.setStyleSheet("QCheckBox { spacing: 8px; }")
        layout.addWidget(self.shift_box)
        layout.addStretch(1)

        self.video_box.hide()
        self.text_box.hide()

        for w in (
            self.in_spin,
            self.out_spin,
            self.tdur,
            self.t_start,
            self.t_dur,
            self.rot,
            self.scale,
            self.size,
            self.stroke_w,
        ):
            w.valueChanged.connect(self._apply)
        self.vol.valueChanged.connect(self._on_vol)
        self.mute.toggled.connect(self._apply)
        self.trans.currentIndexChanged.connect(self._apply)
        self.text_edit.textChanged.connect(self._apply)
        self.font.currentFontChanged.connect(lambda _: self._apply())
        self.stroke.toggled.connect(self._apply)
        self.plate.toggled.connect(self._apply)
        self.shadow.toggled.connect(self._apply)
        self.shift_box.toggled.connect(self._apply)
        self.color_btn.clicked.connect(self._pick_color)
        self.font_btn.clicked.connect(self._custom_font)
        self.preset_box.currentIndexChanged.connect(self._apply_preset)
        self.save_preset_btn.clicked.connect(self._save_preset)

    def set_project(self, project: EditorProject) -> None:
        self.project = project
        self._lock = True
        self.shift_box.setChecked(project.shift_text_on_uniquize)
        self._reload_presets()
        self._lock = False
        self.show_clip(self.kind, self.clip_id)

    def _reload_presets(self) -> None:
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItem("—", None)
        presets = self.project.text_presets if self.project else load_text_presets()
        for p in presets:
            self.preset_box.addItem(p.name, p.name)
        self.preset_box.blockSignals(False)

    def show_clip(self, kind: str, clip_id: str) -> None:
        self.kind, self.clip_id = kind, clip_id
        clip = self._clip()
        self.video_box.setVisible(isinstance(clip, VideoClip))
        self.text_box.setVisible(isinstance(clip, TextClip))
        if clip is None:
            self.hint.setText("Выберите клип на таймлайне или текст на холсте.")
            return
        self._lock = True
        if isinstance(clip, VideoClip):
            self.hint.setText("Видеоклип — обрезка, громкость, переход к следующему.")
            self.in_spin.setValue(clip.in_point)
            self.out_spin.setValue(clip.out_point)
            self.vol.setValue(int(clip.volume * 100))
            self.vol_lab.setText(f"{int(clip.volume * 100)}%")
            self.mute.setChecked(clip.muted)
            idx = self.trans.findData(clip.transition if clip.transition in TRANSITIONS else "none")
            self.trans.setCurrentIndex(max(0, idx))
            self.tdur.setValue(clip.transition_duration)
        elif isinstance(clip, TextClip):
            self.hint.setText("Текст — шрифт, обводка, плашка, тень, длительность на таймлайне.")
            self.text_edit.setText(clip.text)
            self.font.setCurrentFont(self.font.font())
            fam = clip.font_family
            self.font.setCurrentText(fam)
            self.size.setValue(clip.font_size)
            self.stroke.setChecked(clip.stroke_enabled)
            self.stroke_w.setValue(clip.stroke_width)
            self.plate.setChecked(clip.plate)
            self.shadow.setChecked(clip.shadow)
            self.t_start.setValue(clip.start)
            self.t_dur.setValue(clip.duration)
            self.rot.setValue(clip.rotation)
            self.scale.setValue(clip.scale)
        self._lock = False

    def _clip(self) -> VideoClip | TextClip | None:
        if self.project is None or not self.clip_id:
            return None
        if self.kind == "video":
            return next((c for c in self.project.video_clips if c.clip_id == self.clip_id), None)
        return next((c for c in self.project.text_clips if c.clip_id == self.clip_id), None)

    def _on_vol(self, value: int) -> None:
        self.vol_lab.setText(f"{value}%")
        self._apply()

    def _apply(self) -> None:
        if self._lock or self.project is None:
            return
        self.project.shift_text_on_uniquize = self.shift_box.isChecked()
        clip = self._clip()
        if isinstance(clip, VideoClip):
            clip.in_point = self.in_spin.value()
            clip.out_point = self.out_spin.value()
            clip.volume = self.vol.value() / 100.0
            clip.muted = self.mute.isChecked()
            clip.transition = str(self.trans.currentData() or "none")
            clip.transition_duration = self.tdur.value()
            clip.clamped()
        elif isinstance(clip, TextClip):
            clip.text = self.text_edit.text()
            clip.font_family = self.font.currentFont().family()
            clip.font_size = self.size.value()
            clip.stroke_enabled = self.stroke.isChecked()
            clip.stroke_width = self.stroke_w.value()
            clip.plate = self.plate.isChecked()
            clip.shadow = self.shadow.isChecked()
            clip.start = self.t_start.value()
            clip.duration = self.t_dur.value()
            clip.rotation = self.rot.value()
            clip.scale = self.scale.value()
            clip.clamped()
        self.changed.emit()

    def _pick_color(self) -> None:
        clip = self._clip()
        if not isinstance(clip, TextClip):
            return
        col = QColorDialog.getColor(QColor(clip.color), self, "Цвет текста")
        if col.isValid():
            clip.color = col.name()
            self.changed.emit()

    def _custom_font(self) -> None:
        clip = self._clip()
        if not isinstance(clip, TextClip):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Шрифт", "", "Шрифты (*.ttf *.otf *.ttc)")
        if not path:
            return
        fid = QFontDatabase.addApplicationFont(path)
        fams = QFontDatabase.applicationFontFamilies(fid)
        clip.font_file = path
        if fams:
            clip.font_family = fams[0]
            self.font.setCurrentText(fams[0])
        self.changed.emit()

    def _apply_preset(self) -> None:
        if self._lock or self.project is None:
            return
        name = self.preset_box.currentData()
        if not name:
            return
        preset = next((p for p in self.project.text_presets if p.name == name), None)
        clip = self._clip()
        if preset and isinstance(clip, TextClip):
            preset.apply_to(clip)
            self.show_clip("text", clip.clip_id)
            self.changed.emit()

    def _save_preset(self) -> None:
        clip = self._clip()
        if not isinstance(clip, TextClip) or self.project is None:
            return
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Стиль текста", "Имя пресета:")
        if not ok or not name.strip():
            return
        preset = TextStylePreset(
            name=name.strip(),
            font_family=clip.font_family,
            font_file=clip.font_file,
            font_size=clip.font_size,
            color=clip.color,
            stroke_enabled=clip.stroke_enabled,
            stroke_width=clip.stroke_width,
            stroke_color=clip.stroke_color,
            plate=clip.plate,
            plate_color=clip.plate_color,
            plate_opacity=clip.plate_opacity,
            shadow=clip.shadow,
            shadow_x=clip.shadow_x,
            shadow_y=clip.shadow_y,
            shadow_color=clip.shadow_color,
        )
        self.project.text_presets = upsert_preset(self.project.text_presets, preset)
        save_text_presets(self.project.text_presets)
        self._reload_presets()
