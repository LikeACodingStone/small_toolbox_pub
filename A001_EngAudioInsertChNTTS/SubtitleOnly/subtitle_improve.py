#!/usr/bin/env python3
import argparse
import configparser
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"
OLLAMA_API = "http://localhost:11434/api/generate"
DEFAULT_NO_OUTPUT_TIMEOUT_SECONDS = 8 * 60 * 60
COMPLETE_MARKER = "<!-- TRANSCRIPTION_COMPLETE -->"
OLLAMA_SEMAPHORE = None

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


def load_transcribe_helpers():
    from transcribe_module import build_translation_text, load_filter_words, load_translation_config

    return build_translation_text, load_filter_words, load_translation_config


class NoOutputProgressError(RuntimeError):
    pass


class ProgressMonitor:
    def __init__(self, timeout_seconds):
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self.last_output_at = time.monotonic()
        self.last_output_path = None
        self.last_output_reason = "startup"
        self.active_files = {}
        self.stop_event = threading.Event()
        self._lock = threading.Lock()
        self._timeout_logged = False

    def update_file(self, input_path, stage, current=0, total=0):
        with self._lock:
            self.active_files[str(input_path)] = {
                "stage": stage,
                "current": current,
                "total": total,
            }

    def finish_file(self, input_path):
        with self._lock:
            self.active_files.pop(str(input_path), None)

    def mark_output(self, output_path, reason):
        with self._lock:
            self.last_output_at = time.monotonic()
            self.last_output_path = str(output_path)
            self.last_output_reason = reason

    def check(self):
        if self.stop_event.is_set():
            raise NoOutputProgressError("Subtitle improvement stopped because output progress timed out")

        if self.timeout_seconds <= 0:
            return

        elapsed = time.monotonic() - self.last_output_at
        if elapsed <= self.timeout_seconds:
            return

        with self._lock:
            if not self._timeout_logged:
                active = []
                for path, state in sorted(self.active_files.items()):
                    current = state["current"]
                    total = state["total"]
                    progress = f"{current}/{total}" if total else "unknown"
                    active.append(f"{Path(path).name} stage={state['stage']} progress={progress}")

                logging.error(
                    "No subtitle output file was completed or updated for %.1f hours; stopping automatically. "
                    "last_output=%s last_reason=%s active=%s. "
                    "Likely cause: active files are waiting on Ollama punctuation/translation requests or are very long.",
                    elapsed / 3600,
                    self.last_output_path or "<none>",
                    self.last_output_reason,
                    " | ".join(active) if active else "<none>",
                )
                self._timeout_logged = True
            self.stop_event.set()

        raise NoOutputProgressError("Subtitle output progress timeout")


def env_positive_int(name, default):
    value = os.getenv(name)
    if value is None:
        return max(1, int(default))
    try:
        return max(1, int(value))
    except ValueError:
        logging.warning("Invalid %s=%r, using default=%s", name, value, default)
        return max(1, int(default))


def env_nonnegative_float(name, default):
    value = os.getenv(name)
    if value is None:
        return max(0.0, float(default))
    try:
        return max(0.0, float(value))
    except ValueError:
        logging.warning("Invalid %s=%r, using default=%s", name, value, default)
        return max(0.0, float(default))


def configure_ollama_concurrency(limit):
    global OLLAMA_SEMAPHORE
    OLLAMA_SEMAPHORE = threading.BoundedSemaphore(max(1, int(limit)))


def acquire_ollama_slot(stop_event=None):
    semaphore = OLLAMA_SEMAPHORE
    if semaphore is None:
        return None

    while True:
        if stop_event is not None and stop_event.is_set():
            raise NoOutputProgressError("Subtitle improvement stopped before Ollama request")
        if semaphore.acquire(timeout=1):
            return semaphore


def post_ollama(payload, timeout, stop_event=None):
    semaphore = acquire_ollama_slot(stop_event=stop_event)
    if semaphore is None:
        return requests.post(OLLAMA_API, json=payload, timeout=timeout)

    try:
        if stop_event is not None and stop_event.is_set():
            raise NoOutputProgressError("Subtitle improvement stopped before Ollama request")
        return requests.post(OLLAMA_API, json=payload, timeout=timeout)
    finally:
        semaphore.release()


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


