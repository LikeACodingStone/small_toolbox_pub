import logging
import os
import re
import gc
import argparse
import configparser
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import requests
from cefrpy import CEFRAnalyzer
from faster_whisper import WhisperModel
from wordfreq import word_frequency


logger = logging.getLogger(__name__)
_LOG_INITIALIZED = False
_LOG_FILE = None
_RUNTIME_CORE_CACHE = {"mtime": None, "core": None}
_PROPER_NOUN_CONFIG_CACHE = {"mtime": None, "config": None}
_TRANSLATION_CONFIG_CACHE = {"mtime": None, "config": None}
_SPACY_NLP_CACHE = {"model": None, "nlp": None, "failed_models": set()}

analyzer = CEFRAnalyzer()
OLLAMA_API = "http://localhost:11434/api/generate"
FILTER_FILE = Path(__file__).resolve().parent / "filter.txt"
CONFIG_FILE = Path(__file__).resolve().parent / "config.ini"
COMPLETE_MARKER = "<!-- TRANSCRIPTION_COMPLETE -->"


def setup_logging():
    global _LOG_INITIALIZED, _LOG_FILE

    if _LOG_INITIALIZED:
        return _LOG_FILE

    script_dir = Path(__file__).resolve().parent
    log_dir = script_dir / "Log"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _LOG_FILE = log_dir / f"transcribe_module_{timestamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    _LOG_INITIALIZED = True
    logger.info("Log file: %s", _LOG_FILE)
    return _LOG_FILE


def env_int(name, default):
    try:
        return max(1, int(os.getenv(name, default)))
    except ValueError:
        logger.warning("Invalid integer env %s=%r, using default=%s", name, os.getenv(name), default)
        return max(1, int(default))


def env_nonnegative_int(name, default):
    try:
        return max(0, int(os.getenv(name, default)))
    except ValueError:
        logger.warning("Invalid integer env %s=%r, using default=%s", name, os.getenv(name), default)
        return max(0, int(default))


def env_float(name, default):
    try:
        return max(0.0, float(os.getenv(name, default)))
    except ValueError:
        logger.warning("Invalid float env %s=%r, using default=%s", name, os.getenv(name), default)
        return max(0.0, float(default))


def env_bool(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_ollama_model():
    return os.getenv("AUDIOSOURCE_OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"


def get_configured_calculate_core():
    mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
    if _RUNTIME_CORE_CACHE["core"] is not None and _RUNTIME_CORE_CACHE["mtime"] == mtime:
        return _RUNTIME_CORE_CACHE["core"]

    core = "GPU"
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("RuntimeConfig"):
            section = parser["RuntimeConfig"]
            core = section.get("CaculateCore", section.get("CalculateCore", "GPU"))

    core = "CPU" if str(core).strip().upper() == "CPU" else "GPU"
    _RUNTIME_CORE_CACHE["mtime"] = mtime
    _RUNTIME_CORE_CACHE["core"] = core
    return core


def get_whisper_cpu_threads():
    value = os.getenv("AUDIOSOURCE_WHISPER_CPU_THREADS")
    if value is not None:
        return env_int("AUDIOSOURCE_WHISPER_CPU_THREADS", "1")
    if get_configured_calculate_core() == "CPU":
        return os.cpu_count() or 1
    return 1


def get_whisper_gpu_retries():
    return env_nonnegative_int("AUDIOSOURCE_WHISPER_GPU_RETRIES", "1")


def get_whisper_retry_sleep_seconds():
    return env_float("AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS", "45")


def get_whisper_subprocess_timeout_seconds():
    return env_float("AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS", "1200")


def get_whisper_device():
    configured_default = "cpu" if get_configured_calculate_core() == "CPU" else "cuda"
    return os.getenv("AUDIOSOURCE_WHISPER_DEVICE", configured_default).strip() or configured_default


def get_whisper_compute_type(device):
    default = "int8" if device == "cpu" else "float16"
    return os.getenv("AUDIOSOURCE_WHISPER_COMPUTE_TYPE", default).strip() or default


def get_whisper_chunk_seconds():
    value = os.getenv("AUDIOSOURCE_WHISPER_CHUNK_SECONDS")
    if value is None:
        return 0 if get_whisper_device() == "cpu" else 300

    try:
        return max(0, int(value))
    except ValueError:
        logger.warning("Invalid AUDIOSOURCE_WHISPER_CHUNK_SECONDS=%r, using default", value)
        return 0 if get_whisper_device() == "cpu" else 300


def get_whisper_isolate_chunks():
    return env_bool("AUDIOSOURCE_WHISPER_ISOLATE_CHUNKS", get_whisper_device() != "cpu")


def load_whisper_model():
    device = get_whisper_device()
    compute_type = get_whisper_compute_type(device)
    cpu_threads = get_whisper_cpu_threads()
    start_time = time.monotonic()

    logger.info(
        "Loading WhisperModel large-v3 device=%s compute_type=%s cpu_threads=%s",
        device,
        compute_type,
        cpu_threads,
    )

    try:
        model = WhisperModel(
            "large-v3",
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
        )
        logger.info("Loaded WhisperModel on device=%s elapsed=%.2fs", device, time.monotonic() - start_time)
        return model
    except Exception:
        if device == "cpu" or not env_bool("AUDIOSOURCE_WHISPER_FALLBACK_CPU", True):
            raise

        logger.exception(
            "Failed to load WhisperModel on device=%s compute_type=%s; falling back to CPU int8",
            device,
            compute_type,
        )
        fallback_start = time.monotonic()
        model = WhisperModel(
            "large-v3",
            device="cpu",
            compute_type="int8",
            cpu_threads=cpu_threads,
        )
        logger.info("Loaded fallback CPU WhisperModel elapsed=%.2fs", time.monotonic() - fallback_start)
        return model


def run_cmd(cmd, description):
    logger.info("%s: %s", description, " ".join(str(item) for item in cmd))
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    if proc.stdout.strip():
        logger.info("%s stdout: %s", description, proc.stdout[-4000:])
    if proc.stderr.strip():
        logger.info("%s stderr: %s", description, proc.stderr[-4000:])
    if proc.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}")
    return proc


def probe_audio_duration(input_mp3):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise FileNotFoundError("ffprobe not found in PATH")

    proc = run_cmd(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(input_mp3),
        ],
        "FFprobe audio duration",
    )
    return float(proc.stdout.strip())


