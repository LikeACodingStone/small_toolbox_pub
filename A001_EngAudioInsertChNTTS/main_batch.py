import logging
import os
import faulthandler
import multiprocessing
import platform
import re
import resource
import configparser
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime
from pathlib import Path

from transcribe_module import markdown_has_segments, markdown_is_complete, process_transcription
from tts_module import process_tts


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

CONFIG_FILE = SCRIPT_DIR / "config.ini"
LOG_DIR = SCRIPT_DIR / "Log"
RUNNING_RECORD_FILE = LOG_DIR / "RunningListRecording.log"
AUDIO_SUFFIXES = (".mp3", ".opus")
NUMBER_RE = re.compile(r"\d+")


def ensure_default_config():
    if CONFIG_FILE.exists():
        return

    CONFIG_FILE.write_text(
        "[OriginalConfigPath]\n"
        "# Directory that contains the original input audio files.\n"
        "OriginalAudioPath=../Resource/Dwark\n"
        "# Directory where generated markdown translation notes are written.\n"
        "TranslatePath=../Resource/translate\n"
        "# Directory where generated Chinese vocabulary audio files are written.\n"
        "AudioTranslatedPath=../Resource/chineseTTS\n"
        "\n"
        "[RuntimeConfig]\n"
        "# Select the compute branch: GPU uses the ROCm/CUDA Whisper path, CPU uses all available CPU cores.\n"
        "CaculateCore=GPU\n"
        "\n"
        "[DifficultyConfig]\n"
        "# CEFR levels that should always be treated as difficult vocabulary.\n"
        "AdvancedLevels=C1,C2\n"
        "# Minimum word length before a word can be considered for difficulty checks.\n"
        "MinCandidateLength=5\n"
        "# Minimum length for B1 words before frequency filtering can mark them as difficult.\n"
        "B1MinLength=8\n"
        "# Maximum word frequency for B1 words to be treated as difficult.\n"
        "B1FrequencyThreshold=0.000003\n"
        "# Minimum length for B2 words before frequency filtering can mark them as difficult.\n"
        "B2MinLength=8\n"
        "# Maximum word frequency for B2 words to be treated as difficult.\n"
        "B2FrequencyThreshold=0.000012\n"
        "# Minimum length for words with unknown CEFR level before frequency filtering can mark them as difficult.\n"
        "UnknownMinLength=8\n"
        "# Maximum word frequency for unknown-level words to be treated as difficult.\n"
        "UnknownFrequencyThreshold=0.000003\n"
        "\n"
        "[TranslationConfig]\n"
        "# Number of source segments to group before extracting and translating vocabulary.\n"
        "SegmentsPerTranslation=2\n"
        "# Use the current segment group as context to choose one best Chinese meaning per word.\n"
        "UseContextMeaning=1\n"
        "# Maximum number of characters allowed for each Chinese meaning.\n"
        "MaxMeaningChars=8\n"
        "# Retry once when the model returns a verbose or invalid meaning.\n"
        "RetryOnVerboseMeaning=1\n"
        "# Policy for unclear meanings; skip means the word is omitted from the output.\n"
        "AmbiguousMeaningPolicy=skip\n"
        "# Ollama sampling temperature for deterministic vocabulary meanings.\n"
        "OllamaTemperature=0\n"
        "# Do not translate the same word again within this many seconds.\n"
        "TranslationRepeatWindowSeconds=120\n"
        "\n"
        "[ProperNounConfig]\n"
        "# Enable spaCy NER filtering so person/place/organization names are not translated.\n"
        "SkipProperNouns=1\n"
        "# spaCy English NER model loaded on CPU.\n"
        "NlpModel=en_core_web_sm\n"
        "# Entity labels that should be filtered before vocabulary translation.\n"
        "EntityLabels=PERSON,GPE,LOC,FAC,ORG\n"
        "# Extra comma-separated words to skip even if the NER model misses them.\n"
        "SkipWords=\n",
        encoding="utf-8",
    )


def resolve_config_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def load_config_paths():
    ensure_default_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    section = parser["OriginalConfigPath"]

    original_audio_path = resolve_config_path(
        os.getenv("AUDIOSOURCE_SRC_DIR", section.get("OriginalAudioPath", "../Resource/Dwark"))
    )
    translate_root = resolve_config_path(
        os.getenv("AUDIOSOURCE_TRANSLATE_DIR", section.get("TranslatePath", "../Resource/translate"))
    )
    audio_root = resolve_config_path(
        os.getenv(
            "AUDIOSOURCE_AUDIO_TRANSLATED_DIR",
            section.get("AudioTranslatedPath", "../Resource/chineseTTS"),
        )
    )
    source_name = original_audio_path.name

    return original_audio_path, translate_root / source_name, audio_root / source_name


