from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


AUDIO_EXTENSIONS = {".mp3", ".flac"}
SOURCE_DELETE_EXTENSIONS = {".mp3", ".flac"}
TARGET_SAMPLE_RATES = (8000, 12000, 16000, 24000, 48000)


@dataclass
class AudioFile:
    source_path: Path
    output_path: Path
    format_name: str = ""
    sample_rate: int | None = None
    bitrate_kbps: float | None = None
    target_sample_rate: int | None = None
    target_bitrate: str = ""
    status: str = "Pending"
    message: str = ""

    @property
    def can_delete_source(self) -> bool:
        return (
            self.source_path.suffix.lower() in SOURCE_DELETE_EXTENSIONS
            and self.output_path.is_file()
        )


def target_sample_rate_auto(sample_rate_hz: int | None) -> int:
    if not sample_rate_hz:
        return 48000

    if sample_rate_hz <= 8000:
        return 8000
    if sample_rate_hz <= 12000:
        return 12000
    if sample_rate_hz <= 16000:
        return 16000
    if sample_rate_hz <= 24000:
        return 24000
    return 48000


def target_sample_rate_with_limit(
    sample_rate_hz: int | None,
    max_sample_rate_hz: int | None,
) -> int:
    chosen = target_sample_rate_auto(sample_rate_hz)
    if max_sample_rate_hz is None:
        return chosen

    allowed_rates = [rate for rate in TARGET_SAMPLE_RATES if rate <= max_sample_rate_hz]
    if not allowed_rates:
        return min(TARGET_SAMPLE_RATES)
    return min(chosen, max(allowed_rates))


def target_bitrate_auto(bitrate_kbps: float | None, source_suffix: str = "") -> str:
    suffix = source_suffix.lower()
    if bitrate_kbps is None:
        return "128k"

    if suffix == ".mp3":
        if bitrate_kbps <= 64:
            return "48k"
        if bitrate_kbps <= 96:
            return "64k"
        if bitrate_kbps <= 128:
            return "80k"
        if bitrate_kbps <= 160:
            return "96k"
        if bitrate_kbps <= 192:
            return "112k"
        if bitrate_kbps <= 256:
            return "128k"
        return "160k"

    if bitrate_kbps <= 64:
        return "48k"
    if bitrate_kbps <= 96:
        return "64k"
    if bitrate_kbps <= 128:
        return "80k"
    if bitrate_kbps <= 160:
        return "96k"
    if bitrate_kbps <= 192:
        return "112k"
    if bitrate_kbps <= 256:
        return "128k"
    return "160k"
