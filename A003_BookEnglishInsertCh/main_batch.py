#!/usr/bin/env python3
import argparse
import configparser
import hashlib
import html
import json
import logging
import os
import posixpath
import queue
import re
import signal
import shlex
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from book_vocab_module import VocabularyAnnotator


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"
DEFAULT_SSH_CONTROL_PERSIST_SECONDS = 72 * 60 * 60

DEFAULT_CONFIG_TEXT = """[OriginalConfigPath]
OriginalBookPath=./original
OutputBookPath=./Output
WorkPath=./tmp_cache

[RuntimeConfig]
# Set RunMode=local to process only on this machine.
# Set RunMode=remote to split work across RemoteConfig.RemoteWorkers.
RunMode=local
# CPU is the default. GPU selects CUDA paths when the environment supports them.
CaculateCore=CPU
# 0 = auto (use available CPU cores)
MaxWorkers=0
# Number of books processed at the same time in local mode. 1 is safest.
BookWorkers=1
# 0 = auto. Used for PDF OCR page workers per book.
OcrWorkers=0

[RemoteConfig]
# This section is used only when RuntimeConfig.RunMode=remote.
# Format: ssh_user@host:/absolute/path or ssh_user@host:~/path
RemoteWorkers=
# 1 keeps this machine as one worker when RunMode=remote. Ignored in local mode.
RemoteIncludeLocalWorker=1
# Remote temporary work directory used on each SSH worker.
RemoteWorkPath=/tmp/bookvocab_remote
# Python executable on each remote project checkout.
RemotePython=./venv/bin/python3
# 1 copies this project to each remote worker before processing.
RemoteSyncProject=1
# 1 runs EnvSetup/SetupCPU.sh on remote workers when required tools are missing.
RemoteSetupIfMissing=1
# Extra ssh/scp options used for remote workers.
# BatchMode prevents unattended runs from blocking on a password or passphrase prompt.
RemoteSshOptions=-o BatchMode=yes -o NumberOfPasswordPrompts=0 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3
# Directory for persistent SSH control sockets.
RemoteSshControlPath=/tmp/bookvocab_remote_ssh
# Keep authenticated SSH sessions for 72 hours. 259200 seconds = 72 hours.
RemoteSshControlPersistSeconds=259200
# Password retry count when opening each SSH control session.
RemoteSshPasswordRetries=1
# Seconds without remote output before a worker is treated as stalled. 0 disables it.
RemoteNoResponseTimeoutSeconds=120
# Capacity controls for remote scheduling.
RemoteMemoryReservePercent=15
RemoteMinFreeMemoryMB=2048
RemoteMemoryPerJobMB=4096
RemoteCpuPerJob=2
RemoteMaxJobsPerHost=0
RemoteChunksPerSlot=4

[DifficultyConfig]
AdvancedLevels=C1,C2
MinCandidateLength=5
B1MinLength=8
B1FrequencyThreshold=0.000003
B2MinLength=8
B2FrequencyThreshold=0.000012
UnknownMinLength=8
UnknownFrequencyThreshold=0.000003

[TranslationConfig]
SegmentsPerTranslation=1
UseContextMeaning=1
MaxMeaningChars=8
RetryOnVerboseMeaning=1
AmbiguousMeaningPolicy=skip
OllamaTemperature=0
# Local mode normally uses localhost. In remote mode, localhost means each worker's own Ollama.
OllamaApi=http://localhost:11434/api/generate
OllamaModel=qwen2.5:7b
TranslationRepeatWindowWords=250
TranslationBatchSize=8
MaxContextChars=1800
OllamaTimeoutSeconds=240
OllamaRequestRetries=2
OllamaRetrySleepSeconds=3
SkipOnServiceUnavailable=1
FailOnServiceUnavailable=0
ServiceUnavailableFailureLimit=1
IpaProvider=auto

[ProperNounConfig]
SkipProperNouns=1
NlpModel=en_core_web_sm
EntityLabels=PERSON,GPE,LOC,FAC,ORG
SkipWords=

[OcrConfig]
EnablePdfOcr=1
ForcePdfOcr=1
OcrLanguage=eng
PdfDpi=300
TesseractPsm=1
MinPdfTextChars=200

[BookOutputConfig]
OutputFormat=azw3
InputSuffixes=.pdf,.epub,.mobi,.azw3,.azw,.txt,.html,.htm,.docx,.rtf
OverwriteOutput=0
KeepIntermediate=0
"""


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"book_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
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


def ensure_default_config():
    if CONFIG_FILE.exists():
        return
    CONFIG_FILE.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")


def resolve_config_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def config_bool(section, section_name, key, default):
    try:
        return section.getboolean(key, fallback=default)
    except ValueError:
        logging.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return default


def config_positive_int(section, section_name, key, default):
    try:
        return max(1, section.getint(key, fallback=default))
    except ValueError:
        logging.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(1, int(default))


def config_nonnegative_int(section, section_name, key, default):
    try:
        return max(0, section.getint(key, fallback=default))
    except ValueError:
        logging.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(0, int(default))


def load_config():
    ensure_default_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")

    path_section = parser["OriginalConfigPath"]
    runtime_section = parser["RuntimeConfig"] if parser.has_section("RuntimeConfig") else {}
    remote_section = parser["RemoteConfig"] if parser.has_section("RemoteConfig") else {}
    translation_section = parser["TranslationConfig"] if parser.has_section("TranslationConfig") else {}
    ocr_section = parser["OcrConfig"] if parser.has_section("OcrConfig") else {}
    output_section = parser["BookOutputConfig"] if parser.has_section("BookOutputConfig") else {}

    suffixes = output_section.get(
        "InputSuffixes",
        ".pdf,.epub,.mobi,.azw3,.azw,.txt,.html,.htm,.docx,.rtf",
    )
    input_suffixes = tuple(item.strip().lower() for item in suffixes.split(",") if item.strip())
    if not input_suffixes:
        input_suffixes = (".pdf", ".epub", ".mobi", ".azw3")

    calculate_core = runtime_section.get(
        "CaculateCore",
        runtime_section.get("CalculateCore", "CPU"),
    ).strip().upper()
    if calculate_core != "GPU":
        calculate_core = "CPU"

    run_mode = runtime_section.get("RunMode", "local").strip().lower()
    if run_mode not in {"local", "remote"}:
        logging.warning("Invalid RuntimeConfig.RunMode=%r, using local", run_mode)
        run_mode = "local"

    remote_workers_raw = remote_section.get("RemoteWorkers", "") if remote_section else ""
    remote_workers = []
    for item in re.sub(r"\\\s*(?:\r?\n)?", "", str(remote_workers_raw)).split(","):
        item = item.strip().strip("\\").strip()
        if item and item != "\\":
            remote_workers.append(item)

    return {
        "run_mode": run_mode,
        "original_dir": resolve_config_path(
            os.getenv("BOOKVOCAB_SRC_DIR", path_section.get("OriginalBookPath", "./original"))
        ),
        "output_dir": resolve_config_path(
            os.getenv("BOOKVOCAB_OUTPUT_DIR", path_section.get("OutputBookPath", "./Output"))
        ),
        "work_dir": resolve_config_path(
            os.getenv("BOOKVOCAB_WORK_DIR", path_section.get("WorkPath", "./tmp_cache"))
        ),
        "calculate_core": calculate_core,
        "max_workers": config_nonnegative_int(runtime_section, "RuntimeConfig", "MaxWorkers", 0) if runtime_section else 0,
        "book_workers": config_nonnegative_int(runtime_section, "RuntimeConfig", "BookWorkers", 1) if runtime_section else 1,
        "ocr_workers": config_nonnegative_int(runtime_section, "RuntimeConfig", "OcrWorkers", 0) if runtime_section else 0,
        "ocr": {
            "enabled": config_bool(ocr_section, "OcrConfig", "EnablePdfOcr", True) if ocr_section else True,
            "force": config_bool(ocr_section, "OcrConfig", "ForcePdfOcr", False) if ocr_section else False,
            "language": ocr_section.get("OcrLanguage", "eng").strip() if ocr_section else "eng",
            "dpi": config_positive_int(ocr_section, "OcrConfig", "PdfDpi", 300) if ocr_section else 300,
            "psm": config_positive_int(ocr_section, "OcrConfig", "TesseractPsm", 1) if ocr_section else 1,
            "min_text_chars": config_positive_int(ocr_section, "OcrConfig", "MinPdfTextChars", 200) if ocr_section else 200,
        },
        "output_format": output_section.get("OutputFormat", "azw3").strip().lower() if output_section else "azw3",
        "input_suffixes": input_suffixes,
        "overwrite_output": config_bool(output_section, "BookOutputConfig", "OverwriteOutput", False) if output_section else False,
        "keep_intermediate": config_bool(output_section, "BookOutputConfig", "KeepIntermediate", False) if output_section else False,
        "translation": {
            "ollama_api": translation_section.get("OllamaApi", "http://localhost:11434/api/generate").strip()
            if translation_section
            else "http://localhost:11434/api/generate",
            "ollama_model": translation_section.get("OllamaModel", "qwen2.5:7b").strip()
            if translation_section
            else "qwen2.5:7b",
        },
        "remote": {
            "workers": remote_workers,
            "include_local_worker": config_bool(
                remote_section, "RemoteConfig", "RemoteIncludeLocalWorker", True
            )
            if remote_section
            else True,
            "work_path": remote_section.get("RemoteWorkPath", "/tmp/bookvocab_remote").strip()
            if remote_section
            else "/tmp/bookvocab_remote",
            "python": remote_section.get("RemotePython", "./venv/bin/python3").strip()
            if remote_section
            else "./venv/bin/python3",
            "sync_project": config_bool(remote_section, "RemoteConfig", "RemoteSyncProject", True)
            if remote_section
            else True,
            "setup_if_missing": config_bool(remote_section, "RemoteConfig", "RemoteSetupIfMissing", False)
            if remote_section
            else False,
            "ssh_options": remote_section.get(
                "RemoteSshOptions",
                "-o BatchMode=yes -o NumberOfPasswordPrompts=0 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3",
            ).strip()
            if remote_section
            else "-o BatchMode=yes -o NumberOfPasswordPrompts=0 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3",
            "ssh_control_path": resolve_config_path(
                remote_section.get("RemoteSshControlPath", "/tmp/bookvocab_remote_ssh")
                if remote_section
                else "/tmp/bookvocab_remote_ssh"
            ),
            "ssh_control_persist_seconds": config_nonnegative_int(
                remote_section,
                "RemoteConfig",
                "RemoteSshControlPersistSeconds",
                DEFAULT_SSH_CONTROL_PERSIST_SECONDS,
            )
            if remote_section
            else DEFAULT_SSH_CONTROL_PERSIST_SECONDS,
            "ssh_password_retries": config_positive_int(
                remote_section, "RemoteConfig", "RemoteSshPasswordRetries", 1
            )
            if remote_section
            else 1,
            "no_response_timeout_seconds": config_nonnegative_int(
                remote_section, "RemoteConfig", "RemoteNoResponseTimeoutSeconds", 120
            )
            if remote_section
            else 120,
            "memory_reserve_percent": config_nonnegative_int(
                remote_section, "RemoteConfig", "RemoteMemoryReservePercent", 15
            )
            if remote_section
            else 15,
            "min_free_memory_mb": config_nonnegative_int(
                remote_section, "RemoteConfig", "RemoteMinFreeMemoryMB", 2048
            )
            if remote_section
            else 2048,
            "memory_per_job_mb": config_positive_int(
                remote_section, "RemoteConfig", "RemoteMemoryPerJobMB", 4096
            )
            if remote_section
            else 4096,
            "cpu_per_job": config_positive_int(remote_section, "RemoteConfig", "RemoteCpuPerJob", 2)
            if remote_section
            else 2,
            "max_jobs_per_host": config_nonnegative_int(
                remote_section, "RemoteConfig", "RemoteMaxJobsPerHost", 0
            )
            if remote_section
            else 0,
            "chunks_per_slot": config_positive_int(remote_section, "RemoteConfig", "RemoteChunksPerSlot", 4)
            if remote_section
            else 4,
        },
    }


def apply_runtime_env(config):
    cpu_count = os.cpu_count() or 1
    configured_workers = config["max_workers"]
    if configured_workers <= 0:
        configured_workers = cpu_count
    configured_workers = max(1, min(configured_workers, cpu_count))
    if config["calculate_core"] == "CPU":
        os.environ.setdefault("BOOKVOCAB_DEVICE", "cpu")
        os.environ.setdefault("BOOKVOCAB_CPU_THREADS", str(cpu_count))
        os.environ.setdefault("BOOKVOCAB_MAX_WORKERS", str(configured_workers))
    else:
        os.environ.setdefault("BOOKVOCAB_DEVICE", "cuda")
        os.environ.setdefault("BOOKVOCAB_GPU_ENABLED", "1")
        os.environ.setdefault("BOOKVOCAB_MAX_WORKERS", str(configured_workers))
    os.environ.setdefault("BOOKVOCAB_OLLAMA_MODEL", config.get("translation", {}).get("ollama_model") or "qwen2.5:7b")
    os.environ.setdefault(
        "BOOKVOCAB_OLLAMA_API",
        config.get("translation", {}).get("ollama_api") or "http://localhost:11434/api/generate",
    )
    logging.info(
        "Runtime: CaculateCore=%s BOOKVOCAB_DEVICE=%s BOOKVOCAB_CPU_THREADS=%s",
        config["calculate_core"],
        os.getenv("BOOKVOCAB_DEVICE"),
        os.getenv("BOOKVOCAB_CPU_THREADS", ""),
    )
    logging.info("Runtime parallel workers configured=%s cpu_count=%s", configured_workers, cpu_count)
    config["effective_workers"] = configured_workers


def safe_stem(path):
    value = re.sub(r"[^\w.\-]+", "_", Path(path).stem, flags=re.UNICODE).strip("._")
    return value or "book"


def progress_label(current, total):
    total = max(0, int(total))
    current = max(0, min(int(current), total)) if total else 0
    percentage = (current * 100.0 / total) if total else 100.0
    return f"{current}/{total} ({percentage:.1f}%)"


