from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThread, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAction,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QSpinBox,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .config import load_ui_config
from .models import (
    AudioFile,
    OPUS_AUDIO_EXTENSIONS,
    SOURCE_DELETE_EXTENSIONS,
    TARGET_SAMPLE_RATES,
    target_bitrate_auto,
    target_sample_rate_with_limit,
)
from .platform_utils import system_name, worker_count
from .workers import ConvertWorker, DeleteWorker, ScanWorker


HEADERS = [
    "File",
    "Format",
    "Original Hz",
    "Original kbps",
    "Target Hz",
    "Target kbps",
    "Output",
    "Status",
    "Message",
]


APP_STYLE_TEMPLATE = """
QMainWindow, QWidget {
    background-color: #f3f7ff;
    color: #1f2937;
    font-size: __FONT_SIZE__pt;
}

QToolBar {
    background-color: #dbeafe;
    border-bottom: 1px solid #93c5fd;
    spacing: 8px;
}

QLabel, QCheckBox, QComboBox, QSpinBox {
    color: #1e3a8a;
}

QPushButton {
    background-color: #2563eb;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 18px;
}

QPushButton:hover {
    background-color: #1d4ed8;
}

QPushButton:pressed {
    background-color: #1e40af;
}

QPushButton:disabled {
    background-color: #94a3b8;
    color: #e2e8f0;
}

QComboBox, QSpinBox, QTextEdit {
    background-color: #ffffff;
    border: 1px solid #93c5fd;
    border-radius: 6px;
    padding: 6px;
}

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #eff6ff;
    gridline-color: #bfdbfe;
    selection-background-color: #bfdbfe;
    selection-color: #111827;
}

QHeaderView::section {
    background-color: #1e40af;
    color: white;
    padding: 8px;
    border: 1px solid #1d4ed8;
}

QProgressBar {
    background-color: #dbeafe;
    border: 1px solid #93c5fd;
    border-radius: 8px;
    color: #1e3a8a;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #22c55e;
    border-radius: 8px;
}

QStatusBar {
    background-color: #dbeafe;
    color: #1e3a8a;
}
"""


