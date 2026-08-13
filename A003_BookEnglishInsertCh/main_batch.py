#!/usr/bin/env python3
import argparse
import configparser
import hashlib
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from book_vocab_module import VocabularyAnnotator


SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"

DEFAULT_CONFIG_TEXT = """[OriginalConfigPath]
OriginalBookPath=./original
OutputBookPath=./Output
WorkPath=./tmp_cache

[RuntimeConfig]
CaculateCore=CPU
# 0 = auto (use available CPU cores)
MaxWorkers=0
BookWorkers=1
OcrWorkers=0

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
OllamaModel=qwen2.5:7b
TranslationRepeatWindowWords=250
TranslationBatchSize=8
MaxContextChars=1800
OllamaTimeoutSeconds=240
OllamaRequestRetries=2
OllamaRetrySleepSeconds=3
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

    return {
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
    }


def apply_runtime_env(config):
    cpu_count = os.cpu_count() or 1
    configured_workers = config["max_workers"]
    if configured_workers <= 0:
        env_workers = os.getenv("BOOKVOCAB_MAX_WORKERS", "").strip()
        if env_workers.isdigit() and int(env_workers) > 0:
            configured_workers = int(env_workers)
        else:
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
    os.environ.setdefault("BOOKVOCAB_OLLAMA_MODEL", "qwen2.5:7b")
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
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}")
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


def extract_pdf_text_with_pdftotext(input_path, work_dir, progress=None):
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        logging.warning("pdftotext not found; PDF text layer extraction skipped")
        return ""

    output_txt = work_dir / "pdf_text_layer.txt"
    if progress is not None and stage_done(progress, "pdf_text_layer", [output_txt]):
        logging.info("Resume PDF text layer from cache: %s", output_txt)
        return output_txt.read_text(encoding="utf-8", errors="ignore")

    try:
        run_cmd([pdftotext, "-layout", input_path, output_txt], "PDF text layer extraction")
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


def ocr_pdf(input_path, work_dir, ocr_config, worker_count=1, progress=None):
    pdftoppm = require_tool("pdftoppm")
    tesseract = require_tool("tesseract")
    image_prefix = work_dir / "ocr_page"
    if progress is not None and stage_done(progress, "pdf_rasterized"):
        images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
        if images:
            logging.info("Resume PDF rasterized pages from cache: %d image(s)", len(images))
        else:
            logging.info("Cached PDF rasterization marker found but images are missing; rasterizing again")
            run_cmd(
                [pdftoppm, "-r", str(ocr_config["dpi"]), "-png", input_path, image_prefix],
                "PDF rasterization for OCR",
            )
            images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
    else:
        run_cmd(
            [pdftoppm, "-r", str(ocr_config["dpi"]), "-png", input_path, image_prefix],
            "PDF rasterization for OCR",
        )
        images = sorted(work_dir.glob("ocr_page-*.png"), key=natural_sort_key)
        if progress is not None:
            mark_stage(progress, work_dir, "pdf_rasterized", pages=len(images))

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
            logging.info("OCR progress %s page %d/%d", input_path.name, index, len(images))
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
                logging.info("OCR progress %s completed %d/%d", input_path.name, completed, len(images))
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


def extract_pdf_text(input_path, work_dir, ocr_config, worker_count=1, progress=None):
    final_text_path = work_dir / "pdf_extracted_text.txt"
    if progress is not None and stage_done(progress, "pdf_text_extracted", [final_text_path]):
        logging.info("Resume extracted PDF text from cache: %s", final_text_path)
        return final_text_path.read_text(encoding="utf-8", errors="ignore")

    text_layer = extract_pdf_text_with_pdftotext(input_path, work_dir, progress=progress)
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
    ocr_text = ocr_pdf(input_path, work_dir, ocr_config, worker_count=worker_count, progress=progress)
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
                logging.info("Text annotation progress %s %d/%d", title, index, total)
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
                "Resume EPUB annotation progress %s file %d/%d from cache: %s",
                input_path.name,
                index,
                len(html_files),
                rel_path,
            )
            continue

        logging.info("EPUB annotation progress %s file %d/%d: %s", input_path.name, index, len(html_files), rel_path)
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


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Insert IPA and Chinese meanings for difficult English vocabulary into books.")
    parser.add_argument("--input", type=Path, default=None, help="Single input book file. Defaults to scanning config OriginalBookPath.")
    parser.add_argument("--input-dir", type=Path, default=None, help="Override OriginalBookPath.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Override OutputBookPath.")
    parser.add_argument("--keep-work", action="store_true", help="Keep Work/ intermediate files.")
    parser.add_argument("--skip-existing", action="store_true", help="Do not overwrite existing output files.")
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

    if config["output_format"] != "azw3":
        raise ValueError("BookOutputConfig.OutputFormat must be azw3 for the current project requirement")

    apply_runtime_env(config)
    logging.info("CONFIG_FILE=%s", CONFIG_FILE)
    logging.info("ORIGINAL_DIR=%s", config["original_dir"])
    logging.info("OUTPUT_DIR=%s", config["output_dir"])
    logging.info("WORK_DIR=%s", config["work_dir"])

    if args.input:
        books = [args.input.resolve()]
    else:
        books = find_books(config["original_dir"], config["input_suffixes"])

    if not books:
        logging.warning("No input books found")
        return 0

    logging.info("Found %d book(s)", len(books))
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
            logging.info("Batch progress %d/%d: %s", index, len(books), book)
            try:
                process_book(book, config)
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
                    future.result()
                    logging.info("Batch progress completed %d/%d: %s", completed, len(books), book)
                except Exception:
                    failures += 1
                    logging.exception("Book failed: %s", book)

    if failures:
        logging.error("Batch finished with %d failure(s)", failures)
        return 1
    logging.info("Batch finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
