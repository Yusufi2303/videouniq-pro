from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any, Literal

PresetName = Literal["light", "optimal", "hard", "manual"]

DEVICE_PRESETS = (
    "iphone_13",
    "iphone_13_pro_max",
    "iphone_14",
    "iphone_15",
    "iphone_15_pro_max",
    "iphone_16",
    "samsung_s23",
    "samsung_s24",
    "capcut",
    "premiere",
    "davinci",
)


@dataclass
class ModuleFlags:
    metadata: bool = True
    trim: bool = True
    tempo: bool = True
    crop: bool = True
    rotate: bool = False
    shift: bool = False
    color: bool = False
    fps: bool = False
    grain: bool = False
    overlay: bool = False
    pitch: bool = False
    audio_filters: bool = False
    audio_noise: bool = True
    mirror: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ModuleFlags:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        return cls(**{k: bool(v) for k, v in data.items() if k in valid})


@dataclass
class ManualRanges:
    crop_min: float = 0.5
    crop_max: float = 1.5
    rotate_max: float = 0.25
    shift_min: int = 1
    shift_max: int = 2
    brightness: float = 0.015
    contrast: float = 0.015
    saturation: float = 0.02
    gamma: float = 0.015
    trim_min: float = 0.03
    trim_max: float = 0.12
    tempo_delta: float = 0.012
    pitch_max: float = 0.15
    fps_delta: float = 0.04
    highpass_min: float = 25.0
    highpass_max: float = 35.0
    lowpass_min: float = 18000.0
    lowpass_max: float = 19500.0

    def clamp(self) -> ManualRanges:
        self.crop_min = _clip(self.crop_min, 0.5, 2.5)
        self.crop_max = _clip(max(self.crop_min, self.crop_max), 0.5, 2.5)
        self.rotate_max = _clip(self.rotate_max, 0.0, 0.4)
        self.shift_min = int(_clip(self.shift_min, 1, 3))
        self.shift_max = int(_clip(max(self.shift_min, self.shift_max), 1, 3))
        self.brightness = _clip(self.brightness, 0.0, 0.02)
        self.contrast = _clip(self.contrast, 0.0, 0.02)
        self.saturation = _clip(self.saturation, 0.0, 0.03)
        self.gamma = _clip(self.gamma, 0.0, 0.02)
        self.trim_min = _clip(self.trim_min, 0.03, 0.15)
        self.trim_max = _clip(max(self.trim_min, self.trim_max), 0.03, 0.15)
        self.tempo_delta = _clip(self.tempo_delta, 0.0, 0.015)
        self.pitch_max = _clip(self.pitch_max, 0.0, 0.2)
        self.fps_delta = _clip(self.fps_delta, 0.0, 0.08)
        self.highpass_min = _clip(self.highpass_min, 25.0, 35.0)
        self.highpass_max = _clip(max(self.highpass_min, self.highpass_max), 25.0, 35.0)
        self.lowpass_min = _clip(self.lowpass_min, 18000.0, 19500.0)
        self.lowpass_max = _clip(max(self.lowpass_min, self.lowpass_max), 18000.0, 19500.0)
        return self

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ManualRanges:
        if not data:
            return cls()
        valid = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in valid:
                continue
            kwargs[key] = int(value) if key.startswith("shift_") else float(value)
        return cls(**kwargs).clamp()


