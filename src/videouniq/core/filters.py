from __future__ import annotations

import math

from videouniq.core.overlay import temporal_overlay_chain
from videouniq.core.params import UniqueParams
from videouniq.core.probe import MediaInfo


def even(value: float) -> int:
    n = max(2, int(round(value)))
    return n - (n % 2)


def rotation_zoom(angle_deg: float, width: int, height: int) -> float:
    a = abs(math.radians(angle_deg))
    if a < 1e-6:
        return 1.0
    zoom_w = abs(math.cos(a)) + abs(math.sin(a)) * (height / max(1, width))
    zoom_h = abs(math.cos(a)) + abs(math.sin(a)) * (width / max(1, height))
    return max(1.01, max(zoom_w, zoom_h) + 0.004)


def output_duration(media: MediaInfo, params: UniqueParams) -> float:
    trimmed = max(0.2, media.duration - params.trim_start - params.trim_end)
    tempo = params.tempo if params.tempo > 0 else 1.0
    extra = max(0.0, params.aac_priming_ms) / 1000.0
    return trimmed / tempo + extra


def _eq_notch(freq: float | None, q: float, gain: float) -> str | None:
    if freq is None or abs(gain) < 0.05:
        return None
    return f"equalizer=f={freq:.1f}:t=q:w={max(0.5, q):.2f}:g={gain:.2f}"


def _label(name: str) -> str:
    s = (name or "").strip()
    if s.startswith("[") and s.endswith("]"):
        return s
    return f"[{s}]"