def create_audio_chunk(input_mp3, start_seconds, duration_seconds, output_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found in PATH")

    output_path = Path(output_path)
    run_cmd(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(input_mp3),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(output_path),
        ],
        f"FFmpeg create whisper chunk start={start_seconds:.2f}",
    )

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"FFmpeg produced empty chunk: {output_path}")

    return output_path


def transcribe_file_to_json(input_audio, output_json, device, compute_type, cpu_threads):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger.info(
        "Chunk child loading WhisperModel input=%s output=%s device=%s compute_type=%s cpu_threads=%s",
        input_audio,
        output_json,
        device,
        compute_type,
        cpu_threads,
    )
    model = WhisperModel(
        "large-v3",
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    segments, info = model.transcribe(str(input_audio), beam_size=5)
    rows = []
    for segment in segments:
        rows.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": segment.text,
            }
        )

    output_json = Path(output_json)
    output_json.write_text(
        json.dumps({"info": str(info), "segments": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Chunk child completed segments=%d output=%s", len(rows), output_json)


def transcribe_chunk_subprocess(chunk_path, tmp_dir, chunk_index, device, compute_type, cpu_threads):
    output_json = Path(tmp_dir) / f"chunk_{chunk_index:04d}_segments.json"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--transcribe-chunk",
        str(chunk_path),
        str(output_json),
        "--device",
        device,
        "--compute-type",
        compute_type,
        "--cpu-threads",
        str(cpu_threads),
    ]
    env = os.environ.copy()
    env.setdefault("PYTHONFAULTHANDLER", "1")
    env.setdefault("TQDM_DISABLE", "1")
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    description = f"Whisper chunk child index={chunk_index} device={device}"
    timeout_seconds = get_whisper_subprocess_timeout_seconds()
    logger.info("%s timeout_seconds=%.1f", description, timeout_seconds)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            env=env,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else exc.stdout
        stderr = (exc.stderr or "")[-8000:] if isinstance(exc.stderr, str) else exc.stderr
        if stdout:
            logger.error("%s timeout stdout: %s", description, stdout)
        if stderr:
            logger.error("%s timeout stderr: %s", description, stderr)
        raise RuntimeError(f"{description} timed out after {timeout_seconds:.1f}s") from exc
    if proc.stdout.strip():
        logger.info("%s stdout: %s", description, proc.stdout[-4000:])
    if proc.stderr.strip():
        logger.info("%s stderr: %s", description, proc.stderr[-8000:])
    if proc.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}")
    if not output_json.exists() or output_json.stat().st_size <= 0:
        raise RuntimeError(f"{description} produced no JSON output: {output_json}")

    payload = json.loads(output_json.read_text(encoding="utf-8"))
    logger.info("%s completed info=%s segments=%d", description, payload.get("info"), len(payload.get("segments", [])))
    return [
        SimpleNamespace(
            start=float(row["start"]),
            end=float(row["end"]),
            text=row.get("text", ""),
        )
        for row in payload.get("segments", [])
    ]


def transcribe_chunk_with_fallback(chunk_path, tmp_dir, chunk_index):
    device = get_whisper_device()
    compute_type = get_whisper_compute_type(device)
    cpu_threads = get_whisper_cpu_threads()
    gpu_attempts = get_whisper_gpu_retries() + 1
    retry_sleep = get_whisper_retry_sleep_seconds()

    if device == "cpu":
        return transcribe_chunk_subprocess(
            chunk_path,
            tmp_dir,
            chunk_index,
            "cpu",
            compute_type,
            cpu_threads,
        )

    last_error = None
    for attempt in range(1, gpu_attempts + 1):
        try:
            logger.info(
                "GPU chunk attempt %d/%d index=%d path=%s device=%s compute_type=%s",
                attempt,
                gpu_attempts,
                chunk_index,
                chunk_path,
                device,
                compute_type,
            )
            return transcribe_chunk_subprocess(
                chunk_path,
                tmp_dir,
                chunk_index,
                device,
                compute_type,
                cpu_threads,
            )
        except Exception as exc:
            last_error = exc
            if attempt < gpu_attempts:
                logger.exception(
                    "GPU chunk attempt failed index=%d attempt=%d/%d; sleeping %.1fs before retry",
                    chunk_index,
                    attempt,
                    gpu_attempts,
                    retry_sleep,
                )
                time.sleep(retry_sleep)
                continue

    if not env_bool("AUDIOSOURCE_WHISPER_FALLBACK_CPU", True):
        raise last_error

    logger.error(
        "GPU chunk subprocess failed after %d attempt(s) index=%d path=%s; retrying this chunk on CPU int8",
        gpu_attempts,
        chunk_index,
        chunk_path,
        exc_info=(type(last_error), last_error, last_error.__traceback__),
    )
    return transcribe_chunk_subprocess(
        chunk_path,
        tmp_dir,
        chunk_index,
        "cpu",
        "int8",
        cpu_threads,
    )


def iter_whisper_segments_chunked(model, input_mp3, chunk_seconds):
    duration = probe_audio_duration(input_mp3)
    isolate_chunks = get_whisper_isolate_chunks()
    logger.info(
        "Chunked Whisper transcription enabled input=%s duration=%.2fs chunk_seconds=%s isolate_chunks=%s",
        input_mp3,
        duration,
        chunk_seconds,
        isolate_chunks,
    )

    with tempfile.TemporaryDirectory(prefix="audiosource_whisper_chunks_") as tmp_dir:
        tmp_dir = Path(tmp_dir)
        chunk_index = 0
        chunk_start = 0.0

        while chunk_start < duration:
            chunk_duration = min(chunk_seconds, duration - chunk_start)
            chunk_path = tmp_dir / f"chunk_{chunk_index:04d}_{int(chunk_start):08d}.mp3"
            create_audio_chunk(input_mp3, chunk_start, chunk_duration, chunk_path)

            logger.info(
                "Whisper chunk transcribe start index=%d offset=%.2fs duration=%.2fs path=%s",
                chunk_index,
                chunk_start,
                chunk_duration,
                chunk_path,
            )
            chunk_transcribe_start = time.monotonic()
            if isolate_chunks:
                segments = transcribe_chunk_with_fallback(chunk_path, tmp_dir, chunk_index)
            else:
                segments, info = model.transcribe(str(chunk_path), beam_size=5)
                logger.info(
                    "Whisper chunk transcribe call returned index=%d elapsed=%.2fs info=%s",
                    chunk_index,
                    time.monotonic() - chunk_transcribe_start,
                    info,
                )

            chunk_segment_count = 0
            for segment in segments:
                chunk_segment_count += 1
                yield chunk_start, chunk_index, segment

            logger.info(
                "Whisper chunk exhausted index=%d segments=%d elapsed=%.2fs",
                chunk_index,
                chunk_segment_count,
                time.monotonic() - chunk_transcribe_start,
            )
            gc.collect()
            chunk_index += 1
            chunk_start += chunk_seconds


SKIP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "can", "did", "do", "for",
    "from", "get", "go", "had", "has", "have", "he", "her", "him", "his", "how", "i",
    "if", "in", "is", "it", "its", "me", "my", "no", "not", "of", "on", "or", "our",
    "out", "she", "so", "the", "to", "too", "up", "us", "was", "we", "who", "why", "you",
    "aren", "couldn", "didn", "doesn", "don", "hadn", "hasn", "haven", "isn", "ll", "re",
    "shan", "shouldn", "ve", "wasn", "weren", "won", "wouldn",
    "billion", "billions", "communities", "community", "mean", "means", "media", "user",
    "users", "volunteer", "volunteers",
    "aac", "adb", "aes", "ai", "amd", "api", "arm", "aws", "bash", "bsd", "cli", "cmake",
    "codec", "codecs", "cpu", "cuda", "css", "csv", "dns", "docker", "ffmpeg", "flac",
    "gdb", "gif", "git", "github", "gitlab", "gpt", "gpu", "gui", "h264", "h265",
    "hevc", "html", "http", "https", "ide", "ios", "ip", "ipc", "jpeg", "jpg", "json",
    "k8s", "linux", "llm", "macos", "mp3", "mp4", "mpeg", "mysql", "nasm", "netflix",
    "nvidia", "objc", "opencv", "openai", "opengl", "openssl", "opus", "pdf", "png",
    "postgres", "protobuf", "pytorch", "qt", "ram", "redis", "rest", "rgb", "rgbd",
    "rtmp", "rtsp", "sdk", "smtp", "sql", "ssh", "ssl", "svg", "tcp", "tensorflow",
    "tls", "udp", "ui", "unix", "url", "usb", "utf", "ux", "v8", "vimeo", "vlc",
    "vpn", "wav", "webgl", "webm", "webp", "wifi", "xml", "yaml", "youtube",
    "angular", "bun", "csharp", "deno", "django", "dotnet",
    "electron", "express", "fastapi", "flask", "flutter", "golang", "java", "javascript",
    "jquery", "kotlin", "laravel", "lua", "nextjs", "node", "nodejs", "numpy", "pandas",
    "php", "python", "react", "ruby", "rust", "scala", "svelte", "swift", "typescript",
    "uefi", "unity", "unreal", "vue", "wasm", "adobe", "airbnb", "alibaba", "amazon",
    "android", "anthropic", "apple", "azure", "bing", "bytedance", "chatgpt", "chrome",
    "chromium", "claude", "cloudflare", "deepmind", "deepseek", "discord", "facebook",
    "figma", "firefox", "google", "huggingface", "instagram", "intel", "iphone", "linkedin",
    "meta", "microsoft", "mozilla", "neuralink", "opencl", "openwrt", "oracle", "paypal",
    "reddit", "safari", "slack", "spacex", "spotify", "telegram", "tesla", "tiktok",
    "twitch", "twitter", "uber", "ubuntu", "wechat", "whatsapp", "windows", "xbox", "xcode",
    "alex", "andrew", "anna", "baptiste", "bernie", "bjorn", "brownworth", "dario", "dave",
    "demis", "dhh", "elon", "ezra", "fridman", "graham", "ivar", "janna", "javier",
    "jensen", "joe", "jordan", "kempf", "kiran", "lars", "laurent", "linus", "marc",
    "michael", "oliver", "paul", "pavel", "ragnar", "robert", "rolf", "rollo", "saagar",
    "rogan",
    "scott", "sundar", "terence", "tim", "volodymyr", "america", "american", "britain",
    "british", "byzantine", "canada", "china", "chinese", "danish", "england", "english",
    "europe", "european", "france", "frankish", "german", "germany", "greek", "india",
    "iran", "italian", "italy", "japan", "japanese", "mongol", "mongols", "norman",
    "normans", "norway", "norwegian", "norse", "russia", "russian", "saxon", "scandinavia",
    "scandinavian", "sicily", "ukraine", "ukrainian", "viking", "vikings",
}

