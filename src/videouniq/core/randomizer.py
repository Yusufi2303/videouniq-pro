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
_TIMESCALES = (24000, 25000, 30000, 48000, 60000, 90000)


def _rng(source: str, copy_index: int, salt: int = 0) -> random.Random:
    payload = f"{source}|{copy_index}|{salt}".encode("utf-8")
    seed = int(hashlib.sha256(payload).hexdigest()[:16], 16)
    return random.Random(seed)


def _rand_signed(rng: random.Random, magnitude: float) -> float:
    if magnitude <= 0:
        return 0.0
    value = rng.uniform(magnitude * 0.25, magnitude)
    return value if rng.random() < 0.5 else -value


def _spread(rng: random.Random, lo: float, hi: float, copy_index: int, bins: int = 7) -> float:
    """Pick a value in [lo, hi] using a per-copy slot so copies don't cluster."""
    if hi <= lo:
        return lo
    bins = max(2, int(bins))
    slot = (hi - lo) / bins
    # Coprime stride spreads copies across the range; jitter stays inside the slot.
    bucket = (copy_index * 5) % bins
    return lo + slot * bucket + rng.uniform(0.08, 0.92) * slot


def _is_hard(ranges: ManualRanges) -> bool:
    return ranges.crop_max >= 2.0 or ranges.rotate_max >= 0.38


def fps_catalog(src_fps: float, delta: float = 0.04) -> list[float]:
    """Nearby FPS values that never equal the source rate."""
    src = float(src_fps or 0)
    if abs(src - 30) < 0.05:
        catalog = [29.97, 30.03, 29.94, 30.04, 29.96, 30.02, 29.92, 30.08]
    elif abs(src - 60) < 0.05:
        catalog = [59.94, 60.06, 59.97, 60.03, 59.90, 60.10, 59.88, 60.12]
    elif abs(src - 24) < 0.05:
        catalog = [23.976, 24.04, 23.98, 24.02, 23.94, 24.06, 23.92, 24.08]
    elif abs(src - 25) < 0.05:
        catalog = [24.96, 25.04, 24.92, 25.08, 24.88, 25.12, 24.84, 25.16]
    else:
        step = max(0.02, float(delta) * 0.5 if delta > 0 else 0.04)
        catalog = []
        k = 1
        while len(catalog) < 8:
            for sign in (-1, 1):
                val = round(src + sign * step * k, 3)
                if val > 1.0 and abs(val - src) > 0.015:
                    catalog.append(val)
            k += 1
    out: list[float] = []
    for val in catalog:
        if abs(val - src) <= 0.015:
            continue
        if any(abs(val - x) < 0.008 for x in out):
            continue
        out.append(round(val, 3))
    return out


