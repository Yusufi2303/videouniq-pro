from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from videouniq.core.filters import build_filter_complex, output_duration
from videouniq.core.hardware import EncoderChoice, cpu_encoder, is_gpu_encode_error
from videouniq.core.metadata import ffmpeg_metadata_args
from videouniq.core.params import UniqueParams
from videouniq.core.probe import MediaInfo
from videouniq.paths import cache_dir, ffmpeg_bin

try:
    from videouniq.editor.filtergraph import GraphSpec
except Exception:  # pragma: no cover - editor always ships with core
    GraphSpec = None  # type: ignore[misc,assignment]

ProgressCb = Callable[[float, str], None]
LogCb = Callable[[str], None]


class JobCancelled(RuntimeError):
    pass


def file_md5(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def append_padding(path: str | Path, nbytes: int) -> None:
    n = max(16, int(nbytes))
    with Path(path).open("ab") as fh:
        fh.write(secrets.token_bytes(n))


def extract_preview(src: str | Path, dest: str | Path, size: int = 64) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-vf",
        f"scale={size}:{size}:force_original_aspect_ratio=decrease,pad={size}:{size}:(ow-iw)/2:(oh-ih)/2:color=black",
        "-q:v",
        "3",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError((proc.stderr or "preview failed").strip() or "preview failed")
    return dest


def preview_cache_path(src: str | Path) -> Path:
    p = Path(src)
    try:
        stamp = int(p.stat().st_mtime)
        size = p.stat().st_size
    except OSError:
        stamp, size = 0, 0
    key = hashlib.sha1(f"{p.resolve()}|{stamp}|{size}".encode()).hexdigest()[:20]
    return cache_dir() / "previews" / f"{key}.jpg"


def _parse_progress_line(line: str, store: dict[str, str]) -> None:
    if "=" not in line:
        return
    key, value = line.split("=", 1)
    store[key.strip()] = value.strip()


def _seconds_from_ts(value: str) -> float:
    if not value or value in {"N/A", "nan"}:
        return 0.0
    try:
        return max(0.0, float(value) / 1_000_000)
    except ValueError:
        return 0.0


def demux_sanitize_args() -> list[str]:
    """Rebuild timestamps from phone MP4s (VFR, edit lists). Do not use +igndts:

    discarding DTS makes audio PTS = AV_NOPTS_VALUE (−2^63); x264 then finishes
    and mux dies with Conversion failed.
    """
    return [
        "-fflags",
        "+genpts+discardcorrupt",
        "-ignore_editlist",
        "1",
        "-avoid_negative_ts",
        "make_zero",
        "-start_at_zero",
    ]


def wrap_input_files(paths: list[str]) -> list[str]:
    args: list[str] = []
    video_ext = {".mp4", ".mov", ".m4v", ".qt"}
    for src in paths:
        ext = Path(src).suffix.lower()
        if ext in video_ext:
            args += demux_sanitize_args()
        args += ["-i", src]
    return args


_X264_NOISE = (
    "mb I ",
    "mb P ",
    "mb B ",
    "i16 v,h,dc,p",
    "i8 v,h,dc",
    "i4 v,h,dc",
    "i8c dc,h,v,p",
    "ref P L0",
    "ref B L0",
    "ref B L1",
    "coded y,uvDC",
    "direct mvs",
    "8x8 transform",
    "Weighted P-Frames",
    "consecutive B-frames",
    "frame I:",
    "frame P:",
    "frame B:",
    "kb/s:",
    "Qavg:",
    "using cpu capabilities",
    "profile High",
    "264 - core",
    "frame=  ",
    "No accelerated colorspace",
    "[swscaler @",
)


def ffmpeg_error_tail(stderr: str, limit: int = 30) -> str:
    """Last useful ffmpeg lines, skipping libx264 stat tables."""
    keep: list[str] = []
    for raw in (stderr or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if any(tok in line for tok in _X264_NOISE):
            continue
        keep.append(line)
    if keep:
        return "\n".join(keep[-limit:])
    lines = [ln.rstrip() for ln in (stderr or "").splitlines() if ln.strip()]
    return "\n".join(lines[-limit:])


def encode_stderr_failed(stderr: str) -> bool:
    s = (stderr or "").lower()
    keys = (
        "conversion failed",
        "error while filtering",
        "error muxing",
        "failed to avoid negative timestamp",
        "error submitting a packet",
        "invalid argument",
        "error opening",
        "non-monotonic dts",
        "922337203685477",
    )
    return any(k in s for k in keys)


def mux_sanitize_args() -> list[str]:
    return [
        "-fps_mode",
        "cfr",
        "-avoid_negative_ts",
        "make_zero",
        "-max_interleave_delta",
        "0",
        "-max_muxing_queue_size",
        "9999",
        "-shortest",
    ]


def container_output_args(params: UniqueParams, encoder_kind: str) -> list[str]:
    """Per-copy GOP, keyframe offset, timescale, and mux priming — hash-visible, eye-invisible."""
    args: list[str] = []
    gop = int(params.gop_size or 0)
    if gop > 0:
        args += ["-g", str(gop), "-keyint_min", str(max(8, gop // 2))]
        if encoder_kind == "cpu":
            args += ["-sc_threshold", str(int(params.scenecut or 40))]
    if params.keyframe_offset > 0:
        args += ["-force_key_frames", f"{params.keyframe_offset:.3f}"]
    if params.timescale > 0:
        args += ["-video_track_timescale", str(int(params.timescale))]
    args += [
        "-muxpreload",
        f"{float(params.mux_preload):.3f}",
        "-muxdelay",
        f"{float(params.mux_delay):.3f}",
    ]
    return args


def _color_args(media: MediaInfo) -> list[str]:
    rng = "tv" if media.color_range in {"tv", "limited", "mpeg"} else media.color_range
    return [
        "-colorspace",
        media.color_space or "bt709",
        "-color_primaries",
        media.color_primaries or "bt709",
        "-color_trc",
        media.color_trc or "bt709",
        "-color_range",
        rng or "tv",
    ]


def finalize_filter_graph(graph: str, vout: str = "vout") -> tuple[str, str]:
    """Force format=yuv420p immediately before the encoder map (NVENC/QSV/AMF)."""
    label = vout.strip("[]") or "vout"
    mapped = "v420"
    if f"[{mapped}]" in graph:
        mapped = "v420e"
    finalized = f"{graph};[{label}]format=yuv420p[{mapped}]"
    return finalized, f"[{mapped}]"


def encode_copy(
    media: MediaInfo,
    params: UniqueParams,
    dest: str | Path,
    encoder: EncoderChoice,
    stop_event: threading.Event | None = None,
    progress_cb: ProgressCb | None = None,
    log_cb: LogCb | None = None,
    x264_threads: int = 0,
    graph_spec: object | None = None,
    allow_cpu_fallback: bool = True,
) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    spec: GraphSpec | None = graph_spec if isinstance(graph_spec, GraphSpec) else None
    if spec is not None:
        graph = spec.graph
        input_args = wrap_input_files(list(spec.inputs))
        has_audio = spec.has_audio
        color_media = spec.as_media(media.path)
        expected = max(0.2, spec.duration)
        if params.tempo > 0:
            expected = expected / params.tempo + max(0.0, params.aac_priming_ms) / 1000.0
    else:
        graph = build_filter_complex(media, params)
        input_args = wrap_input_files([media.path])
        has_audio = media.has_audio
        color_media = media
        expected = max(0.2, output_duration(media, params))

    graph, v_map = finalize_filter_graph(graph)
    maps = ["-map", v_map]
    audio_args: list[str] = []
    if has_audio:
        maps += ["-map", "[aout]"]
        audio_args = ["-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-ac", "2"]
    else:
        audio_args = ["-an"]

    encoders = [encoder]
    if allow_cpu_fallback and encoder.kind != "cpu":
        encoders.append(cpu_encoder())

    last_error = ""
    for attempt, enc in enumerate(encoders):
        thread_args: list[str] = []
        if enc.kind == "cpu" and x264_threads > 0:
            thread_args = ["-threads", str(x264_threads)]
        cmd = [
            ffmpeg_bin(),
            "-hide_banner",
            "-y",
            "-nostdin",
            *input_args,
            "-filter_complex",
            graph,
            *maps,
            "-c:v",
            enc.video_codec,
            *enc.extra,
            *container_output_args(params, enc.kind),
            *thread_args,
            "-pix_fmt",
            "yuv420p",
            *_color_args(color_media),
            *audio_args,
            *ffmpeg_metadata_args(params),
            *mux_sanitize_args(),
            "-movflags",
            "+faststart+use_metadata_tags",
            "-progress",
            "pipe:1",
            "-nostats",
            str(dest),
        ]

        if log_cb:
            kind = "проект+уникализация" if spec is not None else enc.label
            if attempt > 0:
                log_cb(f"GPU недоступен, fallback {enc.label}")
            log_cb(f"FFmpeg {kind} → {dest.name}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        err_chunks: list[str] = []
        store: dict[str, str] = {}

        def _drain_err() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                err_chunks.append(line)
                if log_cb and ("error" in line.lower() or "failed" in line.lower()):
                    log_cb(line.rstrip())

        err_thread = threading.Thread(target=_drain_err, daemon=True)
        err_thread.start()
        code = 1
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                if stop_event is not None and stop_event.is_set():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    raise JobCancelled("Остановлено")
                line = raw.strip()
                _parse_progress_line(line, store)
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    current = _seconds_from_ts(store.get("out_time_us") or "")
                    if current <= 0 and "out_time_ms" in store:
                        try:
                            current = float(store["out_time_ms"]) / 1_000_000
                        except ValueError:
                            current = 0.0
                    frac = min(0.99, current / expected) if expected else 0.0
                    if progress_cb:
                        progress_cb(frac, "рендер")
                if line == "progress=end":
                    break
            try:
                code = proc.wait(timeout=180)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=8)
                code = -1
                err_chunks.append("ffmpeg mux timeout after encode\n")
        except JobCancelled:
            if dest.exists():
                dest.unlink(missing_ok=True)
            raise
        finally:
            err_thread.join(timeout=30)

        err_text = "".join(err_chunks)
        ok_file = dest.is_file() and dest.stat().st_size >= 64
        if code == 0 and ok_file and not encode_stderr_failed(err_text):
            append_padding(dest, params.pad_bytes)
            if progress_cb:
                progress_cb(1.0, "готово")
            return dest

        last_error = ffmpeg_error_tail(err_text) or f"ffmpeg exit {code}"
        if dest.exists():
            dest.unlink(missing_ok=True)
        can_retry = (
            attempt == 0
            and allow_cpu_fallback
            and enc.kind != "cpu"
            and is_gpu_encode_error(last_error)
        )
        if not can_retry:
            raise RuntimeError(last_error)
        if log_cb:
            log_cb(f"Ошибка GPU ({last_error.splitlines()[-1] if last_error else 'encode'}), CPU libx264")

    raise RuntimeError(last_error or "encode failed")


def uniquize_source(
    media: MediaInfo,
    copies: list[UniqueParams],
    out_dir: str | Path,
    encoder: EncoderChoice,
    stop_event: threading.Event | None = None,
    progress_cb: Callable[[int, int, float, str], None] | None = None,
    log_cb: LogCb | None = None,
    x264_threads: int = 0,
    max_hash_retries: int = 3,
) -> list[Path]:
    """Encode all copies for one source sequentially; used by tests. UI uses parallel jobs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    hashes: set[str] = set()
    for idx, params in enumerate(copies, start=1):
        dest = out_dir / f"video_{idx}.mp4"
        attempt = 0
        current = params
        while True:
            attempt += 1
            if stop_event is not None and stop_event.is_set():
                raise JobCancelled("Остановлено")

            def _cb(frac: float, stage: str, copy=idx) -> None:
                if progress_cb:
                    progress_cb(copy, len(copies), frac, stage)

            encode_copy(
                media,
                current,
                dest,
                encoder,
                stop_event=stop_event,
                progress_cb=_cb,
                log_cb=log_cb,
                x264_threads=x264_threads,
            )
            digest = file_md5(dest)
            if digest not in hashes or attempt >= max_hash_retries:
                hashes.add(digest)
                written.append(dest)
                if log_cb:
                    log_cb(f"MD5 {dest.name} = {digest}")
                break
            if log_cb:
                log_cb(f"Коллизия MD5 у {dest.name}, перегенерация ({attempt})")
            dest.unlink(missing_ok=True)
            current.pad_bytes = current.pad_bytes + 37 * attempt
            current.creation_offset_hours += 1.17 * attempt
            time.sleep(0.01)
    return written