def improve_punctuation_request(text, model_name, stop_event=None):
    original = " ".join(str(text or "").split())
    if not original:
        return original

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
        response = post_ollama(payload, timeout=60, stop_event=stop_event)
        response.raise_for_status()
        improved = normalize_ollama_text(response.json().get("response", ""))
    except NoOutputProgressError:
        raise
    except Exception:
        logging.exception("Ollama punctuation failed; keeping original text: %r", original[:200])
        improved = original

    if not improved:
        improved = original

    return improved


def build_translation_text_limited(
    translation_builder,
    start_seconds,
    english_text,
    filter_words=None,
    recent_translations=None,
    repeat_window_seconds=0,
    stop_event=None,
):
    semaphore = acquire_ollama_slot(stop_event=stop_event)
    try:
        if stop_event is not None and stop_event.is_set():
            raise NoOutputProgressError("Subtitle improvement stopped before translation request")
        return translation_builder(
            start_seconds,
            english_text,
            filter_words=filter_words,
            recent_translations=recent_translations,
            repeat_window_seconds=repeat_window_seconds,
        )
    finally:
        if semaphore is not None:
            semaphore.release()


def improve_punctuation(text, model_name, cache):
    original = " ".join(str(text or "").split())
    if not original:
        return original
    if original in cache:
        return cache[original]

    improved = improve_punctuation_request(original, model_name)
    cache[original] = improved
    return improved


def write_markdown_segment(handle, start_seconds, english_text, translation_text):
    handle.write(f"**[{start_seconds:.2f}s] English:** {english_text}  \n")
    handle.write(f"**Translation:** {translation_text}\n\n")


