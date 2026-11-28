"""V2.1 battle checklist as far as this Linux/cloud VM allows."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from videouniq.core.hardware import EncoderChoice, detect_hardware
from videouniq.core.params import UniqueParams
from videouniq.core.pipeline import encode_copy, file_md5
from videouniq.core.probe import probe_media
from videouniq.core.randomizer import generate_unique_set
from videouniq.editor.filtergraph import build_edit_and_uniquize
from videouniq.editor.project import EditorProject, TextClip, VideoClip
from videouniq.editor.proxy import ensure_proxy, is_heavy_source
from videouniq.paths import ffmpeg_bin, ffprobe_bin

FAILED = 0
PASSED = 0


def check(cond: bool, msg: str) -> None:
    global FAILED, PASSED
    if cond:
        PASSED += 1
        print("  OK ", msg)
    else:
        FAILED += 1
        print("  FAIL", msg)


def run(cmd, **kw):
    return subprocess.run(cmd, text=True, capture_output=True, check=False, **kw)


def make_phone_clip(path: Path, seconds: float, size: str = "1080x1920", rate: int = 25) -> Path:
    """Vertical phone MP4: 90 kHz timescale, 80 ms A/V delay, 44.1 kHz AAC."""
    path.parent.mkdir(parents=True, exist_ok=True)
    src = "testsrc2" if seconds <= 8 else "color=c=0x1a334d"
    video = (
        f"{src}=size={size}:rate={rate}:duration={seconds}"
        if src == "testsrc2"
        else f"{src}:s={size}:r={rate}:d={seconds}"
    )
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        video,
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=180:sample_rate=44100:duration={seconds}",
        "-filter_complex",
        "[0:v]setpts=PTS+0.08/TB[v];[1:a]adelay=80|80[a]",
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-video_track_timescale",
        "90000",
        "-c:a",
        "aac",
        "-ar",
        "44100",
        str(path),
    ]
    proc = run(cmd)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "phone sample failed")
    return path


def make_clip(path: Path, seconds: float, size: str, rate: int = 30, freq: int = 440) -> Path:
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
        f"sine=frequency={freq}:duration={seconds}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(path),
    ]
    proc = run(cmd)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "sample failed")
    return path


def ssim_mean(a: Path, b: Path) -> float:
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-i",
        str(a),
        "-i",
        str(b),
        "-filter_complex",
        # 32×18 structural SSIM: full-res testsrc2 is dominated by Optimal's ~1%
        # crop on high-contrast edges (same as V2 luma-MAE note).
        "[0:v]scale=32:18,setsar=1[a];[1:v]scale=32:18,setsar=1[b];[a][b]ssim",
        "-f",
        "null",
        "-",
    ]
    proc = run(cmd, timeout=120)
    text = (proc.stderr or "") + (proc.stdout or "")
    # n:1 All:0.97 ...
    last = 0.0
    for line in text.splitlines():
        if "All:" in line:
            try:
                last = float(line.split("All:")[1].split()[0])
            except (IndexError, ValueError):
                continue
    return last


def av_durations(path: Path) -> tuple[float, float]:
    """Decode-length, not muxer stream tags (timescale/muxdelay confuse ffprobe)."""
    proc = run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,avg_frame_rate",
            "-of",
            "default=nw=1",
            str(path),
        ],
        timeout=60,
    )
    frames, fps = 0.0, 30.0
    for line in (proc.stdout or "").splitlines():
        if line.startswith("nb_read_frames="):
            try:
                frames = float(line.split("=", 1)[1])
            except ValueError:
                pass
        if line.startswith("avg_frame_rate=") and "/" in line:
            n, d = line.split("=", 1)[1].split("/")
            try:
                fps = float(n) / max(1.0, float(d))
            except ValueError:
                pass
    vdur = frames / max(1.0, fps) if frames else 0.0
    proc = run(
        [
            ffprobe_bin(),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-count_frames",
            "-show_entries",
            "stream=nb_read_frames,sample_rate",
            "-of",
            "default=nw=1",
            str(path),
        ],
        timeout=60,
    )
    aframes, rate = 0.0, 48000.0
    for line in (proc.stdout or "").splitlines():
        if line.startswith("nb_read_frames="):
            try:
                aframes = float(line.split("=", 1)[1])
            except ValueError:
                pass
        if line.startswith("sample_rate="):
            try:
                rate = float(line.split("=", 1)[1])
            except ValueError:
                pass
    adur = aframes * 1024.0 / max(1.0, rate) if aframes else 0.0
    return vdur, adur


def project_for(path: Path) -> EditorProject:
    info = probe_media(path)
    clip = VideoClip(
        source_path=info.path,
        in_point=0.05,
        out_point=max(0.2, info.duration - 0.05),
        source_duration=info.duration,
        source_width=info.width,
        source_height=info.height,
        source_fps=info.fps,
        has_audio=info.has_audio,
        transition="crossfade",
        transition_duration=0.25,
    )
    text = TextClip(
        text="Боевой тест",
        start=0.1,
        duration=min(2.0, clip.duration()),
        plate=True,
        shadow=True,
        stroke_enabled=True,
        font_size=48,
        y_norm=0.82,
    )
    proj = EditorProject(name="battle", aspect="16:9", video_clips=[clip], text_clips=[text])
    proj.sync_canvas()
    return proj


def main() -> int:
    print("VideoUniq Pro V2.1 battle checklist (Linux VM)")
    encoder = detect_hardware("cpu")
    with tempfile.TemporaryDirectory(prefix="vu-battle-") as raw:
        tmp = Path(raw)
        print("4K proxy")
        k4 = make_clip(tmp / "u4k.mp4", 1.2, "3840x2160", rate=30)
        info4 = probe_media(k4)
        check(is_heavy_source(info4.width, info4.height), f"{info4.width}x{info4.height}")
        proxy = Path(ensure_proxy(k4, info4.width, info4.height, timeout=180))
        check(proxy.is_file() and proxy.stat().st_size > 1000, proxy)
        pinfo = probe_media(proxy)
        check(max(pinfo.width, pinfo.height) <= 1080, f"proxy {pinfo.width}x{pinfo.height}")
        check(min(pinfo.width, pinfo.height) <= 1080, f"proxy short {pinfo.width}x{pinfo.height}")
        check(pinfo.has_audio, "proxy keeps audio")

        print("9:16 phone encode (DTS sanitize)")
        phone = make_phone_clip(tmp / "phone.mp4", 3.0)
        pinfo = probe_media(phone)
        check((pinfo.width, pinfo.height) == (1080, 1920), (pinfo.width, pinfo.height))
        check(not is_heavy_source(pinfo.width, pinfo.height), "1080x1920 not heavy")
        from videouniq.core.filters import build_filter_complex

        pparams = generate_unique_set(pinfo, 1, "hard")[0]
        graph = build_filter_complex(pinfo, pparams)
        check("async=1" not in graph and "first_pts=0" not in graph, "no async aresample")
        check("asetpts=PTS-STARTPTS" in graph, "PTS reset")
        check("adelay=" in graph and "hue=h=" in graph and "anoisesrc=" in graph, "hard modules")
        check(":d=" in graph, "overlay duration capped")
        from videouniq.core.hardware import auto_encoder_priority, recommended_encode_workers
        from videouniq.core.pipeline import is_oom_error
        from videouniq.editor.proxy import ensure_stream_copy

        check(recommended_encode_workers() in (1, 2), recommended_encode_workers())
        check(auto_encoder_priority()[0] == "nvenc", "NVIDIA before Intel QSV")
        check(is_oom_error("Error while filtering: Cannot allocate memory"), "oom detect")
        copied = Path(ensure_stream_copy(phone))
        cinfo = probe_media(copied)
        check((cinfo.width, cinfo.height) == (1080, 1920), "stream copy stays native")
        fast = EncoderChoice(
            kind="cpu",
            video_codec="libx264",
            extra=["-preset", "ultrafast", "-crf", "23"],
            label="CPU ultrafast",
            gpu_name="",
        )
        pdest = tmp / "phone_out.mp4"
        encode_copy(pinfo, pparams, pdest, fast, x264_threads=2)
        check(pdest.is_file() and pdest.stat().st_size > 1000, pdest)
        pout = probe_media(pdest)
        check(pout.width == 1080 and pout.height == 1920, (pout.width, pout.height))
        check(pout.has_audio and pout.duration > 2.0, (pout.has_audio, pout.duration))

        print("QSV fallback → CPU")
        qsv = EncoderChoice(
            kind="qsv",
            video_codec="h264_qsv",
            extra=["-preset", "fast", "-global_quality", "22"],
            label="Intel Quick Sync",
            gpu_name="Intel",
        )
        qdest = tmp / "phone_qsv.mp4"
        encode_copy(pinfo, pparams, qdest, qsv, x264_threads=2, allow_cpu_fallback=True)
        qout = probe_media(qdest)
        check(qout.has_audio and qout.width == 1080, (qout.width, qout.has_audio))

        print("speech-like A/V + 5 Optimal + master")
        speech = make_clip(tmp / "speech.mp4", 8.0, "1280x720", rate=30, freq=180)
        proj = project_for(speech)
        vup = tmp / "battle.vup"
        proj.save(vup)
        loaded = EditorProject.load(vup)
        check(loaded.text_clips[0].text == "Боевой тест", "vup roundtrip")
        media = probe_media(speech)
        copies = generate_unique_set(media, 5, "optimal")
        check(len({p.gop_size for p in copies}) >= 2, "GOP varies")
        check(any(abs(p.hue_deg) > 0.01 for p in copies), "hue field present")
        check(any(p.eq_notch_hz for p in copies), "notch EQ")
        check(any(p.stereo_delay_ms > 0 for p in copies), "stereo delay")
        out = tmp / "out"
        out.mkdir()
        hashes = []
        for i, params in enumerate(copies, 1):
            spec = build_edit_and_uniquize(loaded, params)
            check("enable='between" in spec.graph, "png overlay")
            dest = out / f"video_{i}.mp4"
            encode_copy(spec.as_media(speech), params, dest, encoder, graph_spec=spec, x264_threads=2)
            check(dest.is_file(), dest)
            hashes.append(file_md5(dest))
            vd, ad = av_durations(dest)
            check(abs(vd - ad) < 0.40, f"A/V sync copy {i} v={vd:.3f} a={ad:.3f}")
        check(len(set(hashes)) == 5, hashes)
        from videouniq.core.auditor import quick_audit, save_report

        ureport = quick_audit(speech, out)
        save_report(ureport)
        check(ureport.verdict in {"unique", "warn"}, ureport.verdict_label)
        check(len(ureport.copies) == 5, len(ureport.copies))
        check(len(ureport.copies[0].md5) == 32, "auditor md5 is real hashlib")
        master_spec = build_edit_and_uniquize(loaded, None)
        master = out / "master.mp4"
        encode_copy(
            master_spec.as_media(speech),
            UniqueParams(write_metadata=False, pad_bytes=16),
            master,
            encoder,
            graph_spec=master_spec,
            x264_threads=2,
        )
        check(master.is_file(), master)
        check(file_md5(master) not in hashes, "master != copies")
        # Text jitter moves the plate; SSIM vs origin uses the uniquizer on the source (no editor text).
        raw_dir = tmp / "rawuniq"
        from videouniq.core.pipeline import uniquize_source

        written = uniquize_source(media, copies, raw_dir, encoder, x264_threads=2)
        scores = [ssim_mean(speech, p) for p in written]
        print("  SSIM vs origin (Optimal, no editor text)", [round(s, 4) for s in scores])
        check(all(s >= 0.95 for s in scores if s > 0), f"SSIM {scores}")
        check(sum(s > 0 for s in scores) == 5, "ssim produced")

        print("GPU graph yuv420p (encode path uses CPU on this VM)")
        spec = build_edit_and_uniquize(loaded, copies[0])
        from videouniq.core.pipeline import finalize_filter_graph

        g, lab = finalize_filter_graph(spec.graph)
        check("format=yuv420p" in g and lab == "[v420]", lab)
        check("hue=h=" in spec.graph, "hue still in uniquize")
        check("adelay=" in spec.graph, "stereo delay still in uniquize")
        check("equalizer=" in spec.graph, "notch still in uniquize")
        check(all(int(p.gop_size or 0) > 0 for p in copies), "gop size set")

    print(f"\nBATTLE PASSED={PASSED} FAILED={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
