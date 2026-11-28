"""Windows portable entry: put src on sys.path, set Qt plugin dirs, surface errors.

Embeddable CPython ignores PYTHONPATH when python*._pth is present. This script
does not rely on that variable. Keep imports inside main() so a missing PySide6
still produces a MessageBox instead of a silent pythonw exit.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def prepare_runtime() -> None:
    os.chdir(str(ROOT))
    src = ROOT / "src"
    src_s = str(src)
    if src.is_dir() and src_s not in sys.path:
        sys.path.insert(0, src_s)
    py = ROOT / "python"
    site = py / "Lib" / "site-packages"
    pyside = site / "PySide6"
    shiboken = site / "shiboken6"
    ffmpeg = ROOT / "vendor" / "ffmpeg" / "win64"
    prepend = [str(ffmpeg), str(py), str(pyside), str(shiboken)]
    os.environ["PATH"] = os.pathsep.join(prepend + [os.environ.get("PATH", "")])
    plugins = pyside / "plugins"
    os.environ["QT_PLUGIN_PATH"] = str(plugins)
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins / "platforms")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ["PYTHONPATH"] = src_s


def log_paths() -> list[Path]:
    paths = [ROOT / "VideoUniqPro-launch.log"]
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        folder = Path(local) / "VideoUniqPro"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            paths.append(folder / "launch.log")
        except OSError:
            pass
    return paths


def write_logs(text: str) -> Path | None:
    last: Path | None = None
    payload = text if text.endswith("\n") else text + "\n"
    for path in log_paths():
        try:
            path.write_text(payload, encoding="utf-8")
            last = path
        except OSError:
            continue
    return last


def message_box(text: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text[:4000], "VideoUniq Pro", 0x10)
    except Exception:
        pass


def fail(title: str, err: BaseException | None = None) -> int:
    tb = traceback.format_exc() if err is not None else title
    log = write_logs(tb)
    body = title + "\n\n" + tb[-1800:]
    if log is not None:
        body += f"\n\nЖурнал: {log}"
    message_box(body)
    return 1


def main() -> int:
    prepare_runtime()
    try:
        from videouniq.app import main as app_main
    except Exception as exc:
        return fail("Не удалось импортировать VideoUniq Pro (Python/Qt).", exc)
    try:
        return int(app_main())
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return 0
        if isinstance(code, int):
            if code != 0:
                write_logs(f"sys.exit({code})\n")
            return code
        return fail("VideoUniq Pro завершился с ошибкой.", exc)
    except Exception as exc:
        return fail("Ошибка при запуске окна VideoUniq Pro.", exc)


if __name__ == "__main__":
    raise SystemExit(main())
