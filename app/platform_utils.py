from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def system_name() -> str:
    return platform.system() or os.name


def worker_count() -> int:
    cpu_count = os.cpu_count() or 4
    return max(1, min(cpu_count, 32))


def find_executable(name: str) -> str | None:
    candidates = [name]
    if os.name == "nt" and not name.lower().endswith(".exe"):
        candidates.append(f"{name}.exe")

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return found
    return None


def delete_file(path: Path) -> None:
    path.unlink()
