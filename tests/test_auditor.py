"""V2.2 uniqueness auditor: real ffprobe + hashlib, not stubs."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from videouniq.core.auditor import (
    HAMMING_UNIQUE,
    SSIM_QUALITY,
    deep_audit,
    file_md5,
    format_text_report,
    load_report,
    probe_identity,
    quick_audit,
    save_report,
)
from videouniq.core.hardware import auto_encoder_priority, detect_hardware
from videouniq.core.pipeline import uniquize_source
from videouniq.core.probe import probe_media
from videouniq.core.randomizer import generate_unique_set
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


def make_sample(path: Path, seconds: float = 1.2, size: str = "640x360") -> Path:
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
            f"testsrc2=size={size}:rate=25:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "sample failed")
    return path


def main() -> int:
    print("V2.2 uniqueness auditor")
    check(auto_encoder_priority()[0] == "nvenc", auto_encoder_priority())
    check("qsv" in auto_encoder_priority(), "QSV after NVIDIA")
    check(HAMMING_UNIQUE == 30, HAMMING_UNIQUE)
    check(SSIM_QUALITY == 0.95, SSIM_QUALITY)
    check(ffprobe_bin(), "ffprobe binary")

    with tempfile.TemporaryDirectory(prefix="vu-aud-") as raw:
        tmp = Path(raw)
        src = make_sample(tmp / "orig.mp4", 1.15)
        info = probe_media(src)
        encoder = detect_hardware("cpu")
        copies = generate_unique_set(info, 3, "optimal")
        dest = tmp / "out"
        written = uniquize_source(info, copies, dest, encoder, x264_threads=2)
        check(len(written) == 3, written)

        t0 = time.perf_counter()
        ident = probe_identity(written[0])
        check(len(ident.md5) == 32, ident.md5)
        check(ident.md5 == file_md5(written[0]), "hashlib matches probe md5")
        check(ident.duration > 0.5, ident.duration)
        check(ident.width == 640 and ident.height == 360, (ident.width, ident.height))
        check(ident.device != "", ident.device)

        report = quick_audit(src, dest)
        elapsed = (time.perf_counter() - t0) * 1000
        print(f"  timing probe+audit ~{report.elapsed_ms:.0f} ms (wall {elapsed:.0f} ms)")
        check(report.elapsed_ms < 4000, f"audit too slow {report.elapsed_ms:.0f} ms")
        check(len(report.copies) == 3, report.copies)
        check(report.original is not None, "original identity")
        check(report.verdict == "unique", report.verdict_label)
        md5s = [c.md5 for c in report.copies]
        check(len(set(md5s)) == 3, md5s)
        check(report.original.md5 not in md5s, "copies differ from source MD5")
        md5_chk = next(c for c in report.checks if c.key == "md5")
        check(md5_chk.ok, md5_chk)
        device_chk = next(c for c in report.checks if c.key == "device")
        check(device_chk.unique_among_copies, device_chk)
        fps_chk = next(c for c in report.checks if c.key == "fps")
        check(fps_chk.unique_among_copies, fps_chk)
        check(all("." in row.duration_label for row in report.files), [r.duration_label for r in report.files])
        src_fps = report.original.fps if report.original else 0
        check(
            all(abs(c.fps - src_fps) > 0.01 for c in report.copies),
            [c.fps_label for c in report.copies],
        )
        for row in report.files:
            check(len(row.md58) == 8, row.md58)
            check("stub" not in row.md5.lower(), row.md5)

        text = format_text_report(report)
        check("отчёт уникальности" in text.lower() or "Отчёт" in text, text[:80])
        check(report.copies[0].md58 in text, "md5 in text report")
        check("ffprobe" in text.lower() or "мс" in text, text[-80:])

        saved = save_report(report)
        check(saved.is_file() and saved.name == "uniqueness.json", saved)
        raw_json = json.loads(saved.read_text(encoding="utf-8"))
        check(raw_json.get("verdict") == "unique", raw_json.get("verdict"))
        check(isinstance(raw_json.get("files"), list) and raw_json["files"][0]["md5"], "json has md5")
        loaded = load_report(dest)
        check(loaded is not None and loaded.copies[0].md5 == report.copies[0].md5, "load json")

        deep = deep_audit(report)
        check(deep.deep is not None, "deep ran")
        assert deep.deep is not None
        check("hamming_pairwise_mean" in deep.deep, deep.deep)
        check("ssim_vs_original_mean" in deep.deep, deep.deep)
        check(int(deep.deep.get("ahash_size") or 0) == 16, deep.deep.get("ahash_size"))
        per = deep.deep.get("per_copy") or []
        check(len(per) == 3, per)
        hams = [row["hamming_vs_original"] for row in per]
        ssims = [row["ssim_vs_original"] for row in per]
        check(len(set(hams)) >= 2 or len(set(ssims)) >= 2, f"per-copy metrics {hams} {ssims}")
        check(all("hamming_vs_copies_mean" in row for row in per), per)
        ssim = float(deep.deep["ssim_vs_original_mean"])
        check(ssim >= 0.90, f"SSIM quality {ssim}")
        text2 = format_text_report(deep)
        check("Hamming" in text2 and "SSIM" in text2, text2)
        check("копия 1" in text2 and "копия 2" in text2, text2)

        # Stub-guard: identities come from real files on disk, not constants.
        fake = tmp / "missing"
        fake.mkdir()
        empty = quick_audit(src, fake)
        check(empty.verdict == "incomplete", empty.verdict)

    print(f"\nPASSED={PASSED} FAILED={FAILED}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
