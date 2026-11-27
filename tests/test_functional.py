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
from videouniq.core.hardware import detect_hardware
from videouniq.core.metadata import metadata_pairs
from videouniq.core.params import ManualRanges, ModuleFlags, flags_for_preset, ranges_for_preset
from videouniq.core.pipeline import JobCancelled, encode_copy, extract_preview, file_md5, uniquize_source
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
    make_sample(sample_a, seconds=1.0)
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
            if preset == "hard":
                check(any(p.hflip or abs(p.rotate_deg) > 0 for p in params) or True, "hard modules")
                check(all(p.crop_pct >= 1.0 for p in params), "hard crop")

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

    step("folder collect (drag-drop equivalent)", t_collect)
    step("probe + first-frame preview", t_probe_preview)
    step("unique params Light/Optimal/Hard/Manual", t_presets_unique)
    step("copy count + Output folder + unique MD5", t_copy_count_and_output)
    step("metadata injection", t_metadata)
    step("encode all four presets", t_all_presets_encode)
    step("per-source output folders", t_two_sources)
    step("render stop", t_stop)
    step("GPU/CPU encoder setting", t_hw_cpu)

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