def load_calculate_core():
    ensure_default_config()
    parser = configparser.ConfigParser()
    parser.read(CONFIG_FILE, encoding="utf-8")
    if not parser.has_section("RuntimeConfig"):
        return "GPU"
    section = parser["RuntimeConfig"]
    core = section.get("CaculateCore", section.get("CalculateCore", "GPU"))
    core = core.strip().upper()
    return "CPU" if core == "CPU" else "GPU"


def apply_runtime_config_defaults():
    core = load_calculate_core()
    cpu_count = os.cpu_count() or 1
    if core == "CPU":
        os.environ.setdefault("AUDIOSOURCE_WHISPER_DEVICE", "cpu")
        os.environ.setdefault("AUDIOSOURCE_WHISPER_COMPUTE_TYPE", "int8")
        os.environ.setdefault("AUDIOSOURCE_WHISPER_CPU_THREADS", str(cpu_count))
        os.environ.setdefault("AUDIOSOURCE_WHISPER_CHUNK_SECONDS", "0")
        os.environ.setdefault("AUDIOSOURCE_MAX_WORKERS", "1")
        os.environ.setdefault("AUDIOSOURCE_USE_PROCESS_POOL", "0")
    else:
        os.environ.setdefault("AUDIOSOURCE_WHISPER_DEVICE", "cuda")
        os.environ.setdefault("AUDIOSOURCE_WHISPER_COMPUTE_TYPE", "float16")
        os.environ.setdefault("AUDIOSOURCE_WHISPER_CHUNK_SECONDS", "300")
        os.environ.setdefault("AUDIOSOURCE_MAX_WORKERS", "1")
    return core


CALCULATE_CORE = apply_runtime_config_defaults()
SRC_DIR, MD_DIR, AUDIO_DIR = load_config_paths()
SUBTITLE_DIRS = [
    Path(os.getenv("AUDIOSOURCE_SUBTITLE_DIR", "/home/neu/usr/bin/subtitles/AUDIOSOURCE")),
    SCRIPT_DIR / "AUDIOSOURCESub",
]

LOG_FILE = LOG_DIR / f"main_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

DEFAULT_WHISPER_DEVICE = os.getenv("AUDIOSOURCE_WHISPER_DEVICE", "cuda").strip().lower()
DEFAULT_MAX_WORKERS = 1 if DEFAULT_WHISPER_DEVICE != "cpu" else min(4, os.cpu_count() or 1)
MAX_WORKERS = max(1, int(os.getenv("AUDIOSOURCE_MAX_WORKERS", DEFAULT_MAX_WORKERS)))
OLLAMA_MODELS = [
    model.strip()
    for model in os.getenv(
        "AUDIOSOURCE_OLLAMA_MODELS",
        os.getenv("AUDIOSOURCE_OLLAMA_MODEL", "qwen2.5:7b"),
    ).split(",")
    if model.strip()
]


def env_bool(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def clear_log_dir():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not env_bool("AUDIOSOURCE_CLEAR_LOGS", True):
        return
    for path in LOG_DIR.iterdir():
        if path.is_file():
            path.unlink()


def record_running_status(status, path):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with RUNNING_RECORD_FILE.open("a", encoding="utf-8") as handle:
        handle.write(f"{status}: {path}\n")


def setup_worker_logging(stem):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    safe_stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)[:80]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    worker_log = LOG_DIR / f"main_batch_worker_{pid}_{timestamp}_{safe_stem}.log"
    fault_log = LOG_DIR / f"main_batch_worker_{pid}_{timestamp}_{safe_stem}.fault.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - [pid=%(process)d] - %(message)s")
    file_handler = logging.FileHandler(worker_log, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    fault_handle = open(fault_log, "w", encoding="utf-8")
    faulthandler.enable(file=fault_handle, all_threads=True)

    logging.info("Worker log file: %s", worker_log)
    logging.info("Worker fault log file: %s", fault_log)
    return worker_log, fault_log, fault_handle


def setup_fault_logging(stem):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    safe_stem = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)[:80]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fault_log = LOG_DIR / f"main_batch_serial_{pid}_{timestamp}_{safe_stem}.fault.log"
    fault_handle = open(fault_log, "w", encoding="utf-8")
    faulthandler.enable(file=fault_handle, all_threads=True)
    logging.info("Serial fault log file: %s", fault_log)
    return fault_log, fault_handle


