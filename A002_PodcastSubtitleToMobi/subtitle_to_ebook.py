#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


SOURCE_EXTENSIONS = {".md", ".txt", ".srt", ".vtt"}
GENERATED_SUFFIXES = ("_preview.txt", ".epub", ".mobi")
RECORD_SIZE = 4096


ENGLISH_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\*{0,2}(?:\[[^\]]+\]\s*)?English:\*{0,2}\s*(?P<text>.*?)\s*$",
    re.IGNORECASE,
)
TRANSLATION_RE = re.compile(
    r"^\s*(?:[-*]\s*)?\*{0,2}Translation:\*{0,2}\s*(?P<text>.*?)\s*$",
    re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(
    r"^\s*(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{2,3}\s*-->\s*"
    r"(?:\d{1,2}:)?\d{1,2}:\d{2}[,.]\d{2,3}"
)


@dataclass
class CaptionSegment:
    text: str
    vocab: list[tuple[str, str]]


@dataclass
class Chapter:
    title: str
    source_path: Path
    paragraphs: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert subtitle vocabulary notes in a folder into a proofread TXT, "
            "then an EPUB and MOBI ebook."
        )
    )
    parser.add_argument("folder", help="Folder containing .md/.txt/.srt/.vtt files.")
    parser.add_argument(
        "-o",
        "--output-dir",
        help="Output folder. Default: <input folder>/_ebook_output",
    )
    parser.add_argument(
        "--title",
        help=(
            "Book title. Default: the only source file name when there is one file, "
            "otherwise the folder name."
        ),
    )
    parser.add_argument("--author", default="Subtitle Notes", help="Book author metadata.")
    parser.add_argument("--language", default="en", help="Book language metadata.")
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Read supported files in subfolders too.",
    )
    parser.add_argument(
        "--segments-per-paragraph",
        type=int,
        default=8,
        help=(
            "Target subtitle lines per paragraph. Paragraphs only break after a sentence-ending mark. "
            "Use 0 for one long paragraph per chapter."
        ),
    )
    parser.add_argument(
        "--annotate-all",
        action="store_true",
        help="Annotate every occurrence of a vocabulary word instead of only the first occurrence in that subtitle line.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help=(
            "Number of files to process concurrently. "
            "Default 0 uses the current CPU core count."
        ),
    )
    parser.add_argument(
        "--converter",
        help="Path to ebook-convert or kindlegen. If omitted, the script searches common locations.",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip the TXT proofread pause and generate the ebook immediately.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.folder).expanduser().resolve()
    if not input_dir.is_dir():
        print(f"Input folder does not exist: {input_dir}", file=sys.stderr)
        return 2

    files = discover_source_files(input_dir, recursive=args.recursive)
    if not files:
        hint = " Try --recursive if the files are inside subfolders." if not args.recursive else ""
        print(f"No supported subtitle text files found in: {input_dir}.{hint}", file=sys.stderr)
        return 2

    title = args.title or default_book_title(input_dir, files)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else input_dir / "_ebook_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    workers = resolve_worker_count(args.workers, file_count=len(files))
    print(f"Processing {len(files)} file(s) with {workers} worker(s)...")

    chapters = build_chapters(
        files=files,
        segments_per_paragraph=args.segments_per_paragraph,
        annotate_all=args.annotate_all,
        workers=workers,
    )
    if not chapters:
        print("No usable English subtitle content was found.", file=sys.stderr)
        return 2

    base_name = sanitize_filename(title)
    preview_path = output_dir / f"{base_name}_preview.txt"
    epub_path = output_dir / f"{base_name}.epub"
    mobi_path = output_dir / f"{base_name}.mobi"

    write_preview_txt(preview_path, title, chapters)
    print(f"TXT proofread file created: {preview_path}")

    if not args.yes:
        answer = input("Open the TXT to proofread. Generate EPUB/MOBI now? Type y to continue: ").strip()
        if answer.lower() != "y":
            print("Stopped. No ebook was generated.")
            return 0

    write_epub(epub_path, title, chapters, author=args.author, language=args.language)
    mobi_note = write_mobi(
        mobi_path=mobi_path,
        epub_path=epub_path,
        title=title,
        chapters=chapters,
        author=args.author,
        language=args.language,
        converter=args.converter,
    )

    print(f"EPUB created: {epub_path}")
    print(f"MOBI created: {mobi_path}")
    if mobi_note:
        print(mobi_note)
    return 0


