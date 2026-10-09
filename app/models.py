from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SOURCE_AUDIO_EXTENSIONS = {".mp3", ".flac"}
OPUS_AUDIO_EXTENSIONS = {".opus"}
RESAMPLED_OPUS_SUFFIX = ".resampled.opus"
RESAMPLED_FOLDER_SUFFIX = "_rsm"
AUDIO_EXTENSIONS = SOURCE_AUDIO_EXTENSIONS | OPUS_AUDIO_EXTENSIONS
SOURCE_DELETE_EXTENSIONS = SOURCE_AUDIO_EXTENSIONS
TARGET_SAMPLE_RATES = (8000, 12000, 16000, 24000, 48000)
DOWNSAMPLE_BITRATE_CAPS_KBPS = {
    8000: 16,
    12000: 24,
    16000: 32,
    24000: 48,
    48000: 160,
}


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


def _bitrate_label(value_kbps: float) -> str:
    return f"{max(6, int(round(value_kbps)))}k"


def target_bitrate_cap_for_sample_rate(sample_rate_hz: int | None) -> int | None:
    if sample_rate_hz is None:
        return None
    for rate in TARGET_SAMPLE_RATES:
        if sample_rate_hz <= rate:
            return DOWNSAMPLE_BITRATE_CAPS_KBPS[rate]
    return DOWNSAMPLE_BITRATE_CAPS_KBPS[max(TARGET_SAMPLE_RATES)]


def target_bitrate_auto(
    bitrate_kbps: float | None,
    source_suffix: str = "",
    target_sample_rate_hz: int | None = None,
    source_sample_rate_hz: int | None = None,
) -> str:
    suffix = source_suffix.lower()
    if bitrate_kbps is None:
        chosen_kbps = 128
    elif suffix == ".mp3":
        if bitrate_kbps <= 64:
            chosen_kbps = 48
        elif bitrate_kbps <= 96:
            chosen_kbps = 64
        elif bitrate_kbps <= 128:
            chosen_kbps = 80
        elif bitrate_kbps <= 160:
            chosen_kbps = 96
        elif bitrate_kbps <= 192:
            chosen_kbps = 112
        elif bitrate_kbps <= 256:
            chosen_kbps = 128
        else:
            chosen_kbps = 160
    elif bitrate_kbps <= 64:
        chosen_kbps = 48
    elif bitrate_kbps <= 96:
        chosen_kbps = 64
    elif bitrate_kbps <= 128:
        chosen_kbps = 80
    elif bitrate_kbps <= 160:
        chosen_kbps = 96
    elif bitrate_kbps <= 192:
        chosen_kbps = 112
    elif bitrate_kbps <= 256:
        chosen_kbps = 128
    else:
        chosen_kbps = 160

    is_downsample = (
        target_sample_rate_hz is not None
        and (source_sample_rate_hz is None or source_sample_rate_hz > target_sample_rate_hz)
    )
    if is_downsample:
        cap_kbps = target_bitrate_cap_for_sample_rate(target_sample_rate_hz)
        if cap_kbps is not None:
            chosen_kbps = min(chosen_kbps, cap_kbps)
        if bitrate_kbps is not None:
            chosen_kbps = min(chosen_kbps, max(6, bitrate_kbps * 0.95))

    return _bitrate_label(chosen_kbps)
