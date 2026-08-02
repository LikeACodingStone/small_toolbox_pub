#!/usr/bin/env python3
import argparse
import configparser
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from transcribe_module import (
    COMPLETE_MARKER,
    build_translation_text,
    load_filter_words,
    load_translation_config,
)


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"
OLLAMA_API = "http://localhost:11434/api/generate"

HEADER_RE = re.compile(
    r"\*\*\[(?P<start>\d+(?:\.\d+)?)s\]\s*English:\*\*\s*",
    re.IGNORECASE,
)


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"subtitle_improve_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.info("Log file: %s", log_file)
    return log_file


def resolve_config_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def load_config_paths():
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    section = parser["OriginalConfigPath"]

    original_audio_path = resolve_config_path(
        os.getenv("AUDIOSOURCE_SRC_DIR", section.get("OriginalAudioPath", "../Resource/Dwark"))
    )
    translate_root = resolve_config_path(
        os.getenv("AUDIOSOURCE_TRANSLATE_DIR", section.get("TranslatePath", "../Resource/translate"))
    )
    source_name = original_audio_path.name
    return translate_root / source_name, translate_root / f"{source_name}_IPV"


def parse_md_segments(content):
    matches = list(HEADER_RE.finditer(content))
    rows = []

    for index, match in enumerate(matches):
        start_seconds = float(match.group("start"))
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[block_start:block_end].replace(COMPLETE_MARKER, "").strip("\n")

        english_lines = []
        translation_lines = []
        in_translation = False

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            translation_match = re.match(r"^\*\*Translation:\*\*\s*(?P<value>.*)$", line, re.IGNORECASE)
            if translation_match:
                in_translation = True
                value = translation_match.group("value").strip()
                if value:
                    translation_lines.append(value)
                continue

            if re.match(r"^\*\*[^*\n]+:\*\*", line):
                in_translation = True
                continue

            if in_translation:
                translation_lines.append(line)
            else:
                english_lines.append(line)

        english_text = " ".join(" ".join(english_lines).split())
        translation_text = " ".join(" ".join(translation_lines).split())
        if english_text:
            rows.append(
                {
                    "start": start_seconds,
                    "english": english_text,
                    "translation": translation_text,
                }
            )

    rows.sort(key=lambda item: item["start"])
    return rows


def read_preamble(content):
    match = HEADER_RE.search(content)
    if not match:
        return "# Podcast vocabulary notes\n"

    preamble = content[: match.start()].replace(COMPLETE_MARKER, "").strip()
    if not preamble:
        return "# Podcast vocabulary notes\n"
    return preamble + "\n"


def get_ollama_model(cli_model=None):
    if cli_model:
        return cli_model
    return os.getenv("AUDIOSOURCE_OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"


def normalize_ollama_text(value):
    value = str(value or "").strip()
    value = re.sub(r"^```(?:text)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    value = value.strip().strip('"').strip("'").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def improve_punctuation(text, model_name, cache):
    original = " ".join(str(text or "").split())
    if not original:
        return original
    if original in cache:
        return cache[original]

    prompt = (
        "Add natural English punctuation and capitalization to this transcript segment.\n"
        "Keep the same language and meaning. Do not translate. Do not explain.\n"
        "Do not add new facts. Return only the improved sentence text.\n\n"
        f"Transcript:\n{original}"
    )
    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0},
    }

    try:
        response = requests.post(OLLAMA_API, json=payload, timeout=60)
        response.raise_for_status()
        improved = normalize_ollama_text(response.json().get("response", ""))
    except Exception:
        logging.exception("Ollama punctuation failed; keeping original text: %r", original[:200])
        improved = original

    if not improved:
        improved = original

    cache[original] = improved
    return improved


def write_markdown_segment(handle, start_seconds, english_text, translation_text):
    handle.write(f"**[{start_seconds:.2f}s] English:** {english_text}  \n")
    handle.write(f"**Translation:** {translation_text}\n\n")


