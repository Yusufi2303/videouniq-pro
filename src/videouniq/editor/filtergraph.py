"""One-pass FFmpeg graph: edit (trim/concat/xfade/text) + uniquize, no double encode."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from videouniq.core.filters import even, uniquize_labeled
from videouniq.core.params import UniqueParams
from videouniq.core.probe import MediaInfo
from videouniq.editor.ops import packed_starts, timeline_duration
from videouniq.editor.project import EditorProject, TextClip, VideoClip
from videouniq.editor.text_paint import clamp_text_shift, render_text_png


@dataclass
class GraphSpec:
    inputs: list[str]
    graph: str
    duration: float
    has_audio: bool
    width: int
    height: int
    fps: float
    color_space: str = "bt709"
    color_primaries: str = "bt709"
    color_trc: str = "bt709"
    color_range: str = "tv"

    def as_media(self, path: str = "") -> MediaInfo:
        return MediaInfo(
            path=path or (self.inputs[0] if self.inputs else ""),
            width=self.width,
            height=self.height,
            fps=self.fps,
            duration=self.duration,
            size_bytes=0,
            has_video=True,
            has_audio=self.has_audio,
            codec_video="",
            codec_audio="aac" if self.has_audio else "",
            pix_fmt="yuv420p",
            color_space=self.color_space,
            color_primaries=self.color_primaries,
            color_trc=self.color_trc,
            color_range=self.color_range,
            audio_rate=48000,
            audio_channels=2,
        )


def _esc_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("'", r"\'")
        .replace(":", r"\:")
        .replace("%", r"\%")
        .replace(",", r"\,")
    )


def _esc_path(path: str) -> str:
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def _hex_to_ffmpeg(color: str, opacity: float | None = None) -> str:
    c = (color or "#FFFFFF").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        c = "FFFFFF"
    if opacity is None:
        return f"0x{c}"
    alpha = max(0, min(255, int(round(float(opacity) * 255))))
    return f"0x{c}{alpha:02X}"


def _default_font_file() -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    return ""


def _drawtext_filter(clip: TextClip, width: int, height: int, dx: int, dy: int) -> str:
    size = max(8, int(round(clip.font_size * clip.scale)))
    x_expr = f"(w*{clip.x_norm:.4f})-(text_w/2)+{int(dx)}"
    y_expr = f"(h*{clip.y_norm:.4f})-(text_h/2)+{int(dy)}"
    bits = [
        f"text='{_esc_text(clip.text)}'",
        f"fontsize={size}",
        f"fontcolor={_hex_to_ffmpeg(clip.color)}",
        f"x={x_expr}",
        f"y={y_expr}",
        "reload=0",
    ]
    font_file = clip.font_file if clip.font_file and Path(clip.font_file).is_file() else ""
    if not font_file:
        font_file = _default_font_file()
    if font_file:
        bits.append(f"fontfile='{_esc_path(font_file)}'")
    elif clip.font_family:
        bits.append(f"font='{_esc_text(clip.font_family)}'")
    if clip.stroke_enabled and clip.stroke_width > 0:
        bits.append(f"borderw={int(clip.stroke_width)}")
        bits.append(f"bordercolor={_hex_to_ffmpeg(clip.stroke_color)}")
    if clip.plate:
        bits.append("box=1")
        bits.append(f"boxcolor={_hex_to_ffmpeg(clip.plate_color, clip.plate_opacity)}")
        bits.append("boxborderw=18")
    if clip.shadow:
        bits.append(f"shadowx={int(clip.shadow_x)}")
        bits.append(f"shadowy={int(clip.shadow_y)}")
        bits.append(f"shadowcolor={_hex_to_ffmpeg(clip.shadow_color)}@0.65")
    start = max(0.0, clip.start)
    end = clip.end()
    bits.append(f"enable='between(t,{start:.4f},{end:.4f})'")
    return "drawtext=" + ":".join(bits)


def _fit_chain(width: int, height: int, fps: float) -> str:
    w, h = even(width), even(height)
    rate = fps if fps > 1 else 30.0
    return (
        f"fps={rate:.4f},scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
    )


def _text_shift(project: EditorProject, params: UniqueParams | None) -> tuple[int, int]:
    if not project.shift_text_on_uniquize or params is None:
        return 0, 0
    seed = int(params.overlay_seed or params.grain_seed or 1)
    rng = random.Random(seed ^ 0xA5A5)
    return rng.randint(-15, 15), rng.randint(-15, 15)


def build_edit_and_uniquize(
    project: EditorProject,
    params: UniqueParams | None = None,
) -> GraphSpec:
    """Build a single filter_complex covering the edit graph and optional uniquize.

    One FFmpeg process, one encode. Uniquize is applied to the composed timeline,
    not as a second pass on an intermediate file.
    """
    project.sync_canvas()
    w, h = even(project.canvas_width), even(project.canvas_height)
    fps = project.fps if project.fps > 1 else 30.0
    clips = [c.clamped() for c in project.video_clips]
    duration = timeline_duration(project)
    if duration <= 0:
        duration = 1.0

    parts: list[str] = []
    inputs: list[str] = []
    index_of: dict[str, int] = {}

    def _input_idx(path: str) -> int:
        key = str(Path(path).resolve()) if path else path
        if key not in index_of:
            index_of[key] = len(inputs)
            inputs.append(key)
        return index_of[key]

    if not clips:
        parts.append(
            f"color=c=black:s={w}x{h}:r={fps:.4f}:d={duration:.4f},format=yuv420p[vcomp]"
        )
        parts.append(
            f"anullsrc=r=48000:cl=stereo:d={duration:.4f},aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[acomp]"
        )
        has_audio = True
        v_edit, a_edit = "vcomp", "acomp"
    else:
        for i, clip in enumerate(clips):
            idx = _input_idx(clip.source_path)
            start = max(0.0, clip.in_point)
            end = max(start + 0.04, clip.out_point)
            parts.append(
                f"[{idx}:v]trim=start={start:.4f}:end={end:.4f},setpts=PTS-STARTPTS,"
                f"{_fit_chain(w, h, fps)}[v{i}]"
            )
            vol = 0.0 if clip.muted else max(0.0, min(2.0, clip.volume))
            if clip.has_audio:
                parts.append(
                    f"[{idx}:a]atrim=start={start:.4f}:end={end:.4f},asetpts=PTS-STARTPTS,"
                    f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"volume={vol:.4f}[a{i}]"
                )
            else:
                dur = clip.duration()
                parts.append(
                    f"anullsrc=r=48000:cl=stereo:d={dur:.4f},"
                    f"aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                    f"volume={vol:.4f}[a{i}]"
                )

        current_v, current_a = "v0", "a0"
        current_dur = clips[0].duration()
        for i in range(1, len(clips)):
            prev = clips[i - 1]
            trans = prev.transition
            td = min(prev.transition_duration, prev.duration() * 0.45, clips[i].duration() * 0.45)
            td = max(0.2, min(1.5, td)) if trans != "none" else 0.0
            if trans == "crossfade" and td > 0:
                offset = max(0.0, current_dur - td)
                parts.append(
                    f"[{current_v}][v{i}]xfade=transition=fade:duration={td:.4f}:offset={offset:.4f}[vx{i}]"
                )
                parts.append(f"[{current_a}][a{i}]acrossfade=d={td:.4f}[ax{i}]")
                current_v, current_a = f"vx{i}", f"ax{i}"
                current_dur = current_dur + clips[i].duration() - td
            elif trans == "fade_black" and td > 0:
                fade_at = max(0.0, current_dur - td)
                parts.append(f"[{current_v}]fade=t=out:st={fade_at:.4f}:d={td:.4f}[vfo{i}]")
                parts.append(f"[v{i}]fade=t=in:st=0:d={td:.4f}[vfi{i}]")
                parts.append(f"[vfo{i}][vfi{i}]concat=n=2:v=1:a=0[vx{i}]")
                parts.append(f"[{current_a}]afade=t=out:st={fade_at:.4f}:d={td:.4f}[afo{i}]")
                parts.append(f"[a{i}]afade=t=in:st=0:d={td:.4f}[afi{i}]")
                parts.append(f"[afo{i}][afi{i}]concat=n=2:v=0:a=1[ax{i}]")
                current_v, current_a = f"vx{i}", f"ax{i}"
                current_dur = current_dur + clips[i].duration()
            else:
                parts.append(f"[{current_v}][v{i}]concat=n=2:v=1:a=0[vx{i}]")
                parts.append(f"[{current_a}][a{i}]concat=n=2:v=0:a=1[ax{i}]")
                current_v, current_a = f"vx{i}", f"ax{i}"
                current_dur += clips[i].duration()
        v_edit, a_edit = current_v, current_a
        has_audio = True
        duration = current_dur

    dx, dy = _text_shift(project, params)
    v_cur = v_edit
    if project.text_clips:
        for ti, tclip in enumerate(project.text_clips):
            nxt = f"vtx{ti}"
            jx, jy = clamp_text_shift(tclip, w, h, dx, dy)
            png = _text_png_or_none(tclip, w, h, jx, jy)
            start = max(0.0, tclip.start)
            end = tclip.end()
            if png is not None:
                idx = _input_idx(str(png))
                parts.append(
                    f"[{v_cur}][{idx}:v]overlay=0:0:format=auto:"
                    f"enable='between(t,{start:.4f},{end:.4f})'[{nxt}]"
                )
            else:
                dt = _drawtext_filter(tclip, w, h, jx, jy)
                if abs(tclip.rotation) > 0.4:
                    rad = math.radians(tclip.rotation)
                    parts.append(f"[{v_cur}]split[vkeep{ti}][vrot{ti}]")
                    parts.append(
                        f"[vrot{ti}]format=rgba,{dt},rotate={rad:.6f}:ow=iw:oh=ih:c=none:fillcolor=none[vr{ti}]"
                    )
                    parts.append(f"[vkeep{ti}][vr{ti}]overlay=0:0:format=auto[{nxt}]")
                else:
                    parts.append(f"[{v_cur}]{dt}[{nxt}]")
            v_cur = nxt

    if params is None:
        parts.append(f"[{v_cur}]format=yuv420p[vout]")
        parts.append(
            f"[{a_edit}]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[aout]"
        )
    else:
        canvas = MediaInfo(
            path=inputs[0] if inputs else "",
            width=w,
            height=h,
            fps=fps,
            duration=duration,
            size_bytes=0,
            has_video=True,
            has_audio=has_audio,
            codec_video="",
            codec_audio="aac",
            pix_fmt="yuv420p",
            color_space="bt709",
            color_primaries="bt709",
            color_trc="bt709",
            color_range="tv",
            audio_rate=48000,
            audio_channels=2,
        )
        uni = uniquize_labeled(canvas, params, v_in=v_cur, a_in=a_edit, v_out="vout", a_out="aout")
        parts.append(uni)

    graph = ";".join(p for p in parts if p)
    return GraphSpec(
        inputs=inputs,
        graph=graph,
        duration=max(0.2, duration),
        has_audio=has_audio,
        width=w,
        height=h,
        fps=fps,
    )


def _text_png_or_none(clip: TextClip, width: int, height: int, dx: int, dy: int) -> str | None:
    try:
        path = render_text_png(clip, width, height, dx, dy)
    except Exception:
        return None
    return str(path) if path and Path(path).is_file() else None


def is_one_pass_graph(graph: str) -> bool:
    """True when the graph contains both an edit op and a uniquize op."""
    edit = any(
        tok in graph
        for tok in ("trim=", "concat=", "xfade=", "drawtext=", "enable='between")
    )
    uni = any(tok in graph for tok in ("noise=", "eq=", "hue=h=", "unsharp=", "anoisesrc="))
    return edit and uni


# packed_starts imported for callers that map playhead → source
__all__ = ["GraphSpec", "build_edit_and_uniquize", "is_one_pass_graph", "packed_starts"]
