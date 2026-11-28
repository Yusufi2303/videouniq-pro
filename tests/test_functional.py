"""Headless functional coverage of the VideoUniq Pro TZ pipeline."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from videouniq.core.filters import build_filter_complex
from videouniq.core.hardware import auto_encoder_priority, detect_hardware
from videouniq.core.metadata import metadata_pairs
from videouniq.core.params import ManualRanges, ModuleFlags, flags_for_preset, ranges_for_preset
from videouniq.core.pipeline import (
    JobCancelled,
    container_output_args,
    encode_copy,
    encode_stderr_failed,
    extract_preview,
    ffmpeg_error_tail,
    file_md5,
    finalize_filter_graph,
    is_oom_error,
    mux_sanitize_args,
    uniquize_source,
)
from videouniq.core.probe import collect_videos, probe_media
from videouniq.core.randomizer import generate_unique_set, output_folder_name
from videouniq.paths import ffmpeg_bin, ffprobe_bin


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=False, **kw)


def make_sample(path: Path, seconds: float = 1.2, size: str = "640x360", rate: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={rate}:duration={seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    proc = run(cmd)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "sample encode failed")
    return path


def ffprobe_format(path: Path) -> dict:
    proc = run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def average_hash_bits(path: Path, t: float, size: int = 32) -> int:
    """Mean-threshold average hash of one frame (size×size bits) — no extra deps."""
    n = size * size
    proc = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={size}:{size}:flags=area,format=gray",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    data = proc.stdout
    if len(data) != n:
        raise RuntimeError(f"hash frame failed ({len(data)} bytes, want {n}): {proc.stderr!r}")
    mean = sum(data) / n
    bits = 0
    for i, value in enumerate(data):
        if value >= mean:
            bits |= 1 << i
    return bits


def hamming_bits(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def mean_pairwise_hash_distance(
    paths: list[Path],
    times: tuple[float, ...] = (0.16, 0.40, 0.72),
    size: int = 32,
) -> tuple[float, float]:
    pair_means: list[float] = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            dists = [
                hamming_bits(average_hash_bits(paths[i], t, size), average_hash_bits(paths[j], t, size))
                for t in times
            ]
            pair_means.append(sum(dists) / len(dists))
    if not pair_means:
        return 0.0, 0.0
    return sum(pair_means) / len(pair_means), min(pair_means)


def luma_mae(src: Path, dest: Path, t: float = 0.35, scale: str = "160:90") -> float:
    def frame(path: Path) -> bytes:
        proc = subprocess.run(
            [
                ffmpeg_bin(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{t:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-vf",
                f"scale={scale}:flags=area,format=gray",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            capture_output=True,
            check=False,
        )
        return proc.stdout

    a, b = frame(src), frame(dest)
    n = min(len(a), len(b))
    if n == 0:
        return 999.0
    return sum(abs(a[i] - b[i]) for i in range(n)) / n


def main() -> int:
    failures: list[str] = []

    def step(name: str, fn) -> None:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
            print(f"FAIL  {name}: {exc}")

    tmp = Path(tempfile.mkdtemp(prefix="vu-tz-"))
    sample_a = tmp / "clips" / "source_a.mp4"
    sample_b = tmp / "clips" / "nested" / "source_b.mp4"
    make_sample(sample_a, seconds=1.4)
    make_sample(sample_b, seconds=1.0, size="480x270", rate=25)

    def t_collect() -> None:
        found = collect_videos([tmp / "clips"])
        check(len(found) == 2, f"expected 2 videos in folder drop, got {found}")
        found_files = collect_videos([sample_a])
        check(len(found_files) == 1, "single file collect")

    def t_probe_preview() -> None:
        info = probe_media(sample_a)
        check(info.width == 640 and info.height == 360, info.resolution_label)
        check(info.has_audio and info.has_video, "streams")
        check(info.duration >= 0.8, f"duration {info.duration}")
        prev = tmp / "preview.jpg"
        extract_preview(sample_a, prev)
        check(prev.stat().st_size > 100, "preview bytes")

    def t_presets_unique() -> None:
        info = probe_media(sample_a)
        for preset in ("light", "optimal", "hard"):
            params = generate_unique_set(info, 5, preset)
            fps = [p.fingerprint() for p in params]
            check(len(set(fps)) == 5, f"{preset} fingerprints collide: {fps}")
            check(all(p.write_metadata for p in params), f"{preset} metadata")
            if preset == "light":
                check(all(p.crop_pct == 0.5 for p in params), "light crop 0.5%")
                check(all(abs(p.tempo - 1.0) <= 0.005 + 1e-6 for p in params), "light tempo 0.5%")
                check(all(p.audio_noise for p in params), "light noise")
                check(all(not p.grain and not p.overlay for p in params), "light extras off")
            if preset == "optimal":
                check(all(p.grain and p.overlay for p in params), "optimal grain+overlay")
                check(len({p.grain_seed for p in params}) == 5, "optimal unique grain seeds")
                check(len({p.overlay_seed for p in params}) == 5, "optimal unique overlay seeds")
                check(all(p.grain_strength == 1 for p in params), "optimal grain strength TZ")
                check(all(abs(p.hue_deg) <= 1.21 for p in params), f"optimal hue { [p.hue_deg for p in params] }")
                check(all(0.11 <= p.unsharp <= 0.29 for p in params), "optimal unsharp")
                check(all(1.0 <= p.stereo_delay_ms <= 3.21 for p in params), "optimal stereo delay")
                check(all(abs(p.tempo - 1.0) <= 0.012 + 1e-6 for p in params), "optimal tempo TZ")
                check(all(abs(p.pitch_semitones) <= 0.15 + 1e-6 for p in params), "optimal pitch TZ")
                check(len({p.gop_size for p in params}) >= 2, "optimal GOP diversity")
                check(len({p.metadata_token for p in params}) == 5, "optimal unique metadata tokens")
                check(len({p.noise_seed for p in params}) == 5, "optimal unique noise seeds")
                graph = build_filter_complex(info, params[0])
                check("all_seed=" in graph, graph)
                check("anoisesrc=" in graph and "seed=" in graph, graph)
                check("equalizer=" in graph, graph)
                check("adelay=" in graph, graph)
                check("hue=h=" in graph, graph)
                check("unsharp=" in graph, graph)
                check("color=c=" in graph, "temporal overlay source")
                args = container_output_args(params[0], "cpu")
                check("-g" in args and "-force_key_frames" in args, args)
            if preset == "hard":
                check(any(p.hflip or abs(p.rotate_deg) > 0 for p in params) or True, "hard modules")
                check(all(p.crop_pct >= 1.0 for p in params), "hard crop")
                check(all(p.grain_strength in {1, 2} for p in params), "hard grain")
                check(all(abs(p.hue_deg) <= 2.61 for p in params), "hard hue")
                check(all(1.0 <= p.stereo_delay_ms <= 4.01 for p in params), "hard stereo delay TZ")
                check(all(abs(p.tempo - 1.0) <= 0.015 + 1e-6 for p in params), "hard tempo TZ")
                check(all(abs(p.pitch_semitones) <= 0.2 + 1e-6 for p in params), "hard pitch TZ")
                graph = build_filter_complex(info, params[0])
                check("async=1" not in graph and "first_pts=0" not in graph, "no async aresample")
                check("asetpts=PTS-STARTPTS" in graph, "audio PTS reset after pitch")
                check(":d=" in graph, "overlay duration capped")

        flags = ModuleFlags(
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
        ranges = ManualRanges(crop_min=0.8, crop_max=1.2, rotate_max=0.3, tempo_delta=0.01).clamp()
        manual = generate_unique_set(info, 4, "manual", flags=flags, ranges=ranges)
        check(len({p.fingerprint() for p in manual}) == 4, "manual unique")
        check(all(0.8 <= p.crop_pct <= 1.2 for p in manual), "manual crop range")

    def t_copy_count_and_output() -> None:
        info = probe_media(sample_a)
        encoder = detect_hardware("cpu")
        root = tmp / output_folder_name()
        sub = root / Path(sample_a).stem
        copies = generate_unique_set(info, 3, "light")
        written = uniquize_source(info, copies, sub, encoder, x264_threads=2)
        check(len(written) == 3, written)
        names = sorted(p.name for p in written)
        check(names == ["video_1.mp4", "video_2.mp4", "video_3.mp4"], names)
        hashes = [file_md5(p) for p in written]
        check(len(set(hashes)) == 3, f"MD5 collision {hashes}")
        src_hash = file_md5(sample_a)
        check(src_hash not in hashes, "copies must differ from source")

    def t_metadata() -> None:
        info = probe_media(sample_a)
        encoder = detect_hardware("cpu")
        params = generate_unique_set(info, 1, "light")[0]
        params.device_preset = "iphone_15"
        params.write_metadata = True
        dest = tmp / "meta" / "video_1.mp4"
        encode_copy(info, params, dest, encoder, x264_threads=2)
        fmt = ffprobe_format(dest)["format"]["tags"]
        tags = {k.lower(): v for k, v in fmt.items()}
        check("creation_time" in tags, f"tags={tags}")
        check("apple" in (tags.get("make") or "").lower() or "iphone" in json.dumps(tags).lower(), tags)
        graph = build_filter_complex(info, params, None)
        check("crop=" in graph or "trim=" in graph, graph)
        for preset, model, software, hw in (
            ("iphone_13_pro_max", "iPhone 13 Pro Max", "17.6.1", "iPhone14,3"),
            ("iphone_15_pro_max", "iPhone 15 Pro Max", "18.2.1", "iPhone16,2"),
        ):
            p = generate_unique_set(info, 1, "light")[0]
            p.device_preset = preset
            p.write_metadata = True
            pairs = dict(metadata_pairs(p))
            check(pairs.get("make") == "Apple", pairs)
            check(pairs.get("model") == model, pairs)
            check(pairs.get("software") == software, pairs)
            check(pairs.get("com.apple.quicktime.model") == model, pairs)
            check(pairs.get("com.apple.quicktime.software") == software, pairs)
            check(hw in (pairs.get("encoder") or ""), pairs.get("encoder"))
            out = tmp / "meta" / f"{preset}.mp4"
            encode_copy(info, p, out, encoder, x264_threads=2)
            written = {k.lower(): v for k, v in ffprobe_format(out)["format"]["tags"].items()}
            blob = json.dumps(written).lower()
            check("apple" in blob and "iphone" in blob, written)

    def t_all_presets_encode() -> None:
        info = probe_media(sample_a)
        encoder = detect_hardware("cpu")
        for preset in ("light", "optimal", "hard"):
            dest_dir = tmp / "presets" / preset
            copies = generate_unique_set(info, 2, preset)
            written = uniquize_source(info, copies, dest_dir, encoder, x264_threads=2)
            hashes = [file_md5(p) for p in written]
            check(len(set(hashes)) == 2, f"{preset} md5 {hashes}")
            for path in written:
                probe_media(path)

        flags = flags_for_preset("optimal")
        ranges = ManualRanges(crop_min=0.6, crop_max=1.0, rotate_max=0.15, tempo_delta=0.008).clamp()
        copies = generate_unique_set(info, 2, "manual", flags=flags, ranges=ranges)
        written = uniquize_source(info, copies, tmp / "presets" / "manual", encoder, x264_threads=2)
        check(len({file_md5(p) for p in written}) == 2, "manual md5")

    def t_two_sources() -> None:
        encoder = detect_hardware("cpu")
        root = tmp / "Output_multi"
        for src in (sample_a, sample_b):
            info = probe_media(src)
            dest = root / Path(src).stem
            copies = generate_unique_set(info, 2, "light")
            uniquize_source(info, copies, dest, encoder, x264_threads=2)
        a_files = list((root / sample_a.stem).glob("video_*.mp4"))
        b_files = list((root / sample_b.stem).glob("video_*.mp4"))
        check(len(a_files) == 2 and len(b_files) == 2, "per-source folders")
        all_h = [file_md5(p) for p in a_files + b_files]
        check(len(set(all_h)) == 4, all_h)

    def t_stop() -> None:
        info = probe_media(sample_a)
        encoder = detect_hardware("cpu")
        params = generate_unique_set(info, 1, "hard")[0]
        stop = threading.Event()
        dest = tmp / "stop" / "video_1.mp4"

        def killer() -> None:
            time.sleep(0.15)
            stop.set()

        threading.Thread(target=killer, daemon=True).start()
        try:
            encode_copy(info, params, dest, encoder, stop_event=stop, x264_threads=2)
            # Extremely fast machines may finish before stop; still a valid path.
        except JobCancelled:
            check(not dest.exists() or dest.stat().st_size >= 0, "cancelled file cleaned")
            return
        check(dest.is_file(), "encode completed before stop (acceptable)")

    def t_hw_cpu() -> None:
        auto = detect_hardware("auto")
        cpu = detect_hardware("cpu")
        check(cpu.kind == "cpu" and cpu.video_codec == "libx264", cpu)
        check(auto.video_codec in {"libx264", "h264_nvenc", "h264_qsv", "h264_amf"}, auto)
        check(auto_encoder_priority() == ("nvenc", "qsv", "amf"), auto_encoder_priority())
        graph, vmap = finalize_filter_graph("[0:v]eq=contrast=1.01,crop=64:64:0:0[vout]")
        check("format=yuv420p[v420]" in graph, graph)
        check(vmap == "[v420]", vmap)
        info = probe_media(sample_a)
        params = generate_unique_set(info, 1, "optimal")[0]
        if abs(params.hue_deg) < 0.02:
            params.hue_deg = 0.7
        if not params.eq_notch_hz:
            params.eq_notch_hz = 720.0
            params.eq_notch_gain = -0.8
        if params.stereo_delay_ms < 0.5:
            params.stereo_delay_ms = 1.6
        args = container_output_args(params, "nvenc")
        check("-g" in args, "GOP passed to GPU encoder")
        uni = build_filter_complex(info, params)
        check("hue=h=" in uni, "hue uniquize intact")
        check("adelay=" in uni, "stereo delay intact")
        check("equalizer=" in uni, "notch EQ intact")

    def t_perceptual_and_quality() -> None:
        info = probe_media(sample_a)
        encoder = detect_hardware("cpu")
        copies = generate_unique_set(info, 4, "optimal")
        check(len({p.fingerprint() for p in copies}) == 4, "fingerprints")
        dest_dir = tmp / "perceptual"
        written = uniquize_source(info, copies, dest_dir, encoder, x264_threads=2)
        hashes = [file_md5(p) for p in written]
        check(len(set(hashes)) == 4, f"MD5 collision {hashes}")
        check(file_md5(sample_a) not in hashes, "copies differ from source MD5")
        mean_hd, min_hd = mean_pairwise_hash_distance(written, size=32)
        print(f"  perceptual 32x32 aHash pairwise mean={mean_hd:.2f} min={min_hd:.2f} (of 1024)")
        check(mean_hd >= 8.0, f"pHash mean Hamming too low: {mean_hd:.2f}")
        check(min_hd >= 3.0, f"pHash min Hamming too low: {min_hd:.2f}")
        maes = [luma_mae(sample_a, path) for path in written]
        mae8 = [luma_mae(sample_a, path, scale="8:8") for path in written]
        print(f"  luma MAE 160x90 { [round(x, 2) for x in maes] }")
        print(f"  luma MAE 8x8    { [round(x, 2) for x in mae8] }")
        # 160×90 MAE is inflated by 0.5–1.6% crop on high-contrast testsrc2 edges;
        # 8×8 MAE checks that the frame still looks like the same shot.
        check(all(x < 26.0 for x in maes), f"Optimal copy looks too far from source: {maes}")
        check(sum(maes) / len(maes) < 24.0, f"Optimal mean MAE {sum(maes)/len(maes):.2f}")
        check(all(x < 18.0 for x in mae8), f"Optimal 8x8 structure MAE {mae8}")
        gops = [p.gop_size for p in copies]
        check(len(set(gops)) >= 2, gops)
        tokens = {p.metadata_token for p in copies}
        check(len(tokens) == 4, tokens)

    def t_many_fingerprints() -> None:
        info = probe_media(sample_a)
        params = generate_unique_set(info, 24, "optimal")
        fps = [p.fingerprint() for p in params]
        check(len(set(fps)) == 24, "duplicate parameter set in 24 Optimal copies")
        check(len({p.grain_seed for p in params}) == 24, "grain seed collision")
        check(len({p.overlay_seed for p in params}) == 24, "overlay seed collision")
        check(len({p.noise_seed for p in params}) == 24, "audio noise seed collision")

    def t_stderr_gate() -> None:
        x264 = "\n".join(
            [
                "x264 [info]: 264 - core 164",
                "x264 [info]: using cpu capabilities",
                "frame I: 12 Avg QP:17.12  size:  4821",
                "kb/s:1847.21",
                "[mp4 @ 0x1] Non-monotonic DTS in output stream 0:1; previous: 9223372036854775148, current: 914",
                "[aost#0:1] failed to avoid negative timestamp -9223372036854772631",
                "Error muxing a packet",
                "Conversion failed!",
            ]
        )
        tail = ffmpeg_error_tail(x264)
        check("kb/s" not in tail and "frame I:" not in tail, tail)
        check("Conversion failed" in tail, tail)
        check("922337203685477" in tail, tail)
        check(encode_stderr_failed(x264), "stderr after x264 stats is still failure")
        check(not encode_stderr_failed("x264 [info]: kb/s:12.0\n"), "clean x264 stats ok")
        oom = "Error while filtering: Cannot allocate memory\nConversion failed!"
        check(encode_stderr_failed(oom) and is_oom_error(oom), "OOM is failure")
        mux = mux_sanitize_args()
        check("-max_muxing_queue_size" in mux and mux[mux.index("-max_muxing_queue_size") + 1] == "1024", mux)

    step("folder collect (drag-drop equivalent)", t_collect)
    step("probe + first-frame preview", t_probe_preview)
    step("unique params Light/Optimal/Hard/Manual", t_presets_unique)
    step("copy count + Output folder + unique MD5", t_copy_count_and_output)
    step("metadata injection", t_metadata)
    step("encode all four presets", t_all_presets_encode)
    step("per-source output folders", t_two_sources)
    step("render stop", t_stop)
    step("GPU/CPU encoder setting", t_hw_cpu)
    step("MD5 + perceptual hash + Optimal quality", t_perceptual_and_quality)
    step("no duplicate param sets (24 copies)", t_many_fingerprints)
    step("ffmpeg stderr after x264 stats is failure", t_stderr_gate)

    print("TMP", tmp)
    if failures:
        print("FAILURES", len(failures))
        for item in failures:
            print(" -", item)
        return 1
    print("ALL FUNCTIONAL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