_FILTER_WORDS_CACHE = {"mtime": None, "words": set()}
_DIFFICULTY_CONFIG_CACHE = {"mtime": None, "config": None}

DEFAULT_DIFFICULTY_CONFIG = {
    "advanced_levels": {"C1", "C2"},
    "min_candidate_length": 5,
    "b1_min_length": 8,
    "b1_frequency_threshold": 0.000003,
    "b2_min_length": 8,
    "b2_frequency_threshold": 0.000012,
    "unknown_min_length": 8,
    "unknown_frequency_threshold": 0.000003,
}

DEFAULT_PROPER_NOUN_CONFIG = {
    "enabled": True,
    "model": "en_core_web_sm",
    "entity_labels": {"PERSON", "GPE", "LOC", "FAC", "ORG"},
    "skip_words": set(),
}

DEFAULT_TRANSLATION_CONFIG = {
    "segments_per_translation": 1,
    "use_context_meaning": True,
    "max_meaning_chars": 8,
    "retry_on_verbose_meaning": True,
    "ambiguous_meaning_policy": "skip",
    "ollama_temperature": 0.0,
    "repeat_window_seconds": 120,
}

RECENT_TRANSLATION_WINDOW_SECONDS = 120.0


def normalize_word(raw_word):
    return raw_word.strip().strip(".,!?;:\"()[]{}<>").replace("\u2019", "'")


def cefr_level_to_text(level):
    if level is None:
        return ""
    if hasattr(level, "name"):
        return str(level.name).upper()
    return str(level).strip().upper()


def parse_csv_levels(value, default):
    levels = {item.strip().upper() for item in str(value).split(",") if item.strip()}
    return levels or set(default)


def parse_csv_words(value):
    words = set()
    for item in str(value).split(","):
        for token in re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", item):
            normalized = normalize_word(token).lower()
            if normalized:
                words.add(normalized)
    return words