@dataclass
class UniqueParams:
    crop_pct: float = 0.0
    rotate_deg: float = 0.0
    shift_x: int = 0
    shift_y: int = 0
    brightness: float = 0.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    hue_deg: float = 0.0
    unsharp: float = 0.0
    trim_start: float = 0.0
    trim_end: float = 0.0
    fps_target: float | None = None
    grain: bool = False
    grain_seed: int = 0
    grain_strength: int = 1
    overlay: bool = False
    overlay_seed: int = 0
    overlay_strength: int = 8
    hflip: bool = False
    tempo: float = 1.0
    pitch_semitones: float = 0.0
    highpass_hz: float | None = None
    lowpass_hz: float | None = None
    eq_notch_hz: float | None = None
    eq_notch_q: float = 4.0
    eq_notch_gain: float = 0.0
    eq_notch2_hz: float | None = None
    eq_notch2_q: float = 4.0
    eq_notch2_gain: float = 0.0
    stereo_delay_ms: float = 0.0
    stereo_delay_on_left: bool = True
    aac_priming_ms: float = 0.0
    audio_noise: bool = False
    noise_color: str = "white"
    noise_seed: int = 0
    device_preset: str = "iphone_15"
    creation_offset_hours: float = 24.0
    metadata_token: str = ""
    pad_bytes: int = 96
    write_metadata: bool = True
    gop_size: int = 0
    keyframe_offset: float = 0.0
    scenecut: int = 40
    timescale: int = 0
    mux_preload: float = 0.5
    mux_delay: float = 0.7

    def fingerprint(self) -> str:
        """Identity of the uniquization combo, excluding always-unique padding."""
        payload = (
            round(self.crop_pct, 3),
            round(self.rotate_deg, 3),
            self.shift_x,
            self.shift_y,
            round(self.brightness, 4),
            round(self.contrast, 4),
            round(self.saturation, 4),
            round(self.gamma, 4),
            round(self.hue_deg, 3),
            round(self.unsharp, 3),
            round(self.trim_start, 3),
            round(self.trim_end, 3),
            None if self.fps_target is None else round(self.fps_target, 3),
            self.grain,
            self.grain_seed,
            self.grain_strength,
            self.overlay,
            self.overlay_seed,
            self.overlay_strength,
            self.hflip,
            round(self.tempo, 4),
            round(self.pitch_semitones, 3),
            None if self.highpass_hz is None else round(self.highpass_hz, 1),
            None if self.lowpass_hz is None else round(self.lowpass_hz, 0),
            None if self.eq_notch_hz is None else round(self.eq_notch_hz, 1),
            round(self.eq_notch_q, 2),
            round(self.eq_notch_gain, 2),
            None if self.eq_notch2_hz is None else round(self.eq_notch2_hz, 1),
            round(self.eq_notch2_q, 2),
            round(self.eq_notch2_gain, 2),
            round(self.stereo_delay_ms, 2),
            self.stereo_delay_on_left,
            round(self.aac_priming_ms, 2),
            self.audio_noise,
            self.noise_color,
            self.noise_seed,
            self.device_preset,
            round(self.creation_offset_hours, 2),
            self.metadata_token,
            self.gop_size,
            round(self.keyframe_offset, 3),
            self.scenecut,
            self.timescale,
            round(self.mux_preload, 3),
            round(self.mux_delay, 3),
        )
        return repr(payload)


@dataclass
class RenderSettings:
    encoder: str = "auto"  # auto | cpu | nvenc | qsv | amf
    threads: int = 1
    crf: int = 17
    nvenc_cq: int = 19
    nvenc_preset: str = "p6"
    cpu_preset: str = "slow"
    enabled_devices: list[str] = field(default_factory=lambda: list(DEVICE_PRESETS))
    output_dir: str = ""
    theme: str = "dark"


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def flags_for_preset(name: PresetName) -> ModuleFlags:
    if name == "light":
        return ModuleFlags(
            metadata=True,
            trim=True,
            tempo=True,
            crop=True,
            rotate=False,
            shift=False,
            color=False,
            fps=False,
            grain=False,
            overlay=False,
            pitch=False,
            audio_filters=False,
            audio_noise=True,
            mirror=False,
        )
    if name == "hard":
        return ModuleFlags(
            metadata=True,
            trim=True,
            tempo=True,
            crop=True,
            rotate=True,
            shift=True,
            color=True,
            fps=True,
            grain=True,
            overlay=True,
            pitch=True,
            audio_filters=True,
            audio_noise=True,
            mirror=True,
        )
    # optimal + default for manual
    return ModuleFlags(
        metadata=True,
        trim=True,
        tempo=True,
        crop=True,
        rotate=True,
        shift=True,
        color=True,
        fps=True,
        grain=True,
        overlay=True,
        pitch=True,
        audio_filters=True,
        audio_noise=True,
        mirror=False,
    )


def ranges_for_preset(name: PresetName) -> ManualRanges:
    if name == "light":
        return ManualRanges(
            crop_min=0.5,
            crop_max=0.5,
            rotate_max=0.0,
            shift_min=1,
            shift_max=1,
            brightness=0.0,
            contrast=0.0,
            saturation=0.0,
            gamma=0.0,
            trim_min=0.03,
            trim_max=0.08,
            tempo_delta=0.005,
            pitch_max=0.0,
            fps_delta=0.0,
        )
    if name == "hard":
        return ManualRanges(
            crop_min=1.0,
            crop_max=2.5,
            rotate_max=0.4,
            shift_min=1,
            shift_max=3,
            brightness=0.02,
            contrast=0.02,
            saturation=0.03,
            gamma=0.02,
            trim_min=0.05,
            trim_max=0.15,
            tempo_delta=0.015,
            pitch_max=0.2,
            fps_delta=0.06,
        )
    # optimal — TZ-safe geometry, still below a visible threshold
    return ManualRanges(
        crop_min=0.5,
        crop_max=1.6,
        rotate_max=0.25,
        shift_min=1,
        shift_max=2,
        brightness=0.015,
        contrast=0.015,
        saturation=0.02,
        gamma=0.015,
        trim_min=0.03,
        trim_max=0.12,
        tempo_delta=0.012,
        pitch_max=0.15,
        fps_delta=0.04,
    )