def discover_source_files(input_dir: Path, recursive: bool = False) -> list[Path]:
    iterator = input_dir.rglob("*") if recursive else input_dir.iterdir()
    files = [
        path
        for path in iterator
        if path.is_file()
        and path.suffix.lower() in SOURCE_EXTENSIONS
        and not path.name.startswith(".")
        and not is_generated_file(path)
    ]
    return sorted(files, key=chapter_sort_key)


def is_generated_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in GENERATED_SUFFIXES)


def natural_sort_key(path: Path) -> list[object]:
    text = str(path.relative_to(path.parents[0]) if path.parent else path).casefold()
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def chapter_sort_key(path: Path) -> tuple[int, int, list[object]]:
    chapter_number = extract_chapter_number(path)
    if chapter_number is None:
        return (1, 0, natural_sort_key(path))
    return (0, chapter_number, natural_sort_key(path))


def extract_chapter_number(path: Path) -> int | None:
    stem = path.stem
    hash_number_matches = re.findall(r"#\s*(\d+)", stem)
    if hash_number_matches:
        return int(hash_number_matches[-1])

    number_matches = re.findall(r"(\d+)", stem)
    if number_matches:
        return int(number_matches[-1])
    return None


def default_book_title(input_dir: Path, files: list[Path]) -> str:
    if len(files) == 1:
        return files[0].stem
    return input_dir.name


def resolve_worker_count(requested_workers: int, file_count: int) -> int:
    if file_count <= 1:
        return 1
    cpu_count = os.cpu_count() or 1
    if requested_workers <= 0:
        return min(cpu_count, file_count)
    return max(1, min(requested_workers, file_count))


def build_chapters(
    files: Iterable[Path],
    segments_per_paragraph: int,
    annotate_all: bool,
    workers: int = 1,
) -> list[Chapter]:
    file_list = list(files)
    if workers <= 1 or len(file_list) <= 1:
        return [
            chapter
            for chapter in (
                build_chapter(source_path, segments_per_paragraph, annotate_all)
                for source_path in file_list
            )
            if chapter is not None
        ]

    results: list[Chapter | None] = [None] * len(file_list)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_file = {
            executor.submit(build_chapter, source_path, segments_per_paragraph, annotate_all): (index, source_path)
            for index, source_path in enumerate(file_list)
        }
        for future in as_completed(future_to_file):
            index, source_path = future_to_file[future]
            try:
                results[index] = future.result()
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Failed to process source file: {source_path}") from exc

    return [chapter for chapter in results if chapter is not None]


def build_chapter(
    source_path: Path,
    segments_per_paragraph: int,
    annotate_all: bool,
) -> Chapter | None:
    raw_text = read_text_flexibly(source_path)
    segments = parse_note_segments(raw_text)
    paragraphs = make_paragraphs(segments, segments_per_paragraph, annotate_all)
    if not paragraphs:
        return None
    return Chapter(title=source_path.stem, source_path=source_path, paragraphs=paragraphs)