def log_runtime_context(label):
    logging.info("%s pid=%s ppid=%s python=%s", label, os.getpid(), os.getppid(), sys.executable)
    logging.info("%s platform=%s", label, platform.platform())
    logging.info(
        "%s runtime CaculateCore=%s", label, CALCULATE_CORE
    )
    logging.info(
        "%s env AUDIOSOURCE_MAX_WORKERS=%r AUDIOSOURCE_WHISPER_DEVICE=%r "
        "AUDIOSOURCE_WHISPER_COMPUTE_TYPE=%r AUDIOSOURCE_WHISPER_CPU_THREADS=%r "
        "AUDIOSOURCE_OLLAMA_MODEL=%r",
        label,
        os.getenv("AUDIOSOURCE_MAX_WORKERS"),
        os.getenv("AUDIOSOURCE_WHISPER_DEVICE"),
        os.getenv("AUDIOSOURCE_WHISPER_COMPUTE_TYPE"),
        os.getenv("AUDIOSOURCE_WHISPER_CPU_THREADS"),
        os.getenv("AUDIOSOURCE_OLLAMA_MODEL"),
    )
    usage = resource.getrusage(resource.RUSAGE_SELF)
    logging.info("%s resource maxrss_kb=%s user_cpu=%.2f sys_cpu=%.2f", label, usage.ru_maxrss, usage.ru_utime, usage.ru_stime)


def norm_name(value):
    normalized = unicodedata.normalize("NFKC", str(value))
    normalized = normalized.replace("\u30fb", " ")
    normalized = normalized.replace("_", " ")
    normalized = normalized.replace("-", " ")
    return "".join(ch.lower() for ch in normalized if ch.isalnum())


def natural_path_key(path):
    try:
        text = str(path.relative_to(SRC_DIR))
    except ValueError:
        text = str(path)

    text = text.casefold()
    parts = []
    index = 0
    for match in NUMBER_RE.finditer(text):
        if match.start() > index:
            parts.append((1, text[index:match.start()]))
        number_text = match.group(0)
        parts.append((0, int(number_text), len(number_text)))
        index = match.end()

    if index < len(text):
        parts.append((1, text[index:]))

    return tuple(parts)


def find_recursive(root, suffixes):
    root = Path(root)
    if not root.exists():
        return []

    results = []
    for suffix in suffixes:
        results.extend(root.rglob(f"*{suffix}"))
    return results


def build_existing_audio_index():
    found = {}
    for path in find_recursive(AUDIO_DIR.parent, [".mp3"]):
        found.setdefault(norm_name(path.stem), path)
    return found


def find_existing_audio(audio_index, stem):
    keys = [norm_name(stem), norm_name(f"{stem}_Vocab")]
    for key in keys:
        if key in audio_index:
            return audio_index[key]

    normalized_stem = norm_name(stem)
    for key, path in audio_index.items():
        if normalized_stem and normalized_stem in key:
            return path

    return None


def find_existing_translation(stem):
    search_root = MD_DIR.parent
    normalized_stem = norm_name(stem)

    for md_path in find_recursive(search_root, [".md"]):
        if norm_name(md_path.stem) == normalized_stem:
            return md_path

    for md_path in find_recursive(search_root, [".md"]):
        normalized_md = norm_name(md_path.stem)
        if normalized_stem and normalized_md and (
            normalized_stem in normalized_md or normalized_md in normalized_stem
        ):
            return md_path

    return None


def find_existing_subtitle(stem):
    normalized_stem = norm_name(stem)
    logging.info("Looking for subtitle for stem=%r normalized=%r", stem, normalized_stem)

    for subtitle_dir in SUBTITLE_DIRS:
        subtitle_dir = Path(subtitle_dir)
        logging.info("Checking subtitle dir: %s exists=%s", subtitle_dir, subtitle_dir.exists())
        if not subtitle_dir.exists():
            continue

        candidates = []
        candidates.extend(find_recursive(subtitle_dir, [".srt"]))
        candidates.extend(find_recursive(subtitle_dir, [".vtt"]))
        candidates.extend(find_recursive(subtitle_dir, [".txt"]))
        logging.info("Found %d subtitle candidates in %s", len(candidates), subtitle_dir)

        for subtitle_path in candidates:
            normalized_subtitle = norm_name(subtitle_path.stem)
            if normalized_stem == normalized_subtitle:
                logging.info("Matched subtitle exact: %s", subtitle_path)
                return subtitle_path

        for subtitle_path in candidates:
            normalized_subtitle = norm_name(subtitle_path.stem)
            if normalized_stem and normalized_subtitle and (
                normalized_stem in normalized_subtitle or normalized_subtitle in normalized_stem
            ):
                logging.info(
                    "Matched subtitle partial: audio=%r subtitle=%r file=%s",
                    normalized_stem,
                    normalized_subtitle,
                    subtitle_path,
                )
                return subtitle_path

    logging.warning("No subtitle matched for stem=%r normalized=%r", stem, normalized_stem)
    return None


