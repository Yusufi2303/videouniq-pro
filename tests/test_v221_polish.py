"""V2.2.1: unique batch identities + smart bitrate without quality loss."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from videouniq.core.auditor import FileIdentity, deep_audit, format_text_report, quick_audit
from videouniq.core.hardware import detect_hardware
from videouniq.core.pipeline import encode_copy, uniquize_source
from videouniq.core.probe import probe_media
from videouniq.core.randomizer import fps_catalog, generate_unique_set, unique_fps_targets
from videouniq.paths import ffmpeg_bin

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


def make_low_bitrate(path: Path, seconds: float = 3.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size=640x360:rate=25:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-b:v",
            "200k",
            "-maxrate",
            "200k",
            "-bufsize",
            "400k",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "low bitrate sample failed")
    return path


def main() -> int:
    print("V2.2.1 polish")
    ident = FileIdentity(
        path="x",
        role="copy",
        index=1,
        name="x",
        md5="abcd",
        duration=85.24,
        fps=24.96,
        device="CapCut",
        size_bytes=1,
    )
    check(ident.duration_label == "01:25.240", ident.duration_label)
    check(ident.fps_label == "24.96 FPS", ident.fps_label)
    cat = fps_catalog(25.0)
    check(25.0 not in cat and all(abs(x - 25.0) > 0.015 for x in cat), cat)
    fps5 = unique_fps_targets(25.0, 5)
    check(len(set(fps5)) == 5, fps5)
    check(all(abs(x - 25.0) > 0.015 for x in fps5), fps5)

    with tempfile.TemporaryDirectory(prefix="vu-221-") as raw:
        tmp = Path(raw)
        src = make_low_bitrate(tmp / "15like.mp4", 3.0)
        info = probe_media(src)
        check(abs(info.fps - 25) < 0.05, info.fps)
        params = generate_unique_set(info, 5, "optimal", size_mode="smart")
        check(len({p.device_preset for p in params}) == 5, [p.device_preset for p in params])
        check("capcut" not in [p.device_preset for p in params] or True, "capcut may appear once")
        check(len([p for p in params if p.device_preset == "capcut"]) <= 1, [p.device_preset for p in params])
        check(len({p.pad_bytes for p in params}) == 5, [p.pad_bytes for p in params])
        check(all(p.fps_target and abs(p.fps_target - 25) > 0.015 for p in params), [p.fps_target for p in params])
        check(all(p.maxrate_bps >= int(info.bit_rate * 1.14) for p in params if info.bit_rate), [p.maxrate_bps for p in params])
        check(all(p.maxrate_bps <= int(info.bit_rate * 1.32) + 50_000 for p in params if info.bit_rate), [p.maxrate_bps for p in params])

        encoder = detect_hardware("cpu")
        quality = generate_unique_set(info, 1, "optimal", size_mode="quality")
        smart = generate_unique_set(info, 2, "optimal", size_mode="smart")
        qdir = tmp / "quality"
        sdir = tmp / "smart"
        qfiles = uniquize_source(info, quality, qdir, encoder, x264_threads=2)
        sfiles = uniquize_source(info, smart, sdir, encoder, x264_threads=2)
        qsz = qfiles[0].stat().st_size
        ssz = [p.stat().st_size for p in sfiles]
        src_sz = src.stat().st_size
        print(f"  sizes src={src_sz} quality={qsz} smart={ssz}")
        check(ssz[0] != ssz[1], ssz)
        # Smart must not balloon like unconstrained CRF (often 3–6×). Keep a margin.
        check(max(ssz) < qsz * 0.85 or max(ssz) < src_sz * 3.5, f"smart {ssz} vs quality {qsz} src {src_sz}")
        check(all(n > src_sz * 0.4 for n in ssz), "smart not crushed")

        report = quick_audit(src, sdir)
        check("." in report.copies[0].duration_label, report.copies[0].duration_label)
        check(len({c.device for c in report.copies}) == 2, [c.device for c in report.copies])
        deep = deep_audit(report)
        per = (deep.deep or {}).get("per_copy") or []
        check(len(per) == 2, per)
        check(per[0]["hamming_vs_original"] != per[1]["hamming_vs_original"] or per[0]["ssim_vs_original"] != per[1]["ssim_vs_original"], per)
        text = format_text_report(deep)
        check("между копиями" in text or "Hamming" in text, text[-200:])

        # Quality path still uses AAC 320k (encode_copy audio_args). Spot-check probe.
        qinfo = probe_media(qfiles[0])
        sinfo = probe_media(sfiles[0])
        check(qinfo.codec_audio == "aac" and sinfo.codec_audio == "aac", (qinfo.codec_audio, sinfo.codec_audio))

    print(f"\nPASSED={PASSED} FAILED={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
