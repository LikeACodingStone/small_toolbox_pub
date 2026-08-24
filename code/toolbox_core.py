"""Platform-aware discovery and command construction for the toolbox launcher.

The script filename is the tool identifier.  There is deliberately no title
registry here: adding a script to the platform folder adds a tool to the UI.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolScript:
    """A runnable script discovered in the active platform folder."""

    name: str
    path: Path

    @property
    def category(self) -> str:
        """Return the leading category code, for example ``A`` or ``D``."""

        return self.name[:1].upper() if self.name else "#"


def _platform_settings(system: str | None = None) -> tuple[str, str, str]:
    """Return ``(folder_name, suffix, runner_name)`` for the host platform."""

    system = system or sys.platform
    if system.startswith("win"):
        return "toolbox_win", ".bat", "windows"
    if system.startswith("linux") or system.startswith("darwin"):
        return "toolbox_linux", ".sh", "posix"
    raise RuntimeError(f"Unsupported platform: {platform.system() or system}")


def platform_folder(base_dir: Path, system: str | None = None) -> Path:
    """Return the folder whose scripts are valid for the current platform."""

    folder_name, _, _ = _platform_settings(system)
    return base_dir / folder_name


def discover_tools(base_dir: Path, system: str | None = None) -> list[ToolScript]:
    """Discover direct child scripts in the active platform folder.

    Script extensions are compared case-insensitively.  The returned name is
    exactly the filename stem, so ``A001_Foo.sh`` appears as
    ``A001_Foo`` without any manually maintained metadata.
    """

    folder_name, suffix, _ = _platform_settings(system)
    folder = base_dir / folder_name
    if not folder.is_dir():
        return []

    tools = [
        ToolScript(path=path, name=path.stem)
        for path in folder.iterdir()
        if path.is_file() and path.suffix.lower() == suffix
    ]
    return sorted(tools, key=lambda tool: tool.name.casefold())


def command_for_tool(tool: ToolScript, system: str | None = None) -> tuple[str, list[str]]:
    """Build a shell-safe process command for a discovered script.

    The caller must set the process working directory to ``tool.path.parent``.
    Passing arguments directly to ``QProcess`` avoids shell interpolation of
    filenames containing spaces.
    """

    _, _, runner = _platform_settings(system)
    if runner == "windows":
        return "cmd.exe", ["/d", "/c", tool.path.name]
    return "bash", [str(tool.path.resolve())]


def platform_label(system: str | None = None) -> str:
    """Return a short user-facing platform label."""

    _, _, runner = _platform_settings(system)
    return "Windows" if runner == "windows" else "Linux"
