import logging
import re
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Callable, Iterable, List, Optional, Set, Tuple

from .models import SongRecord
from .song_matcher import NUMBER_PREFIX_RE
from .storage import BaseStorage, StorageError

LOGGER = logging.getLogger(__name__)
NUMBERED_COPY_RE = re.compile(r"\(\d+\)")
FORMAT_PRIORITY = {
    ".opus": 0,
    ".flac": 1,
    ".mp3": 2,
    ".aac": 3,
}


def delete_records(records: Iterable[SongRecord], storage: BaseStorage) -> int:
    count = 0
    for record in records:
        storage.remove_file(record.path)
        count += 1
    LOGGER.info("Deleted %s files", count)
    return count


def sync_records(records: Iterable[SongRecord], source: BaseStorage, target: BaseStorage) -> int:
    count = 0
    for record in records:
        source.copy_file_to(record.path, target, record.relative_path)
        count += 1
    LOGGER.info("Synced %s files", count)
    return count


def merge_records(
    source_records: Iterable[SongRecord],
    source_storages: dict[str, BaseStorage],
    target: BaseStorage,
    existing_keys: Set[Tuple[str, str]],
    progress_callback: Optional[Callable[[str, SongRecord], None]] = None,
) -> Tuple[int, List[SongRecord]]:
    copied = 0
    skipped: List[SongRecord] = []
    seen_keys = set(existing_keys)
    for record in source_records:
        if not record.key[1] or record.key in seen_keys:
            skipped.append(record)
            if progress_callback:
                progress_callback("skipped", record)
            continue
        source = source_storages[record.root_uri]
        source.copy_file_to(record.path, target, record.relative_path)
        seen_keys.add(record.key)
        copied += 1
        if progress_callback:
            progress_callback("merged", record)
    LOGGER.info("Merged %s files, skipped %s duplicates", copied, len(skipped))
    return copied, skipped


def cleanup_internal_duplicates(
    records: Iterable[SongRecord],
    storage: BaseStorage,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Tuple[int, int, int]:
    records = list(records)
    deleted = 0
    renamed = 0
    skipped_renames = 0

    def progress(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    numbered_copy_paths = set()
    for record in records:
        if NUMBERED_COPY_RE.search(record.stem):
            storage.remove_file(record.path)
            numbered_copy_paths.add(record.path)
            deleted += 1
            progress(f"DELETED numbered copy | {record.relative_path}")

    remaining = [record for record in records if record.path not in numbered_copy_paths]
    groups: dict[Tuple[str, str], List[SongRecord]] = defaultdict(list)
    for record in remaining:
        if record.key[1]:
            groups[record.key].append(record)

    kept_paths = set(record.path for record in remaining)
    for group_records in groups.values():
        if len(group_records) <= 1:
            continue
        keeper = min(
            group_records,
            key=lambda record: (
                FORMAT_PRIORITY.get(record.extension.casefold(), 99),
                len(record.relative_path),
                record.relative_path.casefold(),
            ),
        )
        progress(f"KEEP duplicate group | {keeper.relative_path}")
        for record in group_records:
            if record.path == keeper.path:
                continue
            storage.remove_file(record.path)
            kept_paths.discard(record.path)
            deleted += 1
            progress(f"DELETED duplicate | {record.relative_path}")

    for record in remaining:
        if record.path not in kept_paths:
            continue
        clean_stem = NUMBER_PREFIX_RE.sub("", record.stem).strip()
        if not clean_stem or clean_stem == record.stem:
            continue
        parent = PurePosixPath(record.relative_path).parent
        new_name = f"{clean_stem}{record.extension}"
        new_relative = new_name if str(parent) == "." else (parent / new_name).as_posix()
        if new_relative == record.relative_path:
            continue
        try:
            storage.rename_file(record.path, new_relative)
            renamed += 1
            progress(f"RENAMED number prefix | {record.relative_path} -> {new_relative}")
        except StorageError as exc:
            skipped_renames += 1
            progress(f"SKIPPED rename conflict | {record.relative_path} | {exc}")

    LOGGER.info("Cleaned internal duplicates: deleted %s, renamed %s, skipped renames %s", deleted, renamed, skipped_renames)
    return deleted, renamed, skipped_renames
