import logging
import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QFileDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import BASE_FONT_SIZE, INSTALLED_DIR, SUPPORTED_EXTENSIONS
from .logging_setup import setup_logging
from .operations import cleanup_internal_duplicates, delete_records, merge_records, sync_records
from .platforms import current_platform_label
from .scanner import diff_records, scan_storage
from .storage import BaseStorage

LOGGER = logging.getLogger(__name__)


APP_QSS = """
QMainWindow, QWidget {
    background: #f4f7fb;
    color: #1f2937;
    font-size: 20px;
}
QGroupBox {
    border: 2px solid #c9d7ef;
    border-radius: 8px;
    margin-top: 18px;
    padding: 18px;
    background: #ffffff;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #2854a3;
}
QLineEdit, QTextEdit, QComboBox {
    background: #ffffff;
    border: 2px solid #bed0ea;
    border-radius: 7px;
    padding: 8px 10px;
    selection-background-color: #4f8cff;
}
QLineEdit:focus, QTextEdit:focus {
    border-color: #3b82f6;
}
QPushButton {
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 7px;
    padding: 10px 18px;
    min-height: 36px;
    font-weight: 700;
}
QPushButton:hover {
    background: #1d4ed8;
}
QPushButton:pressed {
    background: #1e40af;
}
QPushButton:disabled {
    background: #9aa9bd;
    color: #edf2f7;
}
QPushButton#DangerButton {
    background: #dc2626;
}
QPushButton#DangerButton:hover {
    background: #b91c1c;
}
QPushButton#SuccessButton {
    background: #059669;
}
QPushButton#SuccessButton:hover {
    background: #047857;
}
QPushButton#SoftButton {
    background: #e0ecff;
    color: #1e3a8a;
}
QPushButton#SoftButton:hover {
    background: #c7dcff;
}
QTabWidget::pane {
    border: 2px solid #c9d7ef;
    border-radius: 8px;
    background: #ffffff;
}
QTabBar::tab {
    background: #dbeafe;
    color: #1e3a8a;
    padding: 12px 22px;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    margin-right: 4px;
    font-weight: 700;
}
QTabBar::tab:selected {
    background: #2563eb;
    color: #ffffff;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #eef5ff;
    gridline-color: #d6e2f3;
    border: 2px solid #c9d7ef;
    border-radius: 7px;
}
QHeaderView::section {
    background: #173b77;
    color: white;
    padding: 8px;
    border: none;
    font-weight: 700;
}
QRadioButton, QCheckBox {
    spacing: 10px;
    padding: 4px;
}
QLabel#TitleLabel {
    color: #173b77;
    font-size: 26px;
    font-weight: 800;
}
QLabel#StatusLabel {
    color: #375985;
    background: #e9f1ff;
    border-radius: 7px;
    padding: 8px 12px;
}
"""


