from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

DARK = {
    "bg": "#121417",
    "surface": "#1B1E24",
    "surface2": "#22262E",
    "border": "#2A2F3A",
    "accent": "#3B82F6",
    "accent_dim": "#2563EB",
    "cta": "#10B981",
    "cta_hover": "#059669",
    "text": "#F3F4F6",
    "muted": "#9CA3AF",
    "success": "#10B981",
    "progress": "#F59E0B",
    "error": "#EF4444",
    "hover": "#252A33",
}

LIGHT = {
    "bg": "#F3F4F6",
    "surface": "#FFFFFF",
    "surface2": "#EEF1F6",
    "border": "#D1D5DB",
    "accent": "#2563EB",
    "accent_dim": "#1D4ED8",
    "cta": "#059669",
    "cta_hover": "#047857",
    "text": "#111827",
    "muted": "#6B7280",
    "success": "#059669",
    "progress": "#D97706",
    "error": "#DC2626",
    "hover": "#E5E7EB",
}


def build_qss(c: dict[str, str]) -> str:
    return f"""
* {{
  font-family: Inter, "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif;
  font-size: 14px;
}}
QMainWindow, QWidget#Root {{
  background: {c["bg"]};
  color: {c["text"]};
}}
QLabel {{
  background: transparent;
  color: {c["text"]};
}}
QLabel[muted="true"] {{
  color: {c["muted"]};
  font-size: 12px;
}}
QLabel[heading="true"] {{
  font-size: 16px;
  font-weight: 600;
}}
QFrame#Sidebar {{
  background: {c["surface"]};
  border-right: 1px solid {c["border"]};
}}
QFrame#RightPanel {{
  background: {c["surface"]};
  border-left: 1px solid {c["border"]};
}}
QFrame#FileCard {{
  background: {c["surface"]};
  border: 1px solid {c["border"]};
  border-radius: 10px;
}}
QFrame#FileCard:hover {{
  border-color: {c["accent"]};
}}
QLabel#ProjectBadge {{
  background: {c["accent"]};
  color: #FFFFFF;
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
}}
QFrame#EditorZone {{
  background: {c["surface"]};
  border: 1px solid {c["border"]};
  border-radius: 10px;
}}
QFrame#Timeline {{
  background: {c["surface"]};
  border: 1px solid {c["border"]};
}}
QWidget#CanvasHost {{
  background: #0B0D10;
}}
QWidget#CanvasOverlay {{
  background: transparent;
}}
QDialog#UniquenessDialog {{
  background: {c["surface"]};
  color: {c["text"]};
}}
QTableWidget#UniquenessTable {{
  background: {c["surface2"]};
  color: {c["text"]};
  gridline-color: {c["border"]};
  border: 1px solid {c["border"]};
  border-radius: 8px;
}}
QTableWidget#UniquenessTable::item {{
  padding: 6px;
}}
QHeaderView::section {{
  background: {c["surface"]};
  color: {c["muted"]};
  border: none;
  padding: 6px;
}}
QSlider#VolumeSlider::groove:horizontal {{
  height: 4px;
}}
QSplitter::handle {{
  background: {c["border"]};
}}
QListWidget {{
  background: {c["surface2"]};
  border: 1px solid {c["border"]};
  border-radius: 8px;
  color: {c["text"]};
  outline: none;
}}
QListWidget::item:selected {{
  background: {c["accent"]};
  color: #FFFFFF;
}}
QTabWidget::pane {{
  border: 1px solid {c["border"]};
  border-radius: 8px;
  background: {c["surface"]};
}}
QTabBar::tab {{
  background: {c["surface2"]};
  color: {c["muted"]};
  padding: 6px 12px;
  border-top-left-radius: 8px;
  border-top-right-radius: 8px;
}}
QTabBar::tab:selected {{
  background: {c["surface"]};
  color: {c["text"]};
}}
QFrame#DropZone {{
  background: {c["surface"]};
  border: 1.5px dashed {c["border"]};
  border-radius: 16px;
}}
QFrame#DropZone[active="true"] {{
  border-color: {c["accent"]};
  background: {c["surface2"]};
}}
QPushButton {{
  background: {c["surface2"]};
  color: {c["text"]};
  border: 1px solid {c["border"]};
  border-radius: 8px;
  padding: 7px 12px;
}}
QPushButton:hover {{
  background: {c["hover"]};
  border-color: {c["accent"]};
}}
QPushButton:pressed {{
  background: {c["border"]};
}}
QPushButton:disabled {{
  color: {c["muted"]};
  background: {c["surface"]};
}}
QPushButton#CtaButton {{
  background: {c["cta"]};
  color: #FFFFFF;
  border: none;
  border-radius: 10px;
  padding: 12px 16px;
  font-size: 14px;
  font-weight: 600;
}}
QPushButton#CtaButton:hover {{
  background: {c["cta_hover"]};
}}
QPushButton#CtaButton:disabled {{
  background: {c["border"]};
  color: {c["muted"]};
}}
QPushButton#StopButton {{
  background: {c["error"]};
  color: #FFFFFF;
  border: none;
  font-weight: 600;
  border-radius: 10px;
  padding: 12px 16px;
}}
QPushButton#GhostButton {{
  background: transparent;
  border: 1px solid {c["border"]};
}}
QPushButton#IconButton {{
  background: transparent;
  border: none;
  padding: 4px;
  min-width: 28px;
  max-width: 32px;
}}
QPushButton#NavBtn {{
  text-align: left;
  padding: 10px 14px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: {c["muted"]};
}}
QPushButton#NavBtn:hover {{
  background: {c["hover"]};
  color: {c["text"]};
}}
QPushButton#NavBtn[active="true"] {{
  background: {c["surface2"]};
  color: {c["text"]};
  font-weight: 600;
  border-left: 3px solid {c["accent"]};
}}
QPushButton#Chip {{
  border-radius: 16px;
  padding: 4px 12px;
  background: {c["surface2"]};
  border: 1px solid {c["border"]};
  color: {c["muted"]};
}}
QPushButton#Chip[active="true"] {{
  background: {c["accent"]};
  color: #FFFFFF;
  border-color: {c["accent"]};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {c["surface2"]};
  color: {c["text"]};
  border: 1px solid {c["border"]};
  border-radius: 8px;
  padding: 6px 8px;
  selection-background-color: {c["accent"]};
}}
QComboBox QAbstractItemView {{
  background: {c["surface"]};
  color: {c["text"]};
  border: 1px solid {c["border"]};
  selection-background-color: {c["accent"]};
}}
QScrollArea {{
  border: none;
  background: transparent;
}}
QScrollBar:vertical {{
  background: transparent;
  width: 10px;
  margin: 4px;
}}
QScrollBar::handle:vertical {{
  background: {c["border"]};
  border-radius: 4px;
  min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
  height: 0;
}}
QProgressBar {{
  background: {c["surface2"]};
  border: none;
  border-radius: 4px;
  height: 6px;
  text-align: center;
  color: transparent;
}}
QProgressBar::chunk {{
  background: {c["progress"]};
  border-radius: 4px;
}}
QProgressBar[state="done"]::chunk {{
  background: {c["success"]};
}}
QProgressBar[state="error"]::chunk {{
  background: {c["error"]};
}}
QCheckBox {{
  spacing: 8px;
  color: {c["text"]};
}}
QCheckBox::indicator {{
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1px solid {c["border"]};
  background: {c["surface2"]};
}}
QCheckBox::indicator:checked {{
  background: {c["accent"]};
  border-color: {c["accent"]};
}}
QSlider::groove:horizontal {{
  height: 4px;
  background: {c["border"]};
  border-radius: 2px;
}}
QSlider::handle:horizontal {{
  width: 14px;
  height: 14px;
  margin: -6px 0;
  border-radius: 7px;
  background: {c["accent"]};
}}
QSlider::sub-page:horizontal {{
  background: {c["accent"]};
  border-radius: 2px;
}}
QPlainTextEdit, QTextEdit {{
  background: {c["surface"]};
  color: {c["text"]};
  border: 1px solid {c["border"]};
  border-radius: 10px;
  font-family: "JetBrains Mono", Consolas, monospace;
  font-size: 12px;
  padding: 8px;
}}
QGroupBox {{
  border: 1px solid {c["border"]};
  border-radius: 10px;
  margin-top: 12px;
  padding: 12px 10px 10px 10px;
  color: {c["muted"]};
  font-size: 12px;
}}
QGroupBox::title {{
  subcontrol-origin: margin;
  left: 12px;
  padding: 0 6px;
}}
QToolTip {{
  background: {c["surface2"]};
  color: {c["text"]};
  border: 1px solid {c["border"]};
  padding: 4px 8px;
}}
"""


def apply_theme(app: QApplication, dark: bool = True) -> dict[str, str]:
    colors = DARK if dark else LIGHT
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(colors["bg"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(colors["surface"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(colors["surface2"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(colors["surface2"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["surface2"]))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
    app.setPalette(pal)
    font = QFont("Inter")
    if font.exactMatch() is False:
        font = QFont("Segoe UI")
        if font.exactMatch() is False:
            font = QFont("Noto Sans")
    font.setPixelSize(14)
    app.setFont(font)
    app.setStyleSheet(build_qss(colors))
    return colors
