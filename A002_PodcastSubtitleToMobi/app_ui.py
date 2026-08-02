#!/usr/bin/env python3
from __future__ import annotations

import faulthandler
import json
import logging
import os
import queue
import shutil
import sys
import tempfile
import threading
import traceback
import uuid
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import gradio as gr

from subtitle_to_ebook import (
    ConversionOptions,
    ConversionResult,
    PhoneticOptions,
    convert_from_options,
)


DOWNLOAD_CACHE = tempfile.TemporaryDirectory(prefix="subtitle-to-ebook-ui-", ignore_cleanup_errors=True)
SERVER_LOG_STREAM = None
STATE_LOCK = threading.RLock()
UI_CSS = """
.folder-row {
    align-items: end;
}
.folder-picker {
    min-width: 112px !important;
    max-width: 112px;
}
.log-box textarea {
    font-family: Consolas, "Cascadia Mono", monospace;
}
"""


def configure_server_logging() -> logging.Logger:
    global SERVER_LOG_STREAM

    log_path = Path(
        os.getenv("APP_LOG_FILE", str(Path(__file__).with_name("app_ui_debug.log")))
    ).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    SERVER_LOG_STREAM = log_path.open("a", encoding="utf-8", buffering=1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(SERVER_LOG_STREAM)],
        force=True,
    )
    if sys.stdout is None:
        sys.stdout = SERVER_LOG_STREAM
    if sys.stderr is None:
        sys.stderr = SERVER_LOG_STREAM
    try:
        faulthandler.enable(file=SERVER_LOG_STREAM, all_threads=True)
    except Exception:
        pass
    return logging.getLogger("subtitle-to-ebook-ui")


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def state_file_path() -> Path:
    configured_path = os.getenv("APP_STATE_FILE", "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return Path(__file__).with_name("app_ui_state.json")


def load_ui_state() -> dict[str, str]:
    path = state_file_path()
    if not path.is_file():
        return {}
    try:
        with STATE_LOCK:
            data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state file root must be an object")
        return {
            key: value
            for key, value in data.items()
            if key in {"input_dir", "output_dir", "updated_at"} and isinstance(value, str)
        }
    except Exception:
        logging.getLogger("subtitle-to-ebook-ui").exception(
            "Unable to read saved UI paths from %s.", path
        )
        return {}


def save_ui_paths(input_dir: str | None = None, output_dir: str | None = None) -> None:
    path = state_file_path()
    try:
        with STATE_LOCK:
            state = load_ui_state()
            if input_dir is not None:
                state["input_dir"] = input_dir
            if output_dir is not None:
                state["output_dir"] = output_dir
            state["updated_at"] = datetime.now().isoformat(timespec="seconds")

            path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = path.with_name(f"{path.name}.tmp")
            temporary_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, path)
        logging.getLogger("subtitle-to-ebook-ui").info(
            "Saved UI paths: input=%s, output=%s",
            state.get("input_dir", ""),
            state.get("output_dir", ""),
        )
    except Exception:
        logging.getLogger("subtitle-to-ebook-ui").exception(
            "Unable to save UI paths to %s.", path
        )


