#!/usr/bin/env python3
"""Exercise the real UI and save PNG screenshots for every TZ state."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from videouniq.app import _parse_args  # noqa: F401
from videouniq.core.pipeline import uniquize_source  # ensure importable
from videouniq.paths import ffmpeg_bin
from videouniq.ui.main_window import MainWindow
from videouniq.ui.theme import apply_theme


def make_sample(path: Path) -> None:
    import subprocess

    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=960x540:rate=30:duration=3",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=330:duration=3",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/videouniq-shots")
    dest.mkdir(parents=True, exist_ok=True)
    sample = Path(tempfile.gettempdir()) / "videouniq-demo" / "demo_clip.mp4"
    if not sample.is_file():
        make_sample(sample)

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, dark=True)
    win = MainWindow()
    win.show()
    win.raise_()
    app.processEvents()

    def shot(name: str) -> None:
        app.processEvents()
        win.repaint()
        app.processEvents()
        win.grab_to(dest / name)
        print("saved", dest / name)

    shot("01-empty.png")

    win.add_paths([str(sample)])
    deadline = time.time() + 12
    while time.time() < deadline:
        app.processEvents()
        if win.items and win.items[0].info is not None and win.items[0].preview_path:
            break
        time.sleep(0.05)
    shot("02-loaded.png")

    win.right.apply_preset("manual")
    win.right.copies_spin.setValue(5)
    win.sidebar.set_page("uniquize")
    app.processEvents()
    time.sleep(0.15)
    app.processEvents()
    shot("03-manual-sliders.png")

    win.sidebar.set_page("render")
    app.processEvents()
    shot("05-render-settings.png")
    win.sidebar.set_page("meta")
    app.processEvents()
    shot("06-metadata-presets.png")
    win.sidebar.set_page("uniquize")
    app.processEvents()

    win.right.copies_spin.setValue(2)
    win.right.apply_preset("light")
    out = dest / "demo-output"
    win.right.set_output_dir(str(out))
    win.start_render()
    deadline = time.time() + 8
    while time.time() < deadline:
        app.processEvents()
        if win.items and win.items[0].progress > 0.05:
            break
        time.sleep(0.04)
    shot("04-render-progress.png")

    deadline = time.time() + 90
    while time.time() < deadline and win.controller.running:
        app.processEvents()
        time.sleep(0.05)
    app.processEvents()
    shot("04b-render-done.png")

    win.sidebar.set_page("logs")
    app.processEvents()
    shot("07-logs.png")

    print("UI demo complete")
    QTimer.singleShot(200, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
