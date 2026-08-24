"""PyQt5 launcher for scripts in ``toolbox_linux`` or ``toolbox_win``."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PyQt5.QtCore import QProcess, Qt, QUrl, pyqtSignal
    from PyQt5.QtGui import QBrush, QColor, QDesktopServices
    from PyQt5.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSplitter,
        QStatusBar,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # Keep the failure useful when PyQt5 is missing.
    raise SystemExit("PyQt5 is required. Install it with: python -m pip install -r requirements.txt") from exc

from toolbox_core import (
    ToolScript,
    command_for_tool,
    discover_tools,
    platform_folder,
    platform_label,
)


BASE_DIR = Path(__file__).resolve().parent
TOOL_ROLE = Qt.UserRole + 1


class ToolTree(QTreeWidget):
    """Tool tree that emits a selected tool without exposing category rows."""

    toolSelected = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(18)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.itemSelectionChanged.connect(self._emit_selection)

    def _emit_selection(self) -> None:
        item = self.currentItem()
        if item is not None:
            self.toolSelected.emit(item.data(0, TOOL_ROLE))

    def set_tools(self, tools: list[ToolScript]) -> None:
        self.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        for tool in tools:
            category = tool.category
            parent = groups.get(category)
            if parent is None:
                parent = QTreeWidgetItem([category])
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setForeground(0, QBrush(QColor("#71808c")))
                self.addTopLevelItem(parent)
                parent.setExpanded(True)
                groups[category] = parent

            child = QTreeWidgetItem([tool.name])
            child.setData(0, TOOL_ROLE, tool)
            parent.addChild(child)

        if tools:
            first_group = self.topLevelItem(0)
            if first_group and first_group.childCount():
                first_group.child(0).setSelected(True)
                self.setCurrentItem(first_group.child(0))

    def apply_filter(self, query: str) -> None:
        query = query.casefold().strip()
        for index in range(self.topLevelItemCount()):
            category = self.topLevelItem(index)
            visible_children = 0
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                tool = child.data(0, TOOL_ROLE)
                visible = not query or query in tool.name.casefold()
                child.setHidden(not visible)
                visible_children += int(visible)
            category.setHidden(visible_children == 0)


class ToolboxWindow(QMainWindow):
    """Main launcher window with discovery, process control, and output log."""

    def __init__(self, base_dir: Path = BASE_DIR):
        super().__init__()
        self.base_dir = base_dir
        self.tools: list[ToolScript] = []
        self.processes: dict[str, QProcess] = {}
        self.logs: dict[str, str] = {}
        self.current_tool: ToolScript | None = None

        self.setWindowTitle("Small Toolbox")
        self.resize(1120, 720)
        self.setMinimumSize(820, 540)
        self._build_ui()
        self.refresh_tools()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #eef1f4; }
            QFrame#sidebar, QFrame#details { background: #ffffff; border: 1px solid #d9dee4; }
            QLabel#eyebrow { color: #71808c; font-size: 12px; font-weight: 700; }
            QLabel#toolTitle { color: #202b34; font-size: 25px; font-weight: 700; }
            QLabel#muted { color: #65737e; }
            QLineEdit { border: 1px solid #cbd3db; border-radius: 5px; padding: 8px; background: #ffffff; }
            QTreeWidget { border: 0; background: #ffffff; outline: 0; padding: 4px; }
            QTreeWidget::item { padding: 7px 5px; }
            QTreeWidget::item:selected { background: #dceff0; color: #17646a; border: 1px solid #3c8f95; border-radius: 4px; }
            QPushButton { min-height: 34px; padding: 0 16px; border-radius: 5px; border: 1px solid #aeb8c1; background: #ffffff; }
            QPushButton#launchButton { color: #ffffff; background: #287f86; border-color: #287f86; font-weight: 700; }
            QPushButton#launchButton:disabled { color: #edf6f6; background: #92b8bb; border-color: #92b8bb; }
            QPlainTextEdit { background: #202a32; color: #c5d0d7; border: 0; border-radius: 4px; padding: 8px; font-family: monospace; }
            QStatusBar { background: #edf1f4; color: #53616c; }
            """
        )

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 8)
        outer.setSpacing(8)

        toolbar = QHBoxLayout()
        title = QLabel("Small Toolbox")
        title.setStyleSheet("font-size: 21px; font-weight: 700; color: #202b34;")
        toolbar.addWidget(title)
        toolbar.addStretch()
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_tools)
        toolbar.addWidget(self.refresh_button)
        self.open_folder_button = QPushButton("Open Script Folder")
        self.open_folder_button.clicked.connect(self.open_script_folder)
        toolbar.addWidget(self.open_folder_button)
        outer.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        outer.addWidget(splitter, 1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        sidebar_layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tools...")
        self.search.textChanged.connect(self._filter_tools)
        sidebar_layout.addWidget(self.search)
        self.tree = ToolTree()
        self.tree.toolSelected.connect(self.select_tool)
        sidebar_layout.addWidget(self.tree, 1)
        splitter.addWidget(sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        details = QFrame()
        details.setObjectName("details")
        details_layout = QVBoxLayout(details)
        details_layout.setContentsMargins(28, 24, 28, 24)
        self.eyebrow = QLabel("NO TOOL SELECTED")
        self.eyebrow.setObjectName("eyebrow")
        details_layout.addWidget(self.eyebrow)
        self.tool_title = QLabel("No tools found")
        self.tool_title.setObjectName("toolTitle")
        details_layout.addWidget(self.tool_title)
        self.tool_path = QLabel("Add .sh files to toolbox_linux or .bat files to toolbox_win.")
        self.tool_path.setObjectName("muted")
        self.tool_path.setWordWrap(True)
        details_layout.addWidget(self.tool_path)
        details_layout.addSpacing(12)
        buttons = QHBoxLayout()
        self.launch_button = QPushButton("Launch Tool")
        self.launch_button.setObjectName("launchButton")
        self.launch_button.clicked.connect(self.launch_selected)
        buttons.addWidget(self.launch_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.stop_selected)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        details_layout.addLayout(buttons)
        details_layout.addStretch()
        self.tool_status = QLabel("Status: No tool selected")
        self.tool_status.setObjectName("muted")
        details_layout.addWidget(self.tool_status)
        right_layout.addWidget(details, 1)

        log_frame = QFrame()
        log_frame.setObjectName("details")
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(28, 18, 28, 18)
        log_heading = QLabel("Process Output")
        log_heading.setStyleSheet("font-size: 17px; font-weight: 700; color: #26323c;")
        log_layout.addWidget(log_heading)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Output from the selected script will appear here.")
        log_layout.addWidget(self.output, 1)
        right_layout.addWidget(log_frame, 1)
        splitter.addWidget(right)
        splitter.setSizes([280, 780])
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self.stop_button.setEnabled(False)
        self.launch_button.setEnabled(False)

    def refresh_tools(self) -> None:
        self.tools = discover_tools(self.base_dir)
        self.tree.set_tools(self.tools)
        self.statusBar().showMessage(
            f"{platform_label()} | {len(self.tools)} tool(s) found in {platform_folder(self.base_dir).name}"
        )
        if not self.tools:
            self.current_tool = None
            self.eyebrow.setText(f"{platform_label().upper()} / NO SCRIPTS")
            self.tool_title.setText("No tools found")
            self.tool_path.setText(
                f"Add .sh files to {platform_folder(self.base_dir).name} and click Refresh."
            )
            self.tool_status.setText("Status: No tool selected")
            self.launch_button.setEnabled(False)
            self.stop_button.setEnabled(False)
        elif self.tree.currentItem() is not None:
            selected = self.tree.currentItem().data(0, TOOL_ROLE)
            if isinstance(selected, ToolScript):
                self.select_tool(selected)

    def _filter_tools(self, query: str) -> None:
        self.tree.apply_filter(query)

    def select_tool(self, tool: ToolScript) -> None:
        if not isinstance(tool, ToolScript):
            return
        self.current_tool = tool
        self.eyebrow.setText(f"{platform_label().upper()} / {tool.category}")
        self.tool_title.setText(tool.name)
        self.tool_path.setText(str(tool.path))
        self.output.setPlainText(self.logs.get(tool.name, ""))
        running = self._is_running(tool.name)
        self.launch_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.tool_status.setText(f"Status: {'Running' if running else 'Ready'}")

    def _is_running(self, name: str) -> bool:
        process = self.processes.get(name)
        return process is not None and process.state() != QProcess.NotRunning

    def _append_log(self, name: str, text: str) -> None:
        if not text:
            return
        self.logs[name] = self.logs.get(name, "") + text
        if self.current_tool and self.current_tool.name == name:
            self.output.setPlainText(self.logs[name])
            cursor = self.output.textCursor()
            cursor.movePosition(cursor.End)
            self.output.setTextCursor(cursor)

    def launch_selected(self) -> None:
        tool = self.current_tool
        if tool is None or self._is_running(tool.name):
            return

        program, arguments = command_for_tool(tool)
        process = QProcess(self)
        process.setWorkingDirectory(str(tool.path.parent.resolve()))
        process.setProgram(program)
        process.setArguments(arguments)
        process.readyReadStandardOutput.connect(
            lambda process=process, name=tool.name: self._read_process_output(process, name, False)
        )
        process.readyReadStandardError.connect(
            lambda process=process, name=tool.name: self._read_process_output(process, name, True)
        )
        process.started.connect(lambda name=tool.name: self._process_started(name))
        process.errorOccurred.connect(
            lambda error, name=tool.name: self._process_error(name, error)
        )
        process.finished.connect(
            lambda code, status, name=tool.name, process=process: self._process_finished(
                name, process, code, status
            )
        )

        self.logs[tool.name] = f"$ {program} {' '.join(arguments)}\n"
        self.processes[tool.name] = process
        self.output.setPlainText(self.logs[tool.name])
        process.start()

    def _read_process_output(self, process: QProcess, name: str, error: bool) -> None:
        data = process.readAllStandardError() if error else process.readAllStandardOutput()
        text = bytes(data).decode("utf-8", errors="replace")
        self._append_log(name, text)

    def _process_started(self, name: str) -> None:
        if self.current_tool and self.current_tool.name == name:
            self.launch_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.tool_status.setText("Status: Running")
        self.statusBar().showMessage(f"Running {name}")

    def _process_error(self, name: str, error: QProcess.ProcessError) -> None:
        process = self.processes.get(name)
        detail = process.errorString() if process else "Unknown process error"
        self._append_log(name, f"\n[ERROR] {detail}\n")

    def _process_finished(
        self, name: str, process: QProcess, exit_code: int, exit_status: QProcess.ExitStatus
    ) -> None:
        self._read_process_output(process, name, False)
        self._read_process_output(process, name, True)
        result = "completed" if exit_code == 0 else f"exited with code {exit_code}"
        self._append_log(name, f"\n[INFO] Process {result}.\n")
        self.processes.pop(name, None)
        process.deleteLater()
        if self.current_tool and self.current_tool.name == name:
            self.launch_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.tool_status.setText(f"Status: {result.capitalize()}")
        self.statusBar().showMessage(f"{name}: {result}")

    def stop_selected(self) -> None:
        tool = self.current_tool
        if tool is None:
            return
        process = self.processes.get(tool.name)
        if process and process.state() != QProcess.NotRunning:
            process.terminate()
            self._append_log(tool.name, "\n[INFO] Stop requested.\n")

    def open_script_folder(self) -> None:
        folder = platform_folder(self.base_dir)
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event) -> None:
        running = [process for process in self.processes.values() if process.state() != QProcess.NotRunning]
        if running:
            answer = QMessageBox.question(
                self,
                "Tools are running",
                "Stop running tools and close the toolbox?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            for process in running:
                process.kill()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Small Toolbox")
    app.setStyle("Fusion")
    window = ToolboxWindow()
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
