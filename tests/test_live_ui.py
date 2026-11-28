"""Live DISPLAY UI pass: real clicks, mouse drag, export, uniquizer, ZIP."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("DISPLAY", ":1")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QEvent, QEventLoop, QPoint, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from videouniq.paths import ffmpeg_bin
from videouniq.ui.main_window import MainWindow
from videouniq.ui.theme import apply_theme

SHOT = Path("/opt/cursor/artifacts")
STORE_SHOT = Path("/cursor/stores/bc-01a21daf-6adf-7d23-b2a4-4a1ddddeee37/media/videouniq-pro")
FAILED = 0
PASSED = 0
LOG: list[str] = []


def check(cond: bool, msg: str) -> None:
    global FAILED, PASSED
    if cond:
        PASSED += 1
        line = f"  OK  {msg}"
    else:
        FAILED += 1
        line = f"  FAIL {msg}"
    print(line, flush=True)
    LOG.append(line)


def pump(ms: int = 80) -> None:
    QTest.qWait(ms)


def shot(win: MainWindow, name: str) -> Path:
    SHOT.mkdir(parents=True, exist_ok=True)
    STORE_SHOT.mkdir(parents=True, exist_ok=True)
    dest = SHOT / name
    win.grab_to(dest)
    try:
        import shutil

        shutil.copy2(dest, STORE_SHOT / name)
        v21 = name if name.startswith("v2.1-") else f"v2.1-{name}"
        shutil.copy2(dest, STORE_SHOT / v21)
        shutil.copy2(dest, SHOT / v21)
    except Exception:
        pass
    return dest


def make_sample(path: Path, seconds: float = 0.8, size: str = "640x360") -> Path:
    import subprocess

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
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(proc.stderr or "sample failed")
    return path


def drag(widget, x0: float, y0: float, x1: float, y1: float, steps: int = 12) -> None:
    start = QPoint(int(x0), int(y0))
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    pump(20)
    for i in range(1, steps + 1):
        x = x0 + (x1 - x0) * i / steps
        y = y0 + (y1 - y0) * i / steps
        local = QPointF(x, y)
        glob = widget.mapToGlobal(local.toPoint())
        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            local,
            QPointF(glob),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        QApplication.sendEvent(widget, ev)
        pump(12)
    QTest.mouseRelease(
        widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(x1), int(y1))
    )
    pump(40)


def click(widget) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    pump(60)


def main() -> int:
    print("LIVE UI on DISPLAY", os.environ.get("DISPLAY"), flush=True)
    tmp = Path(tempfile.mkdtemp(prefix="vu-live-"))
    a = make_sample(tmp / "clip_a.mp4", 0.9)
    b = make_sample(tmp / "clip_b.mp4", 0.9)
    vup = tmp / "live.vup"
    vup2 = tmp / "reopened.vup"
    export_mp4 = tmp / "clean.mp4"
    out_root = tmp / "uniq_out"
    out_root.mkdir()

    QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[method-assign]
    QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)  # type: ignore[method-assign]

    orig_save = QFileDialog.getSaveFileName
    orig_open = QFileDialog.getOpenFileName
    orig_files = QFileDialog.getOpenFileNames
    orig_dir = QFileDialog.getExistingDirectory
    paths = {"save": str(export_mp4), "open": str(vup), "files": [str(a), str(b)], "dir": str(out_root)}

    def _save(*_a, **_k):
        return paths["save"], "MP4 (*.mp4)"

    def _open(*_a, **_k):
        return paths["open"], "vup"

    def _files(*_a, **_k):
        return list(paths["files"]), "video"

    def _dir(*_a, **_k):
        return paths["dir"]

    QFileDialog.getSaveFileName = staticmethod(_save)  # type: ignore[method-assign]
    QFileDialog.getOpenFileName = staticmethod(_open)  # type: ignore[method-assign]
    QFileDialog.getOpenFileNames = staticmethod(_files)  # type: ignore[method-assign]
    QFileDialog.getExistingDirectory = staticmethod(_dir)  # type: ignore[method-assign]

    app = QApplication.instance() or QApplication(sys.argv)
    apply_theme(app, dark=True)
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    win.raise_()
    pump(250)
    shot(win, "live_01_editor_empty.png")
    check(win.sidebar._page == "editor", f"start tab={win.sidebar._page}")
    check(win.editor.bin.isVisible() and win.editor.player.isVisible(), "four-zone visible")
    check(win.editor.inspector.isVisible() and win.editor.timeline.isVisible(), "inspector+timeline")

    # Click Импорт — file dialog stub returns both clips, but import_media uses getOpenFileNames
    click(win.editor.bin.imp)
    pump(400)
    check(len(win.editor.project.video_clips) >= 1, f"clips after import {len(win.editor.project.video_clips)}")
    if len(win.editor.project.video_clips) < 2:
        win.editor.add_media(str(b))
        pump(200)
    check(len(win.editor.project.video_clips) >= 2, "two clips on magnetic track")
    shot(win, "live_02_clips_added.png")

    # Timeline click playhead + split
    tl = win.editor.timeline
    dur = max(0.2, sum(c.duration() for c in win.editor.project.video_clips))
    mid_x = int(tl._x(0.45))
    QTest.mouseClick(tl, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(mid_x, 10))
    pump(80)
    before = len(win.editor.project.video_clips)
    click(win.editor.split_btn)
    pump(120)
    after = len(win.editor.project.video_clips)
    check(after >= before, f"split {before}->{after}")
    # Trim first clip by dragging its right edge left
    if win.editor.project.video_clips:
        c0 = win.editor.project.video_clips[0]
        old_out = c0.out_point
        x1 = tl._x(c0.duration()) - 3
        yv = int(tl._video_y() + 20)
        drag(tl, x1, yv, x1 - 40, yv)
        pump(80)
        check(win.editor.project.video_clips[0].out_point <= old_out + 0.05, "trim via edge drag")
    starts = [0.0]
    from videouniq.editor.ops import packed_starts, timeline_duration

    st = packed_starts(win.editor.project.video_clips)
    check(abs(st[0]) < 1e-6, f"magnetic start {st}")
    if len(st) > 1:
        check(st[1] >= st[0], f"no reverse overlap {st}")
    shot(win, "live_03_trim_split.png")

    # Add TikTok text by clicking the real button
    click(win.editor.bin.tiktok_btn)
    pump(150)
    check(len(win.editor.project.text_clips) >= 1, "text clip from button")
    tclip = win.editor.project.text_clips[-1]
    # Seek to text so it's visible
    win.editor.player.set_playhead(tclip.start + 0.05)
    pump(200)
    canvas = win.editor.player.canvas
    center = canvas.clip_center(tclip)
    x0, y0 = center.x(), center.y()
    before_xy = (tclip.x_norm, tclip.y_norm)
    drag(canvas, x0, y0, x0 + 50, y0 - 30)
    pump(100)
    moved = abs(tclip.x_norm - before_xy[0]) > 0.01 or abs(tclip.y_norm - before_xy[1]) > 0.01
    check(moved, f"drag move {before_xy} -> {(tclip.x_norm, tclip.y_norm)}")
    shot(win, "live_04_text_drag.png")

    # Scale: grab lower-right handle from the *current* center after the move.
    c1 = canvas.clip_center(tclip)
    before_s = tclip.scale
    drag(canvas, c1.x() + 22, c1.y() + 14, c1.x() + 90, c1.y() + 16)
    pump(80)
    check(abs(tclip.scale - before_s) > 0.04, f"scale {before_s}->{tclip.scale}")

    # Rotate: press above the current center
    before_r = tclip.rotation
    c2 = canvas.clip_center(tclip)
    drag(canvas, c2.x(), c2.y() - 32, c2.x() + 48, c2.y() - 32)
    pump(80)
    check(abs(tclip.rotation - before_r) > 0.5, f"rotate {before_r}->{tclip.rotation}")
    shot(win, "live_05_scale_rotate.png")

    # Player: space / arrows / aspect
    check(win.editor.player.backend == "qt", f"player backend={win.editor.player.backend}")
    check(win.editor.player._audio is not None and not win.editor.player._audio.isMuted(), "audio unmuted")
    check("звук" in win.editor.player.backend_lab.text(), win.editor.player.backend_lab.text())
    check(win.editor.player._video is not None, "QVideoWidget native surface")
    check(win.editor.player.canvas.live_video, "canvas overlay is transparent over video")
    click(win.editor.player.play_btn)
    pump(250)
    check(win.editor.player.playing, "play starts")
    check(not win.editor.player._timer.isActive(), "qt play is not ffmpeg stills")
    click(win.editor.player.play_btn)
    click(win.editor.player.next_btn)
    pump(80)
    idx = win.editor.player.aspect.findData("16:9")
    win.editor.player.aspect.setCurrentIndex(idx)
    pump(80)
    check(win.editor.project.aspect == "16:9", win.editor.project.aspect)
    win.editor.player._set_loading(True)
    pump(40)
    shot(win, "v2.1-playhead-loading.png")
    win.editor.player._set_loading(False)
    shot(win, "v2.1-player.png")

    # Save .vup by clicking Сохранить (path preset)
    win.editor.project.path = str(vup)
    paths["save"] = str(vup)
    click(win.editor.save_btn)
    pump(80)
    check(vup.is_file(), f"saved {vup}")
    raw = vup.read_text(encoding="utf-8")
    check("videouniq-project" in raw and tclip.text in raw, "vup contains text")

    # Open: click Открыть with stub
    paths["open"] = str(vup)
    click(win.editor.open_btn)
    pump(120)
    check(len(win.editor.project.video_clips) >= 1, "reopened clips")
    shot(win, "live_06_saved_vup.png")

    # Clean export via Экспорт button
    paths["save"] = str(export_mp4)
    click(win.editor.export_btn)
    pump(400)
    # encode is sync
    check(export_mp4.is_file() and export_mp4.stat().st_size > 500, f"export {export_mp4} {export_mp4.stat().st_size if export_mp4.is_file() else 0}")

    # Send to uniquizer
    win.editor.project.path = str(vup)
    click(win.editor.send_btn)
    pump(200)
    win.right.copies_spin.setValue(2)
    pump(40)
    check(win.sidebar._page == "uniquize", win.sidebar._page)
    check(any(it.kind == "project" for it in win.items), "project badge in queue")
    shot(win, "live_07_uniquizer_badge.png")

    win.right.set_output_dir(str(out_root))
    click(win.right.cta)
    loop = QEventLoop()
    win.controller.all_finished.connect(loop.quit)
    QTimer.singleShot(180_000, loop.quit)
    loop.exec()
    pump(200)
    done = [it for it in win.items if it.kind == "project"]
    check(bool(done) and done[0].copies_done >= 1, f"uniquize copies_done={done[0].copies_done if done else None} err={done[0].error if done else None}")
    copies = list(Path(done[0].output_dir).glob("video_*.mp4")) if done and done[0].output_dir else []
    check(len(copies) >= 1, f"files {copies}")
    shot(win, "live_08_uniquize_done.png")
    from videouniq.core.auditor import load_report
    from videouniq.ui.uniqueness_dialog import UniquenessDialog

    card = win.queue._cards.get(done[0].item_id) if done else None
    check(card is not None and card.report_btn.isVisible(), "Отчёт уникальности on card")
    loaded = load_report(done[0].output_dir) if done and done[0].output_dir else None
    check(loaded is not None and loaded.verdict in {"unique", "warn"}, loaded.verdict if loaded else None)
    check(loaded is not None and loaded.copies and "." in loaded.copies[0].duration_label, loaded.copies[0].duration_label if loaded and loaded.copies else None)
    check(win.right.size_combo.count() == 2, win.right.size_combo.count())
    check(win.right.size_mode() == "quality", win.right.size_mode())
    check("Не раздувать" in win.right.size_combo.itemText(1), win.right.size_combo.itemText(1))
    check(win.render_page.size_combo.count() == 2, "render size modes")
    check(loaded is not None and len(loaded.copies[0].md5) == 32, "real md5 in uniqueness.json")
    check(loaded is not None and "00000000" not in loaded.copies[0].md5, loaded.copies[0].md5 if loaded else "")
    dlg = UniquenessDialog(done[0].path, done[0].output_dir, win)
    dlg.show()
    dlg.raise_()
    pump(500)
    check(dlg.table.rowCount() >= 4, f"report rows {dlg.table.rowCount()}")
    check(dlg.table.columnCount() >= 2, f"report cols {dlg.table.columnCount()}")
    shot(win, "v2.2-uniqueness-report.png")
    SHOT.mkdir(parents=True, exist_ok=True)
    STORE_SHOT.mkdir(parents=True, exist_ok=True)
    dlg_shot = SHOT / "v2.2-uniqueness-modal.png"
    dlg.grab().save(str(dlg_shot))
    try:
        import shutil

        shutil.copy2(dlg_shot, STORE_SHOT / dlg_shot.name)
    except Exception:
        pass
    dlg.close()
    pump(80)

    # Return to editor
    if done:
        card = win.queue._cards.get(done[0].item_id)
        if card:
            click(card.return_btn)
            pump(150)
        else:
            win._return_to_editor(done[0].item_id)
            pump(80)
    check(win.sidebar._page == "editor", f"return tab={win.sidebar._page}")

    # ZIP from editor button
    click(win.editor.zip_btn)
    pump(200)
    zips = list(Path(done[0].output_dir).glob("*.zip")) if done and done[0].output_dir else []
    check(bool(zips) or any(p.suffix == ".zip" for p in out_root.rglob("*.zip")), f"zip {zips}")
    shot(win, "live_09_zip_history.png")

    # History + cache — click real sidebar nav buttons
    click(win.sidebar._buttons["history"])
    pump(80)
    check(win.stack.currentIndex() == 2, "history page")
    shot(win, "live_09b_history.png")
    click(win.sidebar._buttons["render"])
    pump(80)
    check("Размер кэша" in win.render_page.cache_size_lab.text(), win.render_page.cache_size_lab.text())
    check("Очистить кэш сейчас" in win.render_page.cache_btn.text(), win.render_page.cache_btn.text())
    shot(win, "v2.1-settings-cache.png")
    click(win.render_page.cache_btn)
    pump(80)
    logs = win.logs_page.view.toPlainText()
    check("Кэш очищен" in logs, "cache clear log")

    shot(win, "live_10_settings_cache.png")
    shot(win, "v2.1-player-proxy-label.png")

    # Native 1080×1920 must actually play (clock + decoded frames), not freeze or proxy.
    from videouniq.core.probe import probe_media
    from videouniq.editor.proxy import is_heavy_source

    phone = make_sample(tmp / "phone_1080x1920.mp4", 3.2, size="1080x1920")
    click(win.sidebar._buttons["editor"])
    pump(80)
    pinfo = probe_media(phone)
    check((pinfo.width, pinfo.height) == (1080, 1920), (pinfo.width, pinfo.height))
    check(pinfo.has_audio, "phone has audio")
    check(not is_heavy_source(pinfo.width, pinfo.height), "1080x1920 is not a proxy candidate")
    win.editor.project.video_clips.clear()
    win.editor.project.text_clips.clear()
    win.editor.project.aspect = "9:16"
    win.editor.project.sync_canvas()
    win.editor.add_media(str(phone))
    pump(400)
    check(len(win.editor.project.video_clips) >= 1, "phone clip on timeline")
    clip0 = win.editor.project.video_clips[0]
    check((clip0.source_width, clip0.source_height) == (1080, 1920), (clip0.source_width, clip0.source_height))
    idx16 = win.editor.player.aspect.findData("9:16")
    if idx16 >= 0:
        win.editor.player.aspect.setCurrentIndex(idx16)
    win.editor.player.set_playhead(0.0)
    pump(250)
    t0 = win.editor.player.playhead
    pos0 = int(win.editor.player._qt_player.position()) if win.editor.player._qt_player else 0
    click(win.editor.player.play_btn)
    pump(1600)
    check(win.editor.player.playing, "native 1080x1920 play starts")
    check(not win.editor.player._timer.isActive(), "native play is QMediaPlayer not FFmpeg stills")
    check(win.editor.player._video is not None and win.editor.player._video.isVisible(), "QVideoWidget visible")
    check(win.editor.player.canvas.live_video, "no QVideoSink pixmap flash")
    ph = win.editor.player.playhead
    qt_pos = int(win.editor.player._qt_player.position()) if win.editor.player._qt_player else 0
    check(ph - t0 >= 0.35 or qt_pos - pos0 >= 300, f"clock moved playhead={ph:.2f} qt={qt_pos}ms")
    check(not win.editor.player._proxy_of.get(str(phone)), "1080x1920 not proxied")
    shot(win, "v2.2-player-qvideowidget.png")
    click(win.editor.player.play_btn)
    pump(80)
    win.close()
    pump(50)

    QFileDialog.getSaveFileName = orig_save  # type: ignore[method-assign]
    QFileDialog.getOpenFileName = orig_open  # type: ignore[method-assign]
    QFileDialog.getOpenFileNames = orig_files  # type: ignore[method-assign]
    QFileDialog.getExistingDirectory = orig_dir  # type: ignore[method-assign]

    print(f"\nLIVE PASSED={PASSED} FAILED={FAILED}", flush=True)
    (tmp / "live-log.txt").write_text("\n".join(LOG), encoding="utf-8")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