def config_bool(section, key, default):
    return config_section_bool(section, "ProperNounConfig", key, default)


def config_section_bool(section, section_name, key, default):
    try:
        return section.getboolean(key, fallback=default)
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return default


def config_positive_int(section, section_name, key, default):
    try:
        return max(1, section.getint(key, fallback=default))
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(1, int(default))


def config_nonnegative_float(section, section_name, key, default):
    try:
        return max(0.0, section.getfloat(key, fallback=default))
    except ValueError:
        logger.warning("Invalid %s.%s=%r, using default=%s", section_name, key, section.get(key), default)
        return max(0.0, float(default))


def config_int(section, key, default):
    try:
        return max(0, section.getint(key, fallback=default))
    except ValueError:
        logger.warning("Invalid DifficultyConfig.%s=%r, using default=%s", key, section.get(key), default)
        return default


def config_float(section, key, default):
    try:
        return max(0.0, section.getfloat(key, fallback=default))
    except ValueError:
        logger.warning("Invalid DifficultyConfig.%s=%r, using default=%s", key, section.get(key), default)
        return default


def load_difficulty_config():
    mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
    cached_config = _DIFFICULTY_CONFIG_CACHE["config"]
    if cached_config is not None and _DIFFICULTY_CONFIG_CACHE["mtime"] == mtime:
        return cached_config

    config = dict(DEFAULT_DIFFICULTY_CONFIG)
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        section = parser["DifficultyConfig"] if parser.has_section("DifficultyConfig") else {}
        if section:
            config["advanced_levels"] = parse_csv_levels(
                section.get("AdvancedLevels", ",".join(sorted(config["advanced_levels"]))),
                config["advanced_levels"],
            )
            config["min_candidate_length"] = config_int(section, "MinCandidateLength", config["min_candidate_length"])
            config["b1_min_length"] = config_int(section, "B1MinLength", config["b1_min_length"])
            config["b1_frequency_threshold"] = config_float(
                section,
                "B1FrequencyThreshold",
                config["b1_frequency_threshold"],
            )
            config["b2_min_length"] = config_int(section, "B2MinLength", config["b2_min_length"])
            config["b2_frequency_threshold"] = config_float(
                section,
                "B2FrequencyThreshold",
                config["b2_frequency_threshold"],
            )
            config["unknown_min_length"] = config_int(section, "UnknownMinLength", config["unknown_min_length"])
            config["unknown_frequency_threshold"] = config_float(
                section,
                "UnknownFrequencyThreshold",
                config["unknown_frequency_threshold"],
            )

    logger.info(
        "Difficulty config: advanced_levels=%s min_candidate_length=%s "
        "B1(len>=%s,freq<%s) B2(len>=%s,freq<%s) unknown(len>=%s,freq<%s)",
        ",".join(sorted(config["advanced_levels"])),
        config["min_candidate_length"],
        config["b1_min_length"],
        config["b1_frequency_threshold"],
        config["b2_min_length"],
        config["b2_frequency_threshold"],
        config["unknown_min_length"],
        config["unknown_frequency_threshold"],
    )
    _DIFFICULTY_CONFIG_CACHE["mtime"] = mtime
    _DIFFICULTY_CONFIG_CACHE["config"] = config
    return config


def load_proper_noun_config():
    mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
    cached_config = _PROPER_NOUN_CONFIG_CACHE["config"]
    if cached_config is not None and _PROPER_NOUN_CONFIG_CACHE["mtime"] == mtime:
        return cached_config

    config = {
        "enabled": DEFAULT_PROPER_NOUN_CONFIG["enabled"],
        "model": DEFAULT_PROPER_NOUN_CONFIG["model"],
        "entity_labels": set(DEFAULT_PROPER_NOUN_CONFIG["entity_labels"]),
        "skip_words": set(DEFAULT_PROPER_NOUN_CONFIG["skip_words"]),
    }
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("ProperNounConfig"):
            section = parser["ProperNounConfig"]
            config["enabled"] = config_bool(section, "SkipProperNouns", config["enabled"])
            config["model"] = section.get("NlpModel", config["model"]).strip() or config["model"]
            config["entity_labels"] = parse_csv_levels(
                section.get("EntityLabels", ",".join(sorted(config["entity_labels"]))),
                config["entity_labels"],
            )
            config["skip_words"] = parse_csv_words(section.get("SkipWords", ""))

    logger.info(
        "Proper noun config: enabled=%s model=%s labels=%s skip_words=%d",
        config["enabled"],
        config["model"],
        ",".join(sorted(config["entity_labels"])),
        len(config["skip_words"]),
    )
    _PROPER_NOUN_CONFIG_CACHE["mtime"] = mtime
    _PROPER_NOUN_CONFIG_CACHE["config"] = config
    return config


def load_translation_config():
    mtime = CONFIG_FILE.stat().st_mtime if CONFIG_FILE.exists() else None
    cached_config = _TRANSLATION_CONFIG_CACHE["config"]
    if cached_config is not None and _TRANSLATION_CONFIG_CACHE["mtime"] == mtime:
        return cached_config

    config = dict(DEFAULT_TRANSLATION_CONFIG)
    if CONFIG_FILE.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_FILE, encoding="utf-8")
        if parser.has_section("TranslationConfig"):
            section = parser["TranslationConfig"]
            config["segments_per_translation"] = config_positive_int(
                section,
                "TranslationConfig",
                "SegmentsPerTranslation",
                config["segments_per_translation"],
            )
            config["use_context_meaning"] = config_section_bool(
                section,
                "TranslationConfig",
                "UseContextMeaning",
                config["use_context_meaning"],
            )
            config["max_meaning_chars"] = config_positive_int(
                section,
                "TranslationConfig",
                "MaxMeaningChars",
                config["max_meaning_chars"],
            )
            config["retry_on_verbose_meaning"] = config_section_bool(
                section,
                "TranslationConfig",
                "RetryOnVerboseMeaning",
                config["retry_on_verbose_meaning"],
            )
            policy = section.get("AmbiguousMeaningPolicy", config["ambiguous_meaning_policy"]).strip().lower()
            if policy not in {"skip"}:
                logger.warning("Invalid TranslationConfig.AmbiguousMeaningPolicy=%r, using skip", policy)
                policy = "skip"
            config["ambiguous_meaning_policy"] = policy
            config["ollama_temperature"] = config_nonnegative_float(
                section,
                "TranslationConfig",
                "OllamaTemperature",
                config["ollama_temperature"],
            )
            config["repeat_window_seconds"] = config_positive_int(
                section,
                "TranslationConfig",
                "TranslationRepeatWindowSeconds",
                config["repeat_window_seconds"],
            )

    logger.info(
        "Translation config: segments_per_translation=%s use_context_meaning=%s "
        "max_meaning_chars=%s retry_on_verbose_meaning=%s ambiguous_meaning_policy=%s "
        "ollama_temperature=%s repeat_window_seconds=%s",
        config["segments_per_translation"],
        config["use_context_meaning"],
        config["max_meaning_chars"],
        config["retry_on_verbose_meaning"],
        config["ambiguous_meaning_policy"],
        config["ollama_temperature"],
        config["repeat_window_seconds"],
    )
    _TRANSLATION_CONFIG_CACHE["mtime"] = mtime
    _TRANSLATION_CONFIG_CACHE["config"] = config
    return config


