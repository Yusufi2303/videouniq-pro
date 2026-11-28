"""V2 editor TZ: project JSON, magnetic timeline, one-pass filtergraph, UI surfaces."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from videouniq.core.hardware import detect_hardware
from videouniq.core.params import UniqueParams
from videouniq.core.pipeline import encode_copy, file_md5
from videouniq.core.probe import probe_media
from videouniq.core.randomizer import generate_unique_set
from videouniq.core.pipeline import finalize_filter_graph
from videouniq.editor.export import (
    autosave_path,
    cache_size_label,
    clear_app_cache,
    cleanup_on_quit,
    purge_cache_older_than,
    zip_copies,
)
from videouniq.editor.filtergraph import build_edit_and_uniquize, is_one_pass_graph
from videouniq.editor.proxy import is_heavy_source
from videouniq.editor.text_paint import clamp_text_shift, render_text_png
from videouniq.paths import cache_dir
from videouniq.editor.history import append_history, clear_history, load_history
from videouniq.editor.ops import (
    clip_at_time,
    close_gaps,
    delete_clip,
    packed_starts,
    reorder_clip,
    split_clip,
    timeline_duration,
    trim_clip,
)
from videouniq.editor.project import FORMAT, VERSION, EditorProject, TextClip, VideoClip
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


def run(cmd, **kw):
    import subprocess

    return subprocess.run(cmd, text=True, capture_output=True, check=False, **kw)


def make_sample(path: Path, seconds: float = 2.0, size: str = "640x360") -> Path:
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
        f"testsrc2=size={size}:rate=30:duration={seconds}",
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
    ]
    proc = run(cmd)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "sample encode failed")
    return path


def sample_project(a: Path, b: Path | None = None) -> EditorProject:
    info = probe_media(a)
    clips = [
        VideoClip(
            source_path=info.path,
            in_point=0.0,
            out_point=info.duration,
            source_duration=info.duration,
            source_width=info.width,
            source_height=info.height,
            source_fps=info.fps,
            has_audio=info.has_audio,
        )
    ]
    if b is not None:
        ib = probe_media(b)
        clips.append(
            VideoClip(
                source_path=ib.path,
                in_point=0.2,
                out_point=ib.duration - 0.1,
                source_duration=ib.duration,
                source_width=ib.width,
                source_height=ib.height,
                source_fps=ib.fps,
                has_audio=ib.has_audio,
                volume=0.8,
            )
        )
    proj = EditorProject(
        name="тест",
        aspect="16:9",
        video_clips=clips,
        text_clips=[
            TextClip(
                text="Привет",
                start=0.2,
                duration=1.2,
                stroke_enabled=True,
                plate=True,
                shadow=True,
                font_size=40,
            )
        ],
        shift_text_on_uniquize=True,
    )
    proj.add_media_path(info.path)
    proj.sync_canvas()
    return proj


def t_project_json(tmp: Path) -> None:
    print("JSON .vup")
    a = make_sample(tmp / "a.mp4", 1.6)
    proj = sample_project(a)
    dest = tmp / "clip.vup"
    proj.save(dest)
    loaded = EditorProject.load(dest)
    check(loaded.name == "clip" or loaded.name == "тест", loaded.name)
    data = json.loads(dest.read_text(encoding="utf-8"))
    check(data["format"] == FORMAT, data["format"])
    check(int(data["version"]) == VERSION, data["version"])
    check(len(data["video_clips"]) == 1, data["video_clips"])
    check(data["text_clips"][0]["text"] == "Привет", data["text_clips"])
    check(data["shift_text_on_uniquize"] is True, "shift flag")
    roundtrip = EditorProject.from_json(loaded.to_json())
    check(roundtrip.video_clips[0].source_path == proj.video_clips[0].source_path, "path roundtrip")
    check(roundtrip.text_clips[0].plate is True, "plate roundtrip")
    extra = EditorProject.from_dict({**data, "unknown_future": 1, "video_clips": [{**data["video_clips"][0], "zzz": 1}]})
    check(len(extra.video_clips) == 1, "unknown fields ignored")


def t_trim_split_magnetic() -> None:
    print("trim / split / magnetic")
    clip = VideoClip(source_path="/tmp/x.mp4", in_point=0, out_point=3.0, source_duration=3.0)
    proj = EditorProject(video_clips=[clip])
    check(abs(timeline_duration(proj) - 3.0) < 1e-6, f"dur {timeline_duration(proj)}")
    trim_clip(proj, clip.clip_id, in_point=0.5, out_point=2.5)
    check(abs(timeline_duration(proj) - 2.0) < 1e-6, f"trimmed {timeline_duration(proj)}")
    right = split_clip(proj, 1.0)  # local 0.5+0.5=1.0 source? playhead 1.0 on 2s clip starting 0
    check(right is not None, "split")
    check(len(proj.video_clips) == 2, len(proj.video_clips))
    starts = packed_starts(proj.video_clips)
    check(abs(starts[0] - 0.0) < 1e-6, starts)
    check(starts[1] > starts[0], starts)
    check(abs(starts[1] + proj.video_clips[1].duration() - timeline_duration(proj)) < 1e-5, "packed end")
    ids = [c.clip_id for c in proj.video_clips]
    reorder_clip(proj, ids[1], 0)
    check(proj.video_clips[0].clip_id == ids[1], "reorder")
    check(abs(packed_starts(proj.video_clips)[0]) < 1e-9, "magnetic after reorder")
    first_id = proj.video_clips[0].clip_id
    delete_clip(proj, first_id)
    check(len(proj.video_clips) == 1, "delete")
    check(abs(packed_starts(proj.video_clips)[0]) < 1e-9, "close gap")
    close_gaps(proj)
    hit = clip_at_time(proj, 0.1)
    check(hit is not None and hit[1].clip_id == proj.video_clips[0].clip_id, "clip at time")
    # two clips with gap simulation: magnetic never stores gaps
    c1 = VideoClip(in_point=0, out_point=1, source_duration=1)
    c2 = VideoClip(in_point=0, out_point=1, source_duration=1)
    p2 = EditorProject(video_clips=[c1, c2])
    check(abs(packed_starts(p2.video_clips)[1] - 1.0) < 1e-6, "abut")
    p2.video_clips[0].transition = "crossfade"
    p2.video_clips[0].transition_duration = 0.4
    starts = packed_starts(p2.video_clips)
    check(starts[1] < 1.0, f"crossfade overlap {starts}")


def t_filtergraph_one_pass(tmp: Path) -> None:
    print("one-pass filtergraph")
    a = make_sample(tmp / "ga.mp4", 1.4)
    b = make_sample(tmp / "gb.mp4", 1.4, size="480x270")
    proj = sample_project(a, b)
    proj.video_clips[0].transition = "crossfade"
    proj.video_clips[0].transition_duration = 0.3
    proj.video_clips[1].muted = False
    proj.video_clips[1].volume = 1.5
    info = probe_media(a)
    params = generate_unique_set(info, 1, "optimal")[0]
    spec = build_edit_and_uniquize(proj, params)
    g = spec.graph
    check("trim=" in g, "edit trim")
    check("xfade=" in g or "concat=" in g, "edit join")
    check("enable='between" in g or "drawtext=" in g, "text overlay")
    check("overlay=0:0" in g or "box=1" in g, "tiktok plate via png overlay")
    check("format=yuv420p" in g, "yuv420p in graph")
    check("volume=" in g, "per-clip volume")
    check(is_one_pass_graph(g), "edit+uniquize same graph")
    check("noise=" in g or "eq=" in g or "hue=h=" in g, "uniquize in graph")
    check(g.count("-filter_complex") == 0, "graph is the complex, not two commands")
    clean = build_edit_and_uniquize(proj, None)
    check("enable='between" in clean.graph or "drawtext=" in clean.graph, "clean still has text")
    check(not is_one_pass_graph(clean.graph) or "noise=" not in clean.graph, "clean has no uniquize grain")
    # one ffmpeg process encodes edit+uniquize
    encoder = detect_hardware("cpu")
    dest = tmp / "onepass.mp4"
    encode_copy(spec.as_media(a), params, dest, encoder, graph_spec=spec, x264_threads=2)
    check(dest.is_file() and dest.stat().st_size > 1000, dest)
    out = probe_media(dest)
    check(out.duration > 0.5, out.duration)
    master = tmp / "master.mp4"
    encode_copy(clean.as_media(a), UniqueParams(write_metadata=False, pad_bytes=16), master, encoder, graph_spec=clean, x264_threads=2)
    check(master.is_file(), master)
    check(file_md5(dest) != file_md5(master), "uniquized differs from clean master")
    fade = sample_project(a, b)
    fade.video_clips[0].transition = "fade_black"
    fade.video_clips[0].transition_duration = 0.4
    fg = build_edit_and_uniquize(fade, params).graph
    check("fade=t=out" in fg and "fade=t=in" in fg, "fade to black")


def t_zip_history_cache(tmp: Path) -> None:
    print("ZIP / history / cache")
    a = make_sample(tmp / "z1.mp4", 0.6)
    b = make_sample(tmp / "z2.mp4", 0.6)
    folder = tmp / "outclip"
    folder.mkdir()
    (folder / "video_1.mp4").write_bytes(a.read_bytes())
    (folder / "video_2.mp4").write_bytes(b.read_bytes())
    zpath = zip_copies(folder)
    check(zpath.is_file(), zpath)
    with zipfile.ZipFile(zpath) as zf:
        names = set(zf.namelist())
    check("video_1.mp4" in names and "video_2.mp4" in names, names)
    clear_history()
    append_history("zip", zpath.name, str(zpath), copies=2)
    items = load_history()
    check(len(items) >= 1 and items[0]["kind"] == "zip", items[:1])
    removed = clear_app_cache()
    check(isinstance(removed, list), removed)
    auto = autosave_path()
    check(auto.parent.is_dir(), auto)
    check(str(cache_dir()).rstrip("/\\").endswith("cache"), f"cache dir {cache_dir()}")
    check("Размер кэша" in cache_size_label(), cache_size_label())
    junk = cache_dir() / "tmp" / "old.bin"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"x" * 64)
    os.utime(junk, (time.time() - 48 * 3600, time.time() - 48 * 3600))
    purged = purge_cache_older_than(24.0, keep_autosave=True)
    check(any("old.bin" in x for x in purged) or not junk.is_file(), "24h purge")
    auto = autosave_path()
    auto.write_text("{}", encoding="utf-8")
    cleanup_on_quit(keep_autosave=True)
    check(auto.is_file(), "quit keeps autosave")


def t_text_png_and_safe_zone(tmp: Path) -> None:
    print("text PNG overlay / safe zone / yuv420p")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication(["videouniq-test"])
    a = make_sample(tmp / "txt.mp4", 1.2)
    proj = sample_project(a)
    clip = proj.text_clips[0]
    clip.plate = True
    clip.shadow = True
    clip.stroke_enabled = True
    clip.y_norm = 0.02
    png = render_text_png(clip, 1920, 1080, 0, 0)
    check(png.is_file() and png.stat().st_size > 100, png)
    jx, jy = clamp_text_shift(clip, 1920, 1080, 0, -15)
    check(jy >= -15, (jx, jy))
    # near the top edge the -15 jitter must not leave the 5% safe zone
    from videouniq.editor.text_paint import SAFE_PCT, measure_text

    x0, y0, x1, y1 = measure_text(clip, 1920, 1080, jx, jy).aabb
    check(y0 >= 1080 * SAFE_PCT - 1.0, f"safe y0={y0} jy={jy}")
    spec = build_edit_and_uniquize(proj, None)
    check("enable='between" in spec.graph, spec.graph[:200])
    g2, vmap = finalize_filter_graph(spec.graph)
    check("[v420]" in g2 and vmap == "[v420]", vmap)
    check("format=yuv420p[v420]" in g2, "forced yuv420p before encode")
    check(is_heavy_source(3840, 2160) and not is_heavy_source(1920, 1080), "4K is heavy")
    edge = TextClip(text="Низ", x_norm=0.5, y_norm=0.97, font_size=40, plate=True)
    jx2, jy2 = clamp_text_shift(edge, 1080, 1920, 12, 15)
    x0, y0, x1, y1 = measure_text(edge, 1080, 1920, jx2, jy2).aabb
    check(y1 <= 1920 - 1920 * SAFE_PCT + 1.0, f"bottom safe y1={y1} jy={jy2}")


def t_ui_surfaces() -> None:
    print("UI Russian surfaces")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from videouniq.ui.main_window import MainWindow
    from videouniq.ui.sidebar import NAV
    from videouniq.ui.theme import apply_theme

    keys = [k for k, _ in NAV]
    labels = [lab for _, lab in NAV]
    check(keys[0] == "editor", keys)
    check("Видеоредактор" in labels, labels)
    check("Уникализатор" in labels, labels)
    check("История и загрузки" in labels, labels)
    app = QApplication.instance() or QApplication(["videouniq-test"])
    apply_theme(app, dark=True)
    win = MainWindow()
    win.show()
    app.processEvents()
    check(win.editor is not None, "editor page")
    check(win.history_page is not None, "history page")
    # four zones
    check(win.editor.bin is not None, "media bin")
    check(win.editor.player is not None, "player")
    check(win.editor.inspector is not None, "inspector")
    check(win.editor.timeline is not None, "timeline")
    check(win.editor.inspector.shift_box.text().startswith("Слегка"), win.editor.inspector.shift_box.text())
    check("Плашка" in win.editor.bin.tiktok_btn.text() or "TikTok" in win.editor.bin.tiktok_btn.text(), win.editor.bin.tiktok_btn.text())
    win.sidebar.set_page("uniquize")
    app.processEvents()
    check(win.stack.currentIndex() == 1, win.stack.currentIndex())
    check(win.right.master_toggle is not None, "save master")
    check(win.render_page.cache_btn is not None, "cache clear")
    check("Очистить кэш" in win.render_page.cache_btn.text(), win.render_page.cache_btn.text())
    check("Размер кэша" in win.render_page.cache_size_lab.text(), win.render_page.cache_size_lab.text())
    check("сейчас" in win.render_page.cache_btn.text(), "clear now label")
    # project badge path
    proj = EditorProject(name="ui")
    win._from_editor.__func__  # exists
    item_n = len(win.items)
    # without path should warn — save to tmp via project.path
    tmpv = Path(tempfile.gettempdir()) / "vu-ui.vup"
    proj.save(tmpv)
    win._from_editor(proj)
    check(len(win.items) > item_n or any(it.kind == "project" for it in win.items), "project queued")
    check(any(it.kind == "project" for it in win.items), "badge kind")
    win._return_to_editor(win.items[-1].item_id)
    app.processEvents()
    check(win.sidebar._page == "editor", win.sidebar._page)
    check(win.editor._auto.interval() == 60_000, "autosave 60s")
    win.sidebar.set_page("history")
    app.processEvents()
    check(win.stack.currentIndex() == 2, "history page index")
    check(win.history_page.empty is not None, "history empty state")
    win.close()


def main() -> int:
    print("VideoUniq Pro V2 editor tests")
    with tempfile.TemporaryDirectory(prefix="vu-ed-") as raw:
        tmp = Path(raw)
        t_project_json(tmp)
        t_trim_split_magnetic()
        t_filtergraph_one_pass(tmp)
        t_zip_history_cache(tmp)
        t_text_png_and_safe_zone(tmp)
        t_ui_surfaces()
    print(f"\nPASSED={PASSED} FAILED={FAILED}")
    if FAILED:
        print("EDITOR TESTS FAILED")
        return 1
    print("ALL EDITOR TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
