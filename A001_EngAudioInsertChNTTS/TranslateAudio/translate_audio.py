#!/usr/bin/env python3
import argparse
import configparser
import logging
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from tts_module import (
    INSERT_AFTER_TTS_SILENCE_MS,
    INSERT_BEFORE_TTS_SILENCE_MS,
    build_output_profile,
    clean_tts_text,
    create_original_audio_segment,
    create_silence_audio,
    ffconcat_escape,
    ffmpeg_audio_shape_args,
    get_audio_duration_seconds,
    normalize_tts_paths_for_concat,
    parse_md_segments,
    require_ffmpeg,
    run_cmd,
    run_tts_limited,
    should_skip_tts,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"
AUDIO_SUFFIXES = (".mp3", ".opus")
NUMBER_RE = re.compile(r"\d+")


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"translate_audio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
    logging.info("Log file: %s", log_file)


def resolve_config_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def load_config_paths():
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    section = parser["OriginalConfigPath"]
    source_dir = resolve_config_path(
        os.getenv("AUDIOSOURCE_SRC_DIR", section.get("OriginalAudioPath", "../../Resource/Dwark"))
    )
    translation_root = resolve_config_path(
        os.getenv("AUDIOSOURCE_TRANSLATE_DIR", section.get("TranslatePath", "../../Resource/translate"))
    )
    audio_root = resolve_config_path(
        os.getenv(
            "AUDIOSOURCE_AUDIO_TRANSLATED_DIR",
            section.get("AudioTranslatedPath", "../../Resource/chineseTTS"),
        )
    )
    config = parser["TranslateAudioConfig"] if parser.has_section("TranslateAudioConfig") else {}
    suffix = config.get("OutputSuffix", "_TranslateAudio") if config else "_TranslateAudio"
    return source_dir, translation_root / source_dir.name, audio_root / source_dir.name, suffix.strip() or "_TranslateAudio"


def norm_name(value):
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = normalized.replace("\u30fb", " ").replace("_", " ").replace("-", " ")
    return "".join(ch.lower() for ch in normalized if ch.isalnum())


def natural_path_key(path, source_dir):
    try:
        value = str(path.relative_to(source_dir))
    except ValueError:
        value = str(path)
    parts = []
    position = 0
    value = value.casefold()
    for match in NUMBER_RE.finditer(value):
        if match.start() > position:
            parts.append((1, value[position : match.start()]))
        parts.append((0, int(match.group(0)), len(match.group(0))))
        position = match.end()
    if position < len(value):
        parts.append((1, value[position:]))
    return tuple(parts)


def find_markdown(translation_dir, stem):
    if not translation_dir.exists():
        return None
    normalized_stem = norm_name(stem)
    candidates = sorted(path for path in translation_dir.rglob("*.md") if path.is_file())
    for path in candidates:
        if norm_name(path.stem) == normalized_stem:
            return path
    for path in candidates:
        normalized_path = norm_name(path.stem)
        if normalized_stem and normalized_path and (
            normalized_stem in normalized_path or normalized_path in normalized_stem
        ):
            return path
    return None


def output_path_for_source(audio_path, output_dir, suffix):
    audio_path = Path(audio_path)
    return output_dir / f"{audio_path.stem}{suffix}{audio_path.suffix.lower()}"


def row_has_vocabulary(row):
    translation = clean_tts_text(row.get("translation", ""))
    return bool(translation) and not should_skip_tts(translation)


def sentence_vocabulary(row):
    """Accept only explicit word/meaning pairs whose word occurs in this row.

    Older Markdown attaches a whole group's vocabulary to its final row.
    Its group boundaries are not recorded, so never guess another sentence's
    translation from neighboring rows.
    """
    def normalize(text):
        return unicodedata.normalize("NFKC", text).replace("’", "'").casefold()

    english = normalize(row.get("english", ""))
    raw = re.sub(r"\*\*|`", "", row.get("translation", ""))
    raw = re.sub(r"^\s*Vocabulary\s*[:：]\s*", "", raw, flags=re.IGNORECASE)
    accepted = []
    for entry in re.split(r"[;；\n]", raw):
        pair = re.fullmatch(r"\s*([A-Za-z][A-Za-z’' -]*?)\s*[:：]\s*(\S.*?)\s*", entry)
        if not pair:
            if entry.strip():
                logging.warning("Omit unrecognized vocabulary at %.2fs: %r", row["start"], entry)
            continue
        word, meaning = pair.groups()
        pattern = r"(?<![\w'-])" + re.escape(normalize(word)) + r"(?![\w'-])"
        if re.search(pattern, english):
            accepted.append(f"{word}: {meaning}")
        else:
            logging.warning("Omit vocabulary absent from sentence at %.2fs: %s", row["start"], word)
    return "; ".join(accepted)


def write_filtered_concat(rows, tts_paths, original_audio, original_duration, output_path, tmp_dir):
    ffmpeg, ffprobe = require_ffmpeg()
    profile = build_output_profile(original_audio, output_path, ffprobe)
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    silence_before = create_silence_audio(
        tmp_dir / f"silence_before_{INSERT_BEFORE_TTS_SILENCE_MS}ms{profile['suffix']}",
        INSERT_BEFORE_TTS_SILENCE_MS,
        ffmpeg,
        profile,
    )
    silence_after = create_silence_audio(
        tmp_dir / f"silence_after_{INSERT_AFTER_TTS_SILENCE_MS}ms{profile['suffix']}",
        INSERT_AFTER_TTS_SILENCE_MS,
        ffmpeg,
        profile,
    )
    tts_paths = normalize_tts_paths_for_concat(tts_paths, tmp_dir, profile, ffmpeg)
    concat_file = tmp_dir / "translate_audio.ffconcat"
    original_segments_dir = tmp_dir / "original_segments"
    entries = 0

    with concat_file.open("w", encoding="utf-8") as handle:
        handle.write("ffconcat version 1.0\n")
        for index, row in enumerate(rows):
            start_seconds = max(0.0, float(row["start"]))
            next_seconds = float(row.get("next_start", original_duration))
            next_seconds = min(next_seconds, original_duration)
            if start_seconds >= original_duration or next_seconds <= start_seconds:
                logging.warning("Skip invalid selected segment index=%d start=%.3f next=%.3f", index, start_seconds, next_seconds)
                continue

            segment_path = original_segments_dir / (
                f"original_{index:05d}_{int(start_seconds * 1000):012d}_{int(next_seconds * 1000):012d}{profile['suffix']}"
            )
            segment_path = create_original_audio_segment(
                original_audio,
                start_seconds,
                next_seconds - start_seconds,
                segment_path,
                ffmpeg,
                profile,
            ).resolve()
            tts_path = tts_paths[index] if index < len(tts_paths) else None
            if not tts_path or not Path(tts_path).exists() or Path(tts_path).stat().st_size <= 0:
                logging.warning("Skip selected segment without vocabulary TTS index=%d", index)
                continue

            tts_path = Path(tts_path).resolve()
            for _ in range(2):
                handle.write(f"file '{ffconcat_escape(segment_path)}'\n")
                handle.write(f"file '{ffconcat_escape(silence_before)}'\n")
                handle.write(f"file '{ffconcat_escape(tts_path)}'\n")
                handle.write(f"file '{ffconcat_escape(silence_after)}'\n")
                entries += 4
            handle.write(f"file '{ffconcat_escape(segment_path)}'\n")
            entries += 1

    if entries == 0:
        raise RuntimeError("No selected segments were written to the concat list")

    tmp_output = output_path.with_name(output_path.stem + ".part" + output_path.suffix)
    if tmp_output.exists():
        tmp_output.unlink()
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-vn",
    ]
    command.extend(ffmpeg_audio_shape_args(profile))
    command.extend(
        [
            "-f",
            profile["format"],
            "-c:a",
            profile["codec"],
            "-b:a",
            profile["bitrate"],
            str(tmp_output),
        ]
    )
    run_cmd(command, "Export filtered TranslateAudio")
    if not tmp_output.exists() or tmp_output.stat().st_size <= 0:
        raise RuntimeError(f"FFmpeg produced empty output: {tmp_output}")
    tmp_output.replace(output_path)