def improve_rows_concurrently(rows, model_name, punctuation_workers, progress_monitor=None, input_path=None):
    if not rows:
        return []

    punctuation_workers = max(1, int(punctuation_workers))
    improved_rows = [None] * len(rows)
    text_to_indexes = {}
    for index, row in enumerate(rows):
        original = " ".join(str(row["english"] or "").split())
        text_to_indexes.setdefault(original, []).append(index)
    unique_texts = [text for text in text_to_indexes if text]
    completed_rows = 0
    if not unique_texts:
        return rows

    def worker(original):
        if progress_monitor is not None:
            progress_monitor.check()
        stop_event = progress_monitor.stop_event if progress_monitor is not None else None
        return original, improve_punctuation_request(original, model_name, stop_event=stop_event)

    def store_result(original, improved_text):
        nonlocal completed_rows
        for index in text_to_indexes.get(original, []):
            improved_rows[index] = {**rows[index], "english": improved_text}
        completed_rows += len(text_to_indexes.get(original, []))
        if progress_monitor is not None:
            progress_monitor.check()
            progress_monitor.update_file(input_path, "punctuation", completed_rows, len(rows))
        if completed_rows == len(text_to_indexes.get(original, [])) or completed_rows % 25 == 0 or completed_rows == len(rows):
            logging.info("Punctuation progress %s %d/%d", Path(input_path).name, completed_rows, len(rows))

    if punctuation_workers == 1 or len(unique_texts) == 1:
        for original in unique_texts:
            if progress_monitor is not None:
                progress_monitor.check()
            _original, improved_text = worker(original)
            store_result(_original, improved_text)
        return improved_rows

    executor = ThreadPoolExecutor(max_workers=punctuation_workers)
    pending = set()
    text_iter = iter(unique_texts)

    def submit_next():
        if progress_monitor is not None:
            progress_monitor.check()
        try:
            original = next(text_iter)
        except StopIteration:
            return False
        pending.add(executor.submit(worker, original))
        return True

    try:
        for _ in range(min(punctuation_workers, len(unique_texts))):
            submit_next()

        while pending:
            done, pending = wait(pending, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                if progress_monitor is not None:
                    progress_monitor.check()
                continue
            for future in done:
                original, improved_text = future.result()
                store_result(original, improved_text)
                submit_next()
    except NoOutputProgressError:
        for future in pending:
            future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return improved_rows


def improve_file(
    input_path,
    output_path,
    model_name,
    filter_words,
    translation_config,
    translation_builder,
    overwrite=True,
    progress_monitor=None,
    punctuation_workers=1,
):
    input_path = Path(input_path)
    output_path = Path(output_path)

    if output_path.exists() and not overwrite:
        existing_content = output_path.read_text(encoding="utf-8", errors="ignore")
        if COMPLETE_MARKER in existing_content:
            logging.info("Skip existing completed output: %s", output_path)
            return "skipped"
        logging.warning("Existing output is incomplete; rebuilding: %s", output_path)

    content = input_path.read_text(encoding="utf-8", errors="ignore")
    rows = parse_md_segments(content)
    if not rows:
        logging.warning("No markdown segments found, skip: %s", input_path)
        return "no_segments"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if progress_monitor is not None:
        progress_monitor.update_file(input_path, "read", 0, len(rows))
    improved_rows = improve_rows_concurrently(
        rows,
        model_name,
        punctuation_workers=punctuation_workers,
        progress_monitor=progress_monitor,
        input_path=input_path,
    )

    segments_per_translation = translation_config["segments_per_translation"]
    repeat_window_seconds = translation_config["repeat_window_seconds"]
    recent_translations = {}

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(read_preamble(content))
        handle.write("Improved subtitle: punctuation and vocabulary regenerated from current config.\n\n")

        total_groups = (len(improved_rows) + segments_per_translation - 1) // segments_per_translation
        for start_index in range(0, len(improved_rows), segments_per_translation):
            if progress_monitor is not None:
                progress_monitor.check()
                progress_monitor.update_file(
                    input_path,
                    "translation",
                    start_index // segments_per_translation + 1,
                    total_groups,
                )
            group = improved_rows[start_index : start_index + segments_per_translation]
            combined_text = " ".join(row["english"] for row in group if row["english"])
            stop_event = progress_monitor.stop_event if progress_monitor is not None else None
            translation_text = build_translation_text_limited(
                translation_builder,
                group[-1]["start"],
                combined_text,
                filter_words=filter_words,
                recent_translations=recent_translations,
                repeat_window_seconds=repeat_window_seconds,
                stop_event=stop_event,
            )

            for group_index, row in enumerate(group):
                segment_translation = translation_text if group_index == len(group) - 1 else ""
                write_markdown_segment(handle, row["start"], row["english"], segment_translation)
            handle.flush()
            if progress_monitor is not None:
                progress_monitor.mark_output(output_path, f"{input_path.name} group {start_index // segments_per_translation + 1}")

        handle.write(f"\n{COMPLETE_MARKER}\n")
        handle.flush()

    logging.info("Improved subtitle written: %s", output_path)
    return "ok"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Improve generated markdown subtitles without creating audio.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Directory containing source .md subtitles.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for improved .md subtitles.")
    parser.add_argument("--model", default=None, help="Ollama model used for punctuation.")
    parser.add_argument("--skip-existing", action="store_true", help="Do not overwrite files already in output-dir.")
    parser.add_argument("--workers", type=int, default=None, help="Number of subtitle files to process concurrently.")
    parser.add_argument(
        "--punctuation-workers",
        type=int,
        default=None,
        help="Concurrent punctuation requests per subtitle file.",
    )
    parser.add_argument(
        "--ollama-concurrency",
        type=int,
        default=None,
        help="Global concurrent Ollama requests for punctuation and vocabulary translation.",
    )
    parser.add_argument(
        "--no-output-timeout-hours",
        type=float,
        default=None,
        help="Stop if no output file is completed or updated for this many hours. Use 0 to disable.",
    )
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    setup_logging()

    configured_input_dir, configured_output_dir = load_config_paths()
    input_dir = args.input_dir.resolve() if args.input_dir else configured_input_dir
    output_dir = args.output_dir.resolve() if args.output_dir else configured_output_dir
    model_name = get_ollama_model(args.model)
    cpu_count = os.cpu_count() or 1
    default_workers = max(1, min(4, cpu_count // 2 or 1))
    workers = max(1, args.workers or env_positive_int("AUDIOSOURCE_SUBTITLE_WORKERS", default_workers))
    default_punctuation_workers = max(1, cpu_count // workers)
    punctuation_workers = max(
        1,
        args.punctuation_workers
        or env_positive_int("AUDIOSOURCE_SUBTITLE_PUNCTUATION_WORKERS", default_punctuation_workers),
    )
    default_ollama_concurrency = max(1, min(cpu_count, workers * punctuation_workers))
    ollama_concurrency = max(
        1,
        args.ollama_concurrency
        or env_positive_int("AUDIOSOURCE_SUBTITLE_OLLAMA_CONCURRENCY", default_ollama_concurrency),
    )
    timeout_hours = (
        max(0.0, float(args.no_output_timeout_hours))
        if args.no_output_timeout_hours is not None
        else env_nonnegative_float(
            "AUDIOSOURCE_SUBTITLE_NO_OUTPUT_TIMEOUT_HOURS",
            DEFAULT_NO_OUTPUT_TIMEOUT_SECONDS / 3600,
        )
    )
    no_output_timeout_seconds = timeout_hours * 3600
    configure_ollama_concurrency(ollama_concurrency)

    logging.info("CONFIG_FILE=%s", CONFIG_FILE)
    logging.info("INPUT_DIR=%s", input_dir)
    logging.info("OUTPUT_DIR=%s", output_dir)
    logging.info("OLLAMA_MODEL=%s", model_name)
    logging.info(
        "Subtitle concurrency: cpu_count=%s file_workers=%s punctuation_workers_per_file=%s "
        "ollama_concurrency=%s no_output_timeout_hours=%.2f",
        cpu_count,
        workers,
        punctuation_workers,
        ollama_concurrency,
        timeout_hours,
    )
    logging.info("Ollama decides GPU/CPU placement; subtitle_improve uses CPU cores to schedule parallel work.")

    if not input_dir.exists():
        logging.error("Input subtitle directory does not exist: %s", input_dir)
        return 1

    md_files = sorted(path for path in input_dir.rglob("*.md") if path.is_file())
    logging.info("Found %d markdown subtitle files", len(md_files))
    if not md_files:
        return 0

    build_translation_text, load_filter_words, load_translation_config = load_transcribe_helpers()
    filter_words = load_filter_words()
    translation_config = load_translation_config()

    completed = 0
    skipped = 0
    failed = 0
    start_time = time.monotonic()
    progress_monitor = ProgressMonitor(no_output_timeout_seconds)

    def process_md_file(md_path):
        relative_path = md_path.relative_to(input_dir)
        output_path = output_dir / relative_path
        progress_monitor.check()
        progress_monitor.update_file(md_path, "queued", 0, 0)
        try:
            status = improve_file(
                md_path,
                output_path,
                model_name=model_name,
                filter_words=filter_words,
                translation_config=translation_config,
                translation_builder=build_translation_text,
                overwrite=not args.skip_existing,
                progress_monitor=progress_monitor,
                punctuation_workers=punctuation_workers,
            )
            if status == "ok":
                progress_monitor.mark_output(output_path, "file complete")
            return status, md_path, output_path
        finally:
            progress_monitor.finish_file(md_path)

    worker_count = min(workers, len(md_files))
    executor = ThreadPoolExecutor(max_workers=worker_count)
    futures = {executor.submit(process_md_file, md_path): md_path for md_path in md_files}
    pending = set(futures)
    stop_for_timeout = False

    try:
        while pending:
            done, pending = wait(pending, timeout=60, return_when=FIRST_COMPLETED)
            if not done:
                progress_monitor.check()
                continue

            for future in done:
                md_path = futures[future]
                try:
                    status, _md_path, output_path = future.result()
                    if status == "ok":
                        completed += 1
                    else:
                        skipped += 1
                    logging.info(
                        "Subtitle file finished status=%s input=%s output=%s completed=%d skipped=%d failed=%d pending=%d",
                        status,
                        md_path,
                        output_path,
                        completed,
                        skipped,
                        failed,
                        len(pending),
                    )
                except NoOutputProgressError:
                    failed += 1
                    stop_for_timeout = True
                    progress_monitor.stop_event.set()
                    logging.exception("Stopping subtitle improve because no output file was updated in time: %s", md_path)
                    break
                except Exception:
                    failed += 1
                    logging.exception("Failed to improve subtitle: %s", md_path)
                    progress_monitor.check()

            if stop_for_timeout:
                break
    except NoOutputProgressError:
        failed += 1
        stop_for_timeout = True
        progress_monitor.stop_event.set()
        logging.exception("Stopping subtitle improve because no output file was updated in time")
    finally:
        if stop_for_timeout:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
        else:
            executor.shutdown(wait=True)

    logging.info(
        "Subtitle improve completed: improved=%d skipped=%d failed=%d elapsed=%.2fs stopped_for_timeout=%s",
        completed,
        skipped,
        failed,
        time.monotonic() - start_time,
        stop_for_timeout,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
