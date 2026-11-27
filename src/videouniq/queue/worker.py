from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from videouniq.core.hardware import EncoderChoice
from videouniq.core.params import UniqueParams
from videouniq.core.pipeline import JobCancelled, encode_copy, file_md5
from videouniq.core.probe import MediaInfo
from videouniq.queue.models import CopyJob, FileItem


class RenderController(QObject):
    job_progress = Signal(str, int, float, str)  # item_id, copy_index, frac, stage
    job_finished = Signal(str, int, str, str)  # item_id, copy_index, dest, md5
    job_failed = Signal(str, int, str)
    item_finished = Signal(str)
    log_line = Signal(str)
    all_finished = Signal(bool)  # cancelled?
    running_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pool: ThreadPoolExecutor | None = None
        self._futures: list[Future] = []
        self._hashes: dict[str, set[str]] = {}
        self._pending: dict[str, int] = {}
        self._failed: dict[str, int] = {}
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    def start(
        self,
        items: list[FileItem],
        params_map: dict[str, list[UniqueParams]],
        output_root: Path,
        encoder: EncoderChoice,
        parallel: int,
    ) -> int:
        if self._running:
            return 0
        jobs: list[CopyJob] = []
        self._hashes = {}
        self._pending = {}
        self._failed = {}
        for item in items:
            if item.info is None:
                continue
            copies = params_map.get(item.item_id) or []
            if not copies:
                continue
            folder = output_root / Path(item.path).stem
            folder.mkdir(parents=True, exist_ok=True)
            item.output_dir = str(folder)
            item.copies_total = len(copies)
            item.copies_done = 0
            self._hashes[item.item_id] = set()
            self._pending[item.item_id] = len(copies)
            self._failed[item.item_id] = 0
            for idx, params in enumerate(copies, start=1):
                jobs.append(
                    CopyJob(
                        item_id=item.item_id,
                        source_path=item.path,
                        copy_index=idx,
                        copies_total=len(copies),
                        dest=str(folder / f"video_{idx}.mp4"),
                        params=params,
                        media=item.info,
                    )
                )

        if not jobs:
            return 0

        workers = max(1, min(int(parallel), 8, len(jobs)))
        cpu_n = os.cpu_count() or 4
        x264_threads = max(1, cpu_n // workers) if encoder.kind == "cpu" else 0

        self._stop.clear()
        self._running = True
        self.running_changed.emit(True)
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vu-enc")
        self._futures = [
            self._pool.submit(self._run_job, job, encoder, x264_threads) for job in jobs
        ]
        self.log_line.emit(f"Старт: {len(jobs)} копий, потоков {workers}, энкодер {encoder.label}")
        threading.Thread(target=self._wait_done, daemon=True).start()
        return len(jobs)

    def stop(self) -> None:
        if not self._running:
            return
        self._stop.set()
        self.log_line.emit("Остановка…")

    def _wait_done(self) -> None:
        for fut in list(self._futures):
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                self.log_line.emit(f"Ошибка потока: {exc}")
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None
        cancelled = self._stop.is_set()
        self._running = False
        self.running_changed.emit(False)
        self.all_finished.emit(cancelled)

    def _run_job(self, job: CopyJob, encoder: EncoderChoice, x264_threads: int) -> None:
        if self._stop.is_set():
            self.job_failed.emit(job.item_id, job.copy_index, "Остановлено")
            self._mark_item(job.item_id)
            return

        params = job.params
        last_error = ""
        for attempt in range(1, 4):
            if self._stop.is_set():
                self.job_failed.emit(job.item_id, job.copy_index, "Остановлено")
                self._mark_item(job.item_id)
                return
            try:

                def _cb(frac: float, stage: str, item_id=job.item_id, idx=job.copy_index) -> None:
                    self.job_progress.emit(item_id, idx, frac, stage)

                encode_copy(
                    job.media,
                    params,
                    job.dest,
                    encoder,
                    stop_event=self._stop,
                    progress_cb=_cb,
                    log_cb=lambda m: self.log_line.emit(m),
                    x264_threads=x264_threads,
                )
                digest = file_md5(job.dest)
                with self._lock:
                    known = self._hashes.setdefault(job.item_id, set())
                    collision = digest in known
                    if not collision:
                        known.add(digest)
                if collision:
                    self.log_line.emit(
                        f"Коллизия MD5 {Path(job.dest).name} ({digest[:8]}…), попытка {attempt + 1}"
                    )
                    Path(job.dest).unlink(missing_ok=True)
                    params.pad_bytes = params.pad_bytes + 41 * attempt
                    params.creation_offset_hours += 0.73 * attempt
                    continue
                self.log_line.emit(f"Готово {Path(job.dest).name}  MD5 {digest}")
                self.job_finished.emit(job.item_id, job.copy_index, job.dest, digest)
                self._mark_item(job.item_id)
                return
            except JobCancelled:
                self.job_failed.emit(job.item_id, job.copy_index, "Остановлено")
                self._mark_item(job.item_id)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                self.log_line.emit(f"Сбой {Path(job.dest).name}: {last_error}")
                Path(job.dest).unlink(missing_ok=True)
                params.pad_bytes += 17
        self.job_failed.emit(job.item_id, job.copy_index, last_error or "ошибка")
        self._mark_item(job.item_id)

    def _mark_item(self, item_id: str) -> None:
        with self._lock:
            left = self._pending.get(item_id, 1) - 1
            self._pending[item_id] = left
            done = left <= 0
        if done:
            self.item_finished.emit(item_id)
