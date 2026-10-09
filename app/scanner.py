from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from .ffmpeg_tools import build_audio_file, opus_resample_output_path
from .models import (
    OPUS_AUDIO_EXTENSIONS,
    RESAMPLED_FOLDER_SUFFIX,
    RESAMPLED_OPUS_SUFFIX,
    SOURCE_AUDIO_EXTENSIONS,
    AudioFile,
)


ProgressCallback = Callable[[int, int, str], None]


def is_in_generated_resample_folder(path: Path, root: Path) -> bool:
    try:
        parent_parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return False
    return any(part.endswith(RESAMPLED_FOLDER_SUFFIX) for part in parent_parts)


def iter_audio_paths(
    root: Path,
    extensions: set[str],
    skip_resampled_opus: bool = False,
    skip_resampled_folders: bool = False,
) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            if skip_resampled_opus and path.name.lower().endswith(RESAMPLED_OPUS_SUFFIX):
                continue
            if skip_resampled_folders and is_in_generated_resample_folder(path, root):
                continue
            yield path


def scan_audio_files(
    root: Path,
    target_sample_rate: int | None,
    workers: int,
    progress: ProgressCallback | None = None,
    ffprobe_path: str | None = None,
) -> list[AudioFile]:
    opus_source_root: Path | None = None
    paths = sorted(iter_audio_paths(root, SOURCE_AUDIO_EXTENSIONS), key=lambda item: str(item).lower())
    if not paths:
        opus_source_root = root
        paths = sorted(
            iter_audio_paths(
                root,
                OPUS_AUDIO_EXTENSIONS,
                skip_resampled_opus=True,
                skip_resampled_folders=True,
            ),
            key=lambda item: str(item).lower(),
        )
    total = len(paths)
    if total == 0:
        return []

    results: list[AudioFile] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {
            executor.submit(
                build_audio_file,
                path,
                target_sample_rate,
                ffprobe_path,
                opus_source_root,
            ): path
            for path in paths
        }
        for done, future in enumerate(as_completed(future_map), start=1):
            path = future_map[future]
            try:
                audio = future.result()
            except Exception as exc:
                output_path = path.with_suffix(".opus")
                if output_path == path:
                    if opus_source_root is not None:
                        output_path = opus_resample_output_path(path, opus_source_root)
                    else:
                        output_path = path.with_name(f"{path.stem}{RESAMPLED_OPUS_SUFFIX}")
                audio = AudioFile(
                    source_path=path,
                    output_path=output_path,
                    status="Probe failed",
                    message=str(exc),
                )
            results.append(audio)
            if progress:
                progress(done, total, path.name)

    return sorted(results, key=lambda item: str(item.source_path).lower())
