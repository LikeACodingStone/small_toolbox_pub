from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from .ffmpeg_tools import build_audio_file
from .models import AUDIO_EXTENSIONS, AudioFile


ProgressCallback = Callable[[int, int, str], None]


def iter_audio_paths(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS:
            yield path


def scan_audio_files(
    root: Path,
    target_sample_rate: int | None,
    workers: int,
    progress: ProgressCallback | None = None,
    ffprobe_path: str | None = None,
) -> list[AudioFile]:
    paths = sorted(iter_audio_paths(root), key=lambda item: str(item).lower())
    total = len(paths)
    if total == 0:
        return []

    results: list[AudioFile] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(build_audio_file, path, target_sample_rate, ffprobe_path): path
            for path in paths
        }
        for done, future in enumerate(as_completed(future_map), start=1):
            path = future_map[future]
            try:
                audio = future.result()
            except Exception as exc:
                audio = AudioFile(
                    source_path=path,
                    output_path=path.with_suffix(".opus"),
                    status="Probe failed",
                    message=str(exc),
                )
            results.append(audio)
            if progress:
                progress(done, total, path.name)

    return sorted(results, key=lambda item: str(item.source_path).lower())
