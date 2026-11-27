from __future__ import annotations

import hashlib
import random
from datetime import datetime, timezone

from videouniq.core.params import (
    DEVICE_PRESETS,
    ManualRanges,
    ModuleFlags,
    PresetName,
    UniqueParams,
    flags_for_preset,
    ranges_for_preset,
)
from videouniq.core.probe import MediaInfo

PRESETS: tuple[PresetName, ...] = ("light", "optimal", "hard", "manual")


def _rng(source: str, copy_index: int, salt: int = 0) -> random.Random:
    payload = f"{source}|{copy_index}|{salt}".encode("utf-8")
    seed = int(hashlib.sha256(payload).hexdigest()[:16], 16)
    return random.Random(seed)


def _rand_signed(rng: random.Random, magnitude: float) -> float:
    if magnitude <= 0:
        return 0.0
    value = rng.uniform(magnitude * 0.25, magnitude)
    return value if rng.random() < 0.5 else -value


def _fps_target(src_fps: float, delta: float, rng: random.Random) -> float | None:
    if src_fps <= 0 or delta <= 0:
        return None
    # Prefer NTSC-ish neighbor when source is integer 30/60/24.
    catalog = []
    if abs(src_fps - 30) < 0.05:
        catalog = [29.97, 30.03, 29.94, 30.04, 29.96, 30.02]
    elif abs(src_fps - 60) < 0.05:
        catalog = [59.94, 60.06, 59.97, 60.03]
    elif abs(src_fps - 24) < 0.05:
        catalog = [23.976, 24.04, 23.98, 24.02]
    elif abs(src_fps - 25) < 0.05:
        catalog = [24.96, 25.04, 24.98, 25.03]
    if catalog:
        return rng.choice(catalog)
    sign = -1 if rng.random() < 0.5 else 1
    return round(src_fps + sign * rng.uniform(delta * 0.4, delta), 3)


def generate_params(
    media: MediaInfo,
    copy_index: int,
    flags: ModuleFlags,
    ranges: ManualRanges,
    enabled_devices: list[str] | None = None,
    salt: int = 0,
) -> UniqueParams:
    ranges = ranges.clamp()
    rng = _rng(media.path, copy_index, salt)
    devices = [d for d in (enabled_devices or list(DEVICE_PRESETS)) if d in DEVICE_PRESETS]
    if not devices:
        devices = list(DEVICE_PRESETS)

    params = UniqueParams(
        write_metadata=flags.metadata,
        device_preset=rng.choice(devices),
        creation_offset_hours=rng.uniform(24.0, 24.0 * 7.0),
        pad_bytes=rng.randint(48, 256),
    )

    remaining = max(0.6, media.duration * 0.85)
    if flags.trim and media.duration > 0.8:
        lo, hi = ranges.trim_min, ranges.trim_max
        mode = rng.choice(("start", "end", "both"))
        if mode in {"start", "both"}:
            params.trim_start = round(min(rng.uniform(lo, hi), remaining / 3), 3)
        if mode in {"end", "both"}:
            params.trim_end = round(min(rng.uniform(lo, hi), remaining / 3), 3)

    if flags.crop:
        params.crop_pct = round(rng.uniform(ranges.crop_min, ranges.crop_max), 3)

    if flags.shift:
        span = list(range(int(ranges.shift_min), int(ranges.shift_max) + 1))
        params.shift_x = rng.choice(span) * rng.choice((-1, 1))
        params.shift_y = rng.choice(span) * rng.choice((-1, 1))

    if flags.rotate and ranges.rotate_max > 0:
        params.rotate_deg = round(_rand_signed(rng, ranges.rotate_max), 3)

    if flags.color:
        params.brightness = round(_rand_signed(rng, ranges.brightness), 4)
        params.contrast = round(1.0 + _rand_signed(rng, ranges.contrast), 4)
        sat_span = min(ranges.saturation, 0.03)
        params.saturation = round(1.0 + rng.uniform(-min(sat_span, 0.02), sat_span), 4)
        params.gamma = round(1.0 + _rand_signed(rng, ranges.gamma), 4)

    if flags.fps:
        params.fps_target = _fps_target(media.fps, ranges.fps_delta, rng)

    params.grain = bool(flags.grain)
    params.overlay = bool(flags.overlay)
    if flags.mirror:
        params.hflip = rng.random() < 0.35

    if flags.tempo and ranges.tempo_delta > 0:
        params.tempo = round(1.0 + _rand_signed(rng, ranges.tempo_delta), 4)

    if flags.pitch and ranges.pitch_max > 0:
        params.pitch_semitones = round(_rand_signed(rng, ranges.pitch_max), 3)

    if flags.audio_filters:
        params.highpass_hz = round(rng.uniform(ranges.highpass_min, ranges.highpass_max), 1)
        params.lowpass_hz = round(rng.uniform(ranges.lowpass_min, ranges.lowpass_max), 0)

    params.audio_noise = bool(flags.audio_noise)
    if params.audio_noise:
        params.noise_color = rng.choice(("white", "pink"))

    return params


def generate_unique_set(
    media: MediaInfo,
    count: int,
    preset: PresetName,
    flags: ModuleFlags | None = None,
    ranges: ManualRanges | None = None,
    enabled_devices: list[str] | None = None,
) -> list[UniqueParams]:
    active_flags = flags or flags_for_preset(preset)
    active_ranges = (ranges or ranges_for_preset(preset)).clamp()
    out: list[UniqueParams] = []
    seen: set[str] = set()
    for i in range(count):
        chosen: UniqueParams | None = None
        for salt in range(48):
            candidate = generate_params(
                media, i, active_flags, active_ranges, enabled_devices, salt=salt
            )
            fp = candidate.fingerprint()
            if fp not in seen:
                seen.add(fp)
                chosen = candidate
                break
        if chosen is None:
            # Last resort: bump pad/creation so the job still proceeds.
            chosen = generate_params(
                media, i, active_flags, active_ranges, enabled_devices, salt=99
            )
            chosen.pad_bytes = 80 + i * 17
            chosen.creation_offset_hours = 24.0 + i * 3.37
        out.append(chosen)
    return out


def output_folder_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc).astimezone()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"Output_{stamp}"