def file_fingerprint(path):
    stat = Path(path).stat()
    return {
        "path": str(Path(path).resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def output_path_for(input_path, config):
    return config["output_dir"] / f"{safe_stem(input_path)}_translated.{config['output_format']}"


def cache_dir_for(input_path, config):
    key = hashlib.sha1(str(Path(input_path).resolve()).encode("utf-8")).hexdigest()[:10]
    return config["work_dir"] / f"{safe_stem(input_path)}_{key}"


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(path)


def atomic_copy(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dst.with_name(f".{dst.name}.tmp")
    shutil.copy2(src, tmp_path)
    tmp_path.replace(dst)


def atomic_convert_with_calibre(input_path, output_path, description):
    output_path = Path(output_path)
    tmp_path = output_path.with_name(f".{output_path.stem}.tmp{output_path.suffix}")
    if tmp_path.exists():
        tmp_path.unlink()
    convert_with_calibre(input_path, tmp_path, description)
    tmp_path.replace(output_path)


def read_progress(work_dir):
    progress_path = Path(work_dir) / "progress.json"
    if not progress_path.exists():
        return {}
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        logging.warning("Progress file is unreadable; starting conservative resume: %s", progress_path)
        return {}
    return data if isinstance(data, dict) else {}


def write_progress(work_dir, progress):
    serializable = dict(progress)
    serializable["updated_at"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_text(
        Path(work_dir) / "progress.json",
        json.dumps(serializable, ensure_ascii=False, indent=2, sort_keys=True),
    )


def capture_annotator_state(annotator):
    stats = annotator.stats
    return {
        "recent_translations": dict(annotator.recent_translations),
        "word_index": annotator.word_index,
        "stats": {
            "words_seen": stats.words_seen,
            "difficult_candidates": stats.difficult_candidates,
            "translated_words": stats.translated_words,
            "inserted_annotations": stats.inserted_annotations,
            "ollama_requests": stats.ollama_requests,
        },
    }


def restore_annotator_state(annotator, state):
    if not isinstance(state, dict):
        return False
    stats = state.get("stats", {})
    if not isinstance(stats, dict):
        return False
    annotator.recent_translations = {
        str(word): int(position)
        for word, position in dict(state.get("recent_translations", {})).items()
        if str(position).lstrip("-").isdigit()
    }
    try:
        annotator.word_index = int(state.get("word_index", 0))
    except (TypeError, ValueError):
        annotator.word_index = 0
    for key in (
        "words_seen",
        "difficult_candidates",
        "translated_words",
        "inserted_annotations",
        "ollama_requests",
    ):
        try:
            setattr(annotator.stats, key, int(stats.get(key, 0)))
        except (TypeError, ValueError):
            setattr(annotator.stats, key, 0)
    return True


def mark_stage(progress, work_dir, stage, **values):
    stages = progress.setdefault("stages", {})
    stage_info = dict(values)
    stage_info["completed_at"] = datetime.now().isoformat(timespec="seconds")
    stages[stage] = stage_info
    write_progress(work_dir, progress)


def stage_done(progress, stage, required_paths=()):
    stage_info = progress.get("stages", {}).get(stage)
    if not isinstance(stage_info, dict):
        return False
    return all(Path(path).exists() for path in required_paths)


def reset_incompatible_progress(progress, input_path, work_dir):
    fingerprint = file_fingerprint(input_path)
    if progress.get("source") == fingerprint:
        return progress
    if not progress:
        progress = {
            "source": fingerprint,
            "stages": {},
        }
        write_progress(work_dir, progress)
        logging.info("Initialized progress metadata without deleting cache: %s", work_dir)
        return progress
    if progress:
        logging.info("Source changed; resetting cached progress: %s", work_dir)
    work_path = Path(work_dir)
    if work_path.exists():
        for child in work_path.iterdir():
            if child.name == "progress.json":
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    progress = {
        "source": fingerprint,
        "stages": {},
    }
    write_progress(work_dir, progress)
    return progress


def find_books(original_dir, suffixes):
    books = []
    for path in sorted(original_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in suffixes:
            books.append(path)
    return books


def run_cmd(cmd, description, cwd=None, timeout=None, log_stdout=True, log_stderr=True, log_command=True):
    if log_command:
        logging.info("%s: %s", description, " ".join(str(item) for item in cmd))
    proc = subprocess.run(
        [str(item) for item in cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
    )
    if log_stdout and proc.stdout.strip():
        logging.info("%s stdout: %s", description, proc.stdout[-3000:])
    if log_stderr and proc.stderr.strip():
        logging.info("%s stderr: %s", description, proc.stderr[-3000:])
    if proc.returncode != 0:
        details = []
        if proc.stdout.strip():
            details.append(f"stdout={proc.stdout[-1200:].strip()}")
        if proc.stderr.strip():
            details.append(f"stderr={proc.stderr[-1200:].strip()}")
        detail_text = " " + " ".join(details) if details else ""
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}{detail_text}")
    return proc


def require_tool(name):
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found in PATH. Run EnvSetup/SetupCPU.sh first.")
    return path


def convert_with_calibre(input_path, output_path, description):
    ebook_convert = require_tool("ebook-convert")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([ebook_convert, input_path, output_path], description, timeout=None)


def pdf_page_count(input_path):
    pdfinfo = require_tool("pdfinfo")
    proc = run_cmd([pdfinfo, input_path], "PDF page count", log_command=False)
    match = re.search(r"^Pages:\s+(\d+)\s*$", proc.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not read PDF page count from {input_path}")
    return int(match.group(1))


def extract_pdf_text_with_pdftotext(input_path, work_dir, progress=None, page_range=None):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        logging.warning("pdftotext not found; PDF text layer extraction skipped")
        return ""

    output_txt = work_dir / "pdf_text_layer.txt"
    if progress is not None and stage_done(progress, "pdf_text_layer", [output_txt]):
        logging.info("Resume PDF text layer from cache: %s", output_txt)
        return output_txt.read_text(encoding="utf-8", errors="ignore")

    try:
        cmd = [pdftotext, "-layout"]
        if page_range:
            cmd.extend(["-f", str(page_range[0]), "-l", str(page_range[1])])
        cmd.extend([input_path, output_txt])
        run_cmd(cmd, "PDF text layer extraction")
    except Exception:
        logging.exception("PDF text layer extraction failed")
        return ""
    if progress is not None:
        mark_stage(progress, work_dir, "pdf_text_layer", path=str(output_txt))
    return output_txt.read_text(encoding="utf-8", errors="ignore")


PDF_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
PDF_ROMAN_RE = re.compile(r"^[IVXLCDM]+$", re.IGNORECASE)
PDF_VALID_ROMANS = {
    "I",
    "II",
    "III",
    "IV",
    "V",
    "VI",
    "VII",
    "VIII",
    "IX",
    "X",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
    "XVI",
    "XVII",
    "XVIII",
    "XIX",
    "XX",
}
PDF_COMMON_WORDS = {
    "A",
    "AN",
    "AND",
    "ARE",
    "AS",
    "AT",
    "BE",
    "BY",
    "FOR",
    "FROM",
    "IN",
    "IS",
    "IT",
    "OF",
    "ON",
    "OR",
    "THE",
    "TO",
    "UNDER",
    "WITH",
}


def normalize_pdf_unicode(text):
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.replace("\u00ad", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    return normalized


def is_pdf_noise_line(line):
    compact = line.strip()
    if not compact:
        return False

    letters = re.sub(r"[^A-Za-z]", "", compact)
    words = PDF_WORD_RE.findall(compact)
    symbol_count = sum(not char.isalnum() and not char.isspace() for char in compact)

    # OCR frequently leaves decorative marks, page fragments, and one-character
    # lines as standalone content. Keep real words and normal short headings.
    if len(letters) <= 2 and len(words) <= 1:
        return True
    if symbol_count / max(1, len(compact)) > 0.35 and len(words) <= 2:
        return True

    if letters and compact.upper() == compact:
        vowel_count = sum(char.lower() in "aeiouy" for char in letters)
        longest_word = max((len(word) for word in words), default=0)
        vowel_ratio = vowel_count / max(1, len(letters))
        if longest_word >= 12 and vowel_ratio < 0.30:
            return True
        if longest_word >= 18:
            return True
        if len(letters) >= 24 and vowel_ratio < 0.24:
            return True
        common_word_count = sum(word.upper() in PDF_COMMON_WORDS for word in words)
        if len(words) >= 4 and len(letters) >= 20 and symbol_count and common_word_count == 0:
            return True

    compact_roman = re.sub(r"\s+", "", compact)
    if PDF_ROMAN_RE.fullmatch(compact_roman):
        roman = compact_roman.upper()
        if len(roman) <= 5 and roman not in PDF_VALID_ROMANS:
            return True

    return False


def is_pdf_page_artifact_line(line, page_start=False):
    compact = line.strip()
    if not compact:
        return False
    if re.fullmatch(r"[\W_]+", compact):
        return True
    if re.fullmatch(r"\d{1,4}", compact):
        return True
    if compact.islower() and PDF_ROMAN_RE.fullmatch(compact):
        return True
    if page_start and compact == compact.lower():
        if re.fullmatch(r"(?:\d{1,4}|[ivxlcdm]{1,8})\s+[a-z][a-z0-9 .,'’-]{2,60}", compact):
            return True
    return False


def join_pdf_lines(lines):
    joined = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if not line:
            index += 1
            continue

        if (
            line.upper() in PDF_VALID_ROMANS
            and index + 1 < len(lines)
            and lines[index + 1].strip()
        ):
            # Keep valid chapter numbers, but prevent them from becoming
            # isolated one-line paragraphs in the generated ebook.
            line = f"{line} {lines[index + 1].strip()}"
            index += 1

        if joined and joined[-1].endswith("-") and line[:1].islower():
            joined[-1] += line
        else:
            joined.append(line)
        index += 1

    return " ".join(joined)


def clean_pdf_text(text, source="text_layer"):
    normalized = normalize_pdf_unicode(text)
    pages = normalized.split("\f")
    cleaned_pages = []

    for page in pages:
        raw_lines = []
        for raw_line in page.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                if raw_lines and raw_lines[-1] != "":
                    raw_lines.append("")
                continue
            page_start = not any(item for item in raw_lines)
            if is_pdf_page_artifact_line(line, page_start=page_start):
                continue
            if source == "ocr" and is_pdf_noise_line(line):
                continue
            raw_lines.append(line)

        while raw_lines and raw_lines[-1] == "":
            raw_lines.pop()

        if not raw_lines:
            continue

        # Preserve blank-line paragraph boundaries, but reflow physical PDF/OCR
        # lines so a wrapped sentence is not emitted as many tiny ebook lines.
        paragraphs = []
        current = []
        for line in raw_lines:
            if line:
                current.append(line)
            elif current:
                paragraphs.append(join_pdf_lines(current))
                current = []
        if current:
            paragraphs.append(join_pdf_lines(current))

        if paragraphs:
            cleaned_pages.append("\n\n".join(item for item in paragraphs if item))

    return "\n\n".join(cleaned_pages)


def score_pdf_text_quality(text):
    normalized = normalize_pdf_unicode(text)
    if not normalized.strip():
        return float("-inf")

    words = PDF_WORD_RE.findall(normalized)
    letters = re.findall(r"[A-Za-z]", normalized)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    suspicious_lines = sum(is_pdf_noise_line(line) for line in lines)
    uppercase_lines = sum(
        bool(re.search(r"[A-Z]", line)) and line.upper() == line
        for line in lines
    )
    sentence_marks = len(re.findall(r"[.!?]", normalized))
    weird_chars = len(re.findall(r"[^A-Za-z0-9\s.,!?;:'\"()\[\]{}\-–—]", normalized))

    # Word and sentence volume establish usefulness; standalone OCR noise and
    # unusual characters reduce the score. The score is only used to compare
    # two extractions from the same PDF.
    score = (
        len(words)
        + len(letters) / 100.0
        + sentence_marks * 0.15
        + uppercase_lines * 0.05
        - suspicious_lines * 8.0
        - weird_chars * 0.5
    )
    return round(score, 2)


def natural_sort_key(path):
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", str(path))]


def ocr_pdf(input_path, work_dir, ocr_config, worker_count=1, progress=None, page_range=None):
    pdftoppm = require_tool("pdftoppm")
    tesseract = require_tool("tesseract")
    image_prefix = work_dir / "ocr_page"
    raster_cmd = [pdftoppm, "-r", str(ocr_config["dpi"]), "-png"]
    if page_range:
        start_page, end_page = page_range
        raster_cmd.extend(["-f", str(start_page), "-l", str(end_page)])
    raster_cmd.extend([input_path, image_prefix])
    if progress is not None and stage_done(progress, "pdf_rasterized"):
        images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
        if images:
            logging.info("Resume PDF rasterized pages from cache: %d image(s)", len(images))
        else:
            logging.info("Cached PDF rasterization marker found but images are missing; rasterizing again")
            run_cmd(raster_cmd, "PDF rasterization for OCR")
            images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
    else:
        run_cmd(raster_cmd, "PDF rasterization for OCR")
        images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
        if progress is not None:
            stage_values = {"pages": len(images)}
            if page_range:
                stage_values["page_start"] = page_range[0]
                stage_values["page_end"] = page_range[1]
            mark_stage(progress, work_dir, "pdf_rasterized", **stage_values)

    if not images:
        raise RuntimeError("PDF OCR produced no page images")

    worker_count = max(1, min(int(worker_count or 1), len(images)))
    logging.info("OCR worker count for %s: %d page(s)=%d", input_path.name, worker_count, len(images))
    ocr_text_dir = work_dir / "ocr_text"
    ocr_text_dir.mkdir(parents=True, exist_ok=True)
    progress_pages = progress.setdefault("ocr_pages", {}) if progress is not None else {}

    def note_ocr_page_done(index):
        if progress is None:
            return
        page_text_path = ocr_text_dir / f"page_{index:04d}.txt"
        progress_pages[str(index)] = {
            "status": "done",
            "path": str(page_text_path),
        }
        write_progress(work_dir, progress)

    def ocr_one_page(index, image):
        page_text_path = ocr_text_dir / f"page_{index:04d}.txt"
        if page_text_path.exists():
            logging.info("Resume OCR page %s from cache: %d/%d", input_path.name, index, len(images))
            return index, page_text_path.read_text(encoding="utf-8", errors="ignore").strip()

        proc = run_cmd(
            [
                tesseract,
                image,
                "stdout",
                "-l",
                ocr_config["language"],
                "--psm",
                str(ocr_config["psm"]),
            ],
            f"OCR page {index}",
            log_stdout=False,
            log_command=False,
        )
        page_text = proc.stdout.strip()
        atomic_write_text(page_text_path, page_text)
        return index, page_text

    pages = []
    if worker_count == 1:
        for index, image in enumerate(images, start=1):
            logging.info(
                "OCR progress %s page %s",
                input_path.name,
                progress_label(index, len(images)),
            )
            result = ocr_one_page(index, image)
            pages.append(result)
            note_ocr_page_done(result[0])
    else:
        executor = ThreadPoolExecutor(max_workers=worker_count)
        future_to_index = {}
        try:
            future_to_index = {
                executor.submit(ocr_one_page, index, image): index
                for index, image in enumerate(images, start=1)
            }
            completed = 0
            for future in as_completed(future_to_index):
                result = future.result()
                pages.append(result)
                note_ocr_page_done(result[0])
                completed += 1
                logging.info(
                    "OCR progress %s completed %s",
                    input_path.name,
                    progress_label(completed, len(images)),
                )
        except BaseException:
            for future in future_to_index:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)

    if progress is not None:
        mark_stage(progress, work_dir, "pdf_ocr", pages=len(images))
    return "\n\n".join(page for _, page in sorted(pages) if page)


def extract_pdf_text(input_path, work_dir, ocr_config, worker_count=1, progress=None, page_range=None):
    final_text_path = work_dir / "pdf_extracted_text.txt"
    if progress is not None and stage_done(progress, "pdf_text_extracted", [final_text_path]):
        logging.info("Resume extracted PDF text from cache: %s", final_text_path)
        return final_text_path.read_text(encoding="utf-8", errors="ignore")

    text_layer = extract_pdf_text_with_pdftotext(
        input_path,
        work_dir,
        progress=progress,
        page_range=page_range,
    )
    text_chars = len(re.sub(r"\s+", "", text_layer))
    logging.info("PDF text layer characters: %d", text_chars)

    should_ocr = ocr_config["enabled"] and (ocr_config["force"] or text_chars < ocr_config["min_text_chars"])
    if not should_ocr:
        cleaned_text_layer = clean_pdf_text(text_layer, source="text_layer")
        logging.info(
            "PDF text source selected=text_layer score=%.2f",
            score_pdf_text_quality(cleaned_text_layer),
        )
        if progress is not None:
            atomic_write_text(final_text_path, cleaned_text_layer)
            mark_stage(progress, work_dir, "pdf_text_extracted", source="text_layer", path=str(final_text_path))
        return cleaned_text_layer

    logging.info("PDF OCR enabled for %s", input_path.name)
    ocr_text = ocr_pdf(
        input_path,
        work_dir,
        ocr_config,
        worker_count=worker_count,
        progress=progress,
        page_range=page_range,
    )
    ocr_chars = len(re.sub(r"\s+", "", ocr_text))
    logging.info("PDF OCR characters: %d", ocr_chars)
    cleaned_text_layer = clean_pdf_text(text_layer, source="text_layer")
    cleaned_ocr_text = clean_pdf_text(ocr_text, source="ocr")
    text_layer_score = score_pdf_text_quality(cleaned_text_layer)
    ocr_score = score_pdf_text_quality(cleaned_ocr_text)
    logging.info(
        "PDF extraction quality text_layer=%.2f ocr=%.2f",
        text_layer_score,
        ocr_score,
    )

    if cleaned_ocr_text and (
        not cleaned_text_layer
        or ocr_score > text_layer_score + 5.0
    ):
        logging.info("PDF text source selected=ocr")
        if progress is not None:
            atomic_write_text(final_text_path, cleaned_ocr_text)
            mark_stage(progress, work_dir, "pdf_text_extracted", source="ocr", path=str(final_text_path))
        return cleaned_ocr_text
    if cleaned_text_layer:
        logging.info("PDF text source selected=text_layer")
        if progress is not None:
            atomic_write_text(final_text_path, cleaned_text_layer)
            mark_stage(progress, work_dir, "pdf_text_extracted", source="text_layer", path=str(final_text_path))
        return cleaned_text_layer
    if ocr_text.strip():
        logging.info("PDF text source selected=ocr_unfiltered_fallback")
        if progress is not None:
            atomic_write_text(final_text_path, ocr_text)
            mark_stage(progress, work_dir, "pdf_text_extracted", source="ocr_unfiltered_fallback", path=str(final_text_path))
        return ocr_text
    logging.warning("OCR returned no usable text; using text layer fallback")
    if progress is not None:
        atomic_write_text(final_text_path, text_layer)
        mark_stage(progress, work_dir, "pdf_text_extracted", source="text_layer_fallback", path=str(final_text_path))
    return text_layer


def split_text_blocks(text):
    cleaned = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", cleaned) if block.strip()]
    if len(blocks) <= 1 and len(cleaned) > 4000:
        lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
        blocks = []
        current = []
        current_len = 0
        for line in lines:
            current.append(line)
            current_len += len(line)
            if current_len >= 1800:
                blocks.append(" ".join(current))
                current = []
                current_len = 0
        if current:
            blocks.append(" ".join(current))
    return blocks


def write_html_book(title, blocks, annotator, output_html, progress=None, work_dir=None):
    output_html.parent.mkdir(parents=True, exist_ok=True)
    total = len(blocks)
    block_dir = output_html.parent / "annotated_blocks"
    block_dir.mkdir(parents=True, exist_ok=True)
    progress_blocks = progress.setdefault("text_blocks", {}) if progress is not None else {}

    def block_cache_path(index):
        return block_dir / f"block_{index:05d}.html"

    with output_html.open("w", encoding="utf-8") as handle:
        handle.write("<!doctype html>\n<html><head><meta charset=\"utf-8\"/>\n")
        handle.write(f"<title>{html.escape(title)}</title>\n")
        handle.write(
            "<style>body{font-family:serif;line-height:1.45;}p{margin:0 0 1em 0;}</style>\n"
            "</head><body>\n"
        )
        handle.write(f"<h1>{html.escape(title)}</h1>\n")
        for index, block in enumerate(blocks, start=1):
            cached_block = block_cache_path(index)
            block_progress = progress_blocks.get(str(index), {})
            cached_state = block_progress.get("annotator_state")
            if (
                cached_block.exists()
                and block_progress.get("status") == "done"
                and restore_annotator_state(annotator, cached_state)
            ):
                escaped = cached_block.read_text(encoding="utf-8", errors="ignore")
            else:
                annotated = annotator.annotate_text(block)
                escaped = html.escape(annotated, quote=False).replace("\n", "<br/>\n")
                atomic_write_text(cached_block, escaped)
                if progress is not None and work_dir is not None:
                    progress_blocks[str(index)] = {
                        "status": "done",
                        "path": str(cached_block),
                        "annotator_state": capture_annotator_state(annotator),
                    }
                    write_progress(work_dir, progress)
            handle.write(f"<p>{escaped}</p>\n")
            if index == 1 or index % 10 == 0 or index == total:
                logging.info(
                    "Text annotation progress %s %s",
                    title,
                    progress_label(index, total),
                )
        handle.write("</body></html>\n")


def annotated_text_blocks_to_fragment(title, blocks, annotator):
    pieces = []
    total = len(blocks)
    for index, block in enumerate(blocks, start=1):
        annotated = annotator.annotate_text(block)
        escaped = html.escape(annotated, quote=False).replace("\n", "<br/>\n")
        pieces.append(f"<p>{escaped}</p>\n")
        if index == 1 or index % 10 == 0 or index == total:
            logging.info(
                "Remote text chunk annotation progress %s %s",
                title,
                progress_label(index, total),
            )
    return "".join(pieces)


def write_html_fragments_book(title, fragment_paths, output_html):
    output_html.parent.mkdir(parents=True, exist_ok=True)
    with output_html.open("w", encoding="utf-8") as handle:
        handle.write("<!doctype html>\n<html><head><meta charset=\"utf-8\"/>\n")
        handle.write(f"<title>{html.escape(title)}</title>\n")
        handle.write(
            "<style>body{font-family:serif;line-height:1.45;}p{margin:0 0 1em 0;}</style>\n"
            "</head><body>\n"
        )
        handle.write(f"<h1>{html.escape(title)}</h1>\n")
        for fragment_path in sorted(fragment_paths, key=natural_sort_key):
            handle.write(Path(fragment_path).read_text(encoding="utf-8", errors="ignore"))
        handle.write("</body></html>\n")


class HtmlVocabularyParser(HTMLParser):
    SKIP_TAGS = {"script", "style", "title", "svg", "math"}

    def __init__(self, annotator):
        super().__init__(convert_charrefs=False)
        self.annotator = annotator
        self.output = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        text = self.get_starttag_text()
        self.output.append(text if text is not None else self._format_starttag(tag, attrs))
        if tag.lower() in self.SKIP_TAGS:
            self.skip_depth += 1

    def handle_startendtag(self, tag, attrs):
        text = self.get_starttag_text()
        self.output.append(text if text is not None else self._format_starttag(tag, attrs, closed=True))

    def handle_endtag(self, tag):
        self.output.append(f"</{tag}>")
        if tag.lower() in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.skip_depth:
            self.output.append(data)
            return
        annotated = self.annotator.annotate_text(data)
        self.output.append(html.escape(annotated, quote=False))

    def handle_entityref(self, name):
        self.output.append(f"&{name};")

    def handle_charref(self, name):
        self.output.append(f"&#{name};")

    def handle_comment(self, data):
        self.output.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.output.append(f"<!{decl}>")

    def handle_pi(self, data):
        self.output.append(f"<?{data}>")

    def unknown_decl(self, data):
        self.output.append(f"<![{data}]>")

    def _format_starttag(self, tag, attrs, closed=False):
        pieces = [tag]
        for key, value in attrs:
            if value is None:
                pieces.append(key)
            else:
                pieces.append(f'{key}="{html.escape(value, quote=True)}"')
        suffix = "/>" if closed else ">"
        return "<" + " ".join(pieces) + suffix

    def get_html(self):
        return "".join(self.output)


def annotate_html_content(content, annotator):
    parser = HtmlVocabularyParser(annotator)
    parser.feed(content)
    parser.close()
    return parser.get_html()


def annotate_html_file(path, annotator):
    content = path.read_text(encoding="utf-8", errors="ignore")
    atomic_write_text(path, annotate_html_content(content, annotator))


def unpack_epub(epub_path, extract_dir):
    with zipfile.ZipFile(epub_path) as archive:
        archive.extractall(extract_dir)


def repack_epub(extract_dir, output_epub):
    output_epub.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_epub, "w") as archive:
        mimetype = extract_dir / "mimetype"
        if mimetype.exists():
            archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(extract_dir.rglob("*")):
            if not path.is_file() or path == mimetype:
                continue
            archive.write(path, path.relative_to(extract_dir).as_posix(), compress_type=zipfile.ZIP_DEFLATED)


def process_pdf_book(input_path, output_path, work_dir, config, progress):
    annotator = VocabularyAnnotator()
    text = extract_pdf_text(
        input_path,
        work_dir,
        config["ocr"],
        worker_count=config.get("page_workers", 1),
        progress=progress,
    )
    if not text.strip():
        raise RuntimeError(f"No text extracted from PDF: {input_path}")
    blocks = split_text_blocks(text)
    html_path = work_dir / f"{safe_stem(input_path)}_annotated.html"
    if stage_done(progress, "pdf_html_annotated", [html_path]):
        logging.info("Resume annotated PDF HTML from cache: %s", html_path)
        restore_annotator_state(annotator, progress.get("stages", {}).get("pdf_html_annotated", {}).get("annotator_state"))
    else:
        write_html_book(input_path.stem, blocks, annotator, html_path, progress=progress, work_dir=work_dir)
        mark_stage(
            progress,
            work_dir,
            "pdf_html_annotated",
            path=str(html_path),
            blocks=len(blocks),
            annotator_state=capture_annotator_state(annotator),
        )
    if stage_done(progress, "output_converted", [output_path]):
        logging.info("Resume converted output from cache: %s", output_path)
        restore_annotator_state(
            annotator,
            progress.get("stages", {}).get("output_converted", {}).get("annotator_state"),
        )
    else:
        atomic_convert_with_calibre(html_path, output_path, "Convert annotated PDF HTML to AZW3")
        mark_stage(
            progress,
            work_dir,
            "output_converted",
            path=str(output_path),
            annotator_state=capture_annotator_state(annotator),
        )
    return annotator.stats


def convert_input_to_epub(input_path, work_dir, progress):
    epub_path = work_dir / f"{safe_stem(input_path)}_source.epub"
    if stage_done(progress, "source_epub_ready", [epub_path]):
        logging.info("Resume source EPUB from cache: %s", epub_path)
        return epub_path
    if input_path.suffix.lower() == ".epub":
        atomic_copy(input_path, epub_path)
    else:
        atomic_convert_with_calibre(input_path, epub_path, "Convert source book to EPUB")
    mark_stage(progress, work_dir, "source_epub_ready", path=str(epub_path))
    return epub_path


def process_reflowable_book(input_path, output_path, work_dir, progress):
    annotator = VocabularyAnnotator()
    source_epub = convert_input_to_epub(input_path, work_dir, progress)
    extract_dir = work_dir / "epub_unpacked"
    html_suffixes = {".html", ".htm", ".xhtml"}
    if stage_done(progress, "epub_unpacked", [extract_dir]) and any(
        path.is_file() and path.suffix.lower() in html_suffixes
        for path in extract_dir.rglob("*")
    ):
        logging.info("Resume unpacked EPUB from cache: %s", extract_dir)
    else:
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        unpack_epub(source_epub, extract_dir)
        mark_stage(progress, work_dir, "epub_unpacked", path=str(extract_dir))

    html_files = [
        path
        for path in sorted(extract_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in html_suffixes
    ]
    if not html_files:
        raise RuntimeError(f"No HTML/XHTML content found in converted EPUB: {input_path}")

    epub_files_progress = progress.setdefault("epub_html_files", {})
    annotated_html_dir = work_dir / "annotated_epub_html"
    for index, html_file in enumerate(html_files, start=1):
        rel_path = html_file.relative_to(extract_dir).as_posix()
        annotated_cache = annotated_html_dir / rel_path
        file_progress = epub_files_progress.get(rel_path, {})
        if (
            file_progress.get("status") == "done"
            and annotated_cache.exists()
            and restore_annotator_state(annotator, file_progress.get("annotator_state"))
        ):
            atomic_copy(annotated_cache, html_file)
            logging.info(
                "Resume EPUB annotation progress %s file %s from cache: %s",
                input_path.name,
                progress_label(index, len(html_files)),
                rel_path,
            )
            continue

        logging.info(
            "EPUB annotation progress %s file %s: %s",
            input_path.name,
            progress_label(index, len(html_files)),
            rel_path,
        )
        content = html_file.read_text(encoding="utf-8", errors="ignore")
        annotated_html = annotate_html_content(content, annotator)
        atomic_write_text(annotated_cache, annotated_html)
        epub_files_progress[rel_path] = {
            "status": "done",
            "path": str(annotated_cache),
            "annotator_state": capture_annotator_state(annotator),
        }
        write_progress(work_dir, progress)
        atomic_write_text(html_file, annotated_html)

    annotated_epub = work_dir / f"{safe_stem(input_path)}_annotated.epub"
    if stage_done(progress, "epub_repacked", [annotated_epub]):
        logging.info("Resume repacked annotated EPUB from cache: %s", annotated_epub)
        restore_annotator_state(
            annotator,
            progress.get("stages", {}).get("epub_repacked", {}).get("annotator_state"),
        )
    else:
        repack_epub(extract_dir, annotated_epub)
        mark_stage(
            progress,
            work_dir,
            "epub_repacked",
            path=str(annotated_epub),
            files=len(html_files),
            annotator_state=capture_annotator_state(annotator),
        )
    if stage_done(progress, "output_converted", [output_path]):
        logging.info("Resume converted output from cache: %s", output_path)
        restore_annotator_state(
            annotator,
            progress.get("stages", {}).get("output_converted", {}).get("annotator_state"),
        )
    else:
        atomic_convert_with_calibre(annotated_epub, output_path, "Convert annotated EPUB to AZW3")
        mark_stage(
            progress,
            work_dir,
            "output_converted",
            path=str(output_path),
            annotator_state=capture_annotator_state(annotator),
        )
    return annotator.stats


def stats_to_dict(stats):
    return {
        "words_seen": int(getattr(stats, "words_seen", 0)),
        "difficult_candidates": int(getattr(stats, "difficult_candidates", 0)),
        "translated_words": int(getattr(stats, "translated_words", 0)),
        "inserted_annotations": int(getattr(stats, "inserted_annotations", 0)),
        "ollama_requests": int(getattr(stats, "ollama_requests", 0)),
        "ai_service_unavailable": bool(getattr(stats, "ai_service_unavailable", False)),
    }


def write_stats(path, stats, extra=None):
    payload = stats_to_dict(stats)
    if extra:
        payload.update(extra)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def sum_stats_dicts(items):
    total = {
        "words_seen": 0,
        "difficult_candidates": 0,
        "translated_words": 0,
        "inserted_annotations": 0,
        "ollama_requests": 0,
        "ai_service_unavailable": 0,
    }
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in total:
            try:
                total[key] += int(bool(item.get(key, False))) if key == "ai_service_unavailable" else int(item.get(key, 0))
            except (TypeError, ValueError):
                pass
    return total


def run_remote_worker_job(job_path, config):
    job_path = Path(job_path).resolve()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    kind = str(job.get("kind", "")).strip().lower()
    work_dir = Path(job["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = Path(job["artifact_path"])
    stats_path = Path(job["stats_path"])
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    config["page_workers"] = max(1, int(job.get("ocr_workers", config.get("page_workers", 1) or 1)))
    annotator = VocabularyAnnotator()

    if kind == "pdf":
        start_page = int(job["page_start"])
        end_page = int(job["page_end"])
        text = extract_pdf_text(
            Path(job["source_path"]),
            work_dir,
            config["ocr"],
            worker_count=config["page_workers"],
            progress=None,
            page_range=(start_page, end_page),
        )
        blocks = split_text_blocks(text)
        fragment = annotated_text_blocks_to_fragment(
            f"{job.get('title', 'book')} pages {start_page}-{end_page}",
            blocks,
            annotator,
        )
        atomic_write_text(artifact_path, fragment)
        write_stats(
            stats_path,
            annotator.stats,
            {
                "kind": kind,
                "chunk_index": int(job["chunk_index"]),
                "page_start": start_page,
                "page_end": end_page,
                "artifact_path": str(artifact_path),
            },
        )
        logging.info("Remote PDF worker chunk complete: %s", artifact_path)
        return 0

    if kind == "reflowable":
        source_epub = Path(job["source_epub"])
        extract_dir = work_dir / "epub_unpacked"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True, exist_ok=True)
        unpack_epub(source_epub, extract_dir)
        html_files = [str(item) for item in job.get("html_files", [])]
        if not html_files:
            raise RuntimeError("Remote reflowable worker job has no html_files")

        with zipfile.ZipFile(artifact_path, "w") as archive:
            for index, rel_path in enumerate(html_files, start=1):
                html_path = extract_dir / rel_path
                if not html_path.exists():
                    raise FileNotFoundError(f"Chunk HTML not found in EPUB: {rel_path}")
                logging.info(
                    "Remote EPUB worker chunk=%s file %s: %s",
                    job.get("chunk_index"),
                    progress_label(index, len(html_files)),
                    rel_path,
                )
                content = html_path.read_text(encoding="utf-8", errors="ignore")
                archive.writestr(rel_path, annotate_html_content(content, annotator))

        write_stats(
            stats_path,
            annotator.stats,
            {
                "kind": kind,
                "chunk_index": int(job["chunk_index"]),
                "files": len(html_files),
                "artifact_path": str(artifact_path),
            },
        )
        logging.info("Remote reflowable worker chunk complete: %s", artifact_path)
        return 0

    raise ValueError(f"Unknown remote worker job kind: {kind!r}")


def shell_join(args):
    return " ".join(shlex.quote(str(item)) for item in args)


def sanitize_remote_label(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._") or "remote"


def parse_remote_worker_specs(remote_config):
    workers = []
    for raw_spec in remote_config.get("workers", []):
        spec = str(raw_spec).strip()
        if not spec:
            continue
        if ":" not in spec:
            raise ValueError(
                f"Invalid remote worker {spec!r}. Expected ssh_target:/absolute/project/path"
            )
        ssh_target, project_path = spec.split(":", 1)
        ssh_target = ssh_target.strip()
        project_path = project_path.strip().rstrip("/")
        home_relative = project_path == "~" or project_path.startswith("~/")
        if not ssh_target or not (project_path.startswith("/") or home_relative):
            raise ValueError(
                f"Invalid remote worker {spec!r}. Expected ssh_target:/absolute/project/path "
                "or ssh_target:~/project/path"
            )
        label = sanitize_remote_label(ssh_target)
        workers.append(
            {
                "spec": spec,
                "ssh_target": ssh_target,
                "configured_project_path": project_path,
                "project_path": project_path,
                "label": label,
            }
        )
    return workers


def ssh_base_args(remote_config, worker=None, force_tty=False):
    options = shlex.split(remote_config.get("ssh_options", "") or "")
    args = ["ssh"]
    args.extend(options)
    if force_tty:
        args.append("-tt")
    if worker and worker.get("control_socket"):
        args.extend(["-o", "ControlMaster=auto", "-S", str(worker["control_socket"])])
    return args


def scp_base_args(remote_config, worker=None):
    options = shlex.split(remote_config.get("ssh_options", "") or "")
    args = ["scp"]
    args.extend(options)
    if worker and worker.get("control_socket"):
        args.extend(["-o", "ControlMaster=auto", "-o", f"ControlPath={worker['control_socket']}"])
    return args


def run_passthrough(cmd, description, cwd=None, timeout=None):
    logging.info("%s: %s", description, shell_join(cmd))
    proc = subprocess.run([str(item) for item in cmd], cwd=cwd, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}")
    return proc


class StreamingNoOutputTimeout(TimeoutError):
    pass


def process_tail_detail(tail_lines):
    if not tail_lines:
        return ""
    return " tail=" + "\n".join(tail_lines[-20:])


def kill_process_group(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        return
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        proc.wait()


def read_stream_lines(stream, output_queue):
    try:
        for line in stream:
            output_queue.put(line)
    finally:
        output_queue.put(None)


def run_streaming_cmd(cmd, description, cwd=None, timeout=None, idle_timeout=None):
    logging.info("%s: %s", description, shell_join(cmd))
    proc = subprocess.Popen(
        [str(item) for item in cmd],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        start_new_session=(os.name != "nt"),
    )
    tail_lines = []
    line_queue = queue.Queue()
    stdout_done = proc.stdout is None
    reader = None
    if proc.stdout is not None:
        reader = threading.Thread(
            target=read_stream_lines,
            args=(proc.stdout, line_queue),
            daemon=True,
        )
        reader.start()

    start_time = time.monotonic()
    last_output_time = start_time
    try:
        while not stdout_done:
            now = time.monotonic()
            deadlines = []
            if timeout is not None:
                deadlines.append(start_time + float(timeout))
            if idle_timeout is not None and idle_timeout > 0:
                deadlines.append(last_output_time + float(idle_timeout))
            queue_timeout = 0.5
            if deadlines:
                queue_timeout = min(queue_timeout, max(0.0, min(deadlines) - now))

            try:
                line = line_queue.get(timeout=queue_timeout)
            except queue.Empty:
                now = time.monotonic()
                if timeout is not None and now - start_time >= float(timeout):
                    raise subprocess.TimeoutExpired([str(item) for item in cmd], timeout)
                if idle_timeout is not None and idle_timeout > 0 and now - last_output_time >= float(idle_timeout):
                    raise StreamingNoOutputTimeout(
                        f"{description} no response for {idle_timeout}s"
                        f"{process_tail_detail(tail_lines)}"
                    )
                continue

            if line is None:
                stdout_done = True
                continue
            line = line.rstrip()
            if not line:
                continue
            last_output_time = time.monotonic()
            logging.info("%s output: %s", description, line)
            tail_lines.append(line)
            if len(tail_lines) > 80:
                tail_lines = tail_lines[-80:]

        wait_timeout = timeout
        if timeout is not None:
            wait_timeout = max(0.0, start_time + float(timeout) - time.monotonic())
        returncode = proc.wait(timeout=wait_timeout)
    except BaseException:
        kill_process_group(proc)
        raise
    finally:
        if reader is not None:
            reader.join(timeout=1)

    if returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {returncode}{process_tail_detail(tail_lines)}")
    return proc


def run_capture(cmd, description, cwd=None, timeout=None):
    return run_cmd(cmd, description, cwd=cwd, timeout=timeout, log_stdout=True, log_stderr=True)


def remote_shell(worker, remote_config, command, description, timeout=None, capture=True, force_tty=False):
    cmd = ssh_base_args(remote_config, worker, force_tty=force_tty) + [worker["ssh_target"], command]
    if capture:
        return run_capture(cmd, description, timeout=timeout)
    return run_passthrough(cmd, description, timeout=timeout)


def remote_shell_stream(worker, remote_config, command, description, timeout=None, idle_timeout=None, force_tty=False):
    cmd = ssh_base_args(remote_config, worker, force_tty=force_tty) + [worker["ssh_target"], command]
    return run_streaming_cmd(cmd, description, timeout=timeout, idle_timeout=idle_timeout)


def is_remote_connection_error(exc):
    text = str(exc).lower()
    markers = (
        "connection refused",
        "connection timed out",
        "no route to host",
        "network is unreachable",
        "host key verification failed",
        "could not resolve hostname",
        "name or service not known",
        "connection reset",
        "broken pipe",
        "exit code 255",
        "permission denied",
        "resource temporarily unavailable",
        "service temporarily unavailable",
        "service unavailable",
        "timed out",
        "cf-ray",
    )
    return any(marker in text for marker in markers)


def is_remote_setup_error(exc):
    text = str(exc).lower()
    markers = (
        "exit code 127",
        "not found",
        "no such file or directory",
        "envsetup/setupcpu.sh",
        "venv/bin/python3",
        "ebook-convert not found",
        "pdftotext not found",
        "tesseract not found",
        "ollama",
        "no module named",
    )
    return any(marker in text for marker in markers)


def mark_worker_unavailable(worker, reason):
    worker["unavailable"] = True
    worker["unavailable_reason"] = str(reason)
    logging.warning("Marking remote worker unavailable: %s reason=%s", worker.get("ssh_target"), reason)


def remote_mkdir(worker, remote_config, path):
    remote_shell(
        worker,
        remote_config,
        f"mkdir -p {shlex.quote(str(path))}",
        f"Remote mkdir {worker['ssh_target']}:{path}",
        capture=True,
    )


def scp_to_remote(worker, remote_config, local_path, remote_path, recursive=False):
    cmd = scp_base_args(remote_config, worker)
    if recursive:
        cmd.append("-r")
    cmd.extend([str(local_path), f"{worker['ssh_target']}:{remote_path}"])
    return run_passthrough(cmd, f"Copy to remote {worker['ssh_target']}:{remote_path}")


def scp_from_remote(worker, remote_config, remote_path, local_path, recursive=False):
    cmd = scp_base_args(remote_config, worker)
    if recursive:
        cmd.append("-r")
    cmd.extend([f"{worker['ssh_target']}:{remote_path}", str(local_path)])
    return run_passthrough(cmd, f"Copy from remote {worker['ssh_target']}:{remote_path}")


def open_ssh_control_connection(worker, remote_config):
    control_dir = Path(remote_config["ssh_control_path"])
    control_dir.mkdir(parents=True, exist_ok=True)
    target_hash = hashlib.sha1(worker["ssh_target"].encode("utf-8")).hexdigest()[:12]
    spec_hash = hashlib.sha1(worker["spec"].encode("utf-8")).hexdigest()[:12]
    socket_path = control_dir / f"{worker['label']}_{target_hash}.sock"
    legacy_socket_path = control_dir / f"{worker['label']}_{spec_hash}.sock"
    persist_seconds = int(
        remote_config.get("ssh_control_persist_seconds", DEFAULT_SSH_CONTROL_PERSIST_SECONDS) or 0
    )
    socket_candidates = [socket_path, legacy_socket_path]
    socket_candidates.extend(sorted(control_dir.glob(f"{worker['label']}_*.sock")))
    checked_paths = set()
    for candidate in socket_candidates:
        candidate_text = str(candidate)
        if candidate_text in checked_paths or not candidate.exists():
            continue
        checked_paths.add(candidate_text)
        worker["control_socket"] = candidate
        check_cmd = ssh_base_args(remote_config, worker) + ["-O", "check", worker["ssh_target"]]
        check_proc = subprocess.run(
            [str(item) for item in check_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        if check_proc.returncode == 0:
            logging.info("Reusing SSH control connection to %s", worker["ssh_target"])
            return
        candidate.unlink(missing_ok=True)
    worker["control_socket"] = socket_path
    cmd = ssh_base_args(remote_config)
    cmd.extend(
        [
            "-M",
            "-S",
            str(socket_path),
            "-o",
            f"ControlPersist={persist_seconds}",
            "-fN",
            worker["ssh_target"],
        ]
    )
    retries = max(1, int(remote_config.get("ssh_password_retries", 1) or 1))
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            run_passthrough(
                cmd,
                f"Open non-interactive SSH control connection to {worker['ssh_target']} "
                f"(attempt {attempt}/{retries})",
            )
            return
        except Exception as exc:
            last_exc = exc
            socket_path.unlink(missing_ok=True)
            if attempt < retries:
                logging.warning(
                    "Non-interactive SSH connection failed for %s. Check SSH key authentication. attempt=%d/%d reason=%s",
                    worker["ssh_target"],
                    attempt,
                    retries,
                    exc,
                )
    raise last_exc if last_exc is not None else RuntimeError(f"SSH connection failed: {worker['ssh_target']}")


def resolve_remote_project_path(worker, remote_config):
    identity_cmd = (
        "printf 'BOOKVOCAB_USER=%s\\nBOOKVOCAB_HOME=%s\\n' "
        '"$(id -un)" "$HOME"'
    )
    proc = remote_shell(
        worker,
        remote_config,
        identity_cmd,
        f"Read remote identity {worker['ssh_target']}",
    )
    identity = {}
    for line in proc.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in {"BOOKVOCAB_USER", "BOOKVOCAB_HOME"}:
            identity[key] = value.strip()

    remote_user = identity.get("BOOKVOCAB_USER", "")
    remote_home = identity.get("BOOKVOCAB_HOME", "")
    if not remote_user or not remote_home.startswith("/"):
        raise RuntimeError(
            f"Could not determine remote user/home for {worker['ssh_target']}: "
            f"user={remote_user!r} home={remote_home!r}"
        )

    configured_path = worker.get("configured_project_path", worker["project_path"])
    if configured_path == "~":
        resolved_path = remote_home
    elif configured_path.startswith("~/"):
        resolved_path = posixpath.join(remote_home, configured_path[2:])
    else:
        resolved_path = configured_path
    resolved_path = posixpath.normpath(resolved_path)
    if not resolved_path.startswith("/") or resolved_path == "/":
        raise ValueError(
            f"Unsafe resolved project path for {worker['ssh_target']}: {resolved_path!r}"
        )

    worker["remote_user"] = remote_user
    worker["remote_home"] = remote_home
    worker["project_path"] = resolved_path
    logging.info(
        "Remote identity %s user=%s home=%s configured_project=%s resolved_project=%s",
        worker["ssh_target"],
        remote_user,
        remote_home,
        configured_path,
        resolved_path,
    )


def close_ssh_control_connection(worker, remote_config):
    if not worker.get("control_socket"):
        return
    cmd = ssh_base_args(remote_config, worker) + ["-O", "exit", worker["ssh_target"]]
    try:
        subprocess.run([str(item) for item in cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    except Exception:
        pass


def handle_unavailable_worker_connection(worker, remote_config):
    persist_seconds = int(remote_config.get("ssh_control_persist_seconds", 0) or 0)
    control_socket = worker.get("control_socket")
    if persist_seconds > 0 and control_socket and Path(control_socket).exists():
        logging.info(
            "Keeping authenticated SSH control connection to %s alive for %d seconds "
            "so setup can be retried without reopening the SSH connection",
            worker.get("ssh_target"),
            persist_seconds,
        )
        return
    close_ssh_control_connection(worker, remote_config)


def remote_python_command(worker, remote_config):
    python_value = str(remote_config.get("python", "./venv/bin/python3") or "python3")
    if python_value.startswith("/"):
        return python_value
    return f"{worker['project_path']}/{python_value.lstrip('./')}"


def ensure_remote_setup(worker, remote_config, force=False):
    python_cmd = remote_python_command(worker, remote_config)
    if not force:
        check_cmd = (
            f"test -x {shlex.quote(python_cmd)} && "
            "command -v ebook-convert >/dev/null && "
            "command -v pdftotext >/dev/null && "
            "command -v tesseract >/dev/null"
        )
        try:
            remote_shell(worker, remote_config, check_cmd, f"Remote dependency check {worker['ssh_target']}")
            worker["setup_checked"] = True
            return
        except Exception as exc:
            logging.warning("Remote dependency check failed for %s: %s", worker["ssh_target"], exc)

    setup_cmd = f"cd {shlex.quote(worker['project_path'])} && bash EnvSetup/SetupCPU.sh"
    logging.info("Running remote setup on %s", worker["ssh_target"])
    remote_shell(
        worker,
        remote_config,
        setup_cmd,
        f"Remote setup {worker['ssh_target']}",
        capture=False,
        timeout=None,
        force_tty=True,
    )
    worker["setup_checked"] = True
    worker["setup_repaired"] = True


def is_loopback_url(url):
    parsed = urlparse(str(url or ""))
    host = (parsed.hostname or "").strip().lower()
    return host in {"", "localhost", "127.0.0.1", "::1", "0.0.0.0"}


def ollama_tags_url(api_url):
    parsed = urlparse(str(api_url or "http://localhost:11434/api/generate"))
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or "localhost:11434"
    return f"{scheme}://{netloc}/api/tags"


def ensure_remote_ollama_ready(worker, config):
    api_url = os.getenv("BOOKVOCAB_OLLAMA_API") or config.get("translation", {}).get("ollama_api", "")
    if not is_loopback_url(api_url):
        logging.info(
            "Remote Ollama local preflight skipped for %s because API is not loopback: %s",
            worker["ssh_target"],
            api_url,
        )
        return

    remote_config = config["remote"]
    model = os.getenv("BOOKVOCAB_OLLAMA_MODEL") or config.get("translation", {}).get("ollama_model", "qwen2.5:7b")
    tags_url = ollama_tags_url(api_url)
    command = "\n".join(
        [
            "set -eu",
            "command -v ollama >/dev/null",
            "mkdir -p \"$HOME/.ollama\"",
            f"TAGS_URL={shlex.quote(tags_url)}",
            f"MODEL={shlex.quote(model)}",
            "if ! curl -fsS --max-time 3 \"$TAGS_URL\" >/dev/null 2>&1; then",
            "    nohup ollama serve > \"$HOME/.ollama/bookvocab_ollama.log\" 2>&1 &",
            "    sleep 3",
            "fi",
            "curl -fsS --max-time 10 \"$TAGS_URL\" >/dev/null",
            "if ! ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fx \"$MODEL\" >/dev/null 2>&1; then",
            "    ollama pull \"$MODEL\"",
            "fi",
            "curl -fsS --max-time 10 \"$TAGS_URL\" >/dev/null",
        ]
    )
    try:
        remote_shell_stream(
            worker,
            remote_config,
            command,
            f"Remote Ollama preflight {worker['ssh_target']}",
            timeout=None,
        )
    except Exception:
        if not remote_config.get("setup_if_missing", False) or worker.get("setup_repaired"):
            raise
        ensure_remote_setup(worker, remote_config, force=True)
        remote_shell_stream(
            worker,
            remote_config,
            command,
            f"Remote Ollama preflight after setup {worker['ssh_target']}",
            timeout=None,
        )


def sync_project_to_worker(worker, remote_config):
    remote_mkdir(worker, remote_config, worker["project_path"])
    if not remote_config.get("sync_project", True):
        if remote_config.get("setup_if_missing", False):
            ensure_remote_setup(worker, remote_config)
        return

    exclude_args = []
    for item in (
        ".git",
        "Output",
        "Log",
        "tmp_cache",
        "venv",
        "__pycache__",
        "EnvSetup/pip_packages",
    ):
        exclude_args.extend(["--exclude", item])

    rsync = shutil.which("rsync")
    if rsync:
        remote_dest = f"{worker['ssh_target']}:{worker['project_path'].rstrip('/')}/"
        cmd = [
            rsync,
            "-az",
            "--delete",
            "-e",
            shell_join(ssh_base_args(remote_config, worker)),
        ]
        cmd.extend(exclude_args)
        cmd.extend([f"{SCRIPT_DIR}/", remote_dest])
        run_passthrough(cmd, f"Sync project to {worker['ssh_target']}")
    else:
        logging.warning("rsync not found; remote sync falls back to scp without delete/exclude")
        scp_to_remote(worker, remote_config, SCRIPT_DIR, str(Path(worker["project_path"]).parent), recursive=True)

    if remote_config.get("setup_if_missing", False):
        ensure_remote_setup(worker, remote_config)


def read_remote_resources(worker, remote_config):
    command = (
        "python3 -c "
        + shlex.quote(
            "import json, os\n"
            "mem={}\n"
            "with open('/proc/meminfo') as f:\n"
            "    for line in f:\n"
            "        k,v=line.split(':',1)\n"
            "        mem[k]=int(v.strip().split()[0])\n"
            "print(json.dumps({'cpu': os.cpu_count() or 1, "
            "'mem_total_mb': mem.get('MemTotal',0)//1024, "
            "'mem_available_mb': mem.get('MemAvailable',0)//1024}))"
        )
    )
    proc = remote_shell(worker, remote_config, command, f"Read resources {worker['ssh_target']}")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    worker["cpu"] = max(1, int(data.get("cpu", 1)))
    worker["mem_total_mb"] = max(0, int(data.get("mem_total_mb", 0)))
    worker["mem_available_mb"] = max(0, int(data.get("mem_available_mb", 0)))
    set_worker_capacity(worker, remote_config)


def set_worker_capacity(worker, remote_config):
    reserve_percent = min(90, max(0, int(remote_config.get("memory_reserve_percent", 15) or 0)))
    min_free_mb = max(0, int(remote_config.get("min_free_memory_mb", 2048) or 0))
    reserved_by_percent = worker["mem_available_mb"] * reserve_percent // 100
    reserve_mb = max(min_free_mb, reserved_by_percent)
    usable_memory_mb = max(0, worker["mem_available_mb"] - reserve_mb)
    memory_per_job_mb = max(1, int(remote_config.get("memory_per_job_mb", 4096) or 4096))
    cpu_per_job = max(1, int(remote_config.get("cpu_per_job", 2) or 2))
    slots_by_memory = max(1, usable_memory_mb // memory_per_job_mb) if usable_memory_mb else 1
    slots_by_cpu = max(1, worker["cpu"] // cpu_per_job)
    slots = max(1, min(slots_by_memory, slots_by_cpu))
    max_jobs_per_host = int(remote_config.get("max_jobs_per_host", 0) or 0)
    if max_jobs_per_host > 0:
        slots = min(slots, max_jobs_per_host)
    worker["reserve_mb"] = reserve_mb
    worker["usable_memory_mb"] = usable_memory_mb
    worker["slots"] = max(1, slots)
    worker["ocr_workers"] = max(1, min(cpu_per_job, worker["cpu"]))
    logging.info(
        "Remote host %s cpu=%d mem_total=%dMB mem_available=%dMB reserve=%dMB usable=%dMB slots=%d ocr_workers/job=%d",
        worker["ssh_target"],
        worker["cpu"],
        worker["mem_total_mb"],
        worker["mem_available_mb"],
        worker["reserve_mb"],
        worker["usable_memory_mb"],
        worker["slots"],
        worker["ocr_workers"],
    )


def prepare_local_worker(config):
    worker = {
        "spec": "local",
        "ssh_target": "local",
        "project_path": str(SCRIPT_DIR),
        "label": "local",
        "local": True,
        "cpu": max(1, os.cpu_count() or 1),
        "mem_total_mb": 0,
        "mem_available_mb": 0,
    }
    try:
        with Path("/proc/meminfo").open(encoding="utf-8") as handle:
            meminfo = {}
            for line in handle:
                key, value = line.split(":", 1)
                meminfo[key] = int(value.strip().split()[0])
        worker["mem_total_mb"] = max(0, meminfo.get("MemTotal", 0) // 1024)
        worker["mem_available_mb"] = max(0, meminfo.get("MemAvailable", 0) // 1024)
    except (OSError, ValueError):
        logging.warning("Could not read local /proc/meminfo; using CPU-only local capacity")
    set_worker_capacity(worker, config["remote"])
    worker["semaphore"] = threading.BoundedSemaphore(max(1, int(worker.get("slots", 1))))
    logging.info(
        "Local worker enabled cpu=%d mem_available=%dMB slots=%d ocr_workers/job=%d",
        worker["cpu"],
        worker["mem_available_mb"],
        worker["slots"],
        worker["ocr_workers"],
    )
    return worker


def prepare_remote_workers(config, require_all=False):
    remote_config = config["remote"]
    workers = parse_remote_worker_specs(remote_config)
    if not workers:
        raise ValueError("RemoteConfig.RemoteWorkers is empty")

    ready_workers = []
    unavailable_workers = []
    logging.info("Preparing %d remote worker(s) using non-interactive SSH authentication.", len(workers))
    for worker in workers:
        try:
            open_ssh_control_connection(worker, remote_config)
            resolve_remote_project_path(worker, remote_config)
            sync_project_to_worker(worker, remote_config)
            ensure_remote_ollama_ready(worker, config)
            read_remote_resources(worker, remote_config)
            worker["semaphore"] = threading.BoundedSemaphore(max(1, int(worker.get("slots", 1))))
            ready_workers.append(worker)
        except Exception as exc:
            unavailable_workers.append((worker, exc))
            logging.exception("Remote worker unavailable: %s", worker.get("ssh_target"))
            handle_unavailable_worker_connection(worker, remote_config)

    if not ready_workers:
        raise RuntimeError("No remote workers are available")
    if require_all and unavailable_workers:
        details = "; ".join(
            f"{worker.get('ssh_target')}: {exc}" for worker, exc in unavailable_workers
        )
        raise RuntimeError(
            f"{len(unavailable_workers)} of {len(workers)} configured remote worker(s) "
            f"failed preflight: {details}"
        )
    return ready_workers


def get_available_workers(workers):
    return [worker for worker in workers if not worker.get("unavailable")]


def prepare_worker_pool(config):
    workers = prepare_remote_workers(config)
    if config["remote"].get("include_local_worker", True):
        workers.append(prepare_local_worker(config))
    if not workers:
        raise RuntimeError("No workers are available")
    return workers


def cleanup_remote_workers(workers, remote_config):
    persist_seconds = int(remote_config.get("ssh_control_persist_seconds", 0) or 0)
    if persist_seconds > 0:
        logging.info("Keeping SSH control connections alive for %d seconds", persist_seconds)
        return
    for worker in workers:
        if worker.get("local"):
            continue
        close_ssh_control_connection(worker, remote_config)


def weighted_chunk(values, chunk_count):
    values = list(values)
    if not values:
        return []
    chunk_count = max(1, min(int(chunk_count), len(values)))
    chunks = []
    for index in range(chunk_count):
        start = index * len(values) // chunk_count
        end = (index + 1) * len(values) // chunk_count
        if start < end:
            chunks.append(values[start:end])
    return chunks


def plan_pdf_remote_chunks(input_path, config, total_slots):
    pages = pdf_page_count(input_path)
    chunks_per_slot = max(1, int(config["remote"].get("chunks_per_slot", 4) or 4))
    target_chunks = max(1, min(pages, total_slots * chunks_per_slot))
    chunks = []
    for index in range(target_chunks):
        start_page = index * pages // target_chunks + 1
        end_page = (index + 1) * pages // target_chunks
        chunks.append(
            {
                "kind": "pdf",
                "chunk_index": index,
                "page_start": start_page,
                "page_end": end_page,
            }
        )
    logging.info("Remote PDF plan: pages=%d chunks=%d total_slots=%d", pages, len(chunks), total_slots)
    return chunks


def remote_plan_signature(config, total_slots):
    remote_config = config["remote"]
    return {
        "chunks_per_slot": max(1, int(remote_config.get("chunks_per_slot", 4) or 4)),
        "total_slots": max(1, int(total_slots)),
    }


def prepare_reflowable_source_for_remote(input_path, work_dir, config):
    progress = reset_incompatible_progress(read_progress(work_dir), input_path, work_dir)
    source_epub = convert_input_to_epub(input_path, work_dir, progress)
    extract_dir = work_dir / "epub_unpacked_remote_plan"
    html_suffixes = {".html", ".htm", ".xhtml"}
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)
    unpack_epub(source_epub, extract_dir)
    html_files = [
        path.relative_to(extract_dir).as_posix()
        for path in sorted(extract_dir.rglob("*"))
        if path.is_file() and path.suffix.lower() in html_suffixes
    ]
    if not html_files:
        raise RuntimeError(f"No HTML/XHTML content found in converted EPUB: {input_path}")
    return source_epub, extract_dir, html_files


def plan_reflowable_remote_chunks(html_files, config, total_slots):
    chunks_per_slot = max(1, int(config["remote"].get("chunks_per_slot", 4) or 4))
    target_chunks = max(1, min(len(html_files), total_slots * chunks_per_slot))
    chunks = []
    for index, files in enumerate(weighted_chunk(html_files, target_chunks)):
        chunks.append(
            {
                "kind": "reflowable",
                "chunk_index": index,
                "html_files": files,
            }
        )
    logging.info("Remote reflowable plan: html_files=%d chunks=%d total_slots=%d", len(html_files), len(chunks), total_slots)
    return chunks


def build_worker_cycle(workers):
    cycle = []
    for worker in workers:
        cycle.extend([worker] * max(1, int(worker.get("slots", 1))))
    if not cycle:
        raise RuntimeError("No remote worker slots available")
    return cycle


def make_remote_run_id(input_path):
    source = json.dumps(file_fingerprint(input_path), sort_keys=True, separators=(",", ":"))
    return f"{safe_stem(input_path)}_{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}"


def chunk_job_matches(job, chunk):
    if not isinstance(job, dict):
        return False
    if str(job.get("kind", "")).strip().lower() != str(chunk.get("kind", "")).strip().lower():
        return False
    if int(job.get("chunk_index", -1)) != int(chunk.get("chunk_index", -2)):
        return False
    if chunk["kind"] == "pdf":
        return (
            int(job.get("page_start", -1)) == int(chunk.get("page_start", -2))
            and int(job.get("page_end", -1)) == int(chunk.get("page_end", -2))
        )
    return list(job.get("html_files", [])) == list(chunk.get("html_files", []))


def load_saved_chunk_plan(plan_path, input_path, kind, html_files=None, expected_signature=None):
    if not Path(plan_path).is_file():
        return None
    try:
        payload = json.loads(Path(plan_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("source") != file_fingerprint(input_path):
        return None
    if str(payload.get("kind", "")).strip().lower() != kind:
        return None
    if expected_signature is not None and payload.get("plan_signature") != expected_signature:
        logging.info(
            "Remote chunk plan parameters changed; rebuilding plan: %s old=%s new=%s",
            plan_path,
            payload.get("plan_signature"),
            expected_signature,
        )
        return None

    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        return None
    current_html_files = set(html_files or [])
    normalized = []
    seen_indexes = set()
    for item in chunks:
        if not isinstance(item, dict):
            return None
        chunk = dict(item)
        index = int(chunk.get("chunk_index", -1))
        if index < 0 or index in seen_indexes or chunk.get("kind") != kind:
            return None
        if kind == "pdf":
            if int(chunk.get("page_start", 0)) <= 0 or int(chunk.get("page_end", 0)) < int(chunk["page_start"]):
                return None
        elif not chunk.get("html_files") or not set(chunk["html_files"]).issubset(current_html_files):
            return None
        seen_indexes.add(index)
        normalized.append(chunk)
    normalized.sort(key=lambda value: int(value["chunk_index"]))
    return normalized


def save_chunk_plan(plan_path, input_path, kind, chunks, plan_signature=None):
    atomic_write_text(
        plan_path,
        json.dumps(
            {
                "source": file_fingerprint(input_path),
                "kind": kind,
                "plan_signature": plan_signature,
                "chunks": chunks,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    )


def int_stat(stats, key, default=0):
    try:
        return int(stats.get(key, default))
    except (AttributeError, TypeError, ValueError):
        return int(default)


def cache_has_unavailable_ai_result(stats):
    if not isinstance(stats, dict):
        return False
    if "ai_service_unavailable" in stats:
        return bool(stats.get("ai_service_unavailable"))
    return (
        int_stat(stats, "difficult_candidates") > 0
        and int_stat(stats, "ollama_requests") > 0
        and int_stat(stats, "translated_words") == 0
        and int_stat(stats, "inserted_annotations") == 0
    )


def load_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def valid_cached_stats(stats_path, chunk_index, cache_label):
    stats = load_json_file(stats_path)
    if not isinstance(stats, dict):
        return None
    if int_stat(stats, "chunk_index", -1) != int(chunk_index):
        return None
    if cache_has_unavailable_ai_result(stats):
        logging.warning(
            "Ignoring cached chunk %s from %s because AI translation was unavailable when it was produced",
            chunk_index,
            cache_label,
        )
        return None
    return stats


def load_cached_chunk_result(chunk, result_dir):
    chunk_index = int(chunk["chunk_index"])
    job_paths = [
        Path(result_dir) / f"job_{chunk_index:05d}.json",
        Path(result_dir) / f"local_chunk_{chunk_index:05d}" / "job.json",
    ]
    job = None
    job_path = None
    for candidate in job_paths:
        if not candidate.exists():
            continue
        try:
            candidate_job = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if chunk_job_matches(candidate_job, chunk):
            job = candidate_job
            job_path = candidate
            break
    if job is None:
        return None

    artifact_candidates = [Path(job.get("artifact_path", ""))]
    stats_candidates = [Path(job.get("stats_path", ""))]
    if chunk["kind"] == "pdf":
        artifact_candidates.append(Path(result_dir) / f"fragment_{chunk_index:05d}.html")
    else:
        artifact_candidates.append(Path(result_dir) / f"annotated_html_{chunk_index:05d}.zip")
    stats_candidates.append(Path(result_dir) / f"stats_{chunk_index:05d}.json")

    for artifact_path, stats_path in zip(artifact_candidates, stats_candidates):
        if not artifact_path.is_file() or not stats_path.is_file():
            continue
        stats = valid_cached_stats(stats_path, chunk_index, job_path)
        if stats is None:
            continue

        logging.info(
            "Reuse cached local chunk %s from %s",
            chunk_index,
            job_path,
        )
        return {
            "chunk_index": chunk_index,
            "kind": chunk["kind"],
            "artifact": artifact_path,
            "stats": stats,
            "worker": "cache",
        }
    return None


def cached_reflowable_member_map(result_dir):
    result_dir = Path(result_dir)
    member_map = {}
    for job_path in sorted(result_dir.glob("job_*.json")):
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(job.get("kind", "")).strip().lower() != "reflowable":
            continue
        chunk_index = int(job.get("chunk_index", -1))
        if chunk_index < 0:
            continue
        stats_candidates = [
            Path(job.get("stats_path", "")),
            result_dir / f"stats_{chunk_index:05d}.json",
        ]
        if not any(valid_cached_stats(path, chunk_index, job_path) is not None for path in stats_candidates if path):
            continue
        artifact_candidates = [
            Path(job.get("artifact_path", "")),
            result_dir / f"annotated_html_{chunk_index:05d}.zip",
        ]
        for artifact_path in artifact_candidates:
            if not artifact_path.is_file():
                continue
            try:
                with zipfile.ZipFile(artifact_path) as archive:
                    names = set(archive.namelist())
            except (OSError, zipfile.BadZipFile):
                continue
            for member in names:
                member_map.setdefault(member, artifact_path)
            break

    for job_path in sorted(result_dir.glob("local_chunk_*/job.json")):
        try:
            job = json.loads(job_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(job.get("kind", "")).strip().lower() != "reflowable":
            continue
        chunk_index = int(job.get("chunk_index", -1))
        stats_path = Path(job.get("stats_path", ""))
        if chunk_index < 0 or valid_cached_stats(stats_path, chunk_index, job_path) is None:
            continue
        artifact_path = Path(job.get("artifact_path", ""))
        if not artifact_path.is_file():
            continue
        try:
            with zipfile.ZipFile(artifact_path) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            continue
        for member in names:
            member_map.setdefault(member, artifact_path)
    return member_map


def load_cached_reflowable_member_chunk_result(chunk, result_dir, member_map):
    if chunk.get("kind") != "reflowable":
        return None
    html_files = list(chunk.get("html_files", []))
    if not html_files or any(member not in member_map for member in html_files):
        return None

    chunk_index = int(chunk["chunk_index"])
    artifact_path = Path(result_dir) / f"reused_annotated_html_{chunk_index:05d}.zip"
    stats = {
        "kind": "reflowable",
        "chunk_index": chunk_index,
        "files": len(html_files),
        "artifact_path": str(artifact_path),
        "words_seen": 0,
        "difficult_candidates": 0,
        "translated_words": 0,
        "inserted_annotations": 0,
        "ollama_requests": 0,
        "ai_service_unavailable": False,
        "reused_from_member_cache": True,
    }
    with zipfile.ZipFile(artifact_path, "w") as output_archive:
        for member in html_files:
            source_artifact = member_map[member]
            with zipfile.ZipFile(source_artifact) as source_archive:
                output_archive.writestr(member, source_archive.read(member))
    logging.info(
        "Reuse cached reflowable files for chunk=%s files=%d",
        chunk_index,
        len(html_files),
    )
    return {
        "chunk_index": chunk_index,
        "kind": "reflowable",
        "artifact": artifact_path,
        "stats": stats,
        "worker": "cache:files",
    }


def cached_remote_worker_candidates(job, workers):
    target = str(job.get("worker_target", "")).strip()
    label = str(job.get("worker_label", "")).strip()
    artifact_path = str(job.get("artifact_path", ""))
    ordered = []
    for worker in workers:
        if worker.get("unavailable"):
            continue
        if target and worker.get("ssh_target") == target:
            ordered.insert(0, worker)
        elif label and worker.get("label") == label:
            ordered.insert(0, worker)
        elif f"/{worker.get('label')}/chunk_" in artifact_path:
            ordered.insert(0, worker)
        else:
            ordered.append(worker)
    return ordered


def load_cached_remote_chunk_result(chunk, result_dir, workers, remote_config):
    chunk_index = int(chunk["chunk_index"])
    job_path = Path(result_dir) / f"job_{chunk_index:05d}.json"
    if not job_path.is_file():
        return None
    try:
        job = json.loads(job_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not chunk_job_matches(job, chunk):
        return None
    artifact_name = "fragment" if chunk["kind"] == "pdf" else "annotated_html"
    local_artifact = Path(result_dir) / f"{artifact_name}_{chunk_index:05d}.{'html' if chunk['kind'] == 'pdf' else 'zip'}"
    local_stats = Path(result_dir) / f"stats_{chunk_index:05d}.json"
    for worker in cached_remote_worker_candidates(job, workers):
        if not remote_chunk_artifacts_ready(worker, remote_config, job):
            continue
        try:
            scp_from_remote(worker, remote_config, job["artifact_path"], local_artifact)
            scp_from_remote(worker, remote_config, job["stats_path"], local_stats)
            stats = valid_cached_stats(local_stats, chunk_index, job_path)
        except (OSError, json.JSONDecodeError, RuntimeError):
            continue
        if stats is None:
            continue
        logging.info(
            "Reuse cached remote chunk %s from %s worker=%s",
            chunk_index,
            job_path,
            worker.get("ssh_target"),
        )
        return {
            "chunk_index": chunk_index,
            "kind": chunk["kind"],
            "artifact": local_artifact,
            "stats": stats,
            "worker": f"cache:{worker['ssh_target']}",
        }
    return None


def remote_chunk_artifacts_ready(worker, remote_config, job):
    command = (
        f"test -s {shlex.quote(str(job['artifact_path']))} && "
        f"test -s {shlex.quote(str(job['stats_path']))}"
    )
    try:
        remote_shell(
            worker,
            remote_config,
            command,
            f"Check cached remote chunk {job['chunk_index']} on {worker['ssh_target']}",
            capture=True,
        )
        return True
    except Exception:
        return False


def stage_remote_common_files(worker, remote_config, local_paths, remote_dir):
    remote_mkdir(worker, remote_config, remote_dir)
    for local_path, remote_name in local_paths:
        remote_path = posixpath.join(remote_dir, remote_name)
        scp_to_remote(worker, remote_config, local_path, remote_path)


def create_remote_worker_job(chunk, worker, remote_config, run_id, remote_source_name, remote_source_kind):
    remote_root = posixpath.join(str(remote_config["work_path"]).rstrip("/"), run_id, worker["label"])
    chunk_remote_dir = posixpath.join(remote_root, f"chunk_{int(chunk['chunk_index']):05d}")
    artifact_name = "fragment.html" if chunk["kind"] == "pdf" else "annotated_html.zip"
    job = {
        "kind": chunk["kind"],
        "chunk_index": int(chunk["chunk_index"]),
        "title": chunk.get("title", ""),
        "work_dir": posixpath.join(chunk_remote_dir, "work"),
        "artifact_path": posixpath.join(chunk_remote_dir, artifact_name),
        "stats_path": posixpath.join(chunk_remote_dir, "stats.json"),
        "ocr_workers": int(worker.get("ocr_workers", 1)),
        "worker_target": worker["ssh_target"],
        "worker_label": worker["label"],
    }
    if chunk["kind"] == "pdf":
        job["source_path"] = posixpath.join(remote_root, remote_source_name)
        job["page_start"] = int(chunk["page_start"])
        job["page_end"] = int(chunk["page_end"])
    else:
        job["source_epub"] = posixpath.join(remote_root, remote_source_name)
        job["html_files"] = list(chunk["html_files"])
    if remote_source_kind:
        job["source_kind"] = remote_source_kind
    return job, chunk_remote_dir, posixpath.join(chunk_remote_dir, "job.json")


def create_local_worker_job(chunk, worker, source_path, local_result_dir):
    chunk_index = int(chunk["chunk_index"])
    chunk_root = Path(local_result_dir) / f"local_chunk_{chunk_index:05d}"
    artifact_name = "fragment.html" if chunk["kind"] == "pdf" else "annotated_html.zip"
    job = {
        "kind": chunk["kind"],
        "chunk_index": chunk_index,
        "title": chunk.get("title", ""),
        "work_dir": str(chunk_root / "work"),
        "artifact_path": str(chunk_root / artifact_name),
        "stats_path": str(chunk_root / "stats.json"),
        "ocr_workers": int(worker.get("ocr_workers", 1)),
        "worker_target": "local",
        "worker_label": "local",
    }
    if chunk["kind"] == "pdf":
        job["source_path"] = str(Path(source_path).resolve())
        job["page_start"] = int(chunk["page_start"])
        job["page_end"] = int(chunk["page_end"])
    else:
        job["source_epub"] = str(Path(source_path).resolve())
        job["html_files"] = list(chunk["html_files"])
    return job, chunk_root / "job.json"


def run_local_chunk(chunk, config, source_path, local_result_dir):
    worker = chunk["worker"]
    job, local_job_path = create_local_worker_job(chunk, worker, source_path, local_result_dir)
    atomic_write_text(local_job_path, json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True))
    worker_threads = max(1, int(worker.get("ocr_workers", 1)))
    env_command = shutil.which("env") or "/usr/bin/env"
    cmd = [
        env_command,
        f"BOOKVOCAB_MAX_WORKERS={worker_threads}",
        f"BOOKVOCAB_CPU_THREADS={worker_threads}",
        f"BOOKVOCAB_OLLAMA_MODEL={os.getenv('BOOKVOCAB_OLLAMA_MODEL', '').strip()}",
        f"BOOKVOCAB_OLLAMA_API={os.getenv('BOOKVOCAB_OLLAMA_API', '').strip()}",
        "BOOKVOCAB_FAIL_ON_AI_UNAVAILABLE=1",
        sys.executable,
        str(SCRIPT_DIR / "main_batch.py"),
        "--remote-worker-job",
        str(local_job_path),
        "--local-only",
    ]
    run_streaming_cmd(
        cmd,
        f"Run local chunk {chunk['chunk_index']} with {worker_threads} CPU thread(s)",
        cwd=SCRIPT_DIR,
        timeout=None,
    )
    artifact_path = Path(job["artifact_path"])
    stats_path = Path(job["stats_path"])
    stats = valid_cached_stats(stats_path, int(chunk["chunk_index"]), "local")
    if stats is None:
        raise RuntimeError(f"Local chunk {chunk['chunk_index']} produced invalid stats")
    return {
        "chunk_index": int(chunk["chunk_index"]),
        "kind": chunk["kind"],
        "artifact": artifact_path,
        "stats": stats,
        "worker": "local",
    }


def run_remote_chunk(
    chunk,
    config,
    run_id,
    remote_source_name,
    remote_source_kind,
    local_result_dir,
    source_path,
):
    remote_config = config["remote"]
    worker = chunk["worker"]
    semaphore = worker.get("semaphore")
    if semaphore is None:
        semaphore = threading.BoundedSemaphore(max(1, int(worker.get("slots", 1))))
        worker["semaphore"] = semaphore

    with semaphore:
        if worker.get("local"):
            return run_local_chunk(chunk, config, source_path, local_result_dir)

        job, chunk_remote_dir, remote_job_path = create_remote_worker_job(
            chunk,
            worker,
            remote_config,
            run_id,
            remote_source_name,
            remote_source_kind,
        )
        local_job_path = local_result_dir / f"job_{int(chunk['chunk_index']):05d}.json"
        atomic_write_text(local_job_path, json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True))
        remote_mkdir(worker, remote_config, chunk_remote_dir)
        scp_to_remote(worker, remote_config, local_job_path, remote_job_path)

        python_cmd = remote_python_command(worker, remote_config)
        env_parts = []
        env_vars = {
            "BOOKVOCAB_MAX_WORKERS": max(1, int(worker.get("ocr_workers", 1))),
            "BOOKVOCAB_CPU_THREADS": max(1, int(worker.get("ocr_workers", 1))),
            "BOOKVOCAB_OLLAMA_MODEL": os.getenv("BOOKVOCAB_OLLAMA_MODEL", "").strip(),
            "BOOKVOCAB_OLLAMA_API": os.getenv("BOOKVOCAB_OLLAMA_API", "").strip(),
            "BOOKVOCAB_FAIL_ON_AI_UNAVAILABLE": "1",
        }
        for key, value in env_vars.items():
            if value:
                env_parts.append(f"{key}={shlex.quote(str(value))}")
        command = (
            f"cd {shlex.quote(worker['project_path'])} && "
            f"{' '.join(env_parts)} "
            f"{shlex.quote(python_cmd)} main_batch.py "
            f"--remote-worker-job {shlex.quote(remote_job_path)} --local-only"
        )
        no_response_timeout = int(remote_config.get("no_response_timeout_seconds", 120) or 0)
        remote_shell_stream(
            worker,
            remote_config,
            command,
            f"Run remote chunk {chunk['chunk_index']} on {worker['ssh_target']}",
            timeout=None,
            idle_timeout=no_response_timeout if no_response_timeout > 0 else None,
        )

        if chunk["kind"] == "pdf":
            local_artifact = local_result_dir / f"fragment_{int(chunk['chunk_index']):05d}.html"
        else:
            local_artifact = local_result_dir / f"annotated_html_{int(chunk['chunk_index']):05d}.zip"
        local_stats = local_result_dir / f"stats_{int(chunk['chunk_index']):05d}.json"
        scp_from_remote(worker, remote_config, job["artifact_path"], local_artifact)
        scp_from_remote(worker, remote_config, job["stats_path"], local_stats)
        stats = valid_cached_stats(local_stats, int(chunk["chunk_index"]), worker["ssh_target"])
        if stats is None:
            raise RuntimeError(
                f"Remote chunk {chunk['chunk_index']} on {worker['ssh_target']} produced invalid stats"
            )
    return {
        "chunk_index": int(chunk["chunk_index"]),
        "kind": chunk["kind"],
        "artifact": local_artifact,
        "stats": stats,
        "worker": worker["ssh_target"],
    }


def stage_remote_source_to_workers(workers, remote_config, run_id, local_source_path, remote_source_name):
    staged = set()
    for worker in workers:
        if worker.get("local"):
            continue
        remote_root = posixpath.join(str(remote_config["work_path"]).rstrip("/"), run_id, worker["label"])
        if worker["ssh_target"] in staged:
            continue
        stage_remote_common_files(worker, remote_config, [(local_source_path, remote_source_name)], remote_root)
        staged.add(worker["ssh_target"])


def complete_remote_pdf_book(input_path, output_path, work_dir, result_items):
    fragments = [item["artifact"] for item in sorted(result_items, key=lambda item: item["chunk_index"])]
    html_path = work_dir / f"{safe_stem(input_path)}_remote_annotated.html"
    write_html_fragments_book(input_path.stem, fragments, html_path)
    atomic_convert_with_calibre(html_path, output_path, "Convert remote annotated PDF HTML to AZW3")


def complete_remote_reflowable_book(input_path, output_path, work_dir, source_epub, extract_dir, result_items):
    for item in sorted(result_items, key=lambda value: value["chunk_index"]):
        with zipfile.ZipFile(item["artifact"]) as archive:
            for member in archive.namelist():
                destination = extract_dir / member
                destination.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(destination, archive.read(member).decode("utf-8", errors="ignore"))

    annotated_epub = work_dir / f"{safe_stem(input_path)}_remote_annotated.epub"
    repack_epub(extract_dir, annotated_epub)
    atomic_convert_with_calibre(annotated_epub, output_path, "Convert remote annotated EPUB to AZW3")


def process_book_remote(input_path, config):
    input_path = Path(input_path).resolve()
    output_path = output_path_for(input_path, config)
    if output_path.exists() and not config.get("overwrite_output", False):
        logging.info("Skip existing output: %s", output_path)
        return "skipped", output_path, None

    config["output_dir"].mkdir(parents=True, exist_ok=True)
    config["work_dir"].mkdir(parents=True, exist_ok=True)
    work_dir = config["work_dir"] / f"{safe_stem(input_path)}_remote_{hashlib.sha1(str(input_path).encode('utf-8')).hexdigest()[:10]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    result_dir = work_dir / "remote_results"
    result_dir.mkdir(parents=True, exist_ok=True)
    remote_progress = reset_incompatible_progress(read_progress(work_dir), input_path, work_dir)
    if not remote_progress.get("remote_results_ready"):
        logging.info("Remote result cache initialized: %s", result_dir)
        remote_progress["remote_results_ready"] = True
        write_progress(work_dir, remote_progress)

    workers = prepare_worker_pool(config)
    remote_config = config["remote"]
    try:
        total_slots = sum(max(1, int(worker.get("slots", 1))) for worker in workers)
        local_slots = sum(
            max(1, int(worker.get("slots", 1)))
            for worker in workers
            if worker.get("local")
        )
        remote_slots = total_slots - local_slots
        logging.info(
            "Distributed worker pool ready: remote_slots=%d local_slots=%d total_slots=%d",
            remote_slots,
            local_slots,
            total_slots,
        )
        run_id = make_remote_run_id(input_path)
        source_epub = None
        extract_dir = None
        chunk_plan_path = work_dir / "remote_chunk_plan.json"
        plan_signature = remote_plan_signature(config, total_slots)

        if input_path.suffix.lower() == ".pdf":
            chunks = load_saved_chunk_plan(
                chunk_plan_path,
                input_path,
                "pdf",
                expected_signature=plan_signature,
            )
            if chunks is None:
                chunks = plan_pdf_remote_chunks(input_path, config, total_slots)
                save_chunk_plan(chunk_plan_path, input_path, "pdf", chunks, plan_signature=plan_signature)
                logging.info("Saved remote chunk plan: %s", chunk_plan_path)
            else:
                logging.info("Reusing remote chunk plan: %s", chunk_plan_path)
            remote_source_name = input_path.name
            remote_source_path = input_path
            remote_source_kind = "pdf"
        else:
            source_epub, extract_dir, html_files = prepare_reflowable_source_for_remote(input_path, work_dir, config)
            chunks = load_saved_chunk_plan(
                chunk_plan_path,
                input_path,
                "reflowable",
                html_files=html_files,
                expected_signature=plan_signature,
            )
            if chunks is None:
                chunks = plan_reflowable_remote_chunks(html_files, config, total_slots)
                save_chunk_plan(chunk_plan_path, input_path, "reflowable", chunks, plan_signature=plan_signature)
                logging.info("Saved remote chunk plan: %s", chunk_plan_path)
            else:
                logging.info("Reusing remote chunk plan: %s", chunk_plan_path)
            remote_source_name = source_epub.name
            remote_source_path = source_epub
            remote_source_kind = "epub"

        for chunk in chunks:
            chunk["title"] = input_path.stem
        result_items = []
        pending_chunks = []
        cached_indexes = set()
        reflowable_member_map = cached_reflowable_member_map(result_dir) if remote_source_kind == "epub" else {}
        if reflowable_member_map:
            logging.info(
                "Cached reflowable member files available for reuse: %d",
                len(reflowable_member_map),
            )
        for chunk in chunks:
            cached_result = load_cached_chunk_result(chunk, result_dir)
            if cached_result is None:
                cached_result = load_cached_remote_chunk_result(chunk, result_dir, workers, remote_config)
            if cached_result is None and reflowable_member_map:
                cached_result = load_cached_reflowable_member_chunk_result(
                    chunk,
                    result_dir,
                    reflowable_member_map,
                )
            if cached_result is None:
                pending_chunks.append(chunk)
                continue
            result_items.append(cached_result)
            cached_indexes.add(int(chunk["chunk_index"]))

        if pending_chunks:
            stage_remote_source_to_workers(workers, remote_config, run_id, remote_source_path, remote_source_name)

        logging.info(
            "Dispatching distributed chunks for %s total=%d cached=%d pending=%d",
            input_path.name,
            len(chunks),
            len(cached_indexes),
            len(pending_chunks),
        )
        failures = []
        terminal_failures = []
        pending = deque(pending_chunks)
        max_parallel = max(1, min(len(pending), total_slots))
        completed = len(result_items)
        max_attempts_per_chunk = max(1, len(workers))

        def submit_chunk(executor, in_flight, worker):
            if worker.get("unavailable") or not pending:
                return False
            chunk = pending.popleft()
            chunk["worker"] = worker
            future = executor.submit(
                run_remote_chunk,
                chunk,
                config,
                run_id,
                remote_source_name,
                remote_source_kind,
                result_dir,
                remote_source_path,
            )
            in_flight[future] = (chunk, worker)
            logging.info(
                "Dynamic dispatch chunk=%s worker=%s pending=%d running=%d",
                chunk.get("chunk_index"),
                worker.get("ssh_target"),
                len(pending),
                len(in_flight),
            )
            return True

        if pending:
            worker_slots = build_worker_cycle(workers)
            logging.info(
                "Dynamic scheduling started: chunks=%d cached=%d pending=%d slots=%d workers=%d",
                len(chunks),
                len(result_items),
                len(pending),
                len(worker_slots),
                len(workers),
            )
            with ThreadPoolExecutor(max_workers=max_parallel) as executor:
                in_flight = {}
                for worker in worker_slots:
                    if len(in_flight) >= max_parallel or not pending:
                        break
                    submit_chunk(executor, in_flight, worker)

                while in_flight:
                    done, _not_done = wait(tuple(in_flight), return_when=FIRST_COMPLETED)
                    for future in done:
                        chunk, worker = in_flight.pop(future)
                        try:
                            result = future.result()
                            result_items.append(result)
                            completed += 1
                            logging.info(
                                "Remote chunk progress %s chunk=%s worker=%s",
                                progress_label(completed, len(chunks)),
                                result["chunk_index"],
                                result["worker"],
                            )
                        except Exception as exc:
                            failures.append((chunk, exc))
                            worker = chunk.get("worker", {})
                            chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
                            logging.exception(
                                "Remote chunk failed chunk=%s worker=%s",
                                chunk.get("chunk_index"),
                                worker.get("ssh_target"),
                            )
                            setup_repaired = False
                            if (
                                worker
                                and not worker.get("local")
                                and (
                                    isinstance(exc, StreamingNoOutputTimeout)
                                    or is_remote_connection_error(exc)
                                )
                            ):
                                mark_worker_unavailable(worker, exc)
                                close_ssh_control_connection(worker, remote_config)
                            elif (
                                worker
                                and not worker.get("local")
                                and is_remote_setup_error(exc)
                                and not worker.get("setup_repaired")
                            ):
                                try:
                                    ensure_remote_setup(worker, remote_config, force=True)
                                    setup_repaired = True
                                    logging.warning(
                                        "Remote worker setup repaired; requeueing chunk=%s worker=%s",
                                        chunk.get("chunk_index"),
                                        worker.get("ssh_target"),
                                    )
                                except Exception as setup_exc:
                                    logging.exception(
                                        "Remote setup repair failed worker=%s",
                                        worker.get("ssh_target"),
                                    )
                                    mark_worker_unavailable(worker, setup_exc)
                            elif worker:
                                mark_worker_unavailable(worker, exc)

                            if setup_repaired:
                                pending.appendleft(chunk)
                            elif chunk["attempts"] < max_attempts_per_chunk and get_available_workers(workers):
                                pending.append(chunk)
                            else:
                                terminal_failures.append((chunk, exc))
                                logging.error(
                                    "Remote chunk cannot be retried further chunk=%s attempts=%d available_workers=%d",
                                    chunk.get("chunk_index"),
                                    chunk["attempts"],
                                    len(get_available_workers(workers)),
                                )

                        if not worker.get("unavailable"):
                            submit_chunk(executor, in_flight, worker)

                    if pending and not in_flight:
                        available_workers = get_available_workers(workers)
                        if not available_workers:
                            break
                        available_slots = build_worker_cycle(available_workers)
                        for worker in available_slots:
                            if len(in_flight) >= max_parallel or not pending:
                                break
                            submit_chunk(executor, in_flight, worker)
        else:
            logging.info("All distributed chunks restored from cache for %s", input_path.name)

        if pending:
            terminal_failures.extend((chunk, RuntimeError("No worker slot available")) for chunk in pending)

        if terminal_failures:
            raise RuntimeError(f"{len(terminal_failures)} distributed chunk(s) could not be completed")
        if failures and len(result_items) != len(chunks):
            raise RuntimeError(f"{len(failures)} distributed chunk attempt(s) failed")
        if len(result_items) != len(chunks):
            raise RuntimeError(f"Expected {len(chunks)} remote result(s), got {len(result_items)}")

        if input_path.suffix.lower() == ".pdf":
            complete_remote_pdf_book(input_path, output_path, work_dir, result_items)
        else:
            complete_remote_reflowable_book(input_path, output_path, work_dir, source_epub, extract_dir, result_items)

        total_stats = sum_stats_dicts(item.get("stats") for item in result_items)
        logging.info(
            "Remote book complete: %s -> %s words_seen=%d difficult=%d translated=%d inserted=%d ollama_requests=%d",
            input_path,
            output_path,
            total_stats["words_seen"],
            total_stats["difficult_candidates"],
            total_stats["translated_words"],
            total_stats["inserted_annotations"],
            total_stats["ollama_requests"],
        )
        return "ok", output_path, total_stats
    finally:
        cleanup_remote_workers(workers, remote_config)


def process_book(input_path, config):
    output_path = output_path_for(input_path, config)
    if output_path.exists():
        logging.info("Skip existing output: %s", output_path)
        return "skipped", output_path, None

    config["output_dir"].mkdir(parents=True, exist_ok=True)
    config["work_dir"].mkdir(parents=True, exist_ok=True)
    work_dir = cache_dir_for(input_path, config)
    work_dir.mkdir(parents=True, exist_ok=True)
    progress = reset_incompatible_progress(read_progress(work_dir), input_path, work_dir)
    logging.info("Cache work directory: %s", work_dir)

    try:
        if input_path.suffix.lower() == ".pdf":
            stats = process_pdf_book(input_path, output_path, work_dir, config, progress)
        else:
            stats = process_reflowable_book(input_path, output_path, work_dir, progress)
        logging.info(
            "Book complete: %s -> %s words_seen=%d difficult=%d translated=%d inserted=%d ollama_requests=%d",
            input_path,
            output_path,
            stats.words_seen,
            stats.difficult_candidates,
            stats.translated_words,
            stats.inserted_annotations,
            stats.ollama_requests,
        )
        return "ok", output_path, stats
    finally:
        if config["keep_intermediate"]:
            logging.info("Keeping intermediate work directory: %s", work_dir)
        else:
            logging.info("Intermediate cache retained for resume: %s", work_dir)


def remote_preflight(config):
    workers = prepare_remote_workers(config, require_all=True)
    try:
        logging.info("Remote preflight OK: %d worker(s) available", len(workers))
        for worker in workers:
            logging.info(
                "Remote preflight worker=%s project=%s slots=%s ocr_workers=%s mem_available=%sMB",
                worker["ssh_target"],
                worker["project_path"],
                worker.get("slots"),
                worker.get("ocr_workers"),
                worker.get("mem_available_mb"),
            )
    finally:
        cleanup_remote_workers(workers, config["remote"])
    return 0


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Insert IPA and Chinese meanings for difficult English vocabulary into books.")
    parser.add_argument("--input", type=Path, default=None, help="Single input book file. Defaults to scanning config OriginalBookPath.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Override OriginalBookPath.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override OutputBookPath.")
    parser.add_argument("--keep-work", action="store_true", help="Keep Work/ intermediate files.")
    parser.add_argument("--skip-existing", action="store_true", help="Do not overwrite existing output files.")
    parser.add_argument("--run-mode", choices=("local", "remote"), default=None, help="Override RuntimeConfig.RunMode.")
    parser.add_argument("--local-only", action="store_true", help="Force local mode. Used internally by remote workers.")
    parser.add_argument("--remote-preflight", action="store_true", help="Check, sync, and set up remote workers, then exit.")
    parser.add_argument("--remote-worker-job", type=Path, default=None, help=argparse.SUPPRESS)
    return parser


def main(argv=None):
    setup_logging()
    args = build_arg_parser().parse_args(argv)
    config = load_config()
    if args.input_dir:
        config["original_dir"] = args.input_dir.resolve()
    if args.output_dir:
        config["output_dir"] = args.output_dir.resolve()
    if args.keep_work:
        config["keep_intermediate"] = True
    if args.skip_existing:
        config["overwrite_output"] = False
    if args.run_mode:
        config["run_mode"] = args.run_mode
    if args.local_only:
        config["run_mode"] = "local"

    if config["output_format"] != "azw3":
        raise ValueError("BookOutputConfig.OutputFormat must be azw3 for the current project requirement")

    apply_runtime_env(config)
    logging.info("CONFIG_FILE=%s", CONFIG_FILE)
    logging.info("ORIGINAL_DIR=%s", config["original_dir"])
    logging.info("OUTPUT_DIR=%s", config["output_dir"])
    logging.info("WORK_DIR=%s", config["work_dir"])
    logging.info("RUN_MODE=%s", config["run_mode"])

    if args.remote_worker_job:
        return run_remote_worker_job(args.remote_worker_job, config)

    if args.remote_preflight:
        return remote_preflight(config)

    if args.input:
        books = [args.input.resolve()]
    else:
        books = find_books(config["original_dir"], config["input_suffixes"])

    if not books:
        logging.warning("No input books found")
        return 0

    logging.info("Found %d book(s)", len(books))

    if config["run_mode"] == "remote":
        logging.info(
            "Remote workers configured: %s",
            ", ".join(config["remote"].get("workers", [])) or "(none)",
        )
        failures = 0
        for index, book in enumerate(books, start=1):
            logging.info(
                "Remote batch progress starting book %s: %s",
                progress_label(index - 1, len(books)),
                book,
            )
            try:
                status, output_path, _stats = process_book_remote(book, config)
                logging.info(
                    "Remote batch progress completed book %s status=%s: %s -> %s",
                    progress_label(index, len(books)),
                    status,
                    book,
                    output_path,
                )
            except Exception:
                failures += 1
                logging.exception("Remote book failed: %s", book)
        if failures:
            logging.error("Remote batch finished with %d failure(s)", failures)
            return 1
        logging.info("Remote batch finished successfully")
        return 0

    effective_workers = max(1, int(config.get("effective_workers", os.cpu_count() or 1)))
    configured_book_workers = int(config.get("book_workers", 1))
    if configured_book_workers <= 0:
        book_workers = max(1, min(effective_workers, len(books)))
    else:
        book_workers = max(1, min(configured_book_workers, effective_workers, len(books)))

    configured_ocr_workers = int(config.get("ocr_workers", 0))
    if configured_ocr_workers <= 0:
        page_workers = max(1, effective_workers // book_workers)
    else:
        page_workers = max(1, min(configured_ocr_workers, effective_workers))
    config["page_workers"] = page_workers
    logging.info(
        "Parallelism: effective_workers=%d book_workers=%d page_ocr_workers_per_book=%d",
        effective_workers,
        book_workers,
        page_workers,
    )

    failures = 0

    if book_workers == 1:
        for index, book in enumerate(books, start=1):
            logging.info(
                "Batch progress starting book %s: %s",
                progress_label(index - 1, len(books)),
                book,
            )
            try:
                status, output_path, _stats = process_book(book, config)
                logging.info(
                    "Batch progress completed book %s status=%s: %s -> %s",
                    progress_label(index, len(books)),
                    status,
                    book,
                    output_path,
                )
            except Exception:
                failures += 1
                logging.exception("Book failed: %s", book)
    else:
        logging.info("Start parallel book processing with %d workers", book_workers)
        with ThreadPoolExecutor(max_workers=book_workers) as executor:
            future_to_book = {
                executor.submit(process_book, book, config): book
                for book in books
            }
            completed = 0
            for future in as_completed(future_to_book):
                book = future_to_book[future]
                completed += 1
                try:
                    status, output_path, _stats = future.result()
                    logging.info(
                        "Batch progress completed book %s status=%s: %s -> %s",
                        progress_label(completed, len(books)),
                        status,
                        book,
                        output_path,
                    )
                except Exception:
                    failures += 1
                    logging.exception(
                        "Book failed at batch progress %s: %s",
                        progress_label(completed, len(books)),
                        book,
                    )

    if failures:
        logging.error("Batch finished with %d failure(s)", failures)
        return 1
    logging.info("Batch finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