def video_uniquize_filters(media: MediaInfo, params: UniqueParams) -> tuple[list[str], float | None]:
    """Video uniquize chain (no labels) plus optional trim end timestamp."""
    w, h = even(media.width), even(media.height)
    v: list[str] = []
    end = None
    if params.trim_start > 0 or params.trim_end > 0:
        start = max(0.0, params.trim_start)
        if params.trim_end > 0 and media.duration > 0:
            end = max(start + 0.2, media.duration - params.trim_end)
        if end is not None:
            v.append(f"trim=start={start:.4f}:end={end:.4f}")
        else:
            v.append(f"trim=start={start:.4f}")
        v.append("setpts=PTS-STARTPTS")

    if params.hflip:
        v.append("hflip")

    crop_pct = max(0.0, params.crop_pct) / 100.0
    need_crop = crop_pct > 0 or params.shift_x or params.shift_y
    if need_crop:
        crop_w = even(w * (1.0 - 2.0 * crop_pct)) if crop_pct > 0 else w
        crop_h = even(h * (1.0 - 2.0 * crop_pct)) if crop_pct > 0 else h
        crop_w = min(even(max(2, crop_w)), w)
        crop_h = min(even(max(2, crop_h)), h)
        if crop_w % 2:
            crop_w -= 1
        if crop_h % 2:
            crop_h -= 1
        margin_x = max(0, w - crop_w)
        margin_y = max(0, h - crop_h)
        x = (margin_x // 2) + int(params.shift_x)
        y = (margin_y // 2) + int(params.shift_y)
        x = max(0, min(margin_x, x))
        y = max(0, min(margin_y, y))
        v.append(f"crop={crop_w}:{crop_h}:{x}:{y}")
        v.append(f"scale={w}:{h}:flags=lanczos")

    if abs(params.rotate_deg) > 0.001:
        zoom = rotation_zoom(params.rotate_deg, w, h)
        zw, zh = even(w * zoom), even(h * zoom)
        if zw < w + 2:
            zw = w + 2 + (w % 2)
            zw = even(zw + 2)
        if zh < h + 2:
            zh = even(h + 4)
        v.append(f"scale={zw}:{zh}:flags=lanczos")
        rad = f"{math.radians(params.rotate_deg):.8f}"
        v.append(f"rotate={rad}:ow=iw:oh=ih:c=black:bilinear=1")
        v.append(f"crop={w}:{h}:(iw-{w})/2:(ih-{h})/2")

    eq_bits = []
    if abs(params.brightness) > 1e-6:
        eq_bits.append(f"brightness={params.brightness:.4f}")
    if abs(params.contrast - 1.0) > 1e-6:
        eq_bits.append(f"contrast={params.contrast:.4f}")
    if abs(params.saturation - 1.0) > 1e-6:
        eq_bits.append(f"saturation={params.saturation:.4f}")
    if abs(params.gamma - 1.0) > 1e-6:
        eq_bits.append(f"gamma={params.gamma:.4f}")
    if eq_bits:
        v.append("eq=" + ":".join(eq_bits))

    if abs(params.hue_deg) > 0.01:
        v.append(f"hue=h={params.hue_deg:.3f}")

    if abs(params.unsharp) > 0.02:
        amount = max(-0.8, min(0.8, params.unsharp))
        v.append(f"unsharp=lx=5:ly=5:la={amount:.3f}:ca=0")

    if params.grain:
        strength = max(1, min(3, int(params.grain_strength or 1)))
        seed = max(1, int(params.grain_seed) & 0x7FFFFFFF)
        c0, c1, c2 = seed, (seed + 41) & 0x7FFFFFFF, (seed + 73) & 0x7FFFFFFF
        v.append(
            f"noise=alls={strength}:allf=t:all_seed={seed}:c0_seed={c0}:c1_seed={c1}:c2_seed={c2}"
        )

    rate = params.fps_target if params.fps_target and params.fps_target > 1 else 0.0
    if rate <= 1:
        rate = media.fps if 5.0 < float(media.fps or 0) <= 60.5 else 30.0
    v.append(f"fps={rate:.4f}")

    if abs(params.tempo - 1.0) > 1e-4:
        v.append(f"setpts=PTS/{params.tempo:.5f}")
    else:
        v.append("setpts=PTS-STARTPTS")

    v.append("format=yuv420p")
    return v, end


def audio_uniquize_filters(media: MediaInfo, params: UniqueParams, end: float | None) -> list[str]:
    a: list[str] = []
    if params.trim_start > 0 or params.trim_end > 0:
        if end is not None:
            a.append(f"atrim=start={max(0.0, params.trim_start):.4f}:end={end:.4f}")
        else:
            a.append(f"atrim=start={max(0.0, params.trim_start):.4f}")
        a.append("asetpts=PTS-STARTPTS")

    # Do not use aresample=async=1:first_pts=0 — it writes PTS = -2^63 and
    # ffmpeg then prints x264 kb/s and dies with Conversion failed on mux.
    a.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
    rate = 48000
    pitch_ratio = 2 ** (params.pitch_semitones / 12.0) if abs(params.pitch_semitones) > 1e-6 else 1.0
    if abs(pitch_ratio - 1.0) > 1e-6:
        a.append(f"asetrate={rate}*{pitch_ratio:.8f}")
        a.append(f"aresample={rate}")
        a.append("asetpts=PTS-STARTPTS")
    atempo = params.tempo / pitch_ratio
    if abs(atempo - 1.0) > 1e-4:
        a.append(f"atempo={atempo:.5f}")
        a.append("asetpts=PTS-STARTPTS")
    if params.highpass_hz:
        a.append(f"highpass=f={params.highpass_hz:.1f}")
    if params.lowpass_hz:
        a.append(f"lowpass=f={params.lowpass_hz:.0f}")
    notch = _eq_notch(params.eq_notch_hz, params.eq_notch_q, params.eq_notch_gain)
    if notch:
        a.append(notch)
    notch2 = _eq_notch(params.eq_notch2_hz, params.eq_notch2_q, params.eq_notch2_gain)
    if notch2:
        a.append(notch2)
    a.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")

    priming = max(0.0, float(params.aac_priming_ms))
    stereo = max(0.0, min(4.0, float(params.stereo_delay_ms)))
    if priming > 0 or stereo > 0:
        if params.stereo_delay_on_left:
            left, right = priming + stereo, priming
        else:
            left, right = priming, priming + stereo
        a.append(f"adelay={left:.2f}|{right:.2f}:all=1")
    a.append("asetpts=PTS-STARTPTS")
    return a


def uniquize_labeled(
    media: MediaInfo,
    params: UniqueParams,
    v_in: str = "0:v",
    a_in: str | None = "0:a",
    v_out: str = "vout",
    a_out: str = "aout",
) -> str:
    """Uniquize filtergraph from labeled pads to ``vout`` / ``aout``."""
    w, h = even(media.width), even(media.height)
    v, end = video_uniquize_filters(media, params)
    video_chain = ",".join(v) if v else "null"
    vin = _label(v_in)
    vout = v_out.strip("[]")
    parts: list[str] = []
    if params.overlay:
        ov = temporal_overlay_chain(
            w,
            h,
            media.fps or 30.0,
            params.overlay_seed or 1,
            params.overlay_strength or 8,
            opacity=0.012 if params.overlay_strength >= 14 else 0.01,
            duration=max(1.0, output_duration(media, params) + 0.5),
        )
        parts.append(f"{vin}{video_chain}[vbase]")
        parts.append(f"{ov}[ov]")
        parts.append(f"[vbase][ov]overlay=0:0:format=yuv420:shortest=1,format=yuv420p[{vout}]")
    else:
        parts.append(f"{vin}{video_chain}[{vout}]")

    has_audio = bool(media.has_audio and a_in)
    if has_audio:
        a = audio_uniquize_filters(media, params, end)
        audio_chain = ",".join(a) if a else "anull"
        ain = _label(a_in or "0:a")
        aout_name = a_out.strip("[]")
        if params.audio_noise:
            duration = max(0.25, output_duration(media, params) + 1.0)
            color = "pink" if params.noise_color == "pink" else "white"
            seed = max(1, int(params.noise_seed) & 0x7FFFFFFF)
            parts.append(f"{ain}{audio_chain}[a1]")
            parts.append(
                "anoisesrc="
                f"color={color}:amplitude=0.003162:sample_rate=48000:"
                f"duration={duration:.4f}:seed={seed},"
                "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[ano]"
            )
            parts.append(
                f"[a1][ano]amix=inputs=2:duration=first:dropout_transition=0,"
                f"volume=1,asetpts=PTS-STARTPTS,aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[{aout_name}]"
            )
        else:
            parts.append(f"{ain}{audio_chain}[{aout_name}]")
    return ";".join(parts)


def build_filter_complex(
    media: MediaInfo,
    params: UniqueParams,
    overlay_input: int | None = None,
) -> str:
    """Build the uniquization filtergraph.

    ``overlay_input`` is ignored: overlay is generated inside the graph so it
    varies every frame instead of repeating one PNG.
    """
    del overlay_input
    a_in = "0:a" if media.has_audio else None
    return uniquize_labeled(media, params, v_in="0:v", a_in=a_in)
