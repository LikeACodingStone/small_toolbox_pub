import logging
import os
import posixpath
import shlex
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Tuple

from .config import SUPPORTED_EXTENSIONS

LOGGER = logging.getLogger(__name__)


class StorageError(RuntimeError):
    pass


class BaseStorage:
    kind = "base"

    def __init__(self, uri: str):
        self.uri = uri.strip()

    def list_audio_files(self) -> List[str]:
        raise NotImplementedError

    def remove_file(self, path: str) -> None:
        raise NotImplementedError

    def rename_file(self, path: str, new_relative_path: str) -> str:
        raise NotImplementedError

    def copy_file_to(self, source_path: str, target_storage: "BaseStorage", relative_path: str) -> None:
        raise NotImplementedError

    def make_parent(self, relative_path: str) -> None:
        raise NotImplementedError

    def absolute_for_relative(self, relative_path: str) -> str:
        raise NotImplementedError

    def relative_for_path(self, path: str) -> str:
        raise NotImplementedError


class LocalStorage(BaseStorage):
    kind = "local"

    def __init__(self, uri: str):
        super().__init__(uri)
        self.root = Path(uri).expanduser().resolve()

    def list_audio_files(self) -> List[str]:
        if not self.root.exists():
            raise StorageError(f"Folder does not exist: {self.root}")
        files = []
        for path in self.root.rglob("*"):
            if path.is_file() and path.suffix.casefold() in SUPPORTED_EXTENSIONS:
                files.append(str(path))
        return files

    def remove_file(self, path: str) -> None:
        LOGGER.info("Deleting local file: %s", path)
        Path(path).unlink()

    def rename_file(self, path: str, new_relative_path: str) -> str:
        target_path = Path(self.absolute_for_relative(new_relative_path))
        if target_path.exists():
            raise StorageError(f"Rename target already exists: {target_path}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        LOGGER.info("Renaming local file %s -> %s", path, target_path)
        Path(path).rename(target_path)
        return str(target_path)

    def copy_file_to(self, source_path: str, target_storage: BaseStorage, relative_path: str) -> None:
        if isinstance(target_storage, LocalStorage):
            target_path = Path(target_storage.absolute_for_relative(relative_path))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            LOGGER.info("Copying local file %s -> %s", source_path, target_path)
            shutil.copy2(source_path, target_path)
            return
        if isinstance(target_storage, AdbStorage):
            target_storage.make_parent(relative_path)
            LOGGER.info("Pushing local file %s -> %s", source_path, target_storage.absolute_for_relative(relative_path))
            target_storage.push_file(source_path, relative_path)
            return
        raise StorageError(f"Unsupported target storage: {target_storage.kind}")

    def make_parent(self, relative_path: str) -> None:
        Path(self.absolute_for_relative(relative_path)).parent.mkdir(parents=True, exist_ok=True)

    def absolute_for_relative(self, relative_path: str) -> str:
        return str(self.root / Path(relative_path))

    def relative_for_path(self, path: str) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()


class AdbStorage(BaseStorage):
    kind = "adb"

    def __init__(self, uri: str):
        super().__init__(uri)
        body = uri[4:]
        self.serial: Optional[str] = None
        if body.count(":") >= 1 and not body.startswith("/"):
            serial, remote = body.split(":", 1)
            self.serial = serial or None
            self.root = remote
        else:
            self.root = body
        self.root = self.root.rstrip("/") or "/"

    def _adb_cmd(self, *args: str) -> List[str]:
        cmd = ["adb"]
        if self.serial:
            cmd.extend(["-s", self.serial])
        cmd.extend(args)
        return cmd

    def _run(self, *args: str) -> str:
        cmd = self._adb_cmd(*args)
        LOGGER.debug("Running ADB command: %s", cmd)
        completed = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if completed.returncode != 0:
            raise StorageError(completed.stderr.strip() or f"ADB command failed: {' '.join(cmd)}")
        return completed.stdout

    def list_audio_files(self) -> List[str]:
        name_parts = []
        for ext in sorted(SUPPORTED_EXTENSIONS):
            name_parts.extend(["-iname", f"*{ext}", "-o"])
        name_expr = " ".join(shlex.quote(part) for part in name_parts[:-1])
        command = f"find {shlex.quote(self.root)} -type f \\( {name_expr} \\)"
        output = self._run("shell", command)
        return [line.strip() for line in output.splitlines() if line.strip()]

    def remove_file(self, path: str) -> None:
        LOGGER.info("Deleting ADB file: %s", path)
        self._run("shell", "rm", "-f", path)

    def rename_file(self, path: str, new_relative_path: str) -> str:
        target_path = self.absolute_for_relative(new_relative_path)
        quoted_target = shlex.quote(target_path)
        exists = self._run("shell", f"if [ -e {quoted_target} ]; then echo yes; fi").strip()
        if exists:
            raise StorageError(f"Rename target already exists: {target_path}")
        self.make_parent(new_relative_path)
        LOGGER.info("Renaming ADB file %s -> %s", path, target_path)
        self._run("shell", "mv", path, target_path)
        return target_path

    def copy_file_to(self, source_path: str, target_storage: BaseStorage, relative_path: str) -> None:
        if isinstance(target_storage, AdbStorage):
            target_storage.make_parent(relative_path)
            temp_local = Path("installed") / "adb_transfer_cache"
            temp_local.mkdir(parents=True, exist_ok=True)
            temp_file = temp_local / PurePosixPath(relative_path).name
            self.pull_file(source_path, str(temp_file))
            target_storage.push_file(str(temp_file), relative_path)
            return
        if isinstance(target_storage, LocalStorage):
            target_storage.make_parent(relative_path)
            self.pull_file(source_path, target_storage.absolute_for_relative(relative_path))
            return
        raise StorageError(f"Unsupported target storage: {target_storage.kind}")

    def pull_file(self, remote_path: str, local_path: str) -> None:
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self._run("pull", remote_path, local_path)

    def push_file(self, local_path: str, relative_path: str) -> None:
        self._run("push", local_path, self.absolute_for_relative(relative_path))

    def make_parent(self, relative_path: str) -> None:
        parent = posixpath.dirname(self.absolute_for_relative(relative_path))
        self._run("shell", "mkdir", "-p", parent)

    def absolute_for_relative(self, relative_path: str) -> str:
        return posixpath.join(self.root, PurePosixPath(relative_path).as_posix())

    def relative_for_path(self, path: str) -> str:
        rel = posixpath.relpath(path, self.root)
        return "." if rel == "." else rel


def storage_from_uri(uri: str) -> BaseStorage:
    uri = uri.strip()
    if not uri:
        raise StorageError("Path is empty")
    if uri.casefold().startswith("adb:"):
        return AdbStorage(uri)
    return LocalStorage(uri)
