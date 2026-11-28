#!/usr/bin/env python3
"""Rasterize the VU mark into PNG + ICO for the Windows exe."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "videouniq" / "resources"


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT / "src"))
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["vu-icon"])
    OUT.mkdir(parents=True, exist_ok=True)

    img = QImage(256, 256, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(8, 8, 240, 240, 56, 56)
    p.fillPath(path, QColor("#3B82F6"))
    p.setPen(QColor("#FFFFFF"))
    font = QFont("DejaVu Sans", 92)
    font.setBold(True)
    p.setFont(font)
    p.drawText(img.rect(), int(Qt.AlignmentFlag.AlignCenter), "VU")
    p.end()

    png = OUT / "app.png"
    ico = OUT / "app.ico"
    if not img.save(str(png), "PNG"):
        raise SystemExit("png save failed")
    if not img.save(str(ico), "ICO"):
        # Qt ICO writer may be missing; wrap PNG in a Vista ICO.
        data = png.read_bytes()
        import struct

        header = struct.pack("<HHH", 0, 1, 1)
        entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22)
        ico.write_bytes(header + entry + data)
    print("wrote", png, ico, ico.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