def get_spacy_nlp(model_name):
    if _SPACY_NLP_CACHE["model"] == model_name and _SPACY_NLP_CACHE["nlp"] is not None:
        return _SPACY_NLP_CACHE["nlp"]
    if model_name in _SPACY_NLP_CACHE["failed_models"]:
        return None

    try:
        import spacy
    except ImportError:
        logger.warning("spaCy is not installed; proper noun filtering is disabled")
        _SPACY_NLP_CACHE["failed_models"].add(model_name)
        return None

    try:
        nlp = spacy.load(
            model_name,
            disable=["tagger", "parser", "attribute_ruler", "lemmatizer"],
        )
    except Exception as exc:
        logger.warning(
            "spaCy model %s is unavailable; proper noun filtering is disabled: %s",
            model_name,
            exc,
        )
        _SPACY_NLP_CACHE["failed_models"].add(model_name)
        return None

    _SPACY_NLP_CACHE["model"] = model_name
    _SPACY_NLP_CACHE["nlp"] = nlp
    logger.info("Loaded spaCy NER model=%s pipes=%s", model_name, ",".join(nlp.pipe_names))
    return nlp


def find_proper_noun_words(english_text):
    config = load_proper_noun_config()
    if not config["enabled"]:
        return set()

    words = set(config["skip_words"])
    if not english_text.strip():
        return words

    nlp = get_spacy_nlp(config["model"])
    if nlp is None:
        return words

    try:
        doc = nlp(english_text)
    except Exception:
        logger.exception("spaCy proper noun detection failed; using configured SkipWords only")
        return words

    entity_words = set()
    for entity in doc.ents:
        if entity.label_.upper() not in config["entity_labels"]:
            continue
        for token in re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", entity.text):
            normalized = normalize_word(token).lower()
            if normalized:
                entity_words.add(normalized)

    if entity_words:
        logger.info("Filtered proper noun words: %s", ", ".join(sorted(entity_words)))
        words.update(entity_words)

    return words


def load_filter_words():
    if not FILTER_FILE.exists():
        logger.warning("filter.txt does not exist: %s", FILTER_FILE)
        return set()

    mtime = FILTER_FILE.stat().st_mtime
    if _FILTER_WORDS_CACHE["mtime"] == mtime:
        return _FILTER_WORDS_CACHE["words"]

    words = set()
    try:
        for line in FILTER_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
            candidate = re.sub(r"^[-*+]\s*", "", line.strip())
            if not candidate or candidate.startswith("#"):
                continue

            token = candidate.split()[0]
            normalized = normalize_word(token).lower()
            if normalized:
                words.add(normalized)
    except Exception:
        logger.exception("Failed to read filter.txt: %s", FILTER_FILE)
        return set()

    logger.info("Loaded %d filter words from %s", len(words), FILTER_FILE)
    _FILTER_WORDS_CACHE["mtime"] = mtime
    _FILTER_WORDS_CACHE["words"] = words
    return words


def is_acronym_or_tool_name(raw_word, filter_words=None, difficulty_config=None):
    if difficulty_config is None:
        difficulty_config = load_difficulty_config()

    word = normalize_word(raw_word)
    if not word:
        return True

    compact = word.replace("-", "").replace("_", "").replace(".", "").replace("'", "")
    lower = compact.lower()

    if filter_words and lower in filter_words:
        return True

    if lower in SKIP_WORDS:
        return True

    if len(compact) < difficulty_config["min_candidate_length"]:
        return True

    if compact.isupper() and compact.isalpha():
        return True

    if any(ch.isdigit() for ch in compact):
        return True

    has_lower = any(ch.islower() for ch in compact)
    has_upper = any(ch.isupper() for ch in compact)
    is_normal_title_case = (
        len(compact) > 1
        and compact[0].isupper()
        and compact[1:].islower()
    )
    if has_lower and has_upper and not is_normal_title_case:
        return True

    return False


def is_difficult(
    word,
    filter_words=None,
    difficulty_config=None,
):
    if difficulty_config is None:
        difficulty_config = load_difficulty_config()

    word = normalize_word(word)
    clean_word = word.lower()

    if not clean_word.isalpha():
        return False

    if is_acronym_or_tool_name(word, filter_words=filter_words, difficulty_config=difficulty_config):
        return False

    level = cefr_level_to_text(analyzer.get_average_word_level_CEFR(clean_word))
    freq = word_frequency(clean_word, "en")

    if level in difficulty_config["advanced_levels"]:
        return True

    if (
        level == "B2"
        and len(clean_word) >= difficulty_config["b2_min_length"]
        and freq < difficulty_config["b2_frequency_threshold"]
    ):
        return True

    if (
        level == "B1"
        and len(clean_word) >= difficulty_config["b1_min_length"]
        and freq < difficulty_config["b1_frequency_threshold"]
    ):
        return True

    if (
        not level
        and len(clean_word) >= difficulty_config["unknown_min_length"]
        and freq < difficulty_config["unknown_frequency_threshold"]
    ):
        return True

    return False


def extract_json_payload(text):
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)

    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        return stripped[start:end + 1]

    return stripped


def parse_translation_json(response_text):
    payload = extract_json_payload(response_text)
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and isinstance(data.get("translations"), list):
        data = data["translations"]

    mapping = {}
    if isinstance(data, dict):
        for word, meaning in data.items():
            normalized = normalize_word(str(word)).lower()
            if normalized:
                mapping[normalized] = "" if meaning is None else str(meaning).strip()
        return mapping

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            word = normalize_word(str(item.get("word", ""))).lower()
            meaning = item.get("meaning", "")
            if word:
                mapping[word] = "" if meaning is None else str(meaning).strip()
        return mapping

    return None


