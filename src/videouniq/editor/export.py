"""Clean export, ZIP of uniquized copies, cache helpers."""

from __future__ import annotations

import shutil
import time
import zipfile
from pathlib import Path

from videouniq.paths import cache_dir, config_dir

_TRANSIENT = ("proxies", "text", "previews", "tmp", "render", "noise")


def zip_copies(folder: str | Path, dest: str | Path | None = None) -> Path:
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(str(folder))
    videos = sorted(p for p in folder.glob("*.mp4") if p.is_file())
    if not videos:
        videos = sorted(p for p in folder.rglob("*.mp4") if p.is_file())
    if not videos:
        raise FileNotFoundError("Нет готовых mp4 для архива")
    dest = Path(dest) if dest else folder / f"{folder.name}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in videos:
            zf.write(path, arcname=path.name)
    return dest


def autosave_path() -> Path:
    dest = cache_dir() / "autosave"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / "current.vup"


def _is_autosave(path: Path) -> bool:
    return path.name == "current.vup" and "autosave" in path.parts


def cache_size_bytes(root: Path | None = None) -> int:
    root = root or cache_dir()
    total = 0
    if not root.is_dir():
        return 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


def cache_size_label(nbytes: int | None = None) -> str:
    n = cache_size_bytes() if nbytes is None else max(0, int(nbytes))
    if n < 1024:
        return f"Размер кэша: {n} Б"
    if n < 1024 * 1024:
        return f"Размер кэша: {n / 1024:.0f} КБ"
    return f"Размер кэша: {n / (1024 * 1024):.1f} МБ"


def _unlink(path: Path, removed: list[str]) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            path.unlink(missing_ok=True)
        else:
            return
        removed.append(str(path))
    except OSError:
        return


def purge_cache_older_than(hours: float = 24.0, keep_autosave: bool = True) -> list[str]:
    """On start: drop crash leftovers older than ``hours`` (keep last .vup autosave)."""
    removed: list[str] = []
    cache = cache_dir()
    if not cache.is_dir():
        return removed
    cutoff = time.time() - max(0.0, float(hours)) * 3600.0
    for path in list(cache.rglob("*")):
        if not path.is_file():
            continue
        if keep_autosave and _is_autosave(path):
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        _unlink(path, removed)
    _prune_empty(cache)
    return removed


def cleanup_on_quit(keep_autosave: bool = True) -> list[str]:
    """On close: delete temp render/proxy/text; keep last unsaved .vup autosave."""
    removed: list[str] = []
    cache = cache_dir()
    if not cache.is_dir():
        return removed
    for name in _TRANSIENT:
        folder = cache / name
        if folder.exists():
            _unlink(folder, removed)
    for child in list(cache.iterdir()):
        if keep_autosave and child.name == "autosave":
            continue
        if child.name == "autosave" and not keep_autosave:
            _unlink(child, removed)
    cache.mkdir(parents=True, exist_ok=True)
    return removed


def clear_app_cache(also_autosave: bool = False) -> list[str]:
    """Settings «Очистить кэш сейчас». Keeps last autosave unless also_autosave."""
    removed: list[str] = []
    cache = cache_dir()
    if cache.is_dir():
        for child in list(cache.iterdir()):
            if not also_autosave and child.name == "autosave":
                continue
            _unlink(child, removed)
    if also_autosave:
        legacy = config_dir() / "autosave"
        if legacy.is_dir():
            _unlink(legacy, removed)
    cache.mkdir(parents=True, exist_ok=True)
    return removed


def _prune_empty(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_dir() or path == root:
            continue
        if path.name == "autosave":
            continue
        if not any(path.iterdir()):
            try:
                path.rmdir()
            except OSError:
                continue
