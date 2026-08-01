from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Tuple

from .models import SongRecord
from .song_matcher import song_key_from_name
from .storage import BaseStorage, storage_from_uri


def scan_storage(uri: str) -> Tuple[BaseStorage, List[SongRecord]]:
    storage = storage_from_uri(uri)
    records: List[SongRecord] = []
    for path in storage.list_audio_files():
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
    return storage, records


def by_key(records: Iterable[SongRecord]) -> Dict[Tuple[str, str], List[SongRecord]]:
    grouped: Dict[Tuple[str, str], List[SongRecord]] = defaultdict(list)
    for record in records:
        if record.key[1]:
            grouped[record.key].append(record)
    return grouped


def diff_records(a_records: List[SongRecord], b_records: List[SongRecord]) -> Tuple[List[SongRecord], List[SongRecord]]:
    a_map = by_key(a_records)
    b_map = by_key(b_records)
    a_only_keys = set(a_map) - set(b_map)
    b_only_keys = set(b_map) - set(a_map)
    a_only = [record for key in sorted(a_only_keys) for record in a_map[key]]
    b_only = [record for key in sorted(b_only_keys) for record in b_map[key]]
    return a_only, b_only


def duplicate_groups(records: Iterable[SongRecord]) -> Dict[Tuple[str, str], List[SongRecord]]:
    grouped = by_key(records)
    return {key: values for key, values in grouped.items() if len(values) > 1}