def should_rebuild_translation(md_path):
    if not md_path.exists():
        return True

    if not markdown_has_segments(md_path):
        logging.warning("Translation file exists but has no usable segments, will rebuild: %s", md_path)
        return True

    if not markdown_is_complete(md_path):
        logging.warning("Translation file exists but is incomplete, will rebuild before TTS: %s", md_path)
        return True

    return False


def process_one_file(audio_path, ollama_model=None, configure_worker_logging=True):
    audio_path = Path(audio_path)
    stem = audio_path.stem
    result = {"stem": stem, "status": "ok", "output": None}
    start_time = time.monotonic()
    fault_handle = None

    try:
        if configure_worker_logging:
            _worker_log, _fault_log, fault_handle = setup_worker_logging(stem)
        else:
            _fault_log, fault_handle = setup_fault_logging(stem)
        if ollama_model:
            os.environ["AUDIOSOURCE_OLLAMA_MODEL"] = ollama_model

        logging.info("Processing file start: %s", audio_path)
        log_runtime_context("worker-start")
        logging.info("Ollama model for this file: %s", os.getenv("AUDIOSOURCE_OLLAMA_MODEL", "qwen2.5:7b"))

        final_mp3 = AUDIO_DIR / f"{stem}_Vocab.mp3"
        if final_mp3.exists() and final_mp3.stat().st_size > 0:
            logging.info("Skip audio generation, final mp3 exists: %s", final_mp3)
            md_path = find_existing_translation(stem)
            if md_path and not should_rebuild_translation(md_path):
                record_running_status("translated", md_path)
            record_running_status("audio", final_mp3)
            result["status"] = "skipped"
            result["output"] = str(final_mp3)
            return result

        stage_start = time.monotonic()
        logging.info("Stage translation lookup start")
        md_path = find_existing_translation(stem)
        logging.info("Stage translation lookup done elapsed=%.2fs md_path=%s", time.monotonic() - stage_start, md_path)

        if md_path and not should_rebuild_translation(md_path):
            logging.info("Use existing translation md: %s", md_path)
            record_running_status("translated", md_path)
        else:
            md_path = MD_DIR / f"{stem}.md"
            subtitle_path = find_existing_subtitle(stem)
            if subtitle_path:
                logging.info("Use subtitle file instead of audio transcription: %s", subtitle_path)

            stage_start = time.monotonic()
            logging.info("Stage transcription start audio=%s md=%s", audio_path, md_path)
            process_transcription(
                str(audio_path),
                str(md_path),
                subtitle_file=str(subtitle_path) if subtitle_path else None,
            )
            logging.info("Stage transcription done elapsed=%.2fs", time.monotonic() - stage_start)
            record_running_status("translated", md_path)

        if final_mp3.exists() and final_mp3.stat().st_size > 0:
            logging.info("Skip audio generation, final mp3 exists after transcription: %s", final_mp3)
            record_running_status("audio", final_mp3)
            result["status"] = "skipped"
            result["output"] = str(final_mp3)
            return result

        stage_start = time.monotonic()
        logging.info("Stage TTS start md=%s original=%s output=%s", md_path, audio_path, final_mp3)
        process_tts(str(md_path), str(audio_path), str(final_mp3))
        logging.info("Stage TTS done elapsed=%.2fs", time.monotonic() - stage_start)

        if final_mp3.exists() and final_mp3.stat().st_size > 0:
            record_running_status("audio", final_mp3)
            result["output"] = str(final_mp3)
            return result

        raise RuntimeError(f"TTS did not produce a non-empty mp3: {final_mp3}")
    except BaseException:
        logging.exception("Worker failed for file=%s elapsed=%.2fs", audio_path, time.monotonic() - start_time)
        raise
    finally:
        logging.info("Processing file end: %s elapsed=%.2fs", audio_path, time.monotonic() - start_time)
        if fault_handle:
            fault_handle.close()