def process_one(audio_path, translation_dir, output_dir, output_suffix, force=False):
    audio_path = Path(audio_path)
    output_path = output_path_for_source(audio_path, output_dir, output_suffix)
    if not force and output_path.exists() and output_path.stat().st_size > 0:
        logging.info("Skip existing output: %s", output_path)
        return "skipped"

    markdown_path = find_markdown(translation_dir, audio_path.stem)
    if not markdown_path:
        logging.warning("No translation markdown found for: %s", audio_path)
        return "no_translation"

    rows = parse_md_segments(markdown_path.read_text(encoding="utf-8", errors="ignore"))
    all_rows = sorted(rows, key=lambda item: item["start"])
    selected_rows = []
    for index, row in enumerate(all_rows):
        row = {**row, "translation": sentence_vocabulary(row)}
        if not row_has_vocabulary(row):
            continue
        selected_rows.append(
            {
                **row,
                "next_start": all_rows[index + 1]["start"] if index + 1 < len(all_rows) else None,
            }
        )

    if not selected_rows:
        logging.info("No vocabulary sentences found in: %s", markdown_path)
        if force and output_path.exists():
            output_path.unlink()
            logging.info("Removed outdated output with no sentence-matched vocabulary: %s", output_path)
        return "no_vocabulary"

    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / ".translate_audio_tmp" / output_path.stem
    tts_paths = __import__("asyncio").run(run_tts_limited(selected_rows, tmp_dir / "tts"))
    ffprobe = require_ffmpeg()[1]
    duration = get_audio_duration_seconds(audio_path, ffprobe)
    selected_rows = [
        {**row, "next_start": duration if row["next_start"] is None else row["next_start"]}
        for row in selected_rows
    ]
    logging.info("Generating %d vocabulary sentences from %s", len(selected_rows), markdown_path)
    write_filtered_concat(selected_rows, tts_paths, audio_path, duration, output_path, tmp_dir)
    logging.info("Generated: %s", output_path)
    return "ok"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Create audio from vocabulary sentences only.")
    parser.add_argument("--translate-dir", "--input-dir", dest="translate_dir", type=Path, default=None)
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Rebuild existing audio; remove old output if no sentence-matched vocabulary remains.")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    setup_logging()
    source_dir, configured_translation_dir, configured_output_dir, output_suffix = load_config_paths()
    source_dir = args.source_dir.resolve() if args.source_dir else source_dir
    translation_dir = args.translate_dir.resolve() if args.translate_dir else configured_translation_dir
    output_dir = args.output_dir.resolve() if args.output_dir else configured_output_dir
    logging.info("SOURCE_DIR=%s", source_dir)
    logging.info("TRANSLATE_DIR=%s", translation_dir)
    logging.info("OUTPUT_DIR=%s", output_dir)

    if not source_dir.exists():
        logging.error("Source directory does not exist: %s", source_dir)
        return 1
    files = sorted(
        (path for path in source_dir.rglob("*") if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES),
        key=lambda path: natural_path_key(path, source_dir),
    )
    completed = 0
    failed = 0
    for audio_path in files:
        try:
            status = process_one(audio_path, translation_dir, output_dir, output_suffix, force=args.force)
            if status == "ok":
                completed += 1
        except Exception:
            failed += 1
            logging.exception("TranslateAudio failed: %s", audio_path)
    logging.info("TranslateAudio completed: generated=%d failed=%d total=%d", completed, failed, len(files))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