def run_conversion(
    input_dir: str,
    output_dir: str,
    title: str,
    author: str,
    platform: str,
    segments_per_paragraph: int,
    recursive: bool,
    annotate_all: bool,
    make_txt: bool,
    make_epub: bool,
    make_mobi: bool,
    phonetics_enabled: bool,
    phonetic_dictionary: str,
    phonetic_style: str,
    converter: str,
    progress: gr.Progress = gr.Progress(),
) -> Iterator[tuple[str, list[str], str]]:
    app_logger = logging.getLogger("subtitle-to-ebook-ui")
    del platform, make_txt, make_epub, make_mobi
    selected_input_dir = input_dir.strip()
    if not selected_input_dir:
        app_logger.error("Conversion rejected: input folder is empty.")
        yield timestamp_log("ERROR: Input folder is required."), [], "Failed"
        return
    if Path(selected_input_dir).expanduser().is_dir():
        save_ui_paths(selected_input_dir, output_dir.strip())

    try:
        options = ConversionOptions(
            folder=Path(selected_input_dir),
            output_dir=Path(output_dir.strip()) if output_dir.strip() else None,
            title=title.strip() or None,
            author=author.strip() or "Subtitle Notes",
            recursive=recursive,
            segments_per_paragraph=int(segments_per_paragraph),
            annotate_all=annotate_all,
            converter=converter.strip() or None,
            yes=True,
            phonetics=PhoneticOptions(
                enabled=phonetics_enabled,
                dictionary_path=Path(phonetic_dictionary.strip()) if phonetic_dictionary.strip() else None,
                style=phonetic_style,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        app_logger.exception("Conversion options are invalid.")
        yield timestamp_log(f"ERROR: Invalid options: {exc}"), [], "Failed"
        return

    event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
    logs = [
        timestamp_log("Conversion started."),
        timestamp_log(f"Input: {selected_input_dir}"),
        timestamp_log(f"Output: {output_dir.strip() or '<input folder>/_ebook_output'}"),
        timestamp_log(
            f"Options: recursive={recursive}, phonetics={phonetics_enabled}, "
            f"segments/paragraph={int(segments_per_paragraph)}"
        ),
    ]

    def push_progress(value: float, message: str) -> None:
        event_queue.put(("progress", (value, message)))

    def push_log(message: str) -> None:
        event_queue.put(("log", message))

    def worker() -> None:
        app_logger.info(
            "Conversion requested: input=%s, output=%s, title=%s",
            selected_input_dir,
            output_dir.strip() or "<input folder>/_ebook_output",
            title.strip() or "<automatic>",
        )
        try:
            result = convert_from_options(
                options,
                interactive=False,
                progress_callback=push_progress,
                log_callback=push_log,
            )
            event_queue.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            app_logger.exception("Conversion worker failed.")
            event_queue.put(("error", (exc, traceback.format_exc())))

    progress(0, desc="Starting conversion")
    current_status = "0% - Starting"
    yield "\n".join(logs), [], current_status
    threading.Thread(target=worker, name="ebook-conversion", daemon=True).start()

    while True:
        event_type, payload = event_queue.get()
        if event_type == "progress":
            value, message = payload
            progress(value, desc=message)
            current_status = f"{round(value * 100)}% - {message}"
            yield "\n".join(logs), [], current_status
            continue

        if event_type == "log":
            logs.append(timestamp_log(str(payload)))
            yield "\n".join(logs), [], current_status
            continue

        if event_type == "error":
            exc, details = payload
            logs.append(timestamp_log(f"ERROR: {exc}"))
            logs.append(details.rstrip())
            yield "\n".join(logs), [], "Failed"
            return

        result = payload
        if not isinstance(result, ConversionResult):
            logs.append(timestamp_log("ERROR: Conversion returned an unexpected result."))
            yield "\n".join(logs), [], "Failed"
            return

        output_paths = [
            path
            for path in (result.preview_path, result.epub_path, result.mobi_path)
            if path.is_file()
        ]
        for path in output_paths:
            logs.append(timestamp_log(f"Output: {path} ({format_file_size(path.stat().st_size)})"))

        try:
            download_files = prepare_download_files(output_paths)
        except Exception as exc:  # noqa: BLE001
            app_logger.exception("Failed to prepare generated files for browser download.")
            logs.append(timestamp_log(f"ERROR: Unable to prepare download links: {exc}"))
            yield "\n".join(logs), [], "Failed"
            return
        logs.append(
            timestamp_log(
                f"Done: {result.file_count} source file(s), {result.chapter_count} chapter(s), "
                f"{len(output_paths)} output file(s)."
            )
        )
        app_logger.info(
            "Conversion completed: sources=%s, chapters=%s, outputs=%s",
            result.file_count,
            result.chapter_count,
            len(output_paths),
        )
        progress(1.0, desc="Conversion complete")
        yield "\n".join(logs), download_files, "100% - Complete"
        return


def timestamp_log(message: str) -> str:
    return f"[{datetime.now().strftime('%H:%M:%S')}] {message}"


def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def prepare_download_files(paths: list[Path]) -> list[str]:
    run_cache = Path(DOWNLOAD_CACHE.name) / uuid.uuid4().hex
    run_cache.mkdir(parents=True, exist_ok=True)
    downloads: list[str] = []
    for source_path in paths:
        cached_path = run_cache / source_path.name
        shutil.copy2(source_path, cached_path)
        downloads.append(str(cached_path))
    return downloads


def choose_folder(current_value: str, state_key: str) -> str:
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        initial_dir = current_value if current_value and Path(current_value).is_dir() else str(Path.home())
        selected = filedialog.askdirectory(initialdir=initial_dir)
        if selected:
            if state_key == "input_dir":
                save_ui_paths(input_dir=selected)
            elif state_key == "output_dir":
                save_ui_paths(output_dir=selected)
        return selected or current_value
    except Exception:
        logging.getLogger("subtitle-to-ebook-ui").exception("Native folder picker failed.")
        return current_value
    finally:
        if root is not None:
            root.destroy()


def choose_input_folder(current_value: str) -> str:
    return choose_folder(current_value, "input_dir")


def choose_output_folder(current_value: str) -> str:
    return choose_folder(current_value, "output_dir")


def build_ui() -> gr.Blocks:
    saved_state = load_ui_state()
    default_input_dir = os.getenv("APP_INPUT_DIR")
    default_output_dir = os.getenv("APP_OUTPUT_DIR")
    if default_input_dir is None:
        default_input_dir = saved_state.get("input_dir", "")
    if default_output_dir is None:
        default_output_dir = saved_state.get("output_dir", "")

    with gr.Blocks(title="Subtitle Notes To Ebook") as demo:
        gr.Markdown("## Subtitle Notes To Ebook")
        with gr.Row():
            with gr.Column(scale=6):
                with gr.Row(elem_classes=["folder-row"]):
                    input_dir = gr.Textbox(
                        label="Input folder",
                        value=default_input_dir,
                        scale=5,
                    )
                    choose_input = gr.Button(
                        "Browse...",
                        scale=0,
                        elem_classes=["folder-picker"],
                    )
                with gr.Row(elem_classes=["folder-row"]):
                    output_dir = gr.Textbox(
                        label="Output folder",
                        value=default_output_dir,
                        scale=5,
                    )
                    choose_output = gr.Button(
                        "Browse...",
                        scale=0,
                        elem_classes=["folder-picker"],
                    )
                with gr.Row():
                    title = gr.Textbox(label="Book title", value="")
                    author = gr.Textbox(label="Author", value="Subtitle Notes")
                with gr.Row():
                    platform = gr.Dropdown(["Auto", "Linux", "Windows"], value="Auto", label="Platform")
                    segments = gr.Number(label="Segments per paragraph", value=8, precision=0)
                with gr.Row():
                    recursive = gr.Checkbox(label="Read subfolders", value=False)
                    annotate_all = gr.Checkbox(label="Annotate every occurrence", value=False)
                with gr.Row():
                    make_txt = gr.Checkbox(label="TXT preview", value=True, interactive=False)
                    make_epub = gr.Checkbox(label="EPUB", value=True, interactive=False)
                    make_mobi = gr.Checkbox(label="MOBI", value=True, interactive=False)
            with gr.Column(scale=5):
                phonetics_enabled = gr.Checkbox(label="Add phonetics", value=True)
                phonetic_dictionary = gr.Textbox(label="CMUdict path (optional override)", value="")
                phonetic_style = gr.Dropdown(
                    [
                        ("word /phonetic/[meaning]", "word_phonetic_meaning"),
                        ("word[phonetic; meaning]", "bracket_phonetic_meaning"),
                        ("word[meaning; phonetic]", "bracket_meaning_phonetic"),
                    ],
                    value="word_phonetic_meaning",
                    label="Annotation style",
                )
                converter = gr.Textbox(label="ebook-convert / kindlegen path", value="")
                run_button = gr.Button("Start conversion", variant="primary")
                progress_status = gr.Textbox(
                    label="Progress",
                    value="Ready",
                    interactive=False,
                )
                log = gr.Textbox(
                    label="Log",
                    lines=16,
                    max_lines=20,
                    autoscroll=True,
                    interactive=False,
                    elem_classes=["log-box"],
                )
                output_files = gr.Files(label="Generated files")

        run_button.click(
            run_conversion,
            inputs=[
                input_dir,
                output_dir,
                title,
                author,
                platform,
                segments,
                recursive,
                annotate_all,
                make_txt,
                make_epub,
                make_mobi,
                phonetics_enabled,
                phonetic_dictionary,
                phonetic_style,
                converter,
            ],
            outputs=[log, output_files, progress_status],
            show_progress="minimal",
            show_progress_on=progress_status,
            concurrency_limit=1,
            stream_every=0.2,
        )
        choose_input.click(choose_input_folder, inputs=[input_dir], outputs=[input_dir])
        choose_output.click(choose_output_folder, inputs=[output_dir], outputs=[output_dir])
    return demo


if __name__ == "__main__":
    server_logger = configure_server_logging()
    configured_port = os.getenv("APP_PORT", "").strip()
    server_host = os.getenv("APP_HOST", "127.0.0.1")
    open_browser = env_flag("APP_OPEN_BROWSER")
    server_logger.info("=" * 72)
    server_logger.info("Starting Subtitle Notes To Ebook UI")
    server_logger.info("PID: %s", os.getpid())
    server_logger.info("Python executable: %s", sys.executable)
    server_logger.info("Python version: %s", sys.version.replace("\n", " "))
    server_logger.info("Gradio version: %s", gr.__version__)
    server_logger.info("Working directory: %s", Path.cwd())
    server_logger.info("Script directory: %s", Path(__file__).resolve().parent)
    server_logger.info("UI state file: %s", state_file_path())
    server_logger.info(
        "Launch settings: host=%s, port=%s, open_browser=%s",
        server_host,
        configured_port or "auto",
        open_browser,
    )
    try:
        build_ui().launch(
            server_name=server_host,
            server_port=int(configured_port) if configured_port else None,
            inbrowser=open_browser,
            css=UI_CSS,
        )
    except BaseException:
        server_logger.exception("UI server stopped because of an unhandled error.")
        raise
    finally:
        server_logger.info("UI server process is exiting.")