def improve_file(input_path, output_path, model_name, filter_words, translation_config, overwrite=True):
    input_path = Path(input_path)
    output_path = Path(output_path)

    if output_path.exists() and not overwrite:
        logging.info("Skip existing output: %s", output_path)
        return "skipped"

    content = input_path.read_text(encoding="utf-8", errors="ignore")
    rows = parse_md_segments(content)
    if not rows:
        logging.warning("No markdown segments found, skip: %s", input_path)
        return "no_segments"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    punctuation_cache = {}
    improved_rows = []

    for index, row in enumerate(rows, start=1):
        improved_text = improve_punctuation(row["english"], model_name, punctuation_cache)
        improved_rows.append({**row, "english": improved_text})
        if index == 1 or index % 25 == 0:
            logging.info("Punctuation progress %s %d/%d", input_path.name, index, len(rows))

    segments_per_translation = translation_config["segments_per_translation"]
    repeat_window_seconds = translation_config["repeat_window_seconds"]
    recent_translations = {}

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(read_preamble(content))
        handle.write("Improved subtitle: punctuation and vocabulary regenerated from current config.\n\n")

        for start_index in range(0, len(improved_rows), segments_per_translation):
            group = improved_rows[start_index : start_index + segments_per_translation]
            combined_text = " ".join(row["english"] for row in group if row["english"])
            translation_text = build_translation_text(
                group[-1]["start"],
                combined_text,
                filter_words=filter_words,
                recent_translations=recent_translations,
                repeat_window_seconds=repeat_window_seconds,
            )

            for group_index, row in enumerate(group):
                segment_translation = translation_text if group_index == len(group) - 1 else ""
                write_markdown_segment(handle, row["start"], row["english"], segment_translation)

        handle.write(f"\n{COMPLETE_MARKER}\n")

    logging.info("Improved subtitle written: %s", output_path)
    return "ok"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Improve generated markdown subtitles without creating audio.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Directory containing source .md subtitles.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for improved .md subtitles.")
    parser.add_argument("--model", default=None, help="Ollama model used for punctuation.")
    parser.add_argument("--skip-existing", action="store_true", help="Do not overwrite files already in output-dir.")
    return parser


def main(argv=None):
    setup_logging()
    args = build_arg_parser().parse_args(argv)

    configured_input_dir, configured_output_dir = load_config_paths()
    input_dir = args.input_dir.resolve() if args.input_dir else configured_input_dir
    output_dir = args.output_dir.resolve() if args.output_dir else configured_output_dir
    model_name = get_ollama_model(args.model)

    logging.info("CONFIG_FILE=%s", CONFIG_FILE)
    logging.info("INPUT_DIR=%s", input_dir)
    logging.info("OUTPUT_DIR=%s", output_dir)
    logging.info("OLLAMA_MODEL=%s", model_name)

    if not input_dir.exists():
        logging.error("Input subtitle directory does not exist: %s", input_dir)
        return 1

    md_files = sorted(path for path in input_dir.rglob("*.md") if path.is_file())
    logging.info("Found %d markdown subtitle files", len(md_files))
    if not md_files:
        return 0

    filter_words = load_filter_words()
    translation_config = load_translation_config()

    completed = 0
    skipped = 0
    failed = 0
    start_time = time.monotonic()

    for md_path in md_files:
        relative_path = md_path.relative_to(input_dir)
        output_path = output_dir / relative_path
        try:
            status = improve_file(
                md_path,
                output_path,
                model_name=model_name,
                filter_words=filter_words,
                translation_config=translation_config,
                overwrite=not args.skip_existing,
            )
            if status == "ok":
                completed += 1
            else:
                skipped += 1
        except Exception:
            failed += 1
            logging.exception("Failed to improve subtitle: %s", md_path)

    logging.info(
        "Subtitle improve completed: improved=%d skipped=%d failed=%d elapsed=%.2fs",
        completed,
        skipped,
        failed,
        time.monotonic() - start_time,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
