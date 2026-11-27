"""Clean export, ZIP of uniquized copies, cache helpers."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from videouniq.paths import cache_dir, config_dir


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


def clear_app_cache(also_autosave: bool = False) -> list[str]:
    """Delete preview/cache files. Returns list of removed roots."""
    removed: list[str] = []
    cache = cache_dir()
    if cache.is_dir():
        for child in list(cache.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
                removed.append(str(child))
            except OSError:
                continue
    if also_autosave:
        auto = config_dir() / "autosave"
        if auto.is_dir():
            shutil.rmtree(auto, ignore_errors=True)
            removed.append(str(auto))
    cache.mkdir(parents=True, exist_ok=True)
    return removed


def autosave_path() -> Path:
    dest = config_dir() / "autosave"
    dest.mkdir(parents=True, exist_ok=True)
    return dest / "current.vup"