def main():
    clear_log_dir()
    setup_logging()
    logging.info("CONFIG_FILE=%s", CONFIG_FILE)
    logging.info("SRC_DIR=%s", SRC_DIR)
    logging.info("MD_DIR=%s", MD_DIR)
    logging.info("AUDIO_DIR=%s", AUDIO_DIR)
    logging.info("SUBTITLE_DIRS=%s", ", ".join(str(p) for p in SUBTITLE_DIRS))
    logging.info("MAX_WORKERS=%s", MAX_WORKERS)
    logging.info("OLLAMA_MODELS=%s", ", ".join(OLLAMA_MODELS))
    logging.info("multiprocessing start method=%s", multiprocessing.get_start_method(allow_none=True))
    log_runtime_context("parent-start")

    MD_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    if not SRC_DIR.exists():
        logging.error("Source directory does not exist: %s", SRC_DIR)
        return 1

    files = sorted(
        (
            path
            for path in SRC_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_SUFFIXES
        ),
        key=natural_path_key,
    )
    logging.info("Found %d source audio files suffixes=%s", len(files), ", ".join(AUDIO_SUFFIXES))

    audio_index = build_existing_audio_index()

    pending_files = []
    for mp3_path in files:
        existing_audio = find_existing_audio(audio_index, mp3_path.stem)
        if existing_audio:
            logging.info("Skip audio generation, existing translated audio found: %s", existing_audio)
            existing_translation = find_existing_translation(mp3_path.stem)
            if existing_translation and not should_rebuild_translation(existing_translation):
                record_running_status("translated", existing_translation)
            record_running_status("audio", existing_audio)
            continue
        pending_files.append(mp3_path)

    logging.info("Pending source audio files: %d", len(pending_files))
    if not pending_files:
        return 0

    worker_count = min(MAX_WORKERS, len(pending_files))
    logging.info("Start parallel processing with %d workers", worker_count)

    completed = 0
    failed = 0
    use_process_pool_default = DEFAULT_WHISPER_DEVICE == "cpu" and worker_count > 1
    use_process_pool = env_bool("AUDIOSOURCE_USE_PROCESS_POOL", use_process_pool_default)
    logging.info("USE_PROCESS_POOL=%s default=%s", use_process_pool, use_process_pool_default)

    if not use_process_pool:
        logging.info("Run files serially in the main process to avoid ROCm/HIP fork instability")
        for index, mp3_path in enumerate(pending_files):
            model_name = OLLAMA_MODELS[index % len(OLLAMA_MODELS)] if OLLAMA_MODELS else None
            try:
                logging.info("Serial processing file index=%d path=%s ollama_model=%s", index, mp3_path, model_name)
                result = process_one_file(str(mp3_path), model_name, configure_worker_logging=False)
                completed += 1
                logging.info(
                    "Completed %s status=%s output=%s",
                    result["stem"],
                    result["status"],
                    result["output"],
                )
            except Exception:
                failed += 1
                logging.exception("Processing failed: %s", mp3_path)
        logging.info("Batch completed: success=%d failed=%d", completed, failed)
        return 1 if failed else 0

    try:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            future_to_file = {}
            for index, mp3_path in enumerate(pending_files):
                model_name = OLLAMA_MODELS[index % len(OLLAMA_MODELS)] if OLLAMA_MODELS else None
                logging.info("Submit file index=%d path=%s ollama_model=%s", index, mp3_path, model_name)
                future = executor.submit(process_one_file, str(mp3_path), model_name)
                future_to_file[future] = mp3_path

            for future in as_completed(future_to_file):
                mp3_path = future_to_file[future]
                try:
                    result = future.result()
                    completed += 1
                    logging.info(
                        "Completed %s status=%s output=%s",
                        result["stem"],
                        result["status"],
                        result["output"],
                    )
                except BrokenProcessPool:
                    failed += 1
                    logging.exception(
                        "Process pool broke while processing %s. "
                        "A worker was killed abruptly; check Log/main_batch_worker_*.log "
                        "and Log/main_batch_worker_*.fault.log. "
                        "If AUDIOSOURCE_WHISPER_DEVICE=cuda, force AUDIOSOURCE_MAX_WORKERS=1 for AMD GPU.",
                        mp3_path,
                    )
                    raise
                except Exception:
                    failed += 1
                    logging.exception("Processing failed: %s", mp3_path)
    except BrokenProcessPool:
        logging.error("Batch stopped because the process pool is broken. completed=%d failed=%d", completed, failed)
        raise

    logging.info("Batch completed: success=%d failed=%d", completed, failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
