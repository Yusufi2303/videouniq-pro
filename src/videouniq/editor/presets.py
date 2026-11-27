"""Text style presets stored next to app config."""

from __future__ import annotations

import json
from pathlib import Path

from videouniq.editor.project import DEFAULT_PRESETS, TextStylePreset
from videouniq.paths import config_dir


def text_presets_path() -> Path:
    return config_dir() / "text_presets.json"


def load_text_presets() -> list[TextStylePreset]:
    path = text_presets_path()
    if not path.is_file():
        return [p for p in DEFAULT_PRESETS]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [p for p in DEFAULT_PRESETS]
    items = data if isinstance(data, list) else data.get("presets") or []
    out = [TextStylePreset.from_dict(x) for x in items]
    return out or [p for p in DEFAULT_PRESETS]


def save_text_presets(presets: list[TextStylePreset]) -> None:
    payload = [p.to_dict() for p in presets]
    text_presets_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_preset(presets: list[TextStylePreset], preset: TextStylePreset) -> list[TextStylePreset]:
    out = [p for p in presets if p.name != preset.name]
    out.append(preset)
    save_text_presets(out)
    return out
