import asyncio
import hashlib
import json
import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import edge_tts
from pydub import AudioSegment


VOICE = "zh-CN-XiaoxiaoNeural"
VOICE_RATE = "-10%"

MAX_TTS_CONCURRENCY = 3
TTS_RETRY_TIMES = 5
TTS_RETRY_BASE_DELAY = 2.0

INSERT_BEFORE_TTS_SILENCE_MS = 300
INSERT_AFTER_TTS_SILENCE_MS = 600

OUTPUT_BITRATE = "96k"
OUTPUT_OPUS_BITRATE = "96k"
OUTPUT_CHANNELS = "2"
OUTPUT_SAMPLE_RATE = "44100"

NO_TTS_MARKERS = (
    "no difficult words",
    "no vocabulary",
    "none",
    "本段无难词",
    "本段無難詞",
    "无难词",
    "無難詞",
    "没有难词",
    "沒有難詞",
)

logger = logging.getLogger(__name__)
_LOG_INITIALIZED = False
_LOG_FILE = None


def setup_logging():
    global _LOG_INITIALIZED, _LOG_FILE

    if _LOG_INITIALIZED:
        return _LOG_FILE

    script_dir = Path(__file__).resolve().parent
    log_dir = script_dir / "Log"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _LOG_FILE = log_dir / f"tts_module_{timestamp}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _LOG_INITIALIZED = True
    logger.info("Log file: %s", _LOG_FILE)
    return _LOG_FILE


def parse_md_segments(content):
    header_pattern = re.compile(
        r"\*\*\[(?P<start>\d+(?:\.\d+)?)s\]\s*English:\*\*\s*",
        re.IGNORECASE,
    )
    matches = list(header_pattern.finditer(content))
    rows = []

    for index, match in enumerate(matches):
        start_seconds = float(match.group("start"))
        block_start = match.end()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        block = content[block_start:block_end].strip("\n")

        english_lines = []
        translation_lines = []
        in_translation = False

        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            label_match = re.match(r"^\*\*[^*\n]*:\*\*\s*(?P<value>.*)$", line)
            if label_match:
                in_translation = True
                value = label_match.group("value").strip()
                if value:
                    translation_lines.append(value)
                continue

            if in_translation:
                translation_lines.append(line)
            else:
                english_lines.append(line)

        rows.append(
            {
                "start": start_seconds,
                "english": " ".join(" ".join(english_lines).split()),
                "translation": " ".join(" ".join(translation_lines).split()),
            }
        )

    rows.sort(key=lambda item: item["start"])
    return rows


