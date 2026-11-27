from __future__ import annotations

from datetime import datetime, timedelta, timezone

from videouniq.core.params import UniqueParams

DEVICE_LABELS = {
    "iphone_13": "iPhone 13",
    "iphone_14": "iPhone 14",
    "iphone_15": "iPhone 15",
    "iphone_16": "iPhone 16",
    "samsung_s23": "Samsung Galaxy S23",
    "samsung_s24": "Samsung Galaxy S24",
    "capcut": "CapCut",
    "premiere": "Adobe Premiere Pro",
    "davinci": "DaVinci Resolve",
}


def creation_timestamp(params: UniqueParams, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    delta = timedelta(hours=float(params.creation_offset_hours))
    return now - delta


def metadata_pairs(params: UniqueParams, now: datetime | None = None) -> list[tuple[str, str]]:
    created = creation_timestamp(params, now).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    label = DEVICE_LABELS.get(params.device_preset, params.device_preset)
    pairs: list[tuple[str, str]] = [
        ("creation_time", created),
        ("date", created[:10]),
        ("title", label),
        ("artist", label),
        ("comment", label),
        ("synopsis", label),
        ("description", label),
    ]
    preset = params.device_preset
    if preset.startswith("iphone"):
        software = {
            "iphone_13": "16.7.1",
            "iphone_14": "17.5.1",
            "iphone_15": "18.1.1",
            "iphone_16": "18.2",
        }.get(preset, "18.1")
        pairs.extend(
            [
                ("make", "Apple"),
                ("model", label),
                ("copyright", "Apple"),
                ("com.apple.quicktime.make", "Apple"),
                ("com.apple.quicktime.model", label),
                ("com.apple.quicktime.software", software),
                ("com.apple.quicktime.creationdate", created),
                ("encoder", f"Apple {label}"),
            ]
        )
    elif preset.startswith("samsung"):
        model = "SM-S911B" if preset == "samsung_s23" else "SM-S921B"
        pairs.extend(
            [
                ("make", "samsung"),
                ("model", model),
                ("copyright", "samsung"),
                ("encoder", label),
            ]
        )
    elif preset == "capcut":
        pairs.extend(
            [
                ("encoder", "CapCut"),
                ("copyright", "CapCut"),
            ]
        )
    elif preset == "premiere":
        pairs.extend(
            [
                ("encoder", "Adobe Premiere Pro 24.5 (Windows)"),
                ("copyright", "Adobe Premiere Pro"),
            ]
        )
    else:
        pairs.extend(
            [
                ("encoder", "DaVinci Resolve"),
                ("copyright", "DaVinci Resolve Studio"),
            ]
        )
    return pairs


def ffmpeg_metadata_args(params: UniqueParams) -> list[str]:
    args = ["-map_metadata", "-1", "-fflags", "+bitexact"]
    if not params.write_metadata:
        return args
    for key, value in metadata_pairs(params):
        if value == "":
            continue
        args.extend(["-metadata", f"{key}={value}"])
    return args