def unique_fps_targets(src_fps: float, count: int, delta: float = 0.04) -> list[float]:
    src = float(src_fps or 25.0)
    cat = fps_catalog(src, delta)
    out: list[float] = []
    i = 0
    while len(out) < count and i < max(count * 8, 32):
        if i < len(cat):
            val = cat[i]
        else:
            k = i - len(cat) + 1
            sign = -1 if k % 2 else 1
            val = round(src + sign * (0.04 * ((k + 1) // 2) + 0.20), 3)
        i += 1
        if val <= 1.0 or abs(val - src) <= 0.015:
            continue
        if any(abs(val - x) < 0.008 for x in out):
            continue
        out.append(val)
    while len(out) < count:
        val = round(src + 0.04 * (len(out) + 1), 3)
        if abs(val - src) <= 0.015:
            val = round(src + 0.08 + 0.04 * len(out), 3)
        out.append(val)
    return out[:count]


def unique_devices(enabled: list[str] | None, count: int, rng: random.Random) -> list[str]:
    pool = [d for d in (enabled or list(DEVICE_PRESETS)) if d in DEVICE_PRESETS]
    if not pool:
        pool = list(DEVICE_PRESETS)
    order = list(pool)
    rng.shuffle(order)
    out: list[str] = []
    while len(out) < count:
        chunk = list(order)
        rng.shuffle(chunk)
        # Avoid adjacent wrap repeating the last assigned device when possible.
        if out and len(chunk) > 1 and chunk[0] == out[-1]:
            chunk[0], chunk[1] = chunk[1], chunk[0]
        out.extend(chunk)
    return out[:count]


def _fps_target(src_fps: float, delta: float, rng: random.Random) -> float | None:
    cat = fps_catalog(src_fps, delta)
    if cat:
        return rng.choice(cat)
    if src_fps <= 0 or delta <= 0:
        return None
    sign = -1 if rng.random() < 0.5 else 1
    val = round(src_fps + sign * rng.uniform(max(delta * 0.4, 0.02), max(delta, 0.04)), 3)
    if abs(val - src_fps) <= 0.015:
        val = round(src_fps + 0.04, 3)
    return val


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
    hardish = _is_hard(ranges)

    params = UniqueParams(
        write_metadata=flags.metadata,
        device_preset=rng.choice(devices),
        creation_offset_hours=rng.uniform(24.0, 24.0 * 7.0),
        pad_bytes=rng.randint(48, 256),
        metadata_token=f"{rng.randrange(16**8):08x}",
        gop_size=rng.randint(36, 96),
        keyframe_offset=round(rng.uniform(0.04, 0.22), 3),
        scenecut=rng.randint(28, 52),
        timescale=rng.choice(_TIMESCALES),
        mux_preload=round(rng.uniform(0.03, 0.18), 3),
        mux_delay=round(rng.uniform(0.05, 0.24), 3),
        aac_priming_ms=round(rng.uniform(1.5, 10.0), 2),
    )

    remaining = max(0.6, media.duration * 0.85)
    if flags.trim and media.duration > 0.8:
        lo, hi = ranges.trim_min, ranges.trim_max
        mode = rng.choice(("start", "end", "both"))
        if mode in {"start", "both"}:
            params.trim_start = round(min(_spread(rng, lo, hi, copy_index, 5), remaining / 3), 3)
        if mode in {"end", "both"}:
            params.trim_end = round(min(rng.uniform(lo, hi), remaining / 3), 3)

    if flags.crop:
        params.crop_pct = round(_spread(rng, ranges.crop_min, ranges.crop_max, copy_index, 8), 3)

    if flags.shift:
        span = list(range(int(ranges.shift_min), int(ranges.shift_max) + 1))
        sx = span[copy_index % len(span)]
        sy = span[(copy_index // len(span) + salt) % len(span)]
        params.shift_x = sx if (copy_index // 2) % 2 == 0 else -sx
        params.shift_y = -sy if copy_index % 2 == 0 else sy
        if salt % 2:
            params.shift_x = -params.shift_x

    if flags.rotate and ranges.rotate_max > 0:
        mag = _spread(rng, ranges.rotate_max * 0.40, ranges.rotate_max, copy_index, 6)
        sign = -1 if copy_index % 2 == 0 else 1
        if salt:
            sign = -sign if salt % 2 else sign
        params.rotate_deg = round(sign * mag, 3)

    if flags.color:
        params.brightness = round(_rand_signed(rng, ranges.brightness), 4)
        params.contrast = round(1.0 + _rand_signed(rng, ranges.contrast), 4)
        sat_span = min(ranges.saturation, 0.03)
        params.saturation = round(1.0 + rng.uniform(-min(sat_span, 0.02), sat_span), 4)
        params.gamma = round(1.0 + _rand_signed(rng, ranges.gamma), 4)
        hue_max = 2.6 if hardish else 1.2
        params.hue_deg = round(_rand_signed(rng, hue_max), 3)
        if hardish:
            params.unsharp = round(rng.uniform(0.22, 0.52), 3)
        else:
            params.unsharp = round(rng.uniform(0.12, 0.28), 3)

    if flags.fps:
        params.fps_target = _fps_target(media.fps, ranges.fps_delta, rng)

    if flags.grain:
        params.grain = True
        params.grain_seed = rng.randint(1, 2**31 - 2)
        params.grain_strength = 2 if hardish and rng.random() < 0.55 else 1

    if flags.overlay:
        params.overlay = True
        params.overlay_seed = rng.randint(1, 2**31 - 2)
        params.overlay_strength = rng.randint(10, 18) if hardish else rng.randint(6, 12)

    if flags.mirror:
        params.hflip = rng.random() < 0.45

    if flags.tempo and ranges.tempo_delta > 0:
        params.tempo = round(1.0 + _rand_signed(rng, ranges.tempo_delta), 4)

    if flags.pitch and ranges.pitch_max > 0:
        params.pitch_semitones = round(_rand_signed(rng, ranges.pitch_max), 3)

    if flags.audio_filters:
        params.highpass_hz = round(rng.uniform(ranges.highpass_min, ranges.highpass_max), 1)
        params.lowpass_hz = round(rng.uniform(ranges.lowpass_min, ranges.lowpass_max), 0)
        gain_hi = 1.45 if hardish else 1.0
        params.eq_notch_hz = round(_spread(rng, 280.0, 1600.0, copy_index, 6), 1)
        params.eq_notch_q = round(rng.uniform(3.5, 7.5), 2)
        params.eq_notch_gain = round(-rng.uniform(0.35, gain_hi), 2)
        params.eq_notch2_hz = round(_spread(rng, 2200.0, 7600.0, copy_index + 2, 6), 1)
        params.eq_notch2_q = round(rng.uniform(3.2, 7.0), 2)
        params.eq_notch2_gain = round(-rng.uniform(0.35, gain_hi), 2)

    if media.has_audio and (flags.audio_filters or flags.audio_noise or flags.tempo or flags.pitch):
        delay_hi = 4.0 if hardish else 3.2
        params.stereo_delay_ms = round(rng.uniform(1.0, delay_hi), 2)
        params.stereo_delay_on_left = rng.random() < 0.5

    params.audio_noise = bool(flags.audio_noise)
    if params.audio_noise:
        params.noise_color = rng.choice(("white", "pink"))
        params.noise_seed = rng.randint(1, 2**31 - 2)

    return params


def _assign_batch_uniques(
    out: list[UniqueParams],
    media: MediaInfo,
    flags: ModuleFlags,
    ranges: ManualRanges,
    enabled_devices: list[str] | None,
    size_mode: str,
) -> None:
    """No repeated device/FPS/pad within one batch; never keep source FPS."""
    rng = _rng(media.path, 0, salt=7)
    devices = unique_devices(enabled_devices, len(out), rng)
    fps_list = unique_fps_targets(media.fps, len(out), ranges.fps_delta)
    seen_pad: set[int] = set()
    seen_dur: list[float] = []
    br = int(getattr(media, "bit_rate", 0) or 0)
    if br <= 0 and media.duration > 0.2 and media.size_bytes > 1000:
        total = int(media.size_bytes * 8 / media.duration)
        br = max(80_000, total - (128_000 if media.has_audio else 0))
    for i, params in enumerate(out):
        params.device_preset = devices[i]
        if flags.fps:
            params.fps_target = fps_list[i]
        pad = 96 + i * 173 + (params.pad_bytes % 37)
        while pad in seen_pad:
            pad += 19
        seen_pad.add(pad)
        params.pad_bytes = pad
        if flags.grain:
            params.grain_seed = ((params.grain_seed or 1) + (i + 1) * 104729) & 0x7FFFFFFF or 1
        if flags.overlay:
            params.overlay_seed = ((params.overlay_seed or 1) + (i + 1) * 6271) & 0x7FFFFFFF or 1
        if flags.tempo and params.tempo:
            dur = max(0.2, media.duration / params.tempo - params.trim_start - params.trim_end)
        else:
            dur = max(0.2, media.duration - params.trim_start - params.trim_end)
        guard = 0
        while (
            any(abs(dur - d) < 0.012 for d in seen_dur) or abs(dur - media.duration) < 0.012
        ) and guard < 12:
            params.trim_end = round(params.trim_end + 0.018, 3)
            dur = max(0.2, media.duration / max(params.tempo, 0.5) - params.trim_start - params.trim_end)
            guard += 1
        seen_dur.append(dur)
        if size_mode == "smart" and br > 0:
            factor = 1.15 + (i % 5) * 0.0375  # 1.15 … 1.30
            params.maxrate_bps = int(br * factor)
        else:
            params.maxrate_bps = 0


def generate_unique_set(
    media: MediaInfo,
    count: int,
    preset: PresetName,
    flags: ModuleFlags | None = None,
    ranges: ManualRanges | None = None,
    enabled_devices: list[str] | None = None,
    size_mode: str = "quality",
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
            # Last resort: bump identity fields so the job still proceeds.
            chosen = generate_params(
                media, i, active_flags, active_ranges, enabled_devices, salt=99
            )
            chosen.pad_bytes = 80 + i * 17
            chosen.creation_offset_hours = 24.0 + i * 3.37
            chosen.metadata_token = f"{i:08x}{chosen.metadata_token[:8]}"
            chosen.grain_seed = (chosen.grain_seed + 7919 * (i + 1)) & 0x7FFFFFFF
            chosen.overlay_seed = (chosen.overlay_seed + 6271 * (i + 1)) & 0x7FFFFFFF
            chosen.gop_size = 36 + (i % 60)
            chosen.noise_seed = (chosen.noise_seed + 104729 * (i + 1)) & 0x7FFFFFFF
            seen.add(chosen.fingerprint())
        out.append(chosen)
    _assign_batch_uniques(out, media, active_flags, active_ranges, enabled_devices, size_mode)
    return out


def output_folder_name(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc).astimezone()).strftime("%Y-%m-%d_%H-%M-%S")
    return f"Output_{stamp}"