class PathRow(QWidget):
    def __init__(self, label: str, allow_browse: bool = True):
        super().__init__()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Local, mounted Samba, or adb:/sdcard/Music")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(label))
        layout.addWidget(self.edit, 1)
        if allow_browse:
            browse = QPushButton("Browse")
            browse.setObjectName("SoftButton")
            browse.clicked.connect(self.browse_folder)
            layout.addWidget(browse)

    def browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder:
            self.edit.setText(folder)

    def text(self) -> str:
        return self.edit.text().strip()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Audio Filter Tools")
        self.resize(1500, 950)

        self.a_storage: Optional[BaseStorage] = None
        self.b_storage: Optional[BaseStorage] = None
        self.a_only = []
        self.b_only = []
        self.merge_storages: Dict[str, BaseStorage] = {}
        self.merge_records = []

        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setSpacing(14)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"Audio Filter Tools | Platform: {current_platform_label()}")
        title.setObjectName("TitleLabel")
        header_layout.addWidget(title, 1)
        help_button = QPushButton("Help")
        help_button.setObjectName("SoftButton")
        help_button.clicked.connect(self.show_help)
        header_layout.addWidget(help_button)
        main_layout.addWidget(header)

        self.status = QLabel("Ready")
        self.status.setObjectName("StatusLabel")
        main_layout.addWidget(self.status)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sync_tab(), "Mode A - Song Sync")
        self.tabs.addTab(self._build_merge_tab(), "Mode B - Merge")
        main_layout.addWidget(self.tabs, 1)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(110)
        main_layout.addWidget(self.log_view)

    def _build_sync_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        box = QGroupBox("Folders")
        form = QVBoxLayout(box)
        self.path_a = PathRow("Folder A")
        self.path_b = PathRow("Folder B")
        form.addWidget(self.path_a)
        form.addWidget(self.path_b)
        scan = QPushButton("Scan Differences")
        scan.clicked.connect(self.scan_diff)
        form.addWidget(scan)
        splitter.addWidget(box)

        actions = QGroupBox("Action")
        action_layout = QHBoxLayout(actions)
        self.sync_a_to_b = QRadioButton("Sync A-only to B")
        self.sync_b_to_a = QRadioButton("Sync B-only to A")
        self.delete_a = QRadioButton("Delete A-only")
        self.delete_b = QRadioButton("Delete B-only")
        self.sync_a_to_b.setChecked(True)
        for btn in [self.sync_a_to_b, self.sync_b_to_a, self.delete_a, self.delete_b]:
            action_layout.addWidget(btn)
        run = QPushButton("Run Selected Action")
        run.setObjectName("SuccessButton")
        run.clicked.connect(self.run_sync_action)
        action_layout.addWidget(run)
        splitter.addWidget(actions)

        self.diff_table = QTableWidget(0, 6)
        self.diff_table.setHorizontalHeaderLabels(["Side", "Artist Key", "Song Key", "File", "Deepest Folder", "Relative Path"])
        self.configure_table(self.diff_table)
        self.diff_table.setAlternatingRowColors(True)
        splitter.addWidget(self.diff_table)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([180, 120, 520])
        return page

    def _build_merge_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, 1)

        box = QGroupBox("Source folders, up to five")
        grid = QGridLayout(box)
        self.merge_source_paths: List[PathRow] = []
        for i in range(5):
            row = PathRow(f"Source Folder {i + 1}")
            row.edit.textChanged.connect(self.refresh_merge_target_options)
            self.merge_source_paths.append(row)
            grid.addWidget(row, i, 0)

        target_row = QWidget()
        target_layout = QHBoxLayout(target_row)
        target_layout.setContentsMargins(0, 0, 0, 0)
        target_layout.addWidget(QLabel("Merge Target"))
        self.merge_target_combo = QComboBox()
        target_layout.addWidget(self.merge_target_combo, 1)
        grid.addWidget(target_row, 5, 0)
        self.refresh_merge_target_options()

        start_merge = QPushButton("Start Merge")
        start_merge.setObjectName("SuccessButton")
        start_merge.clicked.connect(self.run_merge)
        grid.addWidget(start_merge, 6, 0)
        splitter.addWidget(box)

        log_panel = QWidget()
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.addWidget(QLabel("Merge log"))
        self.merge_log = QTextEdit()
        self.merge_log.setReadOnly(True)
        self.merge_log.setPlaceholderText("Merge progress will appear here.")
        log_layout.addWidget(self.merge_log, 1)
        splitter.addWidget(log_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([330, 620])
        return page

    def apply_screen_size(self) -> None:
        screen = QApplication.primaryScreen()
        if not screen:
            self.resize(1500, 950)
            return
        rect = screen.availableGeometry()
        width = max(1200, int(rect.width() * 0.86))
        height = max(780, int(rect.height() * 0.86))
        self.resize(min(width, rect.width()), min(height, rect.height()))
        self.move(
            rect.x() + max(0, (rect.width() - self.width()) // 2),
            rect.y() + max(0, (rect.height() - self.height()) // 2),
        )

    def configure_table(self, table: QTableWidget) -> None:
        table.setMinimumHeight(260)
        table.verticalHeader().setDefaultSectionSize(42)
        table.verticalHeader().setMinimumSectionSize(38)
        table.horizontalHeader().setMinimumSectionSize(120)
        table.horizontalHeader().setDefaultSectionSize(190)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        table.horizontalHeader().setStretchLastSection(False)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    def scan_diff(self) -> None:
        try:
            a_uri = self.path_a.text()
            b_uri = self.path_b.text()
            LOGGER.info("Scan Differences clicked: A=%s, B=%s", a_uri, b_uri)
            self.diff_table.setRowCount(0)

            self.set_status(f"Scanning Folder A: {a_uri}")
            self.a_storage, a_records = scan_storage(a_uri, self.set_status)
            self.set_status(f"Folder A scan complete: {len(a_records)} audio files")

            self.set_status(f"Scanning Folder B: {b_uri}")
            self.b_storage, b_records = scan_storage(b_uri, self.set_status)
            self.set_status(f"Folder B scan complete: {len(b_records)} audio files")

            self.set_status("Comparing song keys...")
            self.a_only, self.b_only = diff_records(a_records, b_records)
            for side, records in [("A only", self.a_only), ("B only", self.b_only)]:
                for record in records:
                    self._append_diff_row(side, record)
            self.set_status(f"Scan complete: {len(self.a_only)} A-only, {len(self.b_only)} B-only")
        except Exception as exc:
            self.show_error("Scan failed", exc)

    def _append_diff_row(self, side: str, record) -> None:
        row = self.diff_table.rowCount()
        self.diff_table.insertRow(row)
        values = [side, record.key[0], record.key[1], record.file_name, record.deepest_folder, record.relative_path]
        for col, value in enumerate(values):
            self.diff_table.setItem(row, col, QTableWidgetItem(value))

    def run_sync_action(self) -> None:
        if not self.a_storage or not self.b_storage:
            QMessageBox.warning(self, "No scan", "Scan folders first.")
            return
        try:
            if self.sync_a_to_b.isChecked():
                if self.confirm(f"Sync {len(self.a_only)} A-only files to B?"):
                    count = sync_records(self.a_only, self.a_storage, self.b_storage)
                    self.set_status(f"Synced {count} files from A to B")
            elif self.sync_b_to_a.isChecked():
                if self.confirm(f"Sync {len(self.b_only)} B-only files to A?"):
                    count = sync_records(self.b_only, self.b_storage, self.a_storage)
                    self.set_status(f"Synced {count} files from B to A")
            elif self.delete_a.isChecked():
                if self.confirm(f"Delete {len(self.a_only)} A-only files? This cannot be undone."):
                    count = delete_records(self.a_only, self.a_storage)
                    self.set_status(f"Deleted {count} files from A")
            elif self.delete_b.isChecked():
                if self.confirm(f"Delete {len(self.b_only)} B-only files? This cannot be undone."):
                    count = delete_records(self.b_only, self.b_storage)
                    self.set_status(f"Deleted {count} files from B")
        except Exception as exc:
            self.show_error("Action failed", exc)

    def refresh_merge_target_options(self) -> None:
        if not hasattr(self, "merge_target_combo"):
            return
        current_data = self.merge_target_combo.currentData()
        self.merge_target_combo.blockSignals(True)
        self.merge_target_combo.clear()
        for idx, row in enumerate(self.merge_source_paths, start=1):
            uri = row.text()
            label = f"Source Folder {idx}"
            if uri:
                label = f"{label}: {uri}"
            else:
                label = f"{label}: empty"
            self.merge_target_combo.addItem(label, idx - 1)
        if current_data is not None:
            restored = self.merge_target_combo.findData(current_data)
            if restored >= 0:
                self.merge_target_combo.setCurrentIndex(restored)
        self.merge_target_combo.blockSignals(False)

    def selected_merge_target_uri(self) -> str:
        index = self.merge_target_combo.currentData()
        if index is None:
            index = 0
        return self.merge_source_paths[int(index)].text()

    def append_merge_log(self, message: str) -> None:
        self.merge_log.append(message)
        QApplication.processEvents()

    def run_merge(self) -> None:
        self.refresh_merge_target_options()
        source_uris = []
        for row in self.merge_source_paths:
            uri = row.text()
            if uri and uri not in source_uris:
                source_uris.append(uri)

        target_uri = self.selected_merge_target_uri()
        if not source_uris:
            QMessageBox.warning(self, "No sources", "Select at least one source folder.")
            return
        if not target_uri:
            QMessageBox.warning(self, "No target", "Select one non-empty source folder as the merge target.")
            return

        try:
            self.merge_log.clear()
            if len(source_uris) == 1:
                self.run_internal_cleanup(source_uris[0])
                return

            self.append_merge_log(f"Target: {target_uri}")
            self.append_merge_log("Scanning merge target...")
            self.set_status("Scanning merge target and source folders...")
            target_storage, target_records = scan_storage(target_uri)
            existing_keys = {record.key for record in target_records if record.key[1]}
            self.append_merge_log(f"Target already has {len(target_records)} audio files, {len(existing_keys)} song keys.")

            all_source_records = []
            self.merge_storages.clear()
            for uri in source_uris:
                if uri == target_uri:
                    self.append_merge_log(f"Skip target as source: {uri}")
                    continue
                self.append_merge_log(f"Scanning source: {uri}")
                storage, records = scan_storage(uri)
                self.merge_storages[uri] = storage
                all_source_records.extend(records)
                self.append_merge_log(f"Source found {len(records)} audio files: {uri}")

            if not all_source_records:
                QMessageBox.warning(self, "No sources", "No source files to merge after excluding the target folder.")
                return

            if not self.confirm(
                f"Merge {len(all_source_records)} source files into the selected target? Existing duplicates will be skipped."
            ):
                self.append_merge_log("Merge cancelled.")
                return

            def on_merge_progress(action: str, record) -> None:
                if action == "merged":
                    self.append_merge_log(f"MERGED | {record.root_uri} | {record.relative_path}")
                else:
                    self.append_merge_log(f"SKIPPED duplicate | {record.root_uri} | {record.relative_path}")

            self.append_merge_log("Merging songs...")
            self.set_status("Merging songs...")
            copied, skipped = merge_records(
                all_source_records,
                self.merge_storages,
                target_storage,
                existing_keys,
                on_merge_progress,
            )

            self.merge_records = all_source_records
            self.append_merge_log(f"Done: {copied} merged, {len(skipped)} skipped duplicates.")
            self.set_status(f"Merge complete: {copied} merged, {len(skipped)} skipped duplicates")
        except Exception as exc:
            self.show_error("Merge failed", exc)

    def run_internal_cleanup(self, uri: str) -> None:
        self.merge_log.clear()
        self.append_merge_log(f"Internal cleanup target: {uri}")
        self.append_merge_log("Scanning folder...")
        self.set_status("Scanning folder for internal cleanup...")
        storage, records = scan_storage(uri)
        self.append_merge_log(f"Found {len(records)} audio files.")
        if not records:
            QMessageBox.warning(self, "No audio files", "No audio files found in the selected folder.")
            return
        if not self.confirm(
            "Only one folder is selected. Clean internal duplicates now? This will delete duplicate files and rename numbered files."
        ):
            self.append_merge_log("Internal cleanup cancelled.")
            return
        self.append_merge_log("Cleaning internal duplicates...")
        self.set_status("Cleaning internal duplicates...")
        deleted, renamed, skipped_renames = cleanup_internal_duplicates(
            records,
            storage,
            self.append_merge_log,
        )
        self.append_merge_log(f"Done: {deleted} deleted, {renamed} renamed, {skipped_renames} rename conflicts skipped.")
        self.set_status(f"Internal cleanup complete: {deleted} deleted, {renamed} renamed")

    def show_help(self) -> None:
        help_text = """
Audio Filter Tools Help

General
- Supported paths: local folders, mounted Samba folders, and ADB paths such as adb:/sdcard/Music.
- Supported audio formats: .mp3, .flac, .opus, .aac.
- Duplicate rule: songs are treated as duplicates when the parsed artist and song title are the same.
- Destructive actions ask for confirmation first. Deleted files cannot be restored by this tool.

Mode A - Song Sync
1. Select two music folders in Folder A and Folder B.
2. Click Scan Differences.
3. The table shows A only and B only songs.
4. Choose one action:
   - Sync A-only to B: copy songs that only exist in A into B.
   - Sync B-only to A: copy songs that only exist in B into A.
   - Delete A-only: delete songs that only exist in A.
   - Delete B-only: delete songs that only exist in B.
5. Click Run Selected Action.

Mode B - Merge Multiple Folders
1. Fill two or more Source Folder fields.
2. Pick the Merge Target from the source-folder dropdown. Source Folder 1 is selected by default.
3. Click Start Merge.
4. Files from the other source folders are copied into the target folder.
5. Subfolders are created automatically in the target when needed.
6. If the target already has the same artist + song title, the file is skipped.
7. If the same song appears more than once during the same merge, only the first one is copied.
8. Merge log shows scanning progress, copied files, skipped duplicates, and the final summary.

Mode B - Single Folder Cleanup
1. Fill only one Source Folder field.
2. Click Start Merge. The tool switches to internal cleanup mode.
3. Files with numbered-copy names such as (1), (2), ... (n) are deleted.
4. Duplicate songs inside the folder are deleted, keeping only one copy.
5. When duplicates exist in different formats, .opus is kept first.
6. Leading track numbers such as 01, 02, 03 are removed by renaming. This step does not delete the file.
7. Merge log shows each deleted file, each renamed file, rename conflicts, and the final summary.
""".strip()
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        dialog.resize(980, 760)
        layout = QVBoxLayout(dialog)
        text_box = QTextEdit()
        text_box.setReadOnly(True)
        text_box.setPlainText(help_text)
        layout.addWidget(text_box, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec_()

    def confirm(self, message: str) -> bool:
        return QMessageBox.question(self, "Confirm", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def set_status(self, message: str) -> None:
        LOGGER.info(message)
        self.status.setText(message)
        self.log_view.append(message)
        QApplication.processEvents()

    def show_error(self, title: str, exc: Exception) -> None:
        LOGGER.exception(title)
        self.log_view.append(f"ERROR: {title}: {exc}")
        QMessageBox.critical(self, title, f"{exc}\n\nSee logs/debug.log for details.")


def main() -> int:
    INSTALLED_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging()
    LOGGER.info("Starting Audio Filter Tools")
    app = QApplication(sys.argv)
    app.setFont(QFont("Arial", BASE_FONT_SIZE))
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.show()
    try:
        return app.exec_()
    except Exception:
        LOGGER.error("Unhandled exception:\n%s", traceback.format_exc())
        raise



