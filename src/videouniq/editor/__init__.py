"""Visual editor add-on: projects, magnetic timeline, one-pass FFmpeg."""

from videouniq.editor.ops import (
    clip_at_time,
    close_gaps,
    reorder_clip,
    split_clip,
    timeline_duration,
    trim_clip,
)
from videouniq.editor.project import (
    ASPECTS,
    TRANSITIONS,
    EditorProject,
    TextClip,
    TextStylePreset,
    VideoClip,
)

__all__ = [
    "ASPECTS",
    "TRANSITIONS",
    "EditorProject",
    "TextClip",
    "TextStylePreset",
    "VideoClip",
    "clip_at_time",
    "close_gaps",
    "reorder_clip",
    "split_clip",
    "timeline_duration",
    "trim_clip",
]