def read_text_flexibly(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5", "cp932", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_note_segments(raw_text: str) -> list[CaptionSegment]:
    segments: list[CaptionSegment] = []
    current_lines: list[str] = []
    current_vocab: list[tuple[str, str]] = []

    def flush_current() -> None:
        nonlocal current_lines, current_vocab
        text = normalize_text(" ".join(current_lines))
        if text:
            segments.append(CaptionSegment(text=text, vocab=current_vocab))
        current_lines = []
        current_vocab = []

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        english_match = ENGLISH_RE.match(line)
        if english_match:
            flush_current()
            current_lines = [english_match.group("text")]
            current_vocab = []
            continue

        translation_match = TRANSLATION_RE.match(line)
        if translation_match:
            if current_lines:
                current_vocab.extend(parse_vocabulary(translation_match.group("text")))
            continue

        if current_lines and not is_auxiliary_line(line):
            current_lines.append(line)

    flush_current()
    if segments:
        return segments
    return parse_plain_subtitle_segments(raw_text)


def parse_plain_subtitle_segments(raw_text: str) -> list[CaptionSegment]:
    segments: list[CaptionSegment] = []
    for raw_line in raw_text.splitlines():
        line = normalize_text(raw_line)
        if not line:
            continue
        if line.isdigit() or TIMESTAMP_RE.match(line):
            continue
        if line.upper() == "WEBVTT" or line.startswith("NOTE"):
            continue
        if is_auxiliary_line(line):
            continue
        segments.append(CaptionSegment(text=line, vocab=[]))
    return segments


def is_auxiliary_line(line: str) -> bool:
    stripped = line.strip()
    lower = stripped.casefold()
    if lower.startswith("source file:"):
        return True
    if stripped.startswith("#"):
        return True
    if TRANSLATION_RE.match(stripped):
        return True
    return False


def parse_vocabulary(text: str) -> list[tuple[str, str]]:
    clean = strip_inline_markup(text)
    match = re.search(r"\bVocabulary\s*[:：]\s*(?P<body>.+)$", clean, re.IGNORECASE)
    if not match:
        return []

    body = match.group("body").strip()
    pairs: list[tuple[str, str]] = []
    for part in re.split(r"\s*[;；]\s*", body):
        part = part.strip()
        if not part:
            continue
        item_match = re.match(r"(?P<term>[^:：]+?)\s*[:：]\s*(?P<meaning>.+)$", part)
        if not item_match:
            continue
        term = clean_vocab_item(item_match.group("term"))
        meaning = clean_vocab_item(item_match.group("meaning"))
        if term and meaning and term.casefold() != meaning.casefold():
            pairs.append((term, meaning))
    return pairs


def clean_vocab_item(text: str) -> str:
    return strip_inline_markup(text).strip(" \t\r\n-*`[]()")


def strip_inline_markup(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "")
    text = text.replace("__", "")
    text = text.replace("\\", "")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_paragraphs(
    segments: list[CaptionSegment],
    segments_per_paragraph: int,
    annotate_all: bool,
) -> list[str]:
    lines = [segment.text for segment in segments if segment.text]
    chapter_vocab = unique_vocab_pair(pair for segment in segments for pair in segment.vocab)
    lines = annotate_lines(lines, chapter_vocab, annotate_all=annotate_all)
    if not lines:
        return []
    if segments_per_paragraph <= 0:
        return [" ".join(lines)]
    return group_lines_into_sentence_paragraphs(lines, segments_per_paragraph)


def group_lines_into_sentence_paragraphs(
    lines: list[str],
    target_segment_count: int,
) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []

    for line in lines:
        current.append(line)
        if len(current) >= target_segment_count and ends_with_sentence_ending(line):
            paragraphs.append(" ".join(current))
            current = []

    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def ends_with_sentence_ending(text: str) -> bool:
    stripped = text.strip().rstrip("\"')]}\u2019\u201d")
    if not stripped:
        return False
    if stripped.endswith("...") or stripped.endswith("\u2026"):
        return False
    if re.search(r"\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|etc|e\.g|i\.e)\.$", stripped, re.IGNORECASE):
        return False
    return stripped[-1] in ".!?\u3002\uff01\uff1f"


def unique_vocab_pair(pairs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for term, meaning in pairs:
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append((term, meaning))
    return unique


def annotate_lines(
    lines: list[str],
    vocab: list[tuple[str, str]],
    annotate_all: bool = False,
) -> list[str]:
    if not vocab:
        return lines
    return annotate_lines_by_index(
        lines,
        sorted(vocab, key=lambda item: len(item[0]), reverse=True),
        annotate_all=annotate_all,
    )


def annotate_lines_by_index(
    lines: list[str],
    vocab: list[tuple[str, str]],
    annotate_all: bool = False,
) -> list[str]:
    joined = "\n".join(lines)
    lower_joined = joined.lower()
    occurrences: list[tuple[int, int, int, int, str, str]] = []

    for order, (term, meaning) in enumerate(vocab):
        lower_term = term.lower()
        start = 0
        while lower_term:
            position = lower_joined.find(lower_term, start)
            if position < 0:
                break
            end = position + len(term)
            if is_valid_term_match(joined, position, end, term):
                occurrences.append((position, end, -len(term), order, term.casefold(), meaning))
                if not annotate_all:
                    break
            start = position + max(1, len(lower_term))

    if not occurrences:
        return lines

    occurrences.sort()
    selected: list[tuple[int, int, str]] = []
    used_terms: set[str] = set()
    covered_until = -1

    for position, end, _negative_length, _order, key, meaning in occurrences:
        if not annotate_all and key in used_terms:
            continue
        if position < covered_until:
            continue
        selected.append((position, end, meaning))
        used_terms.add(key)
        covered_until = end

    if not selected:
        return lines

    output_parts: list[str] = []
    cursor = 0
    for position, end, meaning in selected:
        output_parts.append(joined[cursor:end])
        output_parts.append(f"[{meaning}]")
        cursor = end
    output_parts.append(joined[cursor:])
    return "".join(output_parts).split("\n")


def is_valid_term_match(text: str, position: int, end: int, term: str) -> bool:
    if end < len(text) and text[end] == "[":
        return False
    if term and is_word_edge(term[0]) and position > 0 and is_ascii_word_char(text[position - 1]):
        return False
    if term and is_word_edge(term[-1]) and end < len(text) and is_ascii_word_char(text[end]):
        return False
    return True


def is_ascii_word_char(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")


def make_vocab_pattern(
    vocab: list[tuple[str, str]]
) -> tuple[re.Pattern[str], dict[str, str], dict[str, str]] | None:
    alternatives: list[str] = []
    group_terms: dict[str, str] = {}
    group_meanings: dict[str, str] = {}

    for index, (term, meaning) in enumerate(vocab):
        if not term:
            continue
        group_name = f"term_{index}"
        escaped = re.escape(term)
        left = r"(?<![A-Za-z0-9_])" if is_word_edge(term[0]) else ""
        right = r"(?![A-Za-z0-9_])" if is_word_edge(term[-1]) else ""
        alternatives.append(f"(?P<{group_name}>{left}{escaped}{right}(?!\\[[^\\]]+\\]))")
        group_terms[group_name] = term.casefold()
        group_meanings[group_name] = meaning

    if not alternatives:
        return None
    return re.compile("|".join(alternatives), re.IGNORECASE), group_terms, group_meanings


def annotate_text(text: str, vocab: list[tuple[str, str]], annotate_all: bool = False) -> str:
    result = text
    seen: set[str] = set()
    for term, meaning in sorted(vocab, key=lambda item: len(item[0]), reverse=True):
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        pattern = make_term_pattern(term)
        count = 0 if annotate_all else 1
        result = pattern.sub(lambda match: f"{match.group(0)}[{meaning}]", result, count=count)
    return result


def make_term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term)
    left = r"(?<![A-Za-z0-9_])" if term and is_word_edge(term[0]) else ""
    right = r"(?![A-Za-z0-9_])" if term and is_word_edge(term[-1]) else ""
    return re.compile(left + escaped + right + r"(?!\[[^\]]+\])", re.IGNORECASE)


def is_word_edge(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char == "_")


def write_preview_txt(path: Path, title: str, chapters: list[Chapter]) -> None:
    lines: list[str] = [title, "=" * min(max(len(title), 3), 80), ""]
    for index, chapter in enumerate(chapters, start=1):
        lines.extend([f"Chapter {index}: {chapter.title}", ""])
        for paragraph in chapter.paragraphs:
            lines.extend([paragraph, ""])
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_epub(path: Path, title: str, chapters: list[Chapter], author: str, language: str) -> None:
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(path, "w") as archive:
        mimetype_info = zipfile.ZipInfo("mimetype")
        mimetype_info.compress_type = zipfile.ZIP_STORED
        archive.writestr(mimetype_info, "application/epub+zip")

        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr("OEBPS/style.css", epub_css(), compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr(
            "OEBPS/title.xhtml",
            title_page_xhtml(title, author, language),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        archive.writestr(
            "OEBPS/nav.xhtml",
            nav_xhtml(title, chapters, language),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for index, chapter in enumerate(chapters, start=1):
            archive.writestr(
                f"OEBPS/chapters/chapter-{index:03}.xhtml",
                chapter_xhtml(index, chapter, language),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        archive.writestr(
            "OEBPS/content.opf",
            content_opf(book_id, title, author, language, modified, chapters),
            compress_type=zipfile.ZIP_DEFLATED,
        )


def epub_css() -> str:
    return """body {
  font-family: serif;
  line-height: 1.55;
  margin: 5%;
}
h1 {
  font-size: 1.6em;
  line-height: 1.25;
}
p {
  margin: 0 0 1em 0;
  text-align: left;
}
a {
  color: inherit;
}
"""


def title_page_xhtml(title: str, author: str, language: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{escape_attr(language)}" lang="{escape_attr(language)}">
<head>
  <title>{escape_html(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <section>
    <h1>{escape_html(title)}</h1>
    <p>{escape_html(author)}</p>
  </section>
</body>
</html>
"""


def nav_xhtml(title: str, chapters: list[Chapter], language: str) -> str:
    items = "\n".join(
        f'      <li><a href="chapters/chapter-{index:03}.xhtml">{escape_html(chapter.title)}</a></li>'
        for index, chapter in enumerate(chapters, start=1)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{escape_attr(language)}" lang="{escape_attr(language)}">
<head>
  <title>{escape_html(title)} Contents</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
{items}
    </ol>
  </nav>
</body>
</html>
"""


def chapter_xhtml(index: int, chapter: Chapter, language: str) -> str:
    paragraphs = "\n".join(f"    <p>{escape_html(paragraph)}</p>" for paragraph in chapter.paragraphs)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{escape_attr(language)}" lang="{escape_attr(language)}">
<head>
  <title>{escape_html(chapter.title)}</title>
  <link rel="stylesheet" type="text/css" href="../style.css"/>
</head>
<body>
  <section epub:type="chapter">
    <h1>{index}. {escape_html(chapter.title)}</h1>
{paragraphs}
  </section>
</body>
</html>
"""


def content_opf(
    book_id: str,
    title: str,
    author: str,
    language: str,
    modified: str,
    chapters: list[Chapter],
) -> str:
    manifest_items = "\n".join(
        f'    <item id="chapter-{index:03}" href="chapters/chapter-{index:03}.xhtml" media-type="application/xhtml+xml"/>'
        for index in range(1, len(chapters) + 1)
    )
    spine_items = "\n".join(
        f'    <itemref idref="chapter-{index:03}"/>'
        for index in range(1, len(chapters) + 1)
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{escape_html(book_id)}</dc:identifier>
    <dc:title>{escape_html(title)}</dc:title>
    <dc:creator>{escape_html(author)}</dc:creator>
    <dc:language>{escape_html(language)}</dc:language>
    <meta property="dcterms:modified">{escape_html(modified)}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="style" href="style.css" media-type="text/css"/>
    <item id="title-page" href="title.xhtml" media-type="application/xhtml+xml"/>
{manifest_items}
  </manifest>
  <spine>
    <itemref idref="title-page"/>
{spine_items}
  </spine>
</package>
"""


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def escape_attr(text: str) -> str:
    return html.escape(text, quote=True)


def write_mobi(
    mobi_path: Path,
    epub_path: Path,
    title: str,
    chapters: list[Chapter],
    author: str,
    language: str,
    converter: str | None,
) -> str:
    converter_path = Path(converter).expanduser().resolve() if converter else find_mobi_converter()
    if converter_path:
        try:
            convert_epub_to_mobi(epub_path, mobi_path, converter_path, title, author)
            return ""
        except Exception as exc:  # noqa: BLE001
            write_basic_mobi(mobi_path, title, chapters, author=author, language=language)
            return (
                f"External converter failed ({exc}). "
                "A basic MOBI file was written directly as a fallback."
            )

    write_basic_mobi(mobi_path, title, chapters, author=author, language=language)
    return (
        "No ebook-convert/kindlegen converter was found. "
        "A basic MOBI file was written directly; install Calibre for a richer Kindle conversion."
    )


def find_mobi_converter() -> Path | None:
    for name in ("ebook-convert", "ebook-convert.exe", "kindlegen", "kindlegen.exe"):
        located = shutil.which(name)
        if located:
            return Path(located)

    candidates: list[Path] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if not base:
            continue
        candidates.extend(
            [
                Path(base) / "Calibre2" / "ebook-convert.exe",
                Path(base) / "calibre" / "ebook-convert.exe",
                Path(base) / "Kindle Previewer 3" / "lib" / "fc" / "bin" / "kindlegen.exe",
            ]
        )
    for path in candidates:
        if path.is_file():
            return path
    return None


def convert_epub_to_mobi(
    epub_path: Path,
    mobi_path: Path,
    converter_path: Path,
    title: str,
    author: str,
) -> None:
    lower_name = converter_path.name.lower()
    if "kindlegen" in lower_name:
        command = [str(converter_path), str(epub_path), "-o", mobi_path.name]
        working_dir = mobi_path.parent
    else:
        command = [
            str(converter_path),
            str(epub_path),
            str(mobi_path),
            "--title",
            title,
            "--authors",
            author,
        ]
        working_dir = None

    completed = subprocess.run(
        command,
        cwd=str(working_dir) if working_dir else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "unknown converter error").strip()
        raise RuntimeError(message)
    if not mobi_path.is_file():
        raise RuntimeError("converter did not create the MOBI file")


def write_basic_mobi(
    mobi_path: Path,
    title: str,
    chapters: list[Chapter],
    author: str,
    language: str,
) -> None:
    text_bytes = legacy_mobi_html(title, chapters, author=author, language=language).encode("utf-8")
    text_records = split_bytes_safely(text_bytes, RECORD_SIZE)
    if not text_records:
        text_records = [b""]

    record_0 = mobi_record_0(title, text_length=len(text_bytes), text_record_count=len(text_records))
    records = [record_0, *text_records]
    mobi_path.write_bytes(pdb_file(title, records))


def legacy_mobi_html(title: str, chapters: list[Chapter], author: str, language: str) -> str:
    toc_items = "\n".join(
        f'<p><a href="#chapter-{index}">{escape_html(chapter.title)}</a></p>'
        for index, chapter in enumerate(chapters, start=1)
    )
    chapter_html: list[str] = []
    for index, chapter in enumerate(chapters, start=1):
        paragraphs = "\n".join(f"<p>{escape_html(paragraph)}</p>" for paragraph in chapter.paragraphs)
        chapter_html.append(
            f'<mbp:pagebreak/><h2><a name="chapter-{index}"></a>{index}. {escape_html(chapter.title)}</h2>\n{paragraphs}'
        )
    chapters_joined = "\n".join(chapter_html)
    return f"""<html>
<head>
<meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
<title>{escape_html(title)}</title>
</head>
<body lang="{escape_attr(language)}">
<h1>{escape_html(title)}</h1>
<p>{escape_html(author)}</p>
<h2>Contents</h2>
{toc_items}
{chapters_joined}
</body>
</html>
"""


def split_bytes_safely(data: bytes, chunk_size: int) -> list[bytes]:
    chunks: list[bytes] = []
    start = 0
    while start < len(data):
        end = min(start + chunk_size, len(data))
        while end > start:
            try:
                data[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        if end == start:
            end = min(start + chunk_size, len(data))
        chunks.append(data[start:end])
        start = end
    return chunks


def mobi_record_0(title: str, text_length: int, text_record_count: int) -> bytes:
    title_bytes = title.encode("utf-8")
    full_name_offset = 16 + 232
    full_name = pad_to_multiple(title_bytes + b"\x00\x00", 4)

    palmdoc = (
        be16(1)
        + be16(0)
        + be32(text_length)
        + be16(text_record_count)
        + be16(RECORD_SIZE)
        + be32(0)
    )

    mobi = bytearray(232)
    put_bytes(mobi, 0, b"MOBI")
    put32(mobi, 4, 232)
    put32(mobi, 8, 2)
    put32(mobi, 12, 65001)
    put32(mobi, 16, int(time.time()) & 0xFFFFFFFF)
    put32(mobi, 20, 6)
    for offset in (24, 28, 32, 36, 40, 44, 48, 52, 56, 60):
        put32(mobi, offset, 0xFFFFFFFF)
    put32(mobi, 64, text_record_count + 1)
    put32(mobi, 68, full_name_offset)
    put32(mobi, 72, len(title_bytes))
    put32(mobi, 76, 1033)
    put32(mobi, 80, 0)
    put32(mobi, 84, 0)
    put32(mobi, 88, 6)
    put32(mobi, 92, 0xFFFFFFFF)
    put32(mobi, 96, 0)
    put32(mobi, 100, 0)
    put32(mobi, 104, 0)
    put32(mobi, 108, 0)
    put32(mobi, 112, 0)
    put32(mobi, 148, 0xFFFFFFFF)
    put32(mobi, 152, 0xFFFFFFFF)
    put32(mobi, 156, 0xFFFFFFFF)
    put32(mobi, 160, 0)
    put32(mobi, 164, 0)
    put16(mobi, 176, 1)
    put16(mobi, 178, text_record_count)
    put32(mobi, 180, 1)
    put32(mobi, 184, 0xFFFFFFFF)
    put32(mobi, 188, 1)
    put32(mobi, 208, 0xFFFFFFFF)
    put32(mobi, 212, 0)
    put32(mobi, 216, 0xFFFFFFFF)
    put32(mobi, 220, 0xFFFFFFFF)
    put32(mobi, 224, 0)
    put32(mobi, 228, 0xFFFFFFFF)

    return palmdoc + bytes(mobi) + full_name


def pdb_file(title: str, records: list[bytes]) -> bytes:
    record_count = len(records)
    header_size = 78 + (8 * record_count)
    offsets: list[int] = []
    offset = header_size
    for record in records:
        offsets.append(offset)
        offset += len(record)

    now = int(time.time()) + 2082844800
    header = bytearray()
    header.extend(truncate_utf8(title, 31).ljust(32, b"\x00"))
    header.extend(be16(0))
    header.extend(be16(0))
    header.extend(be32(now))
    header.extend(be32(now))
    header.extend(be32(0))
    header.extend(be32(0))
    header.extend(be32(0))
    header.extend(be32(0))
    header.extend(b"BOOK")
    header.extend(b"MOBI")
    header.extend(be32(record_count + 1))
    header.extend(be32(0))
    header.extend(be16(record_count))
    for index, record_offset in enumerate(offsets, start=1):
        header.extend(be32(record_offset))
        header.extend(bytes([0]))
        header.extend(index.to_bytes(3, "big"))
    return bytes(header) + b"".join(records)


def truncate_utf8(text: str, max_bytes: int) -> bytes:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    truncated = encoded[:max_bytes]
    while truncated:
        try:
            truncated.decode("utf-8")
            return truncated
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return b""


def pad_to_multiple(data: bytes, multiple: int) -> bytes:
    remainder = len(data) % multiple
    if not remainder:
        return data
    return data + (b"\x00" * (multiple - remainder))


def put_bytes(buffer: bytearray, offset: int, value: bytes) -> None:
    buffer[offset : offset + len(value)] = value


def put16(buffer: bytearray, offset: int, value: int) -> None:
    buffer[offset : offset + 2] = be16(value)


def put32(buffer: bytearray, offset: int, value: int) -> None:
    buffer[offset : offset + 4] = be32(value)


def be16(value: int) -> bytes:
    return struct.pack(">H", value & 0xFFFF)


def be32(value: int) -> bytes:
    return struct.pack(">I", value & 0xFFFFFFFF)


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1F]+', "_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "ebook"
    return cleaned[:120]


if __name__ == "__main__":
    raise SystemExit(main())
