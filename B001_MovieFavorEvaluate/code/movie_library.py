import json
import re
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent
ROOT = CODE_DIR.parent
DATA_DIR = ROOT / "data"
TEST_DIR = ROOT / "test"
MOVIES_DETAILS_DIR = DATA_DIR / "movies_details"

CJK_RE = re.compile(r"[\u3400-\u9fff]+")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
FULL_WIDTH_LEFT_PAREN = "\uff08"
FULL_WIDTH_RIGHT_PAREN = "\uff09"

TITLE_VARIANTS = {
    "英国病人": "英伦病人",
    "第九区": "九区",
    "海街日記": "海街R记",
    "海街日记": "海街R记",
    "十二怒汉": "12怒汉",
    "还有明天": "为了明天",
}


def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def strip_parenthetical(text):
    out = []
    depth = 0
    for ch in text:
        if ch == "(" or ch == FULL_WIDTH_LEFT_PAREN:
            depth += 1
            continue
        if ch == ")" or ch == FULL_WIDTH_RIGHT_PAREN:
            depth = max(0, depth - 1)
            continue
        if depth == 0:
            out.append(ch)
    return "".join(out)


def apply_title_variants(text):
    text = text.replace("：", ":")
    text = text.replace("重复项", "").replace("重複項", "")
    for old, new in TITLE_VARIANTS.items():
        text = text.replace(old, new)
    return text


def compact_title(text):
    text = apply_title_variants(YEAR_RE.sub("", strip_parenthetical(text).strip()))
    return "".join(
        ch.lower()
        for ch in text
        if ch.isalnum() or ("\u3400" <= ch <= "\u9fff")
    )


def title_aliases(title):
    candidates = {title, strip_parenthetical(title)}
    base = apply_title_variants(strip_parenthetical(title))
    chunks = CJK_RE.findall(base)
    if chunks:
        candidates.add("".join(chunks))
        candidates.update(chunks)
        first_cjk = CJK_RE.search(base)
        if first_cjk:
            candidates.add(base[first_cjk.start() :])
    candidates.update(piece.strip() for piece in re.split(r"[/|]", title))
    return {compact_title(candidate) for candidate in candidates if compact_title(candidate)}


def split_md_row(line):
    text = line.strip()
    if not (text.startswith("|") and text.endswith("|")):
        return []
    return [cell.strip() for cell in text.strip("|").split("|")]


def is_separator_row(cells):
    return bool(cells) and all(
        re.fullmatch(r":?-{2,}:?", cell.replace(" ", "")) for cell in cells
    )


def parse_movies_detail_file(path):
    movies = []
    for line in path.read_text(encoding="utf-8").splitlines():
        cells = split_md_row(line)
        if not cells or is_separator_row(cells):
            continue
        first = cells[0].strip()
        if not first or first == "名称" or first.lower().startswith("movie "):
            continue

        if path.name.startswith("00"):
            for cell in cells:
                value = cell.strip()
                if value and not value.lower().startswith("movie "):
                    movies.append(value)
        else:
            movies.append(first)
    return movies


def iter_movies_details():
    for path in sorted(MOVIES_DETAILS_DIR.glob("*.md")):
        sentiment = "negative" if path.name.startswith("00") else "positive"
        for title in parse_movies_detail_file(path):
            yield {
                "sentiment": sentiment,
                "source_file": path.name,
                "title": title,
            }


def json_movie_aliases(*json_paths):
    aliases = set()
    for path in json_paths:
        movies = read_json(path, [])
        if not isinstance(movies, list):
            continue
        for item in movies:
            if isinstance(item, dict) and item.get("title"):
                aliases.update(title_aliases(str(item["title"])))
    return aliases