def parse_translation_fallback(response_text):
    if any(separator in response_text for separator in (";", "；", "、")):
        return None

    mapping = {}
    for line in response_text.splitlines():
        if ":" not in line:
            continue
        word, meaning = line.split(":", 1)
        normalized = normalize_word(word).lower()
        if normalized:
            mapping[normalized] = meaning.strip()
    return mapping or None


def meaning_char_count(meaning):
    return len(re.sub(r"\s+", "", meaning))


def normalize_context_meaning(meaning, max_chars):
    value = str(meaning or "").strip()
    lowered = value.strip().lower()
    if lowered in {"", "skip", "[skip]", "none", "n/a", "na", "unclear", "unknown"}:
        return "", "skip"

    if meaning_char_count(value) > 20:
        return "", "skip verbose meaning"

    if any(separator in value for separator in (";", "；", "、", "/", "|", "\n", "，", ",")):
        value = re.split(r"[;；、/|\n，,]+", value, maxsplit=1)[0].strip()
        lowered = value.strip().lower()
        if lowered in {"", "skip", "[skip]", "none", "n/a", "na", "unclear", "unknown"}:
            return "", "skip"

    if ":" in value or "：" in value:
        return None, "contains nested label"

    if meaning_char_count(value) > max_chars:
        return None, f"exceeds {max_chars} chars"

    return value, ""


def parse_context_translation_response(response_text, expected_words, max_chars):
    parsed = parse_translation_json(response_text)
    if parsed is None:
        parsed = parse_translation_fallback(response_text)
    if parsed is None:
        return {}, set(expected_words), set()

    valid = {}
    invalid = set()
    skipped = set()
    for word in expected_words:
        meaning, reason = normalize_context_meaning(parsed.get(word, ""), max_chars)
        if meaning is None:
            invalid.add(word)
            logger.warning("Invalid contextual meaning word=%s reason=%s raw=%r", word, reason, parsed.get(word, ""))
        elif meaning:
            valid[word] = meaning
        else:
            skipped.add(word)

    return valid, invalid, skipped


def build_context_translation_prompt(unique_words, context_text, max_chars, strict_retry=False):
    strict_line = (
        "Previous output was invalid. Return JSON only and obey the character limit exactly.\n"
        if strict_retry
        else ""
    )
    return (
        "You are translating English vocabulary for Chinese learners.\n"
        f"{strict_line}"
        "Use the context to choose the single best Chinese meaning for each word.\n"
        f"Each Chinese meaning must be {max_chars} Chinese characters or fewer.\n"
        "Return one concise meaning only. Do not list alternatives. Do not give dictionary-style explanations.\n"
        "Do not translate person names, place names, organization names, brand names, or other proper nouns.\n"
        "If the meaning is unclear from context, use an empty string.\n\n"
        f"Context:\n{context_text}\n\n"
        f"Words:\n{json.dumps(unique_words, ensure_ascii=False)}\n\n"
        'Return JSON only: [{"word":"example","meaning":"中文"}]'
    )


def format_translated_words(translated_meanings):
    return "; ".join(
        f"{word}: {translated_meanings[word]}"
        for word in sorted(translated_meanings)
    )


def translate_words_mapping(words_list, context_text="", filter_words=None):
    if not words_list:
        return {}

    difficulty_config = load_difficulty_config()
    translation_config = load_translation_config()
    unique_words = sorted(
        {
            normalize_word(word).lower()
            for word in words_list
            if normalize_word(word)
            and not is_acronym_or_tool_name(
                word,
                filter_words=filter_words,
                difficulty_config=difficulty_config,
            )
        }
    )

    if not unique_words:
        return {}

    model_name = get_ollama_model()
    max_chars = translation_config["max_meaning_chars"]
    attempts = 2 if translation_config["retry_on_verbose_meaning"] else 1
    final_meanings = {}
    remaining_words = list(unique_words)

    for attempt in range(1, attempts + 1):
        if not remaining_words:
            break

        if translation_config["use_context_meaning"]:
            prompt = build_context_translation_prompt(
                remaining_words,
                context_text,
                max_chars,
                strict_retry=attempt > 1,
            )
        else:
            prompt = build_context_translation_prompt(
                remaining_words,
                "",
                max_chars,
                strict_retry=attempt > 1,
            )

        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": translation_config["ollama_temperature"]},
        }

        try:
            logger.info(
                "Ollama contextual translation model=%s words=%d attempt=%d/%d max_chars=%d",
                model_name,
                len(remaining_words),
                attempt,
                attempts,
                max_chars,
            )
            response = requests.post(OLLAMA_API, json=payload, timeout=60)
            response.raise_for_status()
            response_text = response.json().get("response", "").strip()
        except Exception as exc:
            logger.exception("Ollama translation failed: %s", exc)
            return {word: final_meanings[word] for word in unique_words if word in final_meanings}

        valid, invalid, skipped = parse_context_translation_response(response_text, remaining_words, max_chars)
        final_meanings.update(valid)
        if skipped:
            logger.info("Skipped unclear contextual meanings: %s", ", ".join(sorted(skipped)))

        if invalid and attempt < attempts:
            logger.warning("Retrying invalid contextual meanings: %s", ", ".join(sorted(invalid)))
            remaining_words = sorted(invalid)
            continue

        if invalid:
            logger.warning("Skipping invalid contextual meanings after validation failure: %s", ", ".join(sorted(invalid)))
        break

    return {word: final_meanings[word] for word in unique_words if word in final_meanings}


def translate_words_list(words_list, context_text="", filter_words=None):
    return format_translated_words(
        translate_words_mapping(words_list, context_text=context_text, filter_words=filter_words)
    )


def filter_recent_translation_words(
    words,
    start_seconds,
    recent_translations=None,
    window_seconds=RECENT_TRANSLATION_WINDOW_SECONDS,
):
    if recent_translations is None:
        return words

    eligible_words = []
    skipped_words = set()
    for word in words:
        normalized = normalize_word(word).lower()
        if not normalized:
            continue

        last_translated_at = recent_translations.get(normalized)
        if last_translated_at is not None and 0 <= start_seconds - last_translated_at <= window_seconds:
            skipped_words.add(normalized)
            continue

        eligible_words.append(word)

    if skipped_words:
        logger.info(
            "Skipped recently translated words at %.2fs window=%.0fs: %s",
            start_seconds,
            window_seconds,
            ", ".join(sorted(skipped_words)),
        )

    return eligible_words


