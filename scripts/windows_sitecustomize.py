"""Runs because python*._pth lists ``import site``. Puts ../src on sys.path."""

from __future__ import annotations

import sys
from pathlib import Path

_python_dir = Path(__file__).resolve().parents[2]
_src = _python_dir.parent / "src"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))
