"""Time-varying overlay: FFmpeg noise layer at ~1% opacity, unique seed per copy.

A static PNG is not used — each frame gets a different grain pattern so copies
diverge in pHash while the mix stays below visible threshold on Optimal.
"""

from __future__ import annotations


def even_dim(value: float) -> int:
    n = max(2, int(round(value)))
    return n - (n % 2)


def temporal_overlay_chain(
    width: int,
    height: int,
    fps: float,
    seed: int,
    strength: int,
    opacity: float = 0.01,
    duration: float = 8.0,
) -> str:
    """Filter chain (no stream labels) that produces a unique per-frame overlay."""
    w, h = even_dim(width), even_dim(height)
    rate = fps if fps > 1 else 30.0
    strength = max(1, min(40, int(strength)))
    seed = max(1, int(seed) & 0x7FFFFFFF)
    alpha = max(0.004, min(0.03, float(opacity)))
    dur = max(1.0, float(duration))
    c0, c1, c2 = seed, (seed + 17) & 0x7FFFFFFF, (seed + 31) & 0x7FFFFFFF
    return (
        f"color=c=0x808080:s={w}x{h}:r={rate:.4f}:d={dur:.3f},"
        f"format=yuv420p,"
        f"noise=alls={strength}:allf=t:all_seed={seed}:c0_seed={c0}:c1_seed={c1}:c2_seed={c2},"
        f"format=yuva420p,"
        f"colorchannelmixer=aa={alpha:.3f}"
    )