def build_translation_text(
    start_seconds,
    english_text,
    filter_words=None,
    recent_translations=None,
    repeat_window_seconds=RECENT_TRANSLATION_WINDOW_SECONDS,
):
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", english_text)
    difficulty_config = load_difficulty_config()
    combined_filter_words = set(filter_words or set())
    combined_filter_words.update(find_proper_noun_words(english_text))
    difficult_words = [
        word
        for word in words
        if is_difficult(word, filter_words=combined_filter_words, difficulty_config=difficulty_config)
    ]
    difficult_words = filter_recent_translation_words(
        difficult_words,
        start_seconds,
        recent_translations=recent_translations,
        window_seconds=repeat_window_seconds,
    )

    translation_text = ""
    if difficult_words:
        translated_meanings = translate_words_mapping(
            difficult_words,
            context_text=english_text,
            filter_words=combined_filter_words,
        )
        translated_words = format_translated_words(translated_meanings)
        if translated_words and translated_words != "[translation error]":
            translation_text = f"Vocabulary: {translated_words}"
            if recent_translations is not None:
                for word in translated_meanings:
                    recent_translations[word] = start_seconds
            logger.info("Difficult words at %.2fs: %s", start_seconds, translated_words)

    return translation_text


def write_markdown_segment(handle, start_seconds, english_text, translation_text):
    handle.write(f"**[{start_seconds:.2f}s] English:** {english_text}  \n")
    handle.write(f"**Translation:** {translation_text}\n\n")


def write_segment(
    handle,
    start_seconds,
    english_text,
    filter_words=None,
    recent_translations=None,
    repeat_window_seconds=RECENT_TRANSLATION_WINDOW_SECONDS,
):
    translation_text = build_translation_text(
        start_seconds,
        english_text,
        filter_words=filter_words,
        recent_translations=recent_translations,
        repeat_window_seconds=repeat_window_seconds,
    )
    write_markdown_segment(handle, start_seconds, english_text, translation_text)
    handle.flush()


def write_segment_group(
    handle,
    segments,
    filter_words=None,
    recent_translations=None,
    repeat_window_seconds=RECENT_TRANSLATION_WINDOW_SECONDS,
):
    if not segments:
        return

    if len(segments) == 1:
        start_seconds, english_text = segments[0]
        write_segment(
            handle,
            start_seconds,
            english_text,
            filter_words=filter_words,
            recent_translations=recent_translations,
            repeat_window_seconds=repeat_window_seconds,
        )
        return

    group_start = segments[0][0]
    group_end = segments[-1][0]
    combined_text = " ".join(english_text for _start_seconds, english_text in segments if english_text)
    translation_text = build_translation_text(
        group_end,
        combined_text,
        filter_words=filter_words,
        recent_translations=recent_translations,
        repeat_window_seconds=repeat_window_seconds,
    )
    logger.info(
        "Grouped translation segments=%d start=%.2fs end=%.2fs",
        len(segments),
        group_start,
        group_end,
    )

    for index, (start_seconds, english_text) in enumerate(segments):
        segment_translation = translation_text if index == len(segments) - 1 else ""
        write_markdown_segment(handle, start_seconds, english_text, segment_translation)

    handle.flush()


def markdown_has_segments(markdown_path):
    markdown_path = Path(markdown_path)
    if not markdown_path.exists():
        return False

    content = markdown_path.read_text(encoding="utf-8", errors="ignore")
    return bool(re.search(r"\*\*\[\d+(?:\.\d+)?s\] English:\*\*", content))


def markdown_is_complete(markdown_path):
    markdown_path = Path(markdown_path)
    if not markdown_path.exists():
        return False

    content = markdown_path.read_text(encoding="utf-8", errors="ignore")
    return COMPLETE_MARKER in content


def parse_srt_timecode(timecode):
    match = re.match(r"(\d{2}):(\d{2}):(\d{2})[,\.](\d{3})", timecode.strip())
    if not match:
        raise ValueError(f"Invalid SRT timecode: {timecode}")

    hours, minutes, seconds, milliseconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def iter_srt_segments(subtitle_file):
    content = Path(subtitle_file).read_text(encoding="utf-8", errors="ignore")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return

    blocks = re.split(r"\n\s*\n", normalized)
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        if re.fullmatch(r"\d+", lines[0]):
            lines = lines[1:]

        if not lines:
            continue

        time_line = lines[0]
        text_lines = lines[1:]
        if "-->" not in time_line or not text_lines:
            continue

        start_text, _end_text = [part.strip() for part in time_line.split("-->", 1)]
        start_seconds = parse_srt_timecode(start_text)
        english_text = " ".join(line.lstrip("- ").strip() for line in text_lines).strip()

        if english_text:
            yield start_seconds, english_text


def iter_vtt_segments(subtitle_file):
    content = Path(subtitle_file).read_text(encoding="utf-8", errors="ignore")
    normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
    if normalized.startswith("WEBVTT"):
        normalized = normalized[len("WEBVTT"):].strip()

    blocks = re.split(r"\n\s*\n", normalized)
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        if "-->" not in lines[0]:
            lines = lines[1:]
            if len(lines) < 2:
                continue

        time_line = lines[0]
        text_lines = lines[1:]
        if "-->" not in time_line or not text_lines:
            continue

        start_text, _end_text = [part.strip() for part in time_line.split("-->", 1)]
        start_seconds = parse_srt_timecode(start_text.replace(".", ","))
        english_text = " ".join(line.lstrip("- ").strip() for line in text_lines).strip()

        if english_text:
            yield start_seconds, english_text


def iter_plain_text_chunks(subtitle_file, chunk_chars=450):
    text = Path(subtitle_file).read_text(encoding="utf-8", errors="ignore")
    lines = [line.strip("- \t") for line in text.splitlines() if line.strip()]

    buffer = []
    size = 0
    start = 0.0

    for line in lines:
        buffer.append(line)
        size += len(line)
        if size >= chunk_chars:
            yield start, " ".join(buffer)
            start += 10.0
            buffer = []
            size = 0

    if buffer:
        yield start, " ".join(buffer)


