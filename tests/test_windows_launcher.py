"""Packaging contract for the Windows GUI launcher (no uniquization changes)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "windows_launcher.c"
BOOT = ROOT / "scripts" / "windows_boot.py"
ZIP = ROOT / "dist" / "VideoUniqPro-windows-x64.zip"


def _load_build():
    spec = importlib.util.spec_from_file_location(
        "build_windows_portable", ROOT / "scripts" / "build_windows_portable.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load build_windows_portable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_launcher_source_does_not_use_narrow_percent_s() -> None:
    text = SRC.read_text(encoding="utf-8")
    assert "GetModuleFileNameW" in text
    assert "python\\\\python.exe" in text or "python\\python.exe" in text
    assert "boot.py" in text
    assert "launch.log" in text
    assert "CREATE_NO_WINDOW" in text
    assert "STARTF_USESTDHANDLES" in text
    import re

    assert not re.search(r"\bswprintf\s*\(", text)
    assert 'L"%s' not in text


def test_boot_script_adds_src_and_catches_import() -> None:
    text = BOOT.read_text(encoding="utf-8")
    assert "sys.path.insert" in text
    assert "videouniq.app" in text
    assert "MessageBoxW" in text
    assert "LOCALAPPDATA" in text


def test_pth_patch_includes_src() -> None:
    mod = _load_build()
    with tempfile.TemporaryDirectory() as tmp:
        py = Path(tmp)
        (py / "python312._pth").write_text("python312.zip\n.\n", encoding="utf-8")
        mod.patch_pth(py)
        text = (py / "python312._pth").read_text(encoding="utf-8")
    assert "../src" in text
    assert "Lib/site-packages" in text
    assert text.strip().endswith("import site")


def test_compiled_exe_uses_wide_relative_python_paths() -> None:
    gcc = _which("x86_64-w64-mingw32-gcc")
    if gcc is None:
        print("SKIP compile (no mingw)")
        return
    exe = _compile()
    data = exe.read_bytes()
    assert data[:2] == b"MZ"
    assert "python\\python.exe".encode("utf-16le") in data
    assert "boot.py".encode("utf-16le") in data
    assert "launch.log".encode("utf-16le") in data
    assert "%s\\python\\pythonw.exe".encode("utf-16le") not in data
    assert "%s\\python\\python.exe".encode("utf-16le") not in data


def test_zip_contains_python_runtime_and_src_on_pth() -> None:
    if not ZIP.is_file():
        print("SKIP zip (not built yet)")
        return
    import zipfile

    with zipfile.ZipFile(ZIP) as zf:
        names = set(zf.namelist())
        pth = zf.read("VideoUniqPro/python/python312._pth").decode("utf-8")
        boot = zf.read("VideoUniqPro/boot.py").decode("utf-8")
        init = zf.read("VideoUniqPro/src/videouniq/__init__.py").decode("utf-8")
        exe = zf.getinfo("VideoUniqPro/VideoUniqPro.exe")
        pyw = zf.getinfo("VideoUniqPro/python/pythonw.exe")
        pye = zf.getinfo("VideoUniqPro/python/python.exe")
        qwin = zf.getinfo(
            "VideoUniqPro/python/Lib/site-packages/PySide6/plugins/platforms/qwindows.dll"
        )
    for req in (
        "VideoUniqPro/VideoUniqPro.exe",
        "VideoUniqPro/boot.py",
        "VideoUniqPro/python/pythonw.exe",
        "VideoUniqPro/python/python.exe",
        "VideoUniqPro/python/Lib/site-packages/sitecustomize.py",
        "VideoUniqPro/src/videouniq/__main__.py",
    ):
        assert req in names, f"zip missing {req}"
    assert "../src" in pth.replace("\\", "/")
    assert "sys.path.insert" in boot
    assert '__version__ = "2.1.2"' in init
    assert pyw.file_size > 50_000
    assert pye.file_size > 50_000
    assert exe.file_size > 20_000
    assert qwin.file_size > 50_000
    print(f"zip pythonw={pyw.file_size} python={pye.file_size} launcher={exe.file_size} qwindows={qwin.file_size}")


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _compile() -> Path:
    mod = _load_build()
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
        test_boot_script_adds_src_and_catches_import,
        test_pth_patch_includes_src,
        test_compiled_exe_uses_wide_relative_python_paths,
        test_zip_contains_python_runtime_and_src_on_pth,
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
