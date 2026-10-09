import logging
import time
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .models import SongRecord
from .song_matcher import song_key_from_name
from .storage import BaseStorage, storage_from_uri

LOGGER = logging.getLogger(__name__)


def scan_storage(uri: str, progress_callback: Optional[Callable[[str], None]] = None) -> Tuple[BaseStorage, List[SongRecord]]:
    def progress(message: str) -> None:
        LOGGER.info(message)
        if progress_callback:
            progress_callback(message)

    started = time.monotonic()
    progress(f"Preparing scan: {uri}")
    storage = storage_from_uri(uri)
    progress(f"Listing audio files with {storage.kind} storage: {uri}")
    paths = storage.list_audio_files()
    progress(f"Listed {len(paths)} audio files from {uri}; building song records...")
    records: List[SongRecord] = []
    for idx, path in enumerate(paths, start=1):
        rel = storage.relative_for_path(path)
        file_name = PurePosixPath(path.replace("\\", "/")).name
        suffix = Path(file_name).suffix.casefold()
        stem = Path(file_name).stem
        folder = str(PurePosixPath(rel).parent)
        if folder == ".":
            folder = ""
        records.append(
            SongRecord(
                root_uri=uri,
                path=path,
                relative_path=rel,
                file_name=file_name,
                stem=stem,
                extension=suffix,
                deepest_folder=folder,
                key=song_key_from_name(file_name),
                backend=storage.kind,
            )
        )
        if idx % 1000 == 0:
            progress(f"Built {idx} song records from {uri}")
    progress(f"Scan complete for {uri}: {len(records)} records in {time.monotonic() - started:.2f}s")
    return storage, records


def by_key(records: Iterable[SongRecord]) -> Dict[Tuple[str, str], List[SongRecord]]:
    grouped: Dict[Tuple[str, str], List[SongRecord]] = defaultdict(list)
    for record in records:
        if record.key[1]:
            grouped[record.key].append(record)
    return grouped


def diff_records(a_records: List[SongRecord], b_records: List[SongRecord]) -> Tuple[List[SongRecord], List[SongRecord]]:
    LOGGER.info("Diffing records: A=%s, B=%s", len(a_records), len(b_records))
    a_map = by_key(a_records)
    b_map = by_key(b_records)
    a_only_keys = set(a_map) - set(b_map)
    b_only_keys = set(b_map) - set(a_map)
    a_only = [record for key in sorted(a_only_keys) for record in a_map[key]]
    b_only = [record for key in sorted(b_only_keys) for record in b_map[key]]
    LOGGER.info("Diff complete: A-only=%s, B-only=%s", len(a_only), len(b_only))
    return a_only, b_only


def duplicate_groups(records: Iterable[SongRecord]) -> Dict[Tuple[str, str], List[SongRecord]]:
    grouped = by_key(records)
    return {key: values for key, values in grouped.items() if len(values) > 1}
