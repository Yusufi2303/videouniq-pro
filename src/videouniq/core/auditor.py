"""Uniqueness auditor: real hashlib MD5 + ffprobe, optional aHash/SSIM deep pass."""

from __future__ import annotations

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from videouniq.core.probe import VIDEO_EXTENSIONS
from videouniq.paths import ffmpeg_bin, ffprobe_bin

HAMMING_UNIQUE = 30
SSIM_QUALITY = 0.95
AHASH_SIZE = 8
DEEP_FRAMES = 5
REPORT_NAME = "uniqueness.json"


@dataclass
class FileIdentity:
    path: str
    role: str  # original | copy | master
    index: int
    name: str
    md5: str
    duration: float
    fps: float
    device: str
    size_bytes: int
    width: int = 0
    height: int = 0

    @property
    def md58(self) -> str:
        return (self.md5 or "")[:8]

    @property
    def duration_label(self) -> str:
        total = max(0, int(round(self.duration)))
        m, s = divmod(total, 60)
        if m >= 60:
            h, m = divmod(m, 60)
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @property
    def fps_label(self) -> str:
        if self.fps <= 0:
            return "—"
        if abs(self.fps - round(self.fps)) < 0.03:
            return f"{int(round(self.fps))} FPS"
        return f"{self.fps:.2f} FPS"

    @property
    def size_label(self) -> str:
        n = float(self.size_bytes)
        for unit in ("Б", "КБ", "МБ", "ГБ"):
            if n < 1024 or unit == "ГБ":
                if unit == "Б":
                    return f"{int(n)} {unit}"
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{self.size_bytes} Б"


@dataclass
class FieldCheck:
    key: str
    label: str
    unique_vs_original: bool
    unique_among_copies: bool

    @property
    def ok(self) -> bool:
        return self.unique_vs_original and self.unique_among_copies


