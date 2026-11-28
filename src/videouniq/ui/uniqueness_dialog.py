"""Modal uniqueness report: original vs copies, real ffprobe + MD5."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from videouniq.core.auditor import (
    AuditReport,
    deep_audit,
    format_text_report,
    load_report,
    quick_audit,
    save_report,
)
from videouniq.ui.file_card import open_path


class _Bridge(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn, bridge: _Bridge) -> None:
        super().__init__()
        self.fn = fn
        self.bridge = bridge

    def run(self) -> None:
        try:
            self.bridge.done.emit(self.fn())
        except Exception as exc:  # noqa: BLE001
            self.bridge.failed.emit(str(exc))


class UniquenessDialog(QDialog):
    def __init__(self, source: str, output_dir: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("UniquenessDialog")
        self.setWindowTitle("Отчёт уникальности")
        self.resize(820, 460)
        self.source = source
        self.output_dir = output_dir
        self.report: AuditReport | None = load_report(output_dir)
        self._bridge = _Bridge(self)
        self._bridge.done.connect(self._on_ready)
        self._bridge.failed.connect(self._on_fail)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        self.verdict = QLabel("Сбор MD5 и ffprobe…")
        self.verdict.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(self.verdict)
        self.sub = QLabel(Path(output_dir).name)
        self.sub.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self.sub.setWordWrap(True)
        root.addWidget(self.sub)

        self.table = QTableWidget(0, 1)
        self.table.setObjectName("UniquenessTable")
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.checks = QLabel("")
        self.checks.setStyleSheet("color: #9CA3AF; font-size: 12px;")
        self.checks.setWordWrap(True)
        root.addWidget(self.checks)

        row = QHBoxLayout()
        self.copy_btn = QPushButton("Скопировать отчёт текстом")
        self.copy_btn.setObjectName("GhostButton")
        self.copy_btn.clicked.connect(self._copy_text)
        self.folder_btn = QPushButton("Открыть папку")
        self.folder_btn.setObjectName("GhostButton")
        self.folder_btn.clicked.connect(lambda: open_path(self.output_dir))
        self.deep_btn = QPushButton("Глубокий анализ")
        self.deep_btn.setObjectName("GhostButton")
        self.deep_btn.clicked.connect(self._run_deep)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.copy_btn)
        row.addWidget(self.folder_btn)
        row.addWidget(self.deep_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)

        if self.report and self.report.files:
            self._render(self.report)
            if self.report.elapsed_ms > 50:
                # Cached JSON — still refresh in background so hashes match disk.
                self._kick(lambda: quick_audit(self.source, self.output_dir))
        else:
            self._kick(lambda: quick_audit(self.source, self.output_dir))

    def _kick(self, fn) -> None:
        self.deep_btn.setEnabled(False)
        QThreadPool.globalInstance().start(_Task(fn, self._bridge))

    def _on_ready(self, report: object) -> None:
        if not isinstance(report, AuditReport):
            return
        self.report = report
        try:
            save_report(report)
        except OSError:
            pass
        self._render(report)
        self.deep_btn.setEnabled(True)

    def _on_fail(self, message: str) -> None:
        self.verdict.setText("Не удалось собрать отчёт")
        self.verdict.setStyleSheet("font-size: 16px; font-weight: 600; color: #EF4444;")
        self.sub.setText(message[:240])
        self.deep_btn.setEnabled(True)

    def _render(self, report: AuditReport) -> None:
        color = {
            "unique": "#10B981",
            "collision": "#EF4444",
            "warn": "#F59E0B",
            "incomplete": "#9CA3AF",
        }.get(report.verdict, "#F3F4F6")
        self.verdict.setText(report.verdict_label)
        self.verdict.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {color};")
        self.sub.setText(
            f"{Path(report.source).name}  →  {report.output_dir}   ·   {report.elapsed_ms:.0f} мс"
        )
        headers = ["Поле"]
        for row in report.files:
            if row.role == "original":
                headers.append("Оригинал")
            elif row.role == "master":
                headers.append("master")
            else:
                headers.append(f"Копия {row.index}")
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        rows = [
            ("MD5", [f.md58 for f in report.files]),
            ("Длительность", [f.duration_label for f in report.files]),
            ("FPS", [f.fps_label for f in report.files]),
            ("Устройство", [f.device or "—" for f in report.files]),
            ("Вес", [f.size_label for f in report.files]),
        ]
        if report.deep:
            ham = [
                "порог >30"
                if f.role == "original"
                else str(report.deep.get("hamming_vs_original_mean", "—"))
                if f.role == "copy"
                else "—"
                for f in report.files
            ]
            ssim = [
                "качество ≥0.95"
                if f.role == "original"
                else str(report.deep.get("ssim_vs_original_mean", "—"))
                if f.role == "copy"
                else "—"
                for f in report.files
            ]
            rows.append(("aHash Hamming", ham))
            rows.append(("SSIM", ssim))
        self.table.setRowCount(len(rows))
        for r, (label, values) in enumerate(rows):
            item = QTableWidgetItem(label)
            self.table.setItem(r, 0, item)
            for c, value in enumerate(values, start=1):
                cell = QTableWidgetItem(str(value))
                cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(r, c, cell)
        bits = []
        for chk in report.checks:
            mark = "✓" if chk.ok else "—"
            bits.append(f"{mark} {chk.label}")
        if report.deep:
            vis = "✓ визуал" if report.deep.get("visual_unique") else "· визуал микро"
            q = "✓ SSIM" if report.deep.get("quality_ok") else "· SSIM"
            bits.append(f"{vis}  {q}")
        self.checks.setText("   ".join(bits) if bits else "Нет данных для сравнения")

    def _copy_text(self) -> None:
        if self.report is None:
            return
        text = format_text_report(self.report)
        QGuiApplication.clipboard().setText(text)
        self.checks.setText("Отчёт скопирован в буфер обмена")

    def _run_deep(self) -> None:
        if self.report is None:
            return
        self.deep_btn.setEnabled(False)
        self.sub.setText("Глубокий анализ: aHash 5 кадров + SSIM…")
        report = self.report

        def _work() -> AuditReport:
            return deep_audit(report)

        self._kick(_work)
