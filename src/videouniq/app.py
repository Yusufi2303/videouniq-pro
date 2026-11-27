from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Ensure src layout works when launched as a script.
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from videouniq.ui.main_window import MainWindow
from videouniq.ui.theme import apply_theme


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="videouniq-pro")
    parser.add_argument("files", nargs="*", help="Видео или папки для очереди")
    parser.add_argument("--theme", choices=("dark", "light"), default="dark")
    parser.add_argument("--screenshot-dir", type=str, default="")
    parser.add_argument("--auto-quit-ms", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    apply_theme(app, dark=args.theme != "light")
    win = MainWindow()
    if args.theme == "light":
        win._set_dark(False)
        win.render_page.dark_toggle.setChecked(False, emit=False)
    if args.files:
        win.add_paths(args.files)
    win.show()

    if args.screenshot_dir:
        dest = Path(args.screenshot_dir)
        dest.mkdir(parents=True, exist_ok=True)

        def _shot_empty() -> None:
            win.grab_to(dest / "01-empty.png")

        QTimer.singleShot(400, _shot_empty)

    if args.auto_quit_ms > 0:
        QTimer.singleShot(args.auto_quit_ms, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