def build_app_style(font_size: int) -> str:
    return APP_STYLE_TEMPLATE.replace("__FONT_SIZE__", str(font_size))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Resampler Qt")
        self.resize(1360, 820)
        self.ui_config = load_ui_config()
        self.setFont(QFont("Segoe UI", self.ui_config.font_size))
        self.setStyleSheet(build_app_style(self.ui_config.font_size))
        self.folder: Path | None = None
        self.files: list[AudioFile] = []
        self.file_index: dict[Path, int] = {}
        self.thread: QThread | None = None
        self.worker = None

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setDefaultSectionSize(self.ui_config.table_row_height)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(self.ui_config.log_max_height)
        self.log.setFont(QFont("Consolas", self.ui_config.log_font_size))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)

        self.sample_rate_combo = QComboBox()
        self.sample_rate_combo.addItem("Auto mapping", None)
        for value in TARGET_SAMPLE_RATES:
            self.sample_rate_combo.addItem(f"{value} Hz", value)
        self.sample_rate_combo.currentIndexChanged.connect(self.apply_target_settings)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        self.workers_spin.setValue(worker_count())

        self.overwrite_check = QCheckBox("Overwrite existing opus")

        self.open_button = QPushButton("Open Folder")
        self.scan_button = QPushButton("Scan")
        self.convert_button = QPushButton("Convert to Opus")
        self.delete_button = QPushButton("Delete FLAC/MP3 with Opus")

        self.open_button.clicked.connect(self.choose_folder)
        self.scan_button.clicked.connect(self.scan_folder)
        self.convert_button.clicked.connect(self.convert_files)
        self.delete_button.clicked.connect(self.delete_sources)

        controls = QHBoxLayout()
        controls.addWidget(self.open_button)
        controls.addWidget(self.scan_button)
        controls.addWidget(QLabel("Max sample rate:"))
        controls.addWidget(self.sample_rate_combo)
        controls.addWidget(QLabel("Workers:"))
        controls.addWidget(self.workers_spin)
        controls.addWidget(self.overwrite_check)
        controls.addStretch(1)
        controls.addWidget(self.convert_button)
        controls.addWidget(self.delete_button)

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        layout.addWidget(self.log)
        self.setCentralWidget(root)

        self.setStatusBar(QStatusBar())
        self.set_busy(False)
        self._create_menu()
        self.append_log(f"System: {system_name()}, default workers: {worker_count()}")

    def _create_menu(self) -> None:
        toolbar = QToolBar("Main")
        self.addToolBar(toolbar)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(QApplication.quit)
        toolbar.addAction(exit_action)

    def append_log(self, text: str) -> None:
        self.log.append(text)
        self.statusBar().showMessage(text, 5000)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.open_button,
            self.scan_button,
            self.convert_button,
            self.delete_button,
            self.sample_rate_combo,
            self.workers_spin,
            self.overwrite_check,
        ):
            widget.setEnabled(not busy)

    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose music folder")
        if not folder:
            return
        self.folder = Path(folder)
        self.append_log(f"Selected folder: {self.folder}")
        self.scan_folder()

    def selected_target_rate(self) -> int | None:
        return self.sample_rate_combo.currentData()

    def is_opus_resample_mode(self) -> bool:
        return bool(self.files) and all(
            audio.source_path.suffix.lower() in OPUS_AUDIO_EXTENSIONS
            for audio in self.files
        )

    def needs_downsample(self, audio: AudioFile) -> bool:
        return (
            audio.sample_rate is not None
            and audio.target_sample_rate is not None
            and audio.sample_rate > audio.target_sample_rate
        )

    def update_conversion_mode(self) -> None:
        self.convert_button.setText(
            "Resample Opus" if self.is_opus_resample_mode() else "Convert to Opus"
        )

    def apply_target_settings(self) -> None:
        target = self.selected_target_rate()
        for audio in self.files:
            audio.target_sample_rate = target_sample_rate_with_limit(audio.sample_rate, target)
            audio.target_bitrate = target_bitrate_auto(
                audio.bitrate_kbps,
                audio.source_path.suffix,
                target_sample_rate_hz=audio.target_sample_rate,
                source_sample_rate_hz=audio.sample_rate,
            )
        self.populate_table()
        self.update_conversion_mode()

    def scan_folder(self) -> None:
        if not self.folder:
            QMessageBox.information(self, "No folder", "Please open a folder first.")
            return
        self.start_worker(
            ScanWorker(self.folder, self.selected_target_rate(), self.workers_spin.value()),
            self.on_scan_finished,
            "Scanning audio files...",
        )

    def convert_files(self) -> None:
        files = [audio for audio in self.files if audio.status != "Probe failed"]
        if not files:
            QMessageBox.information(self, "No files", "No scannable audio files are loaded.")
            return

        start_message = "Converting audio files..."
        if self.is_opus_resample_mode():
            files = [audio for audio in files if self.needs_downsample(audio)]
            if not files:
                QMessageBox.information(
                    self,
                    "No downsample needed",
                    "Choose a max sample rate lower than at least one loaded Opus file.",
                )
                return
            start_message = "Resampling Opus files..."

        self.start_worker(
            ConvertWorker(files, self.workers_spin.value(), self.overwrite_check.isChecked()),
            self.on_convert_finished,
            start_message,
        )

    def delete_sources(self) -> None:
        candidates = [
            audio for audio in self.files
            if audio.source_path.suffix.lower() in SOURCE_DELETE_EXTENSIONS
        ]
        if not candidates:
            QMessageBox.information(self, "No sources", "No FLAC/MP3 files are loaded.")
            return
        answer = QMessageBox.question(
            self,
            "Confirm deletion",
            (
                f"{len(candidates)} FLAC/MP3 files will be checked in the background.\n"
                "Only files with an existing matching opus output will be deleted. Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.start_worker(DeleteWorker(candidates, self.workers_spin.value()), self.on_delete_finished, "Checking and deleting source files...")

    def start_worker(self, worker, finished_slot, start_message: str) -> None:
        try:
            thread_running = self.thread is not None and self.thread.isRunning()
        except RuntimeError:
            thread_running = False
            self.thread = None

        if thread_running:
            QMessageBox.information(self, "Busy", "A background task is still running.")
            return

        self.set_busy(True)
        self.progress.setRange(0, 0)
        self.append_log(start_message)

        thread = QThread(self)
        self.thread = thread
        self.worker = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.on_progress)
        if hasattr(worker, "log"):
            worker.log.connect(self.append_log)
        worker.finished.connect(finished_slot)
        worker.finished.connect(thread.quit)
        worker.failed.connect(self.on_worker_failed)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.on_worker_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.start()


    def on_worker_thread_finished(self) -> None:
        self.worker = None
        self.thread = None
        self.set_busy(False)

    def on_progress(self, done: int, total: int, payload) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(done)
        if isinstance(payload, AudioFile):
            self.update_audio(payload)
            message = f" - {payload.message}" if payload.message else ""
            self.append_log(f"[{done}/{total}] {payload.source_path.name}: {payload.status}{message}")
        else:
            self.append_log(f"[{done}/{total}] {payload}")

    def on_scan_finished(self, files: list[AudioFile]) -> None:
        self.files = files
        self.populate_table()
        self.update_conversion_mode()
        self.progress.setRange(0, max(1, len(files)))
        self.progress.setValue(len(files))
        self.append_log(f"Scan complete: {len(files)} audio files.")
        if self.is_opus_resample_mode():
            self.append_log("Opus resample mode: choose a lower max sample rate, then click Resample Opus.")

    def on_convert_finished(self, results: list[AudioFile]) -> None:
        for audio in results:
            self.update_audio(audio)
        self.populate_table()
        self.append_log("Opus resampling finished." if self.is_opus_resample_mode() else "Conversion finished.")

    def on_delete_finished(self, results: list[AudioFile]) -> None:
        self.append_log(f"Applying delete results to UI: {len(results)} rows")
        deleted_count = 0
        for audio in results:
            self.update_audio(audio)
            if audio.status == "Deleted source":
                deleted_count += 1

        if deleted_count:
            self.files = [audio for audio in self.files if audio.status != "Deleted source"]
            self.file_index = {audio.source_path: row for row, audio in enumerate(self.files)}
            self.append_log(f"Removed deleted source rows from table: {deleted_count}")

        self.populate_table()
        self.append_log("Delete check finished.")

    def on_worker_failed(self, message: str) -> None:
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.append_log(f"Error: {message}")
        QMessageBox.critical(self, "Error", message)


    def closeEvent(self, event) -> None:
        try:
            thread_running = self.thread is not None and self.thread.isRunning()
        except RuntimeError:
            thread_running = False
            self.thread = None

        if thread_running:
            QMessageBox.information(
                self,
                "Task running",
                "A scan, conversion, or delete task is still running. Please wait for it to finish before closing.",
            )
            event.ignore()
            return

        self.append_log("Closing: clearing table and cached scan results.")
        self.set_busy(True)
        self.table.setUpdatesEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(0)
        self.log.clear()
        self.files.clear()
        self.file_index.clear()
        self.worker = None
        self.thread = None
        event.accept()

    def update_audio(self, updated: AudioFile) -> None:
        index = self.file_index.get(updated.source_path)
        if index is not None and 0 <= index < len(self.files):
            self.files[index] = updated
            return
        self.file_index[updated.source_path] = len(self.files)
        self.files.append(updated)

    def populate_table(self) -> None:
        self.table.setUpdatesEnabled(False)
        try:
            self.file_index = {audio.source_path: row for row, audio in enumerate(self.files)}
            self.table.setRowCount(len(self.files))
            for row, audio in enumerate(self.files):
                values = [
                    audio.source_path.name,
                    audio.format_name,
                    str(audio.sample_rate or ""),
                    f"{audio.bitrate_kbps:.0f}" if audio.bitrate_kbps is not None else "",
                    str(audio.target_sample_rate or ""),
                    audio.target_bitrate,
                    str(audio.output_path),
                    audio.status,
                    audio.message,
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if col in {2, 3, 4, 5}:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(row, col, item)
        finally:
            self.table.setUpdatesEnabled(True)


