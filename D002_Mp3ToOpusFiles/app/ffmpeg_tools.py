from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .models import (
    AudioFile,
    RESAMPLED_FOLDER_SUFFIX,
    RESAMPLED_OPUS_SUFFIX,
    target_bitrate_auto,
    target_sample_rate_with_limit,
)
from .platform_utils import find_executable


class ToolError(RuntimeError):
    pass


def require_tools() -> tuple[str, str]:
    ffprobe = find_executable("ffprobe")
    ffmpeg = find_executable("ffmpeg")
    missing = []
    if not ffprobe:
        missing.append("ffprobe")
    if not ffmpeg:
        missing.append("ffmpeg")
    if missing:
        raise ToolError("Missing required tool(s): " + ", ".join(missing))
    return ffprobe, ffmpeg


def probe_audio(path: Path, ffprobe_path: str | None = None) -> dict[str, object]:
    ffprobe = ffprobe_path or find_executable("ffprobe")
    if not ffprobe:
        raise ToolError("ffprobe was not found in PATH.")

    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,bit_rate,codec_name",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise ToolError(result.stderr.strip() or f"ffprobe failed for {path}")

    payload = json.loads(result.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise ToolError(f"No audio stream found: {path}")

    stream = streams[0]
    sample_rate_raw = stream.get("sample_rate")
    bitrate_raw = stream.get("bit_rate")

    sample_rate = int(sample_rate_raw) if sample_rate_raw else None
    bitrate_kbps = (int(bitrate_raw) / 1000.0) if bitrate_raw else None

    return {
        "format_name": str(stream.get("codec_name") or path.suffix.lower().lstrip(".")),
        "sample_rate": sample_rate,
        "bitrate_kbps": bitrate_kbps,
    }


def opus_resample_output_root(source_root: Path) -> Path:
    if not source_root.name:
        return source_root / f"resampled{RESAMPLED_FOLDER_SUFFIX}"
    return source_root.with_name(f"{source_root.name}{RESAMPLED_FOLDER_SUFFIX}")


def opus_resample_output_path(path: Path, source_root: Path) -> Path:
    output_root = opus_resample_output_root(source_root)
    try:
        relative_path = path.relative_to(source_root)
    except ValueError:
        relative_path = Path(path.name)
    return output_root / relative_path


def build_audio_file(
    path: Path,
    target_sample_rate: int | None,
    ffprobe_path: str | None = None,
    opus_source_root: Path | None = None,
) -> AudioFile:
    details = probe_audio(path, ffprobe_path=ffprobe_path)
    sample_rate = details["sample_rate"]
    bitrate_kbps = details["bitrate_kbps"]
    output_path = path.with_suffix(".opus")

    if output_path == path:
        if opus_source_root is not None:
            output_path = opus_resample_output_path(path, opus_source_root)
        else:
            output_path = path.with_name(f"{path.stem}{RESAMPLED_OPUS_SUFFIX}")

    chosen_sample_rate = target_sample_rate_with_limit(sample_rate, target_sample_rate)
    target_bitrate = target_bitrate_auto(
        bitrate_kbps,
        path.suffix,
        target_sample_rate_hz=chosen_sample_rate,
        source_sample_rate_hz=sample_rate,
    )

    status = "Ready"
    message = ""
    if output_path.exists():
        status = "Exists"
        message = "Output already exists"

    return AudioFile(
        source_path=path,
        output_path=output_path,
        format_name=str(details["format_name"]),
        sample_rate=sample_rate,
        bitrate_kbps=bitrate_kbps,
        target_sample_rate=chosen_sample_rate,
        target_bitrate=target_bitrate,
        status=status,
        message=message,
    )


def format_file_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def convert_audio(
    audio: AudioFile,
    overwrite: bool,
    ffmpeg_path: str | None = None,
) -> AudioFile:
    ffmpeg = ffmpeg_path or find_executable("ffmpeg")
    if not ffmpeg:
        raise ToolError("ffmpeg was not found in PATH.")

    if audio.output_path.exists() and not overwrite:
        audio.status = "Skipped"
        audio.message = "Output already exists"
        return audio

    audio.output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-i",
        str(audio.source_path),
        "-ar",
        str(audio.target_sample_rate or 48000),
        "-c:a",
        "libopus",
        "-b:a",
        audio.target_bitrate or "128k",
        str(audio.output_path),
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        audio.status = "Failed"
        audio.message = result.stderr.strip() or "ffmpeg conversion failed"
        return audio

    try:
        source_size = audio.source_path.stat().st_size
    except OSError:
        source_size = None
    try:
        output_size = audio.output_path.stat().st_size
    except OSError:
        output_size = None

    size_summary = f"{format_file_size(source_size)} -> {format_file_size(output_size)}"
    target_summary = f"target {audio.target_bitrate or 'auto'} @ {audio.target_sample_rate or 48000} Hz"
    audio.status = "Converted"
    if source_size is not None and output_size is not None and output_size > source_size:
        audio.message = f"OK, output larger: {size_summary}; {target_summary}"
    else:
        audio.message = f"OK, size {size_summary}; {target_summary}"
    return audio