def strip_markdown_noise(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = text.replace("*", " ")
    text = text.replace("#", " ")
    text = re.sub(r"^\s*[-+]\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_tts_text(text):
    if not text:
        return ""

    text = strip_markdown_noise(text)
    lowered = text.lower().strip(" .;:：")
    if any(marker in lowered for marker in NO_TTS_MARKERS):
        return ""

    text = re.sub(
        r"^(translation|vocabulary|words|word list|重点词汇释义|重点词汇|重點詞彙釋義|重點詞彙|中文翻译|中文翻譯)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(translation|vocabulary|words|word list)\s*[:：]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.replace("[translation error]", "")

    lowered = text.lower().strip(" .;:：")
    if any(marker in lowered for marker in NO_TTS_MARKERS):
        return ""

    # Make punctuation behave like pauses instead of spoken Markdown or labels.
    text = re.sub(r"([A-Za-z][A-Za-z'-]*)\s*[:：]\s*", r"\1, ", text)
    text = text.replace("；", "。")
    text = text.replace(";", "。")
    text = text.replace("|", " ")
    text = text.replace("[", " ").replace("]", " ")
    text = text.replace("(", " ").replace(")", " ")
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" ,.;:：。")

    return text


def should_skip_tts(clean_text):
    if not clean_text:
        return True

    lowered = clean_text.lower().strip(" .;:：")
    return any(marker in lowered for marker in NO_TTS_MARKERS)


def tts_cache_path(idx, clean_text, tmp_dir):
    digest = hashlib.sha1(clean_text.encode("utf-8")).hexdigest()[:12]
    return Path(tmp_dir) / f"{idx:04d}_{digest}.mp3"


async def synthesize_single(idx, text, tmp_dir, semaphore):
    clean_text = clean_tts_text(text)
    if should_skip_tts(clean_text):
        logger.info("Skip empty/non-vocabulary TTS segment idx=%s raw=%r", idx, text[:120])
        return None

    path = tts_cache_path(idx, clean_text, tmp_dir)
    if path.exists() and path.stat().st_size > 0:
        logger.info("Reuse temp TTS idx=%s path=%s", idx, path)
        return str(path)

    async with semaphore:
        for attempt in range(1, TTS_RETRY_TIMES + 1):
            try:
                logger.info(
                    "Generate TTS idx=%s attempt=%s/%s text=%r",
                    idx,
                    attempt,
                    TTS_RETRY_TIMES,
                    clean_text[:200],
                )

                communicate = edge_tts.Communicate(clean_text, VOICE, rate=VOICE_RATE)
                await communicate.save(str(path))

                if path.exists() and path.stat().st_size > 0:
                    return str(path)

                logger.warning("TTS output file is empty idx=%s path=%s", idx, path)

            except Exception as exc:
                logger.warning(
                    "TTS failed idx=%s attempt=%s/%s error=%r",
                    idx,
                    attempt,
                    TTS_RETRY_TIMES,
                    exc,
                    exc_info=True,
                )

            await asyncio.sleep(TTS_RETRY_BASE_DELAY * attempt)

    logger.error("TTS permanently failed idx=%s text=%r", idx, clean_text[:500])
    return None


async def run_tts_limited(rows, tmp_dir):
    semaphore = asyncio.Semaphore(MAX_TTS_CONCURRENCY)
    tasks = [
        synthesize_single(index, row["translation"], tmp_dir, semaphore)
        for index, row in enumerate(rows)
    ]
    return await asyncio.gather(*tasks)


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


def run_streaming_ffmpeg(cmd, description, write_audio):
    logger.info("%s: %s", description, " ".join(str(item) for item in cmd))

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        write_audio(proc.stdin)
        proc.stdin.close()
        proc.stdin = None
        stdout, stderr = proc.communicate()
    except Exception:
        if proc.stdin:
            proc.stdin.close()
        proc.kill()
        stdout, stderr = proc.communicate()
        logger.error("%s stdout: %s", description, stdout.decode("utf-8", errors="replace")[-4000:])
        logger.error("%s stderr: %s", description, stderr.decode("utf-8", errors="replace")[-4000:])
        raise

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")

    if stdout_text.strip():
        logger.info("%s stdout: %s", description, stdout_text[-4000:])

    if stderr_text.strip():
        logger.info("%s stderr: %s", description, stderr_text[-4000:])

    if proc.returncode != 0:
        raise RuntimeError(f"{description} failed with exit code {proc.returncode}")

    return proc


def require_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")

    if not ffmpeg:
        raise FileNotFoundError("ffmpeg not found in PATH")

    if not ffprobe:
        raise FileNotFoundError("ffprobe not found in PATH")

    return ffmpeg, ffprobe


def normalize_audio_segment(segment):
    return (
        segment
        .set_frame_rate(int(OUTPUT_SAMPLE_RATE))
        .set_channels(int(OUTPUT_CHANNELS))
        .set_sample_width(2)
    )


def write_raw_segment(stream, segment):
    if segment and len(segment) > 0:
        stream.write(segment.raw_data)


def ffconcat_escape(path):
    return str(path).replace("\\", "\\\\").replace("'", "\\'")


def get_audio_duration_seconds(audio_path, ffprobe):
    proc = run_cmd(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        "Probe audio duration",
    )

    value = proc.stdout.strip()
    if not value:
        raise RuntimeError(f"Cannot probe duration: {audio_path}")

    return float(value)


def probe_audio_stream_metadata(audio_path, ffprobe):
    proc = run_cmd(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=sample_rate,channels,channel_layout",
            "-of",
            "json",
            str(audio_path),
        ],
        "Probe audio stream metadata",
    )

    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Cannot parse ffprobe stream metadata: {audio_path}") from exc

    streams = payload.get("streams") or []
    if not streams:
        raise RuntimeError(f"No audio stream found: {audio_path}")

    stream = streams[0]
    sample_rate = str(stream.get("sample_rate") or "").strip()
    channels = str(stream.get("channels") or "").strip() or None
    channel_layout = str(stream.get("channel_layout") or "").strip() or None
    if channel_layout and channel_layout.lower() == "unknown":
        channel_layout = None

    if not sample_rate:
        raise RuntimeError(f"Cannot probe sample rate: {audio_path}")

    return {
        "sample_rate": sample_rate,
        "channels": channels,
        "channel_layout": channel_layout,
    }


def build_output_profile(original_audio, final_output, ffprobe):
    suffix = Path(final_output).suffix.lower()
    if suffix == ".opus":
        metadata = probe_audio_stream_metadata(original_audio, ffprobe)
        if not metadata["channel_layout"]:
            logger.warning(
                "Source audio has no explicit channel_layout; preserving channel count only: %s channels=%s",
                original_audio,
                metadata["channels"],
            )

        profile = {
            "format": "opus",
            "codec": "libopus",
            "suffix": ".opus",
            "bitrate": OUTPUT_OPUS_BITRATE,
            "silence_bitrate": OUTPUT_OPUS_BITRATE,
            "sample_rate": metadata["sample_rate"],
            "channels": metadata["channels"],
            "channel_layout": metadata["channel_layout"],
            "normalize_concat_inputs": True,
            "presegment_original": True,
        }
        logger.info(
            "Opus output profile from source: sample_rate=%s channels=%s channel_layout=%s bitrate=%s",
            profile["sample_rate"],
            profile["channels"],
            profile["channel_layout"] or "",
            profile["bitrate"],
        )
        return profile

    return {
        "format": "mp3",
        "codec": "libmp3lame",
        "suffix": ".mp3",
        "bitrate": OUTPUT_BITRATE,
        "silence_bitrate": "64k",
        "sample_rate": OUTPUT_SAMPLE_RATE,
        "channels": OUTPUT_CHANNELS,
        "channel_layout": None,
        "normalize_concat_inputs": False,
        "presegment_original": False,
    }


def default_channel_layout(channels):
    try:
        channel_count = int(channels)
    except (TypeError, ValueError):
        return None

    if channel_count == 1:
        return "mono"
    if channel_count == 2:
        return "stereo"
    return None


def ffmpeg_audio_shape_args(profile):
    args = ["-ar", str(profile["sample_rate"])]
    channel_layout = profile.get("channel_layout")
    if channel_layout:
        args.extend(["-channel_layout", channel_layout])
    elif profile.get("channels"):
        args.extend(["-ac", str(profile["channels"])])
    return args


def anullsrc_spec(profile):
    spec = f"anullsrc=r={profile['sample_rate']}"
    channel_layout = profile.get("channel_layout") or default_channel_layout(profile.get("channels"))
    if channel_layout:
        spec += f":cl={channel_layout}"
    return spec


def create_silence_audio(path, duration_ms, ffmpeg, profile):
    path = Path(path)

    if path.exists() and path.stat().st_size > 0:
        return path

    duration_seconds = duration_ms / 1000
    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        anullsrc_spec(profile),
        "-t",
        f"{duration_seconds:.3f}",
    ]
    cmd.extend(ffmpeg_audio_shape_args(profile))
    cmd.extend(
        [
            "-f",
            profile["format"],
            "-acodec",
            profile["codec"],
            "-b:a",
            profile["silence_bitrate"],
            str(path),
        ]
    )

    run_cmd(cmd, f"Create silence {duration_ms}ms")

    if not path.exists() or path.stat().st_size <= 0:
        raise RuntimeError(f"Failed to create silence audio: {path}")

    return path


