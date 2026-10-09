"""English PyQt5 interface for the existing music-list generator scripts.

The original scripts remain the single source of the listing behaviour.  This
window calls their public functions and only renames their generated files so
the output type is explicit in the filename.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from extract_musicfiles import generate_filename_list
from recurse_musicfiles import generate_file_list


APP_DIR = Path(__file__).resolve().parent


@contextmanager
def working_directory(directory: Path):
    """Temporarily use the scripts' expected output directory."""
    previous_directory = Path.cwd()
    os.chdir(directory)
    try:
        yield
    finally:
        os.chdir(previous_directory)


class GenerationWorker(QThread):
    """Run the existing generators outside the Qt event loop."""

    completed = pyqtSignal(object, str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        folder: Path,
        output_dir: Path,
        generate_names: bool,
        generate_paths: bool,
    ):
        super().__init__()
        self.folder = folder
        self.output_dir = output_dir
        self.generate_names = generate_names
        self.generate_paths = generate_paths

    def _run_generator(self, generator, suffix: str) -> tuple[Path, str]:
        # Both original scripts use this temporary, date-based output name.
        # Rename it after the function returns, without changing either script.
        date_text = datetime.now().strftime("%Y-%m-%d")
        original_output = self.output_dir / f"{self.folder.name}_{date_text}.txt"
        renamed_output = self.output_dir / f"{self.folder.name}_{suffix}_{date_text}.txt"
        messages = StringIO()

        with working_directory(self.output_dir), redirect_stdout(messages):
            generator(str(self.folder))

        if not original_output.is_file():
            raise RuntimeError(
                "The original generator did not create its expected output file: "
                f"{original_output.name}"
            )

        # The original scripts overwrite their daily output.  Match that
        # convention for the explicit extract/recurse output files as well.
        original_output.replace(renamed_output)
        return renamed_output, messages.getvalue().strip()

    def run(self):
        try:
            created_files: list[Path] = []
            log_lines: list[str] = []

            if self.generate_names:
                output, messages = self._run_generator(
                    generate_filename_list, "extract"
                )
                created_files.append(output)
                log_lines.extend(("File-name list created:", str(output), messages, ""))

            if self.generate_paths:
                output, messages = self._run_generator(generate_file_list, "recurse")
                created_files.append(output)
                log_lines.extend(("Relative-path list created:", str(output), messages, ""))

            self.completed.emit(created_files, "\n".join(log_lines).strip())
        except Exception as error:  # Present unexpected file-system failures in the UI.
            self.failed.emit(str(error))


class MusicFileListWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: GenerationWorker | None = None
        self.setWindowTitle("Music File List Generator")
        self.setMinimumWidth(720)
        self._build_ui()

    def _build_ui(self):
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(14)

        title = QLabel("Music File List Generator")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        description = QLabel(
            "Select a folder, then choose the list format to generate. "
            "All folders are scanned recursively. Choose where to save the output files."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        folder_group = QGroupBox("Source folder")
        folder_layout = QHBoxLayout(folder_group)
        self.folder_field = QLineEdit()
        self.folder_field.setReadOnly(True)
        self.folder_field.setPlaceholderText("Choose the folder to scan")
        self.browse_button = QPushButton("Browse…")
        self.browse_button.clicked.connect(self.choose_folder)
        folder_layout.addWidget(self.folder_field)
        folder_layout.addWidget(self.browse_button)
        layout.addWidget(folder_group)

        output_group = QGroupBox("Output folder")
        output_layout = QHBoxLayout(output_group)
        self.output_folder_field = QLineEdit(str(APP_DIR))
        self.output_folder_field.setReadOnly(True)
        self.output_browse_button = QPushButton("Choose...")
        self.output_browse_button.clicked.connect(self.choose_output_folder)
        output_layout.addWidget(self.output_folder_field)
        output_layout.addWidget(self.output_browse_button)
        layout.addWidget(output_group)

        format_group = QGroupBox("Output format")
        format_layout = QFormLayout(format_group)
        self.extract_checkbox = QCheckBox("File names only (extract)")
        self.extract_checkbox.setChecked(True)
        self.recurse_checkbox = QCheckBox(
            "Relative file paths from the selected folder (recurse)"
        )
        self.recurse_checkbox.setChecked(True)
        format_layout.addRow(self.extract_checkbox)
        format_layout.addRow(self.recurse_checkbox)
        format_note = QLabel(
            "Examples:  song.mp3  /  Album/song.mp3. "
            "Generated names include extract or recurse, for example "
            "Music_extract_2026-08-03.txt."
        )
        format_note.setWordWrap(True)
        format_note.setStyleSheet("color: #555;")
        format_layout.addRow(format_note)
        layout.addWidget(format_group)

        actions = QHBoxLayout()
        self.generate_button = QPushButton("Generate Selected Lists")
        self.generate_button.setDefault(True)
        self.generate_button.clicked.connect(self.generate_lists)
        self.open_output_button = QPushButton("Open Output Folder")
        self.open_output_button.clicked.connect(self.open_output_folder)
        actions.addWidget(self.generate_button)
        actions.addWidget(self.open_output_button)
        actions.addStretch()
        layout.addLayout(actions)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        self.status_label = QLabel("Ready.")
        layout.addWidget(self.status_label)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("Generation details will appear here.")
        self.log_output.setMinimumHeight(150)
        layout.addWidget(self.log_output)

        self.setCentralWidget(central_widget)

    def choose_folder(self):
        selected_folder = QFileDialog.getExistingDirectory(
            self, "Select Music Folder", self.folder_field.text() or str(Path.home())
        )
        if selected_folder:
            self.folder_field.setText(selected_folder)

    def choose_output_folder(self):
        selected_folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder",
            self.output_folder_field.text() or str(APP_DIR),
        )
        if selected_folder:
            self.output_folder_field.setText(selected_folder)

    def generate_lists(self):
        folder_text = self.folder_field.text().strip()
        if not folder_text:
            QMessageBox.warning(self, "Folder required", "Please select a folder to scan.")
            return

        source_folder = Path(folder_text)
        if not source_folder.is_dir():
            QMessageBox.warning(
                self, "Invalid folder", "The selected source folder is no longer available."
            )
            return

        output_text = self.output_folder_field.text().strip()
        output_folder = Path(output_text)
        if not output_folder.is_dir():
            QMessageBox.warning(
                self,
                "Invalid output folder",
                "The selected output folder is no longer available.",
            )
            return

        if not self.extract_checkbox.isChecked() and not self.recurse_checkbox.isChecked():
            QMessageBox.warning(
                self, "Output format required", "Select at least one output format."
            )
            return

        self._set_busy(True)
        self.status_label.setText("Scanning files…")
        self.log_output.clear()
        self.worker = GenerationWorker(
            source_folder,
            output_folder,
            self.extract_checkbox.isChecked(),
            self.recurse_checkbox.isChecked(),
        )
        self.worker.completed.connect(self.generation_completed)
        self.worker.failed.connect(self.generation_failed)
        self.worker.start()

    def generation_completed(self, created_files: list[Path], log_text: str):
        self._set_busy(False)
        self.log_output.setPlainText(log_text)
        file_names = "\n".join(path.name for path in created_files)
        self.status_label.setText(f"Finished. Created {len(created_files)} file(s).")
        QMessageBox.information(
            self,
            "Generation complete",
            f"Created:\n{file_names}\n\nLocation:\n{created_files[0].parent}",
        )

    def generation_failed(self, error_message: str):
        self._set_busy(False)
        self.status_label.setText("Generation failed.")
        self.log_output.setPlainText(error_message)
        QMessageBox.critical(self, "Generation failed", error_message)

    def _set_busy(self, busy: bool):
        self.generate_button.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.output_browse_button.setEnabled(not busy)
        self.extract_checkbox.setEnabled(not busy)
        self.recurse_checkbox.setEnabled(not busy)

    def open_output_folder(self):
        # QDesktopServices handles the platform-specific file manager.
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices

        output_folder = Path(self.output_folder_field.text())
        if not output_folder.is_dir():
            QMessageBox.warning(
                self,
                "Unable to open folder",
                "The selected output folder is no longer available.",
            )
            return

        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_folder))):
            QMessageBox.warning(
                self, "Unable to open folder", f"Output folder:\n{output_folder}"
            )


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Music File List Generator")
    window = MusicFileListWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
