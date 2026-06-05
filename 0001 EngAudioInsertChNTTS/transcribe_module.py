import logging
import os
import re
import gc
import argparse
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

analyzer = CEFRAnalyzer()
OLLAMA_API = "http://localhost:11434/api/generate"
FILTER_FILE = Path(__file__).resolve().parent / "filter.txt"
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


def env_bool(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_ollama_model():
    return os.getenv("JOEROGAN_OLLAMA_MODEL", "qwen2.5:7b").strip() or "qwen2.5:7b"


def get_whisper_cpu_threads():
    return env_int("JOEROGAN_WHISPER_CPU_THREADS", "1")


def get_whisper_device():
    return os.getenv("JOEROGAN_WHISPER_DEVICE", "cuda").strip() or "cuda"


def get_whisper_compute_type(device):
    default = "int8" if device == "cpu" else "float16"
    return os.getenv("JOEROGAN_WHISPER_COMPUTE_TYPE", default).strip() or default


def get_whisper_chunk_seconds():
    value = os.getenv("JOEROGAN_WHISPER_CHUNK_SECONDS")
    if value is None:
        return 0 if get_whisper_device() == "cpu" else 900

    try:
        return max(0, int(value))
    except ValueError:
        logger.warning("Invalid JOEROGAN_WHISPER_CHUNK_SECONDS=%r, using default", value)
        return 0 if get_whisper_device() == "cpu" else 900


def get_whisper_isolate_chunks():
    return env_bool("JOEROGAN_WHISPER_ISOLATE_CHUNKS", get_whisper_device() != "cpu")


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
        if device == "cpu" or not env_bool("JOEROGAN_WHISPER_FALLBACK_CPU", True):
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
    description = f"Whisper chunk child index={chunk_index} device={device}"
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
    )
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

    try:
        return transcribe_chunk_subprocess(
            chunk_path,
            tmp_dir,
            chunk_index,
            device,
            compute_type,
            cpu_threads,
        )
    except Exception:
        if device == "cpu" or not env_bool("JOEROGAN_WHISPER_FALLBACK_CPU", True):
            raise
        logger.exception(
            "GPU chunk subprocess failed index=%d path=%s; retrying this chunk on CPU int8",
            chunk_index,
            chunk_path,
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

    with tempfile.TemporaryDirectory(prefix="joerogan_whisper_chunks_") as tmp_dir:
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


def normalize_word(raw_word):
    return raw_word.strip().strip(".,!?;:\"()[]{}<>").replace("\u2019", "'")


def cefr_level_to_text(level):
    if level is None:
        return ""
    if hasattr(level, "name"):
        return str(level.name).upper()
    return str(level).strip().upper()


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


def is_acronym_or_tool_name(raw_word, filter_words=None):
    word = normalize_word(raw_word)
    if not word:
        return True

    compact = word.replace("-", "").replace("_", "").replace(".", "").replace("'", "")
    lower = compact.lower()

    if filter_words and lower in filter_words:
        return True

    if lower in SKIP_WORDS:
        return True

    if len(compact) <= 4:
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
    b1_freq_threshold=0.000003,
    b2_freq_threshold=0.000012,
    unknown_freq_threshold=0.000003,
):
    word = normalize_word(word)
    clean_word = word.lower()

    if not clean_word.isalpha():
        return False

    if is_acronym_or_tool_name(word, filter_words=filter_words):
        return False

    level = cefr_level_to_text(analyzer.get_average_word_level_CEFR(clean_word))
    freq = word_frequency(clean_word, "en")

    if level in ["C1", "C2"]:
        return True

    if level == "B2" and len(clean_word) >= 8 and freq < b2_freq_threshold:
        return True

    if level == "B1" and len(clean_word) >= 8 and freq < b1_freq_threshold:
        return True

    if not level and len(clean_word) >= 8 and freq < unknown_freq_threshold:
        return True

    return False


def translate_words_list(words_list, filter_words=None):
    if not words_list:
        return ""

    unique_words = sorted(
        {
            normalize_word(word).lower()
            for word in words_list
            if normalize_word(word) and not is_acronym_or_tool_name(word, filter_words=filter_words)
        }
    )

    if not unique_words:
        return ""

    prompt = (
        "You are an English vocabulary teacher. Translate the following English words into Chinese. "
        "Return only compact entries in this format: word: Chinese meaning; word2: Chinese meaning.\n\n"
        f"Words: {', '.join(unique_words)}"
    )
    model_name = get_ollama_model()
    payload = {"model": model_name, "prompt": prompt, "stream": False}

    try:
        logger.info("Ollama translation model=%s words=%d", model_name, len(unique_words))
        response = requests.post(OLLAMA_API, json=payload, timeout=60)
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as exc:
        logger.exception("Ollama translation failed: %s", exc)
        return "[translation error]"


def write_segment(handle, start_seconds, english_text, filter_words=None):
    words = re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", english_text)
    difficult_words = [word for word in words if is_difficult(word, filter_words=filter_words)]

    translation_text = ""
    if difficult_words:
        translated_words = translate_words_list(difficult_words, filter_words=filter_words)
        if translated_words and translated_words != "[translation error]":
            translation_text = f"Vocabulary: {translated_words}"
            logger.info("Difficult words at %.2fs: %s", start_seconds, translated_words)

    handle.write(f"**[{start_seconds:.2f}s] English:** {english_text}  \n")
    handle.write(f"**Translation:** {translation_text}\n\n")
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

            if subtitle_file:
                logger.info("Generating translation md from subtitle file: %s", subtitle_file)
                for start_seconds, english_text in iter_subtitle_segments(subtitle_file):
                    write_segment(handle, start_seconds, english_text, filter_words=filter_words)
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
                            write_segment(handle, absolute_start, english_text, filter_words=filter_words)
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
                            write_segment(handle, segment.start, english_text, filter_words=filter_words)
                            wrote_segments = True

                logger.info(
                    "Whisper segments exhausted count=%d elapsed=%.2fs chunk_seconds=%s",
                    segment_count,
                    time.monotonic() - transcribe_start,
                    chunk_seconds,
                )

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