def iter_subtitle_segments(subtitle_file):
    subtitle_path = Path(subtitle_file)
    suffix = subtitle_path.suffix.lower()

    if suffix == ".srt":
        yield from iter_srt_segments(subtitle_path)
        return

    if suffix == ".vtt":
        yield from iter_vtt_segments(subtitle_path)
        return

    if suffix == ".txt":
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        if "-->" in content and re.search(r"\d{2}:\d{2}:\d{2}[,\.]\d{3}", content):
            yield from iter_srt_segments(subtitle_path)
            return

        logger.warning("Plain txt subtitle has no timecodes, falling back to rough chunking: %s", subtitle_path)
        yield from iter_plain_text_chunks(subtitle_path)
        return

    logger.warning("Unsupported subtitle suffix %s, falling back to rough chunking: %s", suffix, subtitle_path)
    yield from iter_plain_text_chunks(subtitle_path)


def process_transcription(input_mp3, output_md, subtitle_file=None):
    log_file = setup_logging()
    process_start = time.monotonic()
    Path(output_md).parent.mkdir(parents=True, exist_ok=True)
    filter_words = load_filter_words()
    translation_config = load_translation_config()
    segments_per_translation = translation_config["segments_per_translation"]
    repeat_window_seconds = translation_config["repeat_window_seconds"]

    try:
        logger.info(
            "Start transcription/translation: %s input=%s output=%s subtitle=%s",
            os.path.basename(input_mp3),
            input_mp3,
            output_md,
            subtitle_file,
        )
        logger.info("Log file: %s", log_file)

        with open(output_md, "w", encoding="utf-8") as handle:
            handle.write("# Podcast vocabulary notes\n")
            handle.write(f"Source file: {os.path.basename(input_mp3)}\n")
            if subtitle_file:
                handle.write(f"Subtitle file: {subtitle_file}\n")
            handle.write("\n")

            wrote_segments = False
            segment_buffer = []
            recent_translations = {}

            def enqueue_segment(start_seconds, english_text):
                segment_buffer.append((start_seconds, english_text))
                if len(segment_buffer) >= segments_per_translation:
                    write_segment_group(
                        handle,
                        segment_buffer,
                        filter_words=filter_words,
                        recent_translations=recent_translations,
                        repeat_window_seconds=repeat_window_seconds,
                    )
                    segment_buffer.clear()

            if subtitle_file:
                logger.info("Generating translation md from subtitle file: %s", subtitle_file)
                for start_seconds, english_text in iter_subtitle_segments(subtitle_file):
                    enqueue_segment(start_seconds, english_text)
                    wrote_segments = True

            if not wrote_segments:
                if subtitle_file:
                    logger.warning("Subtitle file yielded no usable segments, falling back to Whisper: %s", subtitle_file)

                transcribe_start = time.monotonic()
                segment_count = 0
                chunk_seconds = get_whisper_chunk_seconds()
                isolate_chunks = get_whisper_isolate_chunks()
                model = None

                if chunk_seconds <= 0 or not isolate_chunks:
                    model_load_start = time.monotonic()
                    model = load_whisper_model()
                    logger.info("Whisper model ready elapsed=%.2fs", time.monotonic() - model_load_start)

                if chunk_seconds > 0:
                    logger.info(
                        "Whisper chunk mode start input=%s beam_size=5 chunk_seconds=%s isolate_chunks=%s",
                        input_mp3,
                        chunk_seconds,
                        isolate_chunks,
                    )
                    for chunk_offset, chunk_index, segment in iter_whisper_segments_chunked(
                        model,
                        input_mp3,
                        chunk_seconds,
                    ):
                        segment_count += 1
                        absolute_start = chunk_offset + segment.start
                        absolute_end = chunk_offset + segment.end
                        if segment_count == 1 or segment_count % 50 == 0:
                            logger.info(
                                "Whisper segment progress count=%d chunk=%d start=%.2fs end=%.2fs",
                                segment_count,
                                chunk_index,
                                absolute_start,
                                absolute_end,
                        )
                        english_text = segment.text.strip()
                        if english_text:
                            enqueue_segment(absolute_start, english_text)
                            wrote_segments = True
                else:
                    logger.info("Whisper transcribe call start input=%s beam_size=5", input_mp3)
                    segments, _info = model.transcribe(input_mp3, beam_size=5)
                    logger.info("Whisper transcribe call returned elapsed=%.2fs info=%s", time.monotonic() - transcribe_start, _info)

                    for segment in segments:
                        segment_count += 1
                        if segment_count == 1 or segment_count % 50 == 0:
                            logger.info(
                                "Whisper segment progress count=%d start=%.2fs end=%.2fs",
                                segment_count,
                                segment.start,
                                segment.end,
                        )
                        english_text = segment.text.strip()
                        if english_text:
                            enqueue_segment(segment.start, english_text)
                            wrote_segments = True

                logger.info(
                    "Whisper segments exhausted count=%d elapsed=%.2fs chunk_seconds=%s",
                    segment_count,
                    time.monotonic() - transcribe_start,
                    chunk_seconds,
                )

            if segment_buffer:
                write_segment_group(
                    handle,
                    segment_buffer,
                    filter_words=filter_words,
                    recent_translations=recent_translations,
                    repeat_window_seconds=repeat_window_seconds,
                )
                segment_buffer.clear()

            if not wrote_segments:
                logger.warning("No segments were written to markdown: %s", output_md)

            handle.write(f"\n{COMPLETE_MARKER}\n")
            handle.flush()

        logger.info("Translation md completed: %s elapsed=%.2fs", output_md, time.monotonic() - process_start)
    except Exception:
        logger.exception(
            "Transcription/translation failed: input=%s output=%s subtitle=%s elapsed=%.2fs",
            input_mp3,
            output_md,
            subtitle_file,
            time.monotonic() - process_start,
        )
        raise


def main_cli():
    setup_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcribe-chunk", nargs=2, metavar=("INPUT_AUDIO", "OUTPUT_JSON"))
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--compute-type", default="float16")
    parser.add_argument("--cpu-threads", type=int, default=1)
    args = parser.parse_args()

    if args.transcribe_chunk:
        input_audio, output_json = args.transcribe_chunk
        transcribe_file_to_json(
            input_audio,
            output_json,
            args.device,
            args.compute_type,
            args.cpu_threads,
        )
        return

    parser.error("No command specified")


if __name__ == "__main__":
    main_cli()
