import re
import unicodedata
from pathlib import Path
from typing import Tuple


NUMBER_PREFIX_RE = re.compile(r"^\s*(?:\d+[\s._-]+)+")
ARTIST_TITLE_SEPARATORS = [" - ", "-", "_", "--", "–", "—"]


def normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = NUMBER_PREFIX_RE.sub("", value)
    value = value.casefold()
    return "".join(ch for ch in value if ch.isalnum())


def split_artist_title(stem: str) -> Tuple[str, str]:
    clean = NUMBER_PREFIX_RE.sub("", stem).strip()
    for sep in ARTIST_TITLE_SEPARATORS:
        if sep in clean:
            left, right = clean.split(sep, 1)
            artist = normalize_token(left)
            title = normalize_token(right)
            if artist and title:
                return artist, title
    return "", normalize_token(clean)


def song_key_from_name(file_name: str) -> Tuple[str, str]:
    return split_artist_title(Path(file_name).stem)
