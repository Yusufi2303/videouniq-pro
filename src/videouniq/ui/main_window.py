from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QThreadPool, QRunnable, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QWidget,
)

from videouniq import __app_name__, __version__
from videouniq.core.hardware import detect_hardware, encoder_with_quality
from videouniq.core.params import ManualRanges, ModuleFlags, flags_for_preset, ranges_for_preset
from videouniq.core.pipeline import extract_preview, preview_cache_path
from videouniq.core.probe import collect_videos, probe_media
from videouniq.core.randomizer import generate_unique_set, output_folder_name
from videouniq.paths import presets_path, settings_ini_path
from videouniq.queue.models import FileItem, FileStatus
from videouniq.queue.worker import RenderController
from videouniq.ui.file_card import open_path
from videouniq.ui.pages.logs_page import LogsPage
from videouniq.ui.pages.metadata_page import MetadataPage
from videouniq.ui.pages.render_settings import RenderSettingsPage
from videouniq.ui.queue_view import QueueView
from videouniq.ui.right_panel import RightPanel
from videouniq.ui.sidebar import Sidebar
from videouniq.ui.theme import apply_theme


class ProbeBridge(QObject):
    finished = Signal(str, object, str, str)


class ProbeTask(QRunnable):
    def __init__(self, item_id: str, path: str, bridge: ProbeBridge) -> None:
        super().__init__()
        self.item_id = item_id
        self.path = path
        self.bridge = bridge

    def run(self) -> None:
        try:
            info = probe_media(self.path)
            preview = preview_cache_path(self.path)
            if not preview.is_file():
                extract_preview(self.path, preview)
            self.bridge.finished.emit(self.item_id, info, str(preview), "")
        except Exception as exc:  # noqa: BLE001
            self.bridge.finished.emit(self.item_id, None, "", str(exc))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(__app_name__)
        self.resize(1100, 720)
        self.setMinimumSize(900, 600)

        self.settings = QSettings(str(settings_ini_path()), QSettings.Format.IniFormat)
        self.items: list[FileItem] = []
        self.pool = QThreadPool.globalInstance()
        self.controller = RenderController(self)
        self.probe_bridge = ProbeBridge(self)
        self.probe_bridge.finished.connect(self._probe_done)
        self._copy_progress: dict[str, dict[int, float]] = {}
        self._dark = True

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        uniq_page = QWidget()
        uniq_split = QSplitter(Qt.Orientation.Horizontal)
        uniq_layout = QHBoxLayout(uniq_page)
        uniq_layout.setContentsMargins(0, 0, 0, 0)
        uniq_layout.setSpacing(0)
        self.queue = QueueView()
        self.right = RightPanel()
        uniq_split.addWidget(self.queue)
        uniq_split.addWidget(self.right)
        uniq_split.setStretchFactor(0, 1)
        uniq_split.setStretchFactor(1, 0)
        uniq_split.setSizes([560, 320])
        uniq_layout.addWidget(uniq_split)

        self.render_page = RenderSettingsPage()
        self.meta_page = MetadataPage()
        self.logs_page = LogsPage()

        self.stack.addWidget(uniq_page)
        self.stack.addWidget(self.render_page)
        self.stack.addWidget(self.meta_page)
        self.stack.addWidget(self.logs_page)
        layout.addWidget(self.stack, 1)

        self._wire()
        self._restore()
        self._detect_hw()
        self.logs_page.append(f"{__app_name__} v{__version__} запущен")

        file_menu = self.menuBar().addMenu("Файл")
        act_open = QAction("Открыть видео…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self._browse_files)
        file_menu.addAction(act_open)
        act_folder = QAction("Открыть папку…", self)
        act_folder.triggered.connect(self._browse_folder)
        file_menu.addAction(act_folder)

    def _wire(self) -> None:
        self.sidebar.page_changed.connect(self._on_page)
        self.queue.files_dropped.connect(self.add_paths)
        self.queue.browse_requested.connect(self._browse_files)
        self.queue.remove_requested.connect(self.remove_item)
        self.queue.open_requested.connect(self._open_item_folder)
        self.right.start_requested.connect(self.start_render)
        self.right.stop_requested.connect(self.controller.stop)
        self.right.save_preset_requested.connect(self._save_custom_preset)
        self.render_page.theme_changed.connect(self._set_dark)
        self.controller.job_progress.connect(self._on_job_progress)
        self.controller.job_finished.connect(self._on_job_finished)
        self.controller.job_failed.connect(self._on_job_failed)
        self.controller.item_finished.connect(self._on_item_finished)
        self.controller.log_line.connect(self.logs_page.append)
        self.controller.all_finished.connect(self._on_all_finished)
        self.controller.running_changed.connect(self.right.set_running)

    def _on_page(self, key: str) -> None:
        self.stack.setCurrentIndex({"uniquize": 0, "render": 1, "meta": 2, "logs": 3}.get(key, 0))

    def _detect_hw(self) -> None:
        choice = detect_hardware(self.render_page.encoder_key())
        gpu = choice.gpu_name or "не найден"
        text = f"Энкодер: {choice.label}\nGPU: {gpu}"
        self.sidebar.set_hardware(f"GPU: {gpu}\n{choice.label}")
        self.render_page.set_hardware_info(text)
        self.logs_page.append(f"Аппаратный энкодер: {choice.label}")

    def _restore(self) -> None:
        threads = int(self.settings.value("threads", 2))
        idx = 0 if threads != 4 else 1
        self.render_page.threads.setCurrentIndex(idx)
        enc = str(self.settings.value("encoder", "auto"))
        for i in range(self.render_page.encoder.count()):
            if self.render_page.encoder.itemData(i) == enc:
                self.render_page.encoder.setCurrentIndex(i)
                break
        out = str(self.settings.value("output_dir", ""))
        if out:
            self.right.set_output_dir(out)
        dark = str(self.settings.value("dark", "1")) != "0"
        self.render_page.dark_toggle.setChecked(dark, emit=False)
        self._dark = dark

    def _set_dark(self, dark: bool) -> None:
        self._dark = bool(dark)
        app = QApplication.instance()
        if app:
            apply_theme(app, dark=self._dark)
        self.settings.setValue("dark", "1" if dark else "0")

    def _browse_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Выберите видео",
            str(Path.home()),
            "Видео (*.mp4 *.mov *.avi *.mkv *.webm);;Все файлы (*)",
        )
        if files:
            self.add_paths(files)

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Папка с видео")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: list[str]) -> None:
        videos = collect_videos(paths)
        if not videos:
            QMessageBox.information(self, __app_name__, "Подходящие видео не найдены (.mp4 .mov .avi .mkv .webm).")
            return
        existing = {it.path for it in self.items}
        added = 0
        for path in videos:
            key = str(path.resolve())
            if key in existing:
                continue
            item = FileItem(path=key)
            self.items.append(item)
            added += 1
            self.pool.start(ProbeTask(item.item_id, key, self.probe_bridge))
        if added:
            self.logs_page.append(f"Добавлено файлов: {added}")
            self._refresh_queue()

    @Slot(str, object, str, str)
    def _probe_done(self, item_id: str, info, preview: str, error: str) -> None:
        item = self._find(item_id)
        if item is None:
            return
        item.info = info
        item.preview_path = preview
        item.error = error
        if error:
            item.status = FileStatus.ERROR
            self.logs_page.append(f"Ошибка анализа {Path(item.path).name}: {error}")
        self._refresh_queue()

    def remove_item(self, item_id: str) -> None:
        self.items = [it for it in self.items if it.item_id != item_id]
        self._refresh_queue()

    def _open_item_folder(self, item_id: str) -> None:
        item = self._find(item_id)
        if item and item.output_dir:
            open_path(item.output_dir)

    def _find(self, item_id: str) -> FileItem | None:
        return next((it for it in self.items if it.item_id == item_id), None)

    def _refresh_queue(self) -> None:
        self.queue.set_items(list(self.items))
        self.right.set_file_count(len(self.items))

    def start_render(self) -> None:
        ready = [it for it in self.items if it.info is not None]
        if not ready:
            QMessageBox.warning(self, __app_name__, "Нет готовых файлов в очереди.")
            return
        copies = self.right.copy_count()
        preset = self.right.preset()
        flags: ModuleFlags = self.right.flags()
        ranges: ManualRanges = self.right.ranges() if preset == "manual" else ranges_for_preset(preset)
        if preset != "manual":
            flags = flags_for_preset(preset)

        out_override = self.right.output_dir()
        if out_override:
            root = Path(out_override)
        else:
            first = Path(ready[0].path).parent
            root = first / output_folder_name(datetime.now().astimezone())
        root.mkdir(parents=True, exist_ok=True)
        self.right.set_output_dir(str(root))
        self.settings.setValue("output_dir", str(root))
        self.settings.setValue("threads", self.render_page.thread_count())
        self.settings.setValue("encoder", self.render_page.encoder_key())

        preference = self.render_page.encoder_key()
        detected = detect_hardware(preference)
        encoder = encoder_with_quality(
            detected,
            crf=self.render_page.crf.value(),
            nvenc_cq=self.render_page.cq.value(),
            cpu_preset=str(self.render_page.cpu_preset.currentData()),
            nvenc_preset=str(self.render_page.nv_preset.currentData()),
        )
        self.logs_page.append(f"Выход: {root}")
        self.logs_page.append(f"Пресет: {preset}, копий: {copies}, энкодер: {encoder.label}")

        params_map = {}
        self._copy_progress = {}
        for item in ready:
            assert item.info is not None
            params_map[item.item_id] = generate_unique_set(
                item.info,
                copies,
                preset,
                flags=flags,
                ranges=ranges,
                enabled_devices=self.meta_page.enabled_devices(),
            )
            item.status = FileStatus.RENDERING
            item.progress = 0.0
            item.copies_done = 0
            item.copies_total = copies
            item.error = ""
            item.message = "Запуск…"
            self._copy_progress[item.item_id] = {}
        self._refresh_queue()
        n = self.controller.start(
            ready,
            params_map,
            root,
            encoder,
            parallel=self.render_page.thread_count(),
        )
        if n == 0:
            QMessageBox.warning(self, __app_name__, "Не удалось поставить задачи в очередь.")

    def _on_job_progress(self, item_id: str, copy_index: int, frac: float, stage: str) -> None:
        item = self._find(item_id)
        if item is None:
            return
        bucket = self._copy_progress.setdefault(item_id, {})
        bucket[copy_index] = frac
        total = item.copies_total or 1
        item.progress = sum(bucket.values()) / total
        item.status = FileStatus.RENDERING
        item.message = f"Копия {copy_index}/{total} · {stage}"
        self.queue.update_item(item)

    def _on_job_finished(self, item_id: str, copy_index: int, dest: str, digest: str) -> None:
        item = self._find(item_id)
        if item is None:
            return
        item.copies_done += 1
        item.message = f"Готово {item.copies_done}/{item.copies_total}"
        self.queue.update_item(item)
        self.logs_page.append(f"{Path(dest).name}  {digest}")

    def _on_job_failed(self, item_id: str, copy_index: int, error: str) -> None:
        item = self._find(item_id)
        if item is None:
            return
        if error != "Остановлено":
            item.error = error
        item.message = error
        self.queue.update_item(item)

    def _on_item_finished(self, item_id: str) -> None:
        item = self._find(item_id)
        if item is None:
            return
        if item.copies_done >= item.copies_total and not item.error:
            item.status = FileStatus.DONE
            item.progress = 1.0
            item.message = "Готово"
        elif self.controller._stop.is_set():
            item.status = FileStatus.CANCELLED
        elif item.error:
            item.status = FileStatus.ERROR
        self.queue.update_item(item)

    def _on_all_finished(self, cancelled: bool) -> None:
        if cancelled:
            for item in self.items:
                if item.status == FileStatus.RENDERING:
                    item.status = FileStatus.CANCELLED
            self.logs_page.append("Рендер остановлен")
        else:
            self.logs_page.append("Все задачи завершены")
        self._refresh_queue()

    def _save_custom_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Пресет", "Имя пресета:")
        if not ok or not name.strip():
            return
        payload = {
            "name": name.strip(),
            "flags": self.right.flags().to_dict(),
            "ranges": self.right.ranges().to_dict(),
        }
        path = presets_path()
        data: list = []
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = []
        data = [p for p in data if p.get("name") != payload["name"]]
        data.append(payload)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.logs_page.append(f"Пресет сохранён: {payload['name']}")
        QMessageBox.information(self, __app_name__, f"Сохранено: {payload['name']}")

    def grab_to(self, path: str | Path) -> None:
        pix = self.grab()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(path), "PNG")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.controller.running:
            self.controller.stop()
        self.settings.sync()
        super().closeEvent(event)