@dataclass
class AuditReport:
    source: str
    output_dir: str
    files: list[FileIdentity] = field(default_factory=list)
    checks: list[FieldCheck] = field(default_factory=list)
    verdict: str = "incomplete"
    verdict_label: str = "Нет копий"
    elapsed_ms: float = 0.0
    deep: dict[str, Any] | None = None

    @property
    def original(self) -> FileIdentity | None:
        return next((f for f in self.files if f.role == "original"), None)

    @property
    def copies(self) -> list[FileIdentity]:
        return [f for f in self.files if f.role == "copy"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "output_dir": self.output_dir,
            "files": [asdict(f) for f in self.files],
            "checks": [asdict(c) for c in self.checks],
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "elapsed_ms": self.elapsed_ms,
            "deep": self.deep,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditReport:
        files = [FileIdentity(**row) for row in data.get("files") or [] if isinstance(row, dict)]
        checks = [FieldCheck(**row) for row in data.get("checks") or [] if isinstance(row, dict)]
        return cls(
            source=str(data.get("source") or ""),
            output_dir=str(data.get("output_dir") or ""),
            files=files,
            checks=checks,
            verdict=str(data.get("verdict") or "incomplete"),
            verdict_label=str(data.get("verdict_label") or ""),
            elapsed_ms=float(data.get("elapsed_ms") or 0),
            deep=data.get("deep") if isinstance(data.get("deep"), dict) else None,
        )


def file_md5(path: str | Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.md5()
    with Path(path).open("rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _parse_fps(rate: str) -> float:
    if not rate or rate in {"0/0", "N/A"}:
        return 0.0
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            d = float(den)
            return float(num) / d if d else 0.0
        except ValueError:
            return 0.0
    try:
        return float(rate)
    except ValueError:
        return 0.0


def _device_from_tags(tags: dict[str, Any]) -> str:
    for key in (
        "model",
        "com.apple.quicktime.model",
        "title",
        "artist",
        "encoder",
        "make",
        "com.apple.quicktime.make",
    ):
        val = str(tags.get(key) or "").strip()
        if val:
            return val
    return "—"


def probe_identity(path: str | Path, timeout: float = 12.0) -> FileIdentity:
    src = Path(path)
    cmd = [
        ffprobe_bin(),
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(src),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffprobe failed").strip()
        raise RuntimeError(err.splitlines()[-1] if err else "ffprobe failed")
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), {}) or {}
    tags = dict(fmt.get("tags") or {})
    tags.update(video.get("tags") or {})
    duration = 0.0
    for candidate in (fmt.get("duration"), video.get("duration")):
        if candidate:
            try:
                duration = float(candidate)
                break
            except (TypeError, ValueError):
                continue
    size_bytes = 0
    try:
        size_bytes = int(fmt.get("size") or src.stat().st_size)
    except OSError:
        size_bytes = int(fmt.get("size") or 0)
    fps = _parse_fps(str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""))
    digest = file_md5(src)
    return FileIdentity(
        path=str(src),
        role="copy",
        index=0,
        name=src.name,
        md5=digest,
        duration=duration,
        fps=fps,
        device=_device_from_tags(tags),
        size_bytes=size_bytes,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
    )


def list_copy_files(output_dir: str | Path) -> list[Path]:
    folder = Path(output_dir)
    if not folder.is_dir():
        return []
    copies = sorted(
        p for p in folder.glob("video_*.mp4") if p.is_file() and p.stat().st_size > 1000
    )
    return copies


def report_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / REPORT_NAME


def save_report(report: AuditReport, dest: str | Path | None = None) -> Path:
    path = Path(dest) if dest else report_path(report.output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_report(path: str | Path) -> AuditReport | None:
    p = Path(path)
    if p.is_dir():
        p = report_path(p)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return AuditReport.from_dict(data)


def _unique_strings(values: list[str]) -> bool:
    cleaned = [v.strip() for v in values]
    return len(cleaned) == len(set(cleaned)) and all(cleaned)


def _unique_floats(values: list[float], tol: float) -> bool:
    if len(values) < 2:
        return True
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            if abs(a - b) <= tol:
                return False
    return True


def _vs_original_str(origin: str, copies: list[str]) -> bool:
    return all((c or "").strip() != (origin or "").strip() for c in copies) if copies else False


def _vs_original_float(origin: float, copies: list[float], tol: float) -> bool:
    return all(abs(c - origin) > tol for c in copies) if copies else False


def _verdict(copies: list[FileIdentity], checks: list[FieldCheck]) -> tuple[str, str]:
    if not copies:
        return "incomplete", "Нет копий"
    md5s = [c.md5 for c in copies]
    if len(set(md5s)) != len(md5s):
        return "collision", "Коллизия MD5 — копии не уникальны"
    md5_ok = next((c for c in checks if c.key == "md5"), None)
    if md5_ok and md5_ok.ok:
        extras = [c for c in checks if c.key != "md5" and c.ok]
        if extras:
            return "unique", "Все копии уникальны (хеш и метаданные)"
        return "unique", "Все копии уникальны по MD5"
    if len(set(md5s)) == len(md5s):
        return "unique", "Копии уникальны между собой"
    return "warn", "MD5 совпадает с оригиналом или между копиями"


def quick_audit(source: str | Path, output_dir: str | Path, timeout: float = 12.0) -> AuditReport:
    import time

    t0 = time.perf_counter()
    src = Path(source)
    out = Path(output_dir)
    copies = list_copy_files(out)
    jobs: list[tuple[str, int, Path]] = []
    if src.is_file() and src.suffix.lower() in VIDEO_EXTENSIONS:
        jobs.append(("original", 0, src))
    master = out / "master.mp4"
    if master.is_file() and master.stat().st_size > 1000:
        jobs.append(("master", 0, master))
    for i, path in enumerate(copies, start=1):
        jobs.append(("copy", i, path))

    found: dict[tuple[str, int], FileIdentity] = {}
    if jobs:
        workers = max(1, min(8, len(jobs)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(probe_identity, path, timeout): (role, idx) for role, idx, path in jobs}
            for fut in as_completed(futs):
                role, idx = futs[fut]
                try:
                    ident = fut.result()
                except Exception:
                    if role == "original":
                        continue
                    raise
                ident.role = role
                ident.index = idx
                found[(role, idx)] = ident

    files: list[FileIdentity] = []
    if ("original", 0) in found:
        files.append(found[("original", 0)])
    files.extend(found[( "copy", i)] for i in range(1, len(copies) + 1) if ("copy", i) in found)
    if ("master", 0) in found:
        files.append(found[("master", 0)])

    origin = next((f for f in files if f.role == "original"), None)
    copy_rows = [f for f in files if f.role == "copy"]
    checks: list[FieldCheck] = []
    if origin and copy_rows:
        checks = [
            FieldCheck(
                "md5",
                "MD5",
                _vs_original_str(origin.md5, [c.md5 for c in copy_rows]),
                _unique_strings([c.md5 for c in copy_rows]),
            ),
            FieldCheck(
                "duration",
                "Длительность",
                _vs_original_float(origin.duration, [c.duration for c in copy_rows], 0.04),
                _unique_floats([c.duration for c in copy_rows], 0.04),
            ),
            FieldCheck(
                "fps",
                "FPS",
                _vs_original_float(origin.fps, [c.fps for c in copy_rows], 0.02),
                _unique_floats([c.fps for c in copy_rows], 0.02),
            ),
            FieldCheck(
                "device",
                "Устройство",
                _vs_original_str(origin.device, [c.device for c in copy_rows]),
                _unique_strings([c.device for c in copy_rows]),
            ),
            FieldCheck(
                "size",
                "Вес",
                _vs_original_float(float(origin.size_bytes), [float(c.size_bytes) for c in copy_rows], 0),
                _unique_floats([float(c.size_bytes) for c in copy_rows], 0),
            ),
        ]
    verdict, label = _verdict(copy_rows, checks)
    elapsed = (time.perf_counter() - t0) * 1000.0
    return AuditReport(
        source=str(src),
        output_dir=str(out),
        files=files,
        checks=checks,
        verdict=verdict,
        verdict_label=label,
        elapsed_ms=elapsed,
    )


def _ahash_bits(path: Path, t: float, size: int = AHASH_SIZE) -> int:
    n = size * size
    proc = subprocess.run(
        [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{max(0.0, t):.3f}",
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
        timeout=20,
    )
    data = proc.stdout or b""
    if len(data) != n:
        raise RuntimeError(f"aHash frame failed ({len(data)} bytes)")
    mean = sum(data) / n
    bits = 0
    for i, value in enumerate(data):
        if value >= mean:
            bits |= 1 << i
    return bits


def _hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _frame_times(duration: float, count: int = DEEP_FRAMES) -> list[float]:
    dur = max(0.2, float(duration))
    if count <= 1:
        return [dur * 0.5]
    return [dur * (i + 1) / (count + 1) for i in range(count)]


def _ssim_pair(a: Path, b: Path, t: float) -> float:
    cmd = [
        ffmpeg_bin(),
        "-hide_banner",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(a),
        "-ss",
        f"{t:.3f}",
        "-i",
        str(b),
        "-frames:v",
        "1",
        "-filter_complex",
        "[0:v]scale=32:18,setsar=1[a];[1:v]scale=32:18,setsar=1[b];[a][b]ssim",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    text = (proc.stderr or "") + (proc.stdout or "")
    for token in text.replace("\n", " ").split():
        if token.startswith("All:") and token[4:]:
            try:
                return float(token[4:].rstrip(","))
            except ValueError:
                continue
    return 0.0


def deep_audit(report: AuditReport) -> AuditReport:
    origin = report.original
    copies = report.copies
    if origin is None or not copies:
        report.deep = {"error": "Нет оригинала или копий"}
        return report
    times = _frame_times(origin.duration or 1.0)
    orig_path = Path(origin.path)
    pair_h: list[float] = []
    vs_orig: list[float] = []
    ssim_vs: list[float] = []
    for copy in copies:
        cpath = Path(copy.path)
        h_orig: list[int] = []
        for t in times:
            h_orig.append(_hamming(_ahash_bits(orig_path, t), _ahash_bits(cpath, t)))
        vs_orig.append(sum(h_orig) / len(h_orig))
        ssim_vs.append(sum(_ssim_pair(orig_path, cpath, t) for t in times) / len(times))
    for i in range(len(copies)):
        for j in range(i + 1, len(copies)):
            dists = [
                _hamming(
                    _ahash_bits(Path(copies[i].path), t),
                    _ahash_bits(Path(copies[j].path), t),
                )
                for t in times
            ]
            pair_h.append(sum(dists) / len(dists))
    mean_pair = sum(pair_h) / len(pair_h) if pair_h else 0.0
    min_pair = min(pair_h) if pair_h else 0.0
    mean_orig = sum(vs_orig) / len(vs_orig) if vs_orig else 0.0
    mean_ssim = sum(ssim_vs) / len(ssim_vs) if ssim_vs else 0.0
    visual_unique = min_pair > HAMMING_UNIQUE or mean_orig > HAMMING_UNIQUE
    quality_ok = mean_ssim >= SSIM_QUALITY
    report.deep = {
        "frames": len(times),
        "ahash_size": AHASH_SIZE,
        "hamming_threshold": HAMMING_UNIQUE,
        "ssim_threshold": SSIM_QUALITY,
        "hamming_vs_original_mean": round(mean_orig, 2),
        "hamming_pairwise_mean": round(mean_pair, 2),
        "hamming_pairwise_min": round(min_pair, 2),
        "ssim_vs_original_mean": round(mean_ssim, 4),
        "visual_unique": visual_unique,
        "quality_ok": quality_ok,
        "times": [round(t, 3) for t in times],
    }
    return report


def format_text_report(report: AuditReport) -> str:
    lines = [
        "VideoUniq Pro — отчёт уникальности",
        f"Вердикт: {report.verdict_label}",
        f"Оригинал: {report.source}",
        f"Папка: {report.output_dir}",
        "",
        f"{'Файл':<16} {'MD5':<10} {'Длит.':<8} {'FPS':<10} {'Устройство':<22} {'Вес':<10}",
    ]
    for row in report.files:
        role = "оригинал" if row.role == "original" else ("master" if row.role == "master" else f"копия {row.index}")
        lines.append(
            f"{role:<16} {row.md58:<10} {row.duration_label:<8} {row.fps_label:<10} "
            f"{(row.device or '—')[:22]:<22} {row.size_label:<10}"
        )
    lines.append("")
    for chk in report.checks:
        mark = "✓" if chk.ok else "—"
        vs_o = "≠ оригинал" if chk.unique_vs_original else "= оригинал"
        vs_c = "все копии разные" if chk.unique_among_copies else "есть совпадение"
        lines.append(f"{mark} {chk.label}: {vs_o}, {vs_c}")
    if report.deep:
        deep = report.deep
        lines.append("")
        lines.append("Глубокий анализ (aHash + SSIM):")
        lines.append(
            f"  Hamming vs оригинал (mean) {deep.get('hamming_vs_original_mean')} "
            f"(порог >{HAMMING_UNIQUE})"
        )
        lines.append(
            f"  Hamming между копиями mean={deep.get('hamming_pairwise_mean')} "
            f"min={deep.get('hamming_pairwise_min')}"
        )
        lines.append(
            f"  SSIM vs оригинал {deep.get('ssim_vs_original_mean')} "
            f"(качество ≥{SSIM_QUALITY})"
        )
        vis = "да" if deep.get("visual_unique") else "микро-отличия (пресет бережёт картинку)"
        q = "да" if deep.get("quality_ok") else "нет"
        lines.append(f"  Визуально различны: {vis}")
        lines.append(f"  Качество сохранено: {q}")
    lines.append("")
    lines.append(f"Собрано за {report.elapsed_ms:.0f} мс (ffprobe + MD5).")
    return "\n".join(lines)
