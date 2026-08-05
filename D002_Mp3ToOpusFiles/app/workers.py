from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

from .ffmpeg_tools import convert_audio, require_tools
from .models import AudioFile, SOURCE_DELETE_EXTENSIONS
from .platform_utils import delete_file
from .scanner import scan_audio_files


MAX_FFMPEG_WORKERS = 2


class ScanWorker(QObject):
    progress = pyqtSignal(int, int, str)
    log = pyqtSignal(str)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, folder: Path, target_sample_rate: int | None, workers: int):
        super().__init__()
        self.folder = folder
        self.target_sample_rate = target_sample_rate
        self.workers = workers

    @pyqtSlot()
    def run(self) -> None:
        try:
            ffprobe, _ffmpeg = require_tools()
            self.log.emit(f"ffprobe: {ffprobe}")
            self.log.emit(f"Scan workers: {max(1, self.workers)}, folder: {self.folder}")
            files = scan_audio_files(
                self.folder,
                self.target_sample_rate,
                self.workers,
                progress=lambda done, total, name: self.progress.emit(done, total, name),
                ffprobe_path=ffprobe,
            )
            self.finished.emit(files)
        except Exception as exc:
            self.failed.emit(str(exc))


class ConvertWorker(QObject):
    progress = pyqtSignal(int, int, object)
    log = pyqtSignal(str)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, files: list[AudioFile], workers: int, overwrite: bool):
        super().__init__()
        self.files = [replace(audio) for audio in files]
        self.workers = workers
        self.overwrite = overwrite

    @pyqtSlot()
    def run(self) -> None:
        try:
            _ffprobe, ffmpeg = require_tools()
            convertable = [audio for audio in self.files if audio.status != "Probe failed"]
            total = len(convertable)
            results: list[AudioFile] = []
            self.log.emit(f"ffmpeg: {ffmpeg}")
            if total == 0:
                self.finished.emit(results)
                return

            max_workers = min(max(1, self.workers), MAX_FFMPEG_WORKERS, total)
            progress_every = max(1, total // 100)
            self.log.emit(
                f"Convert workers: {max_workers}, files: {total}, "
                f"requested workers: {self.workers}, overwrite: {self.overwrite}"
            )
            if max_workers < max(1, self.workers):
                self.log.emit(
                    f"Convert workers capped at {MAX_FFMPEG_WORKERS} to keep the UI responsive."
                )
            self.log.emit("Convert progress is throttled to keep the UI responsive.")

            status_counter: Counter[str] = Counter()
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {
                    executor.submit(convert_audio, audio, self.overwrite, ffmpeg): audio
                    for audio in convertable
                }
                for done, future in enumerate(as_completed(future_map), start=1):
                    audio = future_map[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        audio.status = "Failed"
                        audio.message = str(exc)
                        result = audio
                    results.append(result)
                    status_counter[result.status] += 1

                    output_larger = "output larger" in result.message.lower()
                    if done == total or done % progress_every == 0 or result.status == "Failed" or output_larger:
                        payload = result if result.status == "Failed" or output_larger else f"Processed {done}/{total}"
                        self.progress.emit(done, total, payload)

            self.log.emit(
                "Convert summary: "
                f"converted={status_counter['Converted']}, "
                f"skipped={status_counter['Skipped']}, "
                f"failed={status_counter['Failed']}"
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))


class DeleteWorker(QObject):
    progress = pyqtSignal(int, int, object)
    log = pyqtSignal(str)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, files: list[AudioFile], workers: int):
        super().__init__()
        self.files = files
        self.workers = workers

    @pyqtSlot()
    def run(self) -> None:
        try:
            deletable = [
                audio for audio in self.files
                if audio.source_path.suffix.lower() in SOURCE_DELETE_EXTENSIONS
            ]
            total = len(deletable)
            results: list[AudioFile] = []
            if total == 0:
                self.log.emit("Delete check: no FLAC/MP3 files in the current table.")
                self.finished.emit(results)
                return

            max_workers = min(max(1, self.workers), 16, total)
            progress_every = max(1, total // 100)
            self.log.emit(f"Delete check started. Candidates: {total}, workers: {max_workers}")
            self.log.emit("Delete rule: source is removed only when the matching .opus output exists.")
            self.log.emit("Delete progress is throttled to keep the UI responsive.")

            status_counter: Counter[str] = Counter()
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_map = {executor.submit(self._delete_one, audio): audio for audio in deletable}
                for done, future in enumerate(as_completed(future_map), start=1):
                    audio = future_map[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        audio.status = "Delete failed"
                        audio.message = str(exc)
                        result = audio
                    results.append(result)
                    status_counter[result.status] += 1

                    if done == total or done % progress_every == 0:
                        self.progress.emit(done, total, f"Delete checked {done}/{total}")

            self.log.emit(
                "Delete summary: "
                f"deleted={status_counter['Deleted source']}, "
                f"skipped={status_counter['Delete skipped']}, "
                f"failed={status_counter['Delete failed']}"
            )
            self.finished.emit(results)
        except Exception as exc:
            self.failed.emit(str(exc))

    @staticmethod
    def _delete_one(audio: AudioFile) -> AudioFile:
        if not audio.output_path.is_file():
            audio.status = "Delete skipped"
            audio.message = "Matching opus output does not exist"
        elif not audio.source_path.is_file():
            audio.status = "Delete skipped"
            audio.message = "Source file already missing"
        else:
            delete_file(audio.source_path)
            audio.status = "Deleted source"
            audio.message = "Source removed after opus check"
        return audio