def transcode_audio_for_concat(input_path, output_path, ffmpeg, profile):
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    cmd = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
    ]
    cmd.extend(ffmpeg_audio_shape_args(profile))
    cmd.extend(
        [
            "-f",
            profile["format"],
            "-c:a",
            profile["codec"],
            "-b:a",
            profile["bitrate"],
            str(output_path),
        ]
    )
    run_cmd(cmd, f"Normalize TTS for {profile['format']} concat")

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"Failed to normalize TTS audio: {output_path}")

    return output_path


def normalize_tts_paths_for_concat(tts_paths, tmp_dir, profile, ffmpeg):
    if not profile.get("normalize_concat_inputs"):
        return tts_paths

    normalized_dir = Path(tmp_dir) / "normalized_tts"
    normalized_paths = []
    for tts_path in tts_paths:
        if not tts_path:
            normalized_paths.append(tts_path)
            continue

        tts_path = Path(tts_path)
        if not tts_path.exists() or tts_path.stat().st_size <= 0:
            normalized_paths.append(str(tts_path))
            continue

        output_path = normalized_dir / f"{tts_path.stem}{profile['suffix']}"
        normalized_paths.append(str(transcode_audio_for_concat(tts_path, output_path, ffmpeg, profile)))

    return normalized_paths


