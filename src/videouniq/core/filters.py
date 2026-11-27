from __future__ import annotations

import math

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
    return trimmed / tempo


def build_filter_complex(media: MediaInfo, params: UniqueParams, overlay_input: int | None) -> str:
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

    # Edge crop + pixel shift, then lanczos back to source resolution.
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
        # Keep the zoomed frame size; auto-zoom already covers black corners.
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

    if params.grain:
        v.append("noise=alls=1:allf=t")

    if params.fps_target and params.fps_target > 1:
        v.append(f"fps={params.fps_target:.4f}")

    if abs(params.tempo - 1.0) > 1e-4:
        v.append(f"setpts=PTS/{params.tempo:.5f}")

    v.append("format=yuv420p")
    video_chain = ",".join(v) if v else "null"

    parts: list[str] = []
    if overlay_input is not None and params.overlay:
        parts.append(f"[0:v]{video_chain}[vbase]")
        parts.append(
            f"[{overlay_input}:v]scale={w}:{h}:flags=neighbor,format=rgba,colorchannelmixer=aa=0.01[ov]"
        )
        parts.append("[vbase][ov]overlay=0:0:format=auto:repeatlast=1[vout]")
    else:
        parts.append(f"[0:v]{video_chain}[vout]")

    if media.has_audio:
        a: list[str] = []
        if params.trim_start > 0 or params.trim_end > 0:
            if end is not None:
                a.append(f"atrim=start={max(0.0, params.trim_start):.4f}:end={end:.4f}")
            else:
                a.append(f"atrim=start={max(0.0, params.trim_start):.4f}")
            a.append("asetpts=PTS-STARTPTS")

        rate = 48000
        pitch_ratio = 2 ** (params.pitch_semitones / 12.0) if abs(params.pitch_semitones) > 1e-6 else 1.0
        if abs(pitch_ratio - 1.0) > 1e-6:
            a.append(f"asetrate={rate}*{pitch_ratio:.8f}")
            a.append(f"aresample={rate}")
        atempo = params.tempo / pitch_ratio
        if abs(atempo - 1.0) > 1e-4:
            a.append(f"atempo={atempo:.5f}")
        if params.highpass_hz:
            a.append(f"highpass=f={params.highpass_hz:.1f}")
        if params.lowpass_hz:
            a.append(f"lowpass=f={params.lowpass_hz:.0f}")
        a.append("aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo")
        audio_chain = ",".join(a) if a else "anull"

        if params.audio_noise:
            duration = max(0.25, output_duration(media, params))
            color = "pink" if params.noise_color == "pink" else "white"
            parts.append(f"[0:a]{audio_chain}[a1]")
            parts.append(
                f"anoisesrc=color={color}:amplitude=0.003162:sample_rate=48000:duration={duration:.4f}[ano]"
            )
            parts.append("[a1][ano]amix=inputs=2:duration=first:dropout_transition=0,volume=1[aout]")
        else:
            parts.append(f"[0:a]{audio_chain}[aout]")

    return ";".join(parts)
