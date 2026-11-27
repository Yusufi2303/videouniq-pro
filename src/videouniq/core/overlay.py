"""Tiny PNG writer for a sparse random-pixel overlay (1% opacity)."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from random import Random


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def write_noise_overlay(path: str | Path, width: int = 128, height: int = 128, seed: int = 0) -> Path:
    rng = Random(seed)
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    rows = bytearray()
    for _y in range(height):
        rows.append(0)  # filter: none
        for _x in range(width):
            if rng.random() < 0.18:
                rows.extend((rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255), 3))
            else:
                rows.extend((0, 0, 0, 0))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _chunk(b"IEND", b"")
    dest.write_bytes(png)
    return dest
