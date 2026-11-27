"""History of exports and uniquized downloads."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from videouniq.paths import config_dir


def history_path() -> Path:
    return config_dir() / "history.json"


def load_history() -> list[dict[str, Any]]:
    path = history_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return data
    return list(data.get("items") or [])


def save_history(items: list[dict[str, Any]]) -> None:
    history_path().write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(
    kind: str,
    name: str,
    path: str,
    copies: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "kind": kind,
        "name": name,
        "path": path,
        "copies": copies,
    }
    if extra:
        item.update(extra)
    items = load_history()
    items.insert(0, item)
    save_history(items[:200])
    return item


def clear_history() -> None:
    save_history([])
