"""Packaging contract for the Windows GUI launcher (no uniquization changes)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "windows_launcher.c"
EXE = ROOT / "build" / "win-launcher" / "VideoUniqPro.exe"
ZIP = ROOT / "dist" / "VideoUniqPro-windows-x64.zip"


def test_launcher_source_does_not_use_narrow_percent_s() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "GetModuleFileNameW" in text
    assert "python\\\\pythonw.exe" in text or "python\\pythonw.exe" in text
    assert "python\\\\python.exe" in text or "python\\python.exe" in text
    # MinGW C99 swprintf %s is char* — that truncated the exe dir to "C".
    import re

    assert not re.search(r"\bswprintf\s*\(", text)
    assert 'L"%s' not in text


def test_compiled_exe_uses_wide_relative_python_paths() -> None:
    gcc = _which("x86_64-w64-mingw32-gcc")
    if gcc is None:
        print("SKIP compile (no mingw)")
        return
    exe = _compile()
    data = exe.read_bytes()
    assert data[:2] == b"MZ"
    pyw = "python\\pythonw.exe".encode("utf-16le")
    pye = "python\\python.exe".encode("utf-16le")
    assert pyw in data, "exe must embed python\\pythonw.exe as UTF-16"
    assert pye in data, "exe must embed python\\python.exe as UTF-16"
    # The broken 2.1.0 format string looked up C\python\pythonw.exe.
    assert "%s\\python\\pythonw.exe".encode("utf-16le") not in data
    assert "%s\\python\\python.exe".encode("utf-16le") not in data


def test_zip_contains_pythonw_next_to_layout() -> None:
    if not ZIP.is_file():
        print("SKIP zip (not built yet)")
        return
    import zipfile

    with zipfile.ZipFile(ZIP) as zf:
        names = set(zf.namelist())
    for req in (
        "VideoUniqPro/VideoUniqPro.exe",
        "VideoUniqPro/python/pythonw.exe",
        "VideoUniqPro/python/python.exe",
        "VideoUniqPro/VideoUniqPro.bat",
        "VideoUniqPro/src/videouniq/__init__.py",
    ):
        assert req in names, f"zip missing {req}"
    with zipfile.ZipFile(ZIP) as zf:
        pyw = zf.getinfo("VideoUniqPro/python/pythonw.exe")
        pye = zf.getinfo("VideoUniqPro/python/python.exe")
        exe = zf.getinfo("VideoUniqPro/VideoUniqPro.exe")
    assert pyw.file_size > 50_000, pyw.file_size
    assert pye.file_size > 50_000, pye.file_size
    assert exe.file_size > 20_000, exe.file_size
    print(f"zip pythonw={pyw.file_size} python={pye.file_size} launcher={exe.file_size}")


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _compile() -> Path:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_windows_portable", ROOT / "scripts" / "build_windows_portable.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load build_windows_portable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dest_dir = ROOT / "build" / "win-launcher"
    dest_dir.mkdir(parents=True, exist_ok=True)
    exe = mod.compile_windows_exe(dest_dir)
    if exe is None or not exe.is_file():
        raise RuntimeError("failed to compile VideoUniqPro.exe")
    return exe


def main() -> int:
    failed = 0
    for fn in (
        test_launcher_source_does_not_use_narrow_percent_s,
        test_compiled_exe_uses_wide_relative_python_paths,
        test_zip_contains_pythonw_next_to_layout,
    ):
        try:
            fn()
            print("PASS", fn.__name__)
        except Exception as exc:
            failed += 1
            print("FAIL", fn.__name__, exc)
    if failed:
        print(f"FAILED={failed}")
        return 1
    print("ALL WINDOWS LAUNCHER TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