def create_original_audio_segment(input_path, start_seconds, duration_seconds, output_path, ffmpeg, profile):
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    cmd = [
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
        str(input_path),
        "-vn",
        "-avoid_negative_ts",
        "make_zero",
    ]
    cmd.extend(ffmpeg_audio_shape_args(profile))
    cmd.extend(
        [
            "-f",
            profile["format"],
            "-c:a",
            profile["codec"],
            "-b:a",
            profile["bitrate"],
            str(output_path),
        ]
    )
    run_cmd(cmd, f"Create original audio concat segment start={start_seconds:.3f}")

    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise RuntimeError(f"Failed to create original audio segment: {output_path}")

    return output_path


def write_presegmented_concat_list(
    rows,
    tts_paths,
    original_audio,
    original_duration,
    silence_before,
    silence_after,
    concat_file,
    tmp_dir,
    ffmpeg,
    profile,
):
    silence_before = Path(silence_before).resolve()
    silence_after = Path(silence_after).resolve()
    concat_file = Path(concat_file)
    original_segments_dir = Path(tmp_dir) / "original_segments"

    total = len(rows)
    entries = 0

    with concat_file.open("w", encoding="utf-8") as handle:
        handle.write("ffconcat version 1.0\n")

        for index, row in enumerate(rows):
            start_seconds = max(0.0, float(row["start"]))
            next_seconds = float(rows[index + 1]["start"]) if index + 1 < total else original_duration
            next_seconds = min(next_seconds, original_duration)

            if start_seconds >= original_duration or next_seconds <= start_seconds:
                logger.warning(
                    "Skip invalid original segment idx=%s start=%.3f next=%.3f duration=%.3f",
                    index,
                    start_seconds,
                    next_seconds,
                    original_duration,
                )
                continue

            segment_path = original_segments_dir / (
                f"original_{index:05d}_{int(start_seconds * 1000):012d}_{int(next_seconds * 1000):012d}"
                f"{profile['suffix']}"
            )
            segment_path = create_original_audio_segment(
                original_audio,
                start_seconds,
                next_seconds - start_seconds,
                segment_path,
                ffmpeg,
                profile,
            ).resolve()
            handle.write(f"file '{ffconcat_escape(segment_path)}'\n")
            entries += 1

            tts_path = tts_paths[index] if index < len(tts_paths) else None
            if tts_path and Path(tts_path).exists() and Path(tts_path).stat().st_size > 0:
                tts_path = Path(tts_path).resolve()
                handle.write(f"file '{ffconcat_escape(silence_before)}'\n")
                handle.write(f"file '{ffconcat_escape(tts_path)}'\n")
                handle.write(f"file '{ffconcat_escape(silence_after)}'\n")
                entries += 3

    logger.info("Presegmented concat list written: %s entries=%s", concat_file, entries)

    if entries <= 0:
        raise RuntimeError("Concat list is empty")

    return concat_file


