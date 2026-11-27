"""Magnetic timeline operations: trim, split, close gaps, reorder."""

from __future__ import annotations

from videouniq.editor.project import EditorProject, VideoClip, _id


def clip_duration(clip: VideoClip) -> float:
    return clip.duration()


def packed_starts(clips: list[VideoClip]) -> list[float]:
    """Timeline start of each video clip after magnetic packing and transitions."""
    starts: list[float] = []
    t = 0.0
    for i, clip in enumerate(clips):
        starts.append(t)
        t += clip.duration()
        if i < len(clips) - 1 and clip.transition == "crossfade":
            t -= min(clip.transition_duration, clip.duration() * 0.45, clips[i + 1].duration() * 0.45)
    return starts


def timeline_duration(project: EditorProject) -> float:
    if not project.video_clips:
        texts = [c.end() for c in project.text_clips]
        return max(texts) if texts else 0.0
    starts = packed_starts(project.video_clips)
    last = project.video_clips[-1]
    return starts[-1] + last.duration()


def close_gaps(project: EditorProject) -> EditorProject:
    """Magnetic video track: order is list order; starts are derived."""
    for clip in project.video_clips:
        clip.clamped()
    return project


def clip_at_time(project: EditorProject, t: float) -> tuple[int, VideoClip, float] | None:
    """Return (index, clip, local_source_time) for playhead ``t``."""
    starts = packed_starts(project.video_clips)
    for i, clip in enumerate(project.video_clips):
        start = starts[i]
        end = start + clip.duration()
        if start <= t < end or (i == len(project.video_clips) - 1 and abs(t - end) < 1e-4):
            local = clip.in_point + max(0.0, t - start)
            local = min(local, clip.out_point - 1e-3)
            return i, clip, local
    return None


def split_clip(project: EditorProject, t: float) -> VideoClip | None:
    """Split the video clip under playhead. Returns the new right-hand clip."""
    hit = clip_at_time(project, t)
    if hit is None:
        return None
    i, clip, local = hit
    if local <= clip.in_point + 0.04 or local >= clip.out_point - 0.04:
        return None
    right = VideoClip.from_dict(clip.to_dict())
    right.clip_id = _id()
    right.in_point = local
    right.out_point = clip.out_point
    right.transition = clip.transition
    right.transition_duration = clip.transition_duration
    clip.out_point = local
    clip.transition = "none"
    clip.clamped()
    right.clamped()
    project.video_clips.insert(i + 1, right)
    close_gaps(project)
    return right


def trim_clip(project: EditorProject, clip_id: str, in_point: float | None = None, out_point: float | None = None) -> VideoClip | None:
    clip = next((c for c in project.video_clips if c.clip_id == clip_id), None)
    if clip is None:
        return None
    if in_point is not None:
        clip.in_point = in_point
    if out_point is not None:
        clip.out_point = out_point
    clip.clamped()
    close_gaps(project)
    return clip


def reorder_clip(project: EditorProject, clip_id: str, new_index: int) -> bool:
    clips = project.video_clips
    idx = next((i for i, c in enumerate(clips) if c.clip_id == clip_id), -1)
    if idx < 0:
        return False
    new_index = max(0, min(len(clips) - 1, int(new_index)))
    if new_index == idx:
        return True
    clip = clips.pop(idx)
    clips.insert(new_index, clip)
    close_gaps(project)
    return True


def delete_clip(project: EditorProject, clip_id: str) -> bool:
    before = len(project.video_clips)
    project.video_clips = [c for c in project.video_clips if c.clip_id != clip_id]
    if len(project.video_clips) == before:
        before_t = len(project.text_clips)
        project.text_clips = [c for c in project.text_clips if c.clip_id != clip_id]
        if len(project.text_clips) == before_t:
            return False
        return True
    close_gaps(project)
    return True


def text_track_count(project: EditorProject) -> int:
    if not project.text_clips:
        return 2
    return max(2, max(c.track for c in project.text_clips) + 1)
