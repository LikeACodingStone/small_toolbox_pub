from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Tuple


@dataclass(frozen=True)
class SongRecord:
    root_uri: str
    path: str
    relative_path: str
    file_name: str
    stem: str
    extension: str
    deepest_folder: str
    key: Tuple[str, str]
    backend: str

    @property
    def display_key(self) -> str:
        artist, title = self.key
        return f"{artist} - {title}" if artist else title

    @property
    def relative_folder(self) -> str:
        folder = str(PurePosixPath(self.relative_path).parent)
        return "" if folder == "." else folder