def write_concat_list(rows, tts_paths, original_mp3, original_duration, silence_before, silence_after, concat_file):
    original_mp3 = Path(original_mp3).resolve()
    silence_before = Path(silence_before).resolve()
    silence_after = Path(silence_after).resolve()
    concat_file = Path(concat_file)

    total = len(rows)
    entries = 0

    with concat_file.open("w", encoding="utf-8") as handle:
        handle.write("ffconcat version 1.0\n")

        for index, row in enumerate(rows):
            start_seconds = max(0.0, float(row["start"]))
            next_seconds = float(rows[index + 1]["start"]) if index + 1 < total else original_duration
            next_seconds = min(next_seconds, original_duration)

            if start_seconds >= original_duration or next_seconds <= start_seconds:
                logger.warning(
                    "Skip invalid original segment idx=%s start=%.3f next=%.3f duration=%.3f",
                    index,
                    start_seconds,
                    next_seconds,
                    original_duration,
                )
                continue

            handle.write(f"file '{ffconcat_escape(original_mp3)}'\n")
            handle.write(f"inpoint {start_seconds:.3f}\n")
            handle.write(f"outpoint {next_seconds:.3f}\n")
            entries += 1

            tts_path = tts_paths[index] if index < len(tts_paths) else None
            if tts_path and Path(tts_path).exists() and Path(tts_path).stat().st_size > 0:
                tts_path = Path(tts_path).resolve()
                handle.write(f"file '{ffconcat_escape(silence_before)}'\n")
                handle.write(f"file '{ffconcat_escape(tts_path)}'\n")
                handle.write(f"file '{ffconcat_escape(silence_after)}'\n")
                entries += 3

    logger.info("Concat list written: %s entries=%s", concat_file, entries)

    if entries <= 0:
        raise RuntimeError("Concat list is empty")

    return concat_file


