from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from videouniq.paths import ffmpeg_bin

ENCODER_LABELS = {
    "auto": "Авто",
    "cpu": "CPU (libx264)",
    "nvenc": "NVIDIA NVENC",
    "qsv": "Intel Quick Sync",
    "amf": "AMD AMF",
}


@dataclass(frozen=True)
class EncoderChoice:
    kind: str  # cpu | nvenc | qsv | amf
    video_codec: str
    extra: list[str]
    label: str
    gpu_name: str


def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def list_ffmpeg_encoders() -> set[str]:
    try:
        proc = _run([ffmpeg_bin(), "-hide_banner", "-encoders"], timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return set()
    found: set[str] = set()
    for line in (proc.stdout or "").splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0][:1] in {"V", "A", "S"}:
            found.add(parts[1])
    return found


def _probe_nvenc_name() -> str:
    nvidia = shutil.which("nvidia-smi")
    if not nvidia:
        return ""
    try:
        proc = _run([nvidia, "--query-gpu=name", "--format=csv,noheader"], timeout=5)
        line = (proc.stdout or "").strip().splitlines()
        return line[0].strip() if line else ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _win_dll(name: str) -> bool:
    if sys.platform != "win32":
        return False
    roots = [os.environ.get("SystemRoot", r"C:\Windows"), r"C:\Windows"]
    for root in roots:
        for sub in ("System32", "SysWOW64"):
            if Path(root, sub, name).is_file():
                return True
    return False


def _can_encode(codec: str, extra: list[str]) -> bool:
    """CPU filters (crop/noise/eq) → format=yuv420p → GPU/CPU encoder."""
    with tempfile.TemporaryDirectory(prefix="vu-enc-") as tmp:
        out = Path(tmp) / "t.mp4"
        cmd = [
            ffmpeg_bin(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=128x128:d=0.08:r=25",
            "-filter_complex",
            "crop=120:120:4:4,eq=contrast=1.01,noise=alls=1:allf=t,format=yuv420p[vout]",
            "-map",
            "[vout]",
            "-frames:v",
            "2",
            "-c:v",
            codec,
            *extra,
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-y",
            str(out),
        ]
        try:
            proc = _run(cmd, timeout=16)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0 and out.is_file() and out.stat().st_size > 0


def _gpu_present(kind: str) -> bool:
    if kind == "nvenc":
        return bool(
            _probe_nvenc_name()
            or Path("/dev/nvidia0").exists()
            or _win_dll("nvEncodeAPI64.dll")
            or _win_dll("nvcuda.dll")
        )
    if kind == "qsv":
        return (
            Path("/dev/dri/renderD128").exists()
            or Path("/dev/dri/card0").exists()
            or _win_dll("libmfx64-gen.dll")
            or _win_dll("libmfxhw64.dll")
            or _win_dll("igfx11cmrt64.dll")
        )
    if kind == "amf":
        return (
            Path("/dev/dri/renderD128").exists()
            or Path("/dev/kfd").exists()
            or _win_dll("amfrt64.dll")
            or _win_dll("amfrt32.dll")
        )
    return False


def is_gpu_encode_error(message: str) -> bool:
    s = (message or "").lower()
    keys = (
        "nvenc",
        "qsv",
        "amf",
        "pix_fmt",
        "pixel format",
        "not supported",
        "no capable",
        "openencodesession",
        "mfx",
        "cuda",
        "dx11",
        "cannot load nvencodeapi",
        "does not support",
        "invalid pix_fmt",
        "yuv444",
        "yuv422",
        "gbrp",
        "p010",
        "non-monotonic",
        "monotonically",
        "error muxing",
        "conversion failed",
        "invalid argument",
        "invalid data found",
        "dts",
    )
    return any(k in s for k in keys)


def ram_gb() -> float:
    try:
        import psutil

        return float(psutil.virtual_memory().total) / (1024**3)
    except Exception:
        return 8.0


def recommended_encode_workers() -> int:
    """1 worker on 8 GB-class machines; 2 when there is enough RAM."""
    return 1 if ram_gb() <= 12.0 else 2


def cpu_encoder() -> EncoderChoice:
    return EncoderChoice(
        kind="cpu",
        video_codec="libx264",
        extra=["-preset", "slow", "-crf", "17"],
        label="CPU · libx264 CRF 17",
        gpu_name="",
    )


def detect_hardware(preference: str = "auto") -> EncoderChoice:
    encoders = list_ffmpeg_encoders()
    gpu_name = _probe_nvenc_name()

    cpu = EncoderChoice(
        kind="cpu",
        video_codec="libx264",
        extra=["-preset", "slow", "-crf", "17"],
        label="CPU · libx264 CRF 17",
        gpu_name=gpu_name,
    )

    candidates: list[EncoderChoice] = []
    if "h264_nvenc" in encoders:
        candidates.append(
            EncoderChoice(
                kind="nvenc",
                video_codec="h264_nvenc",
                extra=["-preset", "p6", "-rc", "vbr", "-cq", "19", "-b:v", "0"],
                label="NVIDIA NVENC CQ 19",
                gpu_name=gpu_name or "NVIDIA",
            )
        )
    if "h264_qsv" in encoders:
        candidates.append(
            EncoderChoice(
                kind="qsv",
                video_codec="h264_qsv",
                extra=["-preset", "slow", "-global_quality", "19"],
                label="Intel Quick Sync",
                gpu_name=gpu_name or "Intel",
            )
        )
    if "h264_amf" in encoders:
        candidates.append(
            EncoderChoice(
                kind="amf",
                video_codec="h264_amf",
                extra=["-rc", "cqp", "-qp_i", "19", "-qp_p", "19"],
                label="AMD AMF",
                gpu_name=gpu_name or "AMD",
            )
        )

    if preference == "cpu":
        return cpu
    if preference in {"nvenc", "qsv", "amf"}:
        for item in candidates:
            if item.kind == preference:
                if _can_encode(item.video_codec, item.extra):
                    return item
        return cpu

    for item in candidates:
        # Skip encode probe when the GPU is clearly absent (avoids 16s timeouts on CI).
        if not _gpu_present(item.kind):
            continue
        if _can_encode(item.video_codec, item.extra):
            return item
    return cpu


def encoder_with_quality(choice: EncoderChoice, crf: int, nvenc_cq: int, cpu_preset: str, nvenc_preset: str) -> EncoderChoice:
    if choice.kind == "cpu":
        extra = ["-preset", cpu_preset or "slow", "-crf", str(int(crf))]
    elif choice.kind == "nvenc":
        extra = ["-preset", nvenc_preset or "p6", "-rc", "vbr", "-cq", str(int(nvenc_cq)), "-b:v", "0"]
    elif choice.kind == "qsv":
        extra = ["-preset", "slow", "-global_quality", str(int(nvenc_cq))]
    else:
        extra = ["-rc", "cqp", "-qp_i", str(int(nvenc_cq)), "-qp_p", str(int(nvenc_cq))]
    return EncoderChoice(
        kind=choice.kind,
        video_codec=choice.video_codec,
        extra=extra,
        label=choice.label,
        gpu_name=choice.gpu_name,
    )