def combine_audio_fast_ffmpeg(rows, tts_paths, original_mp3, final_output, tmp_dir):
    ffmpeg, ffprobe = require_ffmpeg()

    original_mp3 = Path(original_mp3)
    final_output = Path(final_output)
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    output_profile = build_output_profile(original_mp3, final_output, ffprobe)

    logger.info("Building ffmpeg concat list without loading full original audio: %s", original_mp3)
    original_duration = get_audio_duration_seconds(original_mp3, ffprobe)
    logger.info("Original audio duration: %.3f seconds", original_duration)

    silence_before = create_silence_audio(
        tmp_dir / f"silence_before_{INSERT_BEFORE_TTS_SILENCE_MS}ms{output_profile['suffix']}",
        INSERT_BEFORE_TTS_SILENCE_MS,
        ffmpeg,
        output_profile,
    )
    silence_after = create_silence_audio(
        tmp_dir / f"silence_after_{INSERT_AFTER_TTS_SILENCE_MS}ms{output_profile['suffix']}",
        INSERT_AFTER_TTS_SILENCE_MS,
        ffmpeg,
        output_profile,
    )
    concat_tts_paths = normalize_tts_paths_for_concat(tts_paths, tmp_dir, output_profile, ffmpeg)
    if output_profile.get("presegment_original"):
        concat_file = write_presegmented_concat_list(
            rows,
            concat_tts_paths,
            original_mp3,
            original_duration,
            silence_before,
            silence_after,
            tmp_dir / "tts_concat.ffconcat",
            tmp_dir,
            ffmpeg,
            output_profile,
        )
    else:
        concat_file = write_concat_list(
            rows,
            concat_tts_paths,
            original_mp3,
            original_duration,
            silence_before,
            silence_after,
            tmp_dir / "tts_concat.ffconcat",
        )
    tmp_output = final_output.with_name(final_output.stem + ".part" + final_output.suffix)
    if tmp_output.exists():
        tmp_output.unlink()

    if final_output.exists() and final_output.stat().st_size == 0:
        final_output.unlink()

    logger.info("Start ffmpeg concat export: %s", final_output)
    cmd = [
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
    cmd.extend(ffmpeg_audio_shape_args(output_profile))
    cmd.extend(
        [
            "-f",
            output_profile["format"],
            "-c:a",
            output_profile["codec"],
            "-b:a",
            output_profile["bitrate"],
            str(tmp_output),
        ]
    )
    run_cmd(cmd, "FFmpeg streaming PCM export")

    if not tmp_output.exists() or tmp_output.stat().st_size <= 0:
        raise RuntimeError(f"FFmpeg produced empty output: {tmp_output}")

    tmp_output.replace(final_output)

    if not final_output.exists() or final_output.stat().st_size <= 0:
        raise RuntimeError(f"Final output is empty: {final_output}")

    logger.info("Done: %s size=%s bytes", final_output, final_output.stat().st_size)


def process_tts(md_file, original_mp3, final_output):
    log_file = setup_logging()

    md_file = Path(md_file)
    original_mp3 = Path(original_mp3)
    final_output = Path(final_output)

    final_output.parent.mkdir(parents=True, exist_ok=True)

    if final_output.exists() and final_output.stat().st_size > 0:
        logger.info("Final audio exists, skip: %s", final_output)
        return

    if final_output.exists() and final_output.stat().st_size == 0:
        logger.warning("Remove zero-byte final output: %s", final_output)
        final_output.unlink()

    tmp_dir = final_output.parent / ".tts_tmp" / final_output.stem
    tmp_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Start TTS process")
    logger.info("Markdown: %s", md_file)
    logger.info("Original audio: %s", original_mp3)
    logger.info("Final output: %s", final_output)
    logger.info("Temp dir: %s", tmp_dir)
    logger.info("Log file: %s", log_file)
    logger.info("MAX_TTS_CONCURRENCY=%s", MAX_TTS_CONCURRENCY)
    logger.info("OUTPUT_BITRATE=%s", OUTPUT_BITRATE)
    logger.info("INSERT_BEFORE_TTS_SILENCE_MS=%s", INSERT_BEFORE_TTS_SILENCE_MS)
    logger.info("INSERT_AFTER_TTS_SILENCE_MS=%s", INSERT_AFTER_TTS_SILENCE_MS)

    try:
        if not md_file.exists():
            raise FileNotFoundError(f"Markdown file not found: {md_file}")

        if not original_mp3.exists():
            raise FileNotFoundError(f"Original audio not found: {original_mp3}")

        content = md_file.read_text(encoding="utf-8", errors="ignore")
        rows = parse_md_segments(content)
        logger.info("Parsed markdown segments: %d", len(rows))

        if not rows:
            preview = content[:1000].replace("\n", "\\n")
            logger.error("No markdown segments parsed. Markdown preview: %s", preview)
            raise ValueError(f"No markdown segments parsed from {md_file}")

        tts_paths = asyncio.run(run_tts_limited(rows, tmp_dir))
        tts_count = sum(
            1
            for path in tts_paths
            if path and Path(path).exists() and Path(path).stat().st_size > 0
        )
        logger.info("Generated/reused TTS mp3 count: %d", tts_count)

        logger.info("Start fast ffmpeg combining")
        combine_audio_fast_ffmpeg(
            rows=rows,
            tts_paths=tts_paths,
            original_mp3=original_mp3,
            final_output=final_output,
            tmp_dir=tmp_dir,
        )

    except Exception:
        logger.exception("TTS process failed")
        if final_output.exists() and final_output.stat().st_size == 0:
            try:
                final_output.unlink()
                logger.info("Removed zero-byte failed output: %s", final_output)
            except Exception:
                logger.exception("Failed to remove zero-byte output: %s", final_output)
        raise
