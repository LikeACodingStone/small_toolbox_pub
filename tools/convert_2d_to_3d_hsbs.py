#!/usr/bin/env python3
"""Stream a 2D video through depth estimation into a source-sized Half-SBS H.265 file.

Decoded and generated frames stay in memory. Only the encoded output is written
to disk, so temporary storage does not grow with the input video's duration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import subprocess
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

MATROSKA_STEREO_MODES = {
    "mono",
    "left_right",
    "right_left",
    "bottom_top",
    "top_bottom",
    "checkerboard_rl",
    "checkerboard_lr",
    "row_interleaved_rl",
    "row_interleaved_lr",
    "col_interleaved_rl",
    "col_interleaved_lr",
    "anaglyph_cyan_red",
    "anaglyph_green_magenta",
    "both_eyes_laced_left_first",
    "both_eyes_laced_right_first",
}

AUTO_VALUES = {"", "auto", "source", "input"}
DISABLED_STEREO_METADATA_VALUES = {"", "none", "off", "disable", "disabled", "false", "0"}
UNKNOWN_COLOR_VALUES = {"", "unknown", "unspecified", "reserved"}
X265_COLOR_PRIMARIES = {
    "bt709": "bt709", "bt470m": "bt470m", "bt470bg": "bt470bg",
    "smpte170m": "smpte170m", "smpte240m": "smpte240m", "film": "film",
    "bt2020": "bt2020",
}
X265_COLOR_TRANSFERS = {
    "bt709": "bt709", "smpte170m": "smpte170m", "smpte240m": "smpte240m",
    "linear": "linear", "iec61966-2-4": "iec61966-2-4",
    "bt1361e": "bt1361e", "iec61966-2-1": "iec61966-2-1",
    "bt2020-10": "bt2020-10", "bt2020-12": "bt2020-12",
    "smpte2084": "smpte2084", "arib-std-b67": "arib-std-b67",
}
X265_COLOR_MATRICES = {
    "rgb": "gbr", "bt709": "bt709", "fcc": "fcc", "bt470bg": "bt470bg",
    "smpte170m": "smpte170m", "smpte240m": "smpte240m", "ycgco": "ycgco",
    "bt2020nc": "bt2020nc", "bt2020c": "bt2020c",
}


def load_processing_dependencies() -> None:
    """Load heavy video/model packages only when a new video must be encoded."""
    global cv2, np, Image, tqdm

    import cv2 as cv2_module
    import numpy as numpy_module
    from PIL import Image as image_class
    from tqdm import tqdm as tqdm_function

    cv2 = cv2_module
    np = numpy_module
    Image = image_class
    tqdm = tqdm_function


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    fps: float
    fps_expr: str
    r_fps_expr: str
    width: int
    height: int
    bit_depth: int
    video_bitrate: int | None
    has_audio: bool
    has_subtitles: bool
    color_range: str | None
    color_space: str | None
    color_transfer: str | None
    color_primaries: str | None
    chroma_location: str | None


@dataclass
class StageTimings:
    read_decode: float = 0.0
    model_prep: float = 0.0
    depth_inference: float = 0.0
    depth_postprocess: float = 0.0
    stereo_synthesis: float = 0.0
    encoder_write: float = 0.0
    encoder_drain: float = 0.0
    work_limit: float = 0.0
    frames: int = 0

    def accounted(self) -> float:
        return (
            self.read_decode
            + self.model_prep
            + self.depth_inference
            + self.depth_postprocess
            + self.stereo_synthesis
            + self.encoder_write
            + self.encoder_drain
            + self.work_limit
        )


@dataclass
class DepthScaleStabilizer:
    """Stabilize per-frame depth range without blending moving silhouettes."""

    response: float
    scene_cut_threshold: float
    low: float | None = None
    high: float | None = None
    previous_preview: np.ndarray | None = None

    def range_for(self, depth: np.ndarray, frame_bgr: np.ndarray) -> tuple[float, float]:
        finite = depth[np.isfinite(depth)]
        if finite.size == 0:
            raise RuntimeError("Depth model returned no finite values")
        current_low, current_high = np.percentile(finite, (1.0, 99.0))

        preview = cv2.resize(frame_bgr, (64, 36), interpolation=cv2.INTER_AREA)
        preview = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY).astype(np.float32)
        preview *= 1.0 / np.iinfo(frame_bgr.dtype).max
        scene_cut = self.previous_preview is not None and float(
            np.mean(np.abs(preview - self.previous_preview))
        ) >= self.scene_cut_threshold

        stored_range_is_flat = self.low is not None and self.high is not None and self.high <= self.low
        if self.low is None or self.high is None or scene_cut or stored_range_is_flat:
            self.low = float(current_low)
            self.high = float(current_high)
        else:
            keep = 1.0 - self.response
            self.low = keep * self.low + self.response * float(current_low)
            self.high = keep * self.high + self.response * float(current_high)
        self.previous_preview = preview
        return self.low, self.high


def timing_report(timings: StageTimings, elapsed: float) -> str:
    if timings.frames <= 0:
        return "[TIMING] frames=0"

    accounted = timings.accounted()
    fps = timings.frames / elapsed if elapsed > 0 else 0.0
    stages = (
        ("read/decode", timings.read_decode),
        ("model-prep", timings.model_prep),
        ("depth", timings.depth_inference),
        ("depth-post", timings.depth_postprocess),
        ("stereo-cpu", timings.stereo_synthesis),
        ("encode-write", timings.encoder_write),
        ("encoder-drain", timings.encoder_drain),
        ("work-limit", timings.work_limit),
    )

    parts = [
        f"frames={timings.frames}",
        f"elapsed={elapsed:.1f}s",
        f"overall={fps:.2f} fps",
    ]
    stage_parts = []
    for name, total in stages:
        avg_ms = total * 1000.0 / timings.frames
        share = total * 100.0 / accounted if accounted > 0 else 0.0
        stage_parts.append(f"{name}={avg_ms:.1f}ms ({share:.0f}%)")

    untracked = max(0.0, elapsed - accounted)
    if untracked > 0:
        avg_ms = untracked * 1000.0 / timings.frames
        stage_parts.append(f"other={avg_ms:.1f}ms")

    return "[TIMING] " + ", ".join(parts) + " | " + "; ".join(stage_parts)


def format_duration(seconds: float) -> str:
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()


def ffprobe_json(input_path: Path) -> dict:
    raw = capture([
        "ffprobe",
        "-v", "error",
        "-print_format", "json",
        "-show_streams",
        "-show_format",
        str(input_path),
    ])
    return json.loads(raw)


def first_valid_frame_rate(*values: str | None) -> tuple[float, str]:
    for value in values:
        if not value:
            continue
        try:
            return normalize_frame_rate(value, option_name="source frame rate")
        except ValueError:
            continue
    raise ValueError("Input video does not contain a valid frame rate")


def infer_bit_depth(video_stream: dict) -> int:
    raw_depth = str(video_stream.get("bits_per_raw_sample") or "").strip()
    if raw_depth.isdigit() and int(raw_depth) > 0:
        return int(raw_depth)
    pix_fmt = str(video_stream.get("pix_fmt") or "")
    for depth in (16, 14, 12, 10, 9):
        if str(depth) in pix_fmt:
            return depth
    return 8


def parse_video_bitrate(video_stream: dict) -> int | None:
    candidates = [
        video_stream.get("bit_rate"),
        video_stream.get("tags", {}).get("BPS"),
        video_stream.get("tags", {}).get("BPS-eng"),
    ]
    for value in candidates:
        try:
            bitrate = int(value)
        except (TypeError, ValueError):
            continue
        if bitrate > 0:
            return bitrate
    return None


def clean_color_value(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return None if normalized in UNKNOWN_COLOR_VALUES else normalized


def video_info(input_path: Path) -> VideoInfo:
    data = ffprobe_json(input_path)
    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    fps, fps_expr = first_valid_frame_rate(
        video_stream.get("avg_frame_rate"),
        video_stream.get("r_frame_rate"),
    )
    _, r_fps_expr = first_valid_frame_rate(
        video_stream.get("r_frame_rate"),
        video_stream.get("avg_frame_rate"),
    )
    duration = float(video_stream.get("duration") or data.get("format", {}).get("duration") or 0)
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    has_subtitles = any(s["codec_type"] == "subtitle" for s in data["streams"])
    return VideoInfo(
        duration=duration,
        fps=fps,
        fps_expr=fps_expr,
        r_fps_expr=r_fps_expr,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        bit_depth=infer_bit_depth(video_stream),
        video_bitrate=parse_video_bitrate(video_stream),
        has_audio=has_audio,
        has_subtitles=has_subtitles,
        color_range=clean_color_value(video_stream.get("color_range")),
        color_space=clean_color_value(video_stream.get("color_space")),
        color_transfer=clean_color_value(video_stream.get("color_transfer")),
        color_primaries=clean_color_value(video_stream.get("color_primaries")),
        chroma_location=clean_color_value(video_stream.get("chroma_location")),
    )


def normalize_frame_rate(value: str, *, option_name: str) -> tuple[float, str]:
    """Validate a frame-rate expression and return a stable FFmpeg value."""
    try:
        rate = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{option_name} must be a positive FPS value, got: {value!r}") from exc
    if rate <= 0:
        raise ValueError(f"{option_name} must be positive, got: {value!r}")
    return float(rate), f"{rate.numerator}/{rate.denominator}"


def output_frame_rate(source_fps_expr: str, requested_fps: str) -> tuple[float, str]:
    requested = requested_fps.strip().lower()
    if requested in AUTO_VALUES:
        return normalize_frame_rate(source_fps_expr, option_name="source frame rate")
    return normalize_frame_rate(requested_fps, option_name="--output-fps")


def output_dimension(source: int, requested: str, *, option_name: str) -> int:
    normalized = requested.strip().lower()
    if normalized in AUTO_VALUES:
        value = source
    else:
        try:
            value = int(requested)
        except ValueError as exc:
            raise ValueError(f"{option_name} must be a positive even integer or source, got: {requested!r}") from exc
    if value <= 0 or value % 2:
        raise ValueError(f"{option_name} must be a positive even integer, got: {value}")
    return value


def normalize_stereo_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in DISABLED_STEREO_METADATA_VALUES:
        return None
    if normalized not in MATROSKA_STEREO_MODES:
        valid = ", ".join(sorted(MATROSKA_STEREO_MODES))
        raise ValueError(f"--stereo-mode must be empty/off/none or one of: {valid}")
    return normalized


def color_metadata_args(info: VideoInfo) -> list[str]:
    args: list[str] = []
    for option, value in (
        ("-color_range", info.color_range),
        ("-colorspace", info.color_space),
        ("-color_trc", info.color_transfer),
        ("-color_primaries", info.color_primaries),
        ("-chroma_sample_location", info.chroma_location),
    ):
        if value:
            args += [option, value]
    return args


def x265_color_params(info: VideoInfo) -> list[str]:
    """Return H.265 bitstream color-description parameters understood by x265."""
    params: list[str] = []
    primaries = X265_COLOR_PRIMARIES.get(info.color_primaries or "")
    transfer = X265_COLOR_TRANSFERS.get(info.color_transfer or "")
    matrix = X265_COLOR_MATRICES.get(info.color_space or "")
    if primaries:
        params.append(f"colorprim={primaries}")
    if transfer:
        params.append(f"transfer={transfer}")
    if matrix:
        params.append(f"colormatrix={matrix}")
    if info.color_range in {"tv", "pc"}:
        params.append(f"range={'full' if info.color_range == 'pc' else 'limited'}")
    return params


def resolve_video_bitrate(requested: str, source_info: VideoInfo, multiplier: float) -> str:
    normalized = requested.strip().lower()
    if normalized in {"source", "input"}:
        if source_info.video_bitrate is None:
            return ""
        return f"{max(1, round(source_info.video_bitrate * multiplier / 1000))}k"
    if normalized in {"", "auto", "crf", "quality"}:
        return ""
    return requested.strip()


def dedupe_x265_options(options: list[str]) -> list[str]:
    """Keep the last value for each x265 key, matching x265's override behavior."""
    positions: dict[str, int] = {}
    resolved: list[str | None] = []
    for option in options:
        key = option.split("=", 1)[0].strip()
        if not key:
            continue
        if key in positions:
            resolved[positions[key]] = None
        positions[key] = len(resolved)
        resolved.append(option)
    return [option for option in resolved if option is not None]


def depth_array(result: dict) -> np.ndarray:
    depth = result.get("predicted_depth", result.get("depth"))
    if depth is None:
        raise RuntimeError("Depth model returned neither predicted_depth nor depth")
    if hasattr(depth, "detach"):
        depth = depth.detach().float().cpu().numpy()

    arr = np.asarray(depth, dtype=np.float32).squeeze()
    if arr.ndim == 3:
        arr = arr[0]
    if arr.ndim != 2:
        raise RuntimeError(f"Unexpected depth result shape: {arr.shape}")
    return arr


def normalize_depth(
    result: dict,
    width: int,
    height: int,
    gamma: float,
    scale_range: tuple[float, float] | None = None,
) -> np.ndarray:
    """Convert the model's full-precision prediction into a stable 0..1 map."""
    arr = depth_array(result)

    if scale_range is None:
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            raise RuntimeError("Depth model returned no finite values")
        low, high = np.percentile(finite, (1.0, 99.0))
    else:
        low, high = scale_range
    if high > low:
        arr = np.clip((arr - low) / (high - low), 0.0, 1.0)
    else:
        arr = np.zeros_like(arr)
    if not np.all(np.isfinite(arr)):
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)

    if arr.shape != (height, width):
        arr = cv2.resize(arr, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.power(arr, gamma).astype(np.float32, copy=False)


def refine_depth_edges(
    depth01: np.ndarray,
    guide_bgr: np.ndarray,
    radius: int,
    epsilon: float,
) -> np.ndarray:
    """Align broad depth transitions with strong image edges using a guided filter."""
    if radius <= 0:
        return depth01

    guide = cv2.cvtColor(guide_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    guide *= 1.0 / np.iinfo(guide_bgr.dtype).max
    depth = depth01.astype(np.float32, copy=False)
    kernel = (radius * 2 + 1, radius * 2 + 1)

    def mean(image: np.ndarray) -> np.ndarray:
        return cv2.boxFilter(
            image,
            ddepth=-1,
            ksize=kernel,
            normalize=True,
            borderType=cv2.BORDER_REFLECT,
        )

    mean_guide = mean(guide)
    mean_depth = mean(depth)
    variance = mean(guide * guide) - mean_guide * mean_guide
    covariance = mean(guide * depth) - mean_guide * mean_depth
    coefficient = covariance / (variance + epsilon)
    intercept = mean_depth - coefficient * mean_guide
    refined = mean(coefficient) * guide + mean(intercept)
    return np.clip(refined, 0.0, 1.0).astype(np.float32, copy=False)


@lru_cache(maxsize=8)
def stereo_coordinate_maps(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.tile(np.arange(width, dtype=np.float32), (height, 1))
    y = np.repeat(np.arange(height, dtype=np.float32)[:, None], width, axis=1)
    return x, y


def disparity_edge_mask(
    disparity: np.ndarray,
    threshold: float,
    feather_width: int,
) -> np.ndarray:
    """Soft mask for high-disparity edges where synthesized-eye tearing is most visible."""
    grad_x = cv2.Sobel(disparity, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(disparity, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.magnitude(grad_x, grad_y)
    mask = np.clip((magnitude - threshold) / max(threshold, 1e-6), 0.0, 1.0)
    if feather_width > 0:
        kernel_size = feather_width * 2 + 1
        kernel = np.ones((kernel_size, kernel_size), dtype=np.uint8)
        mask = cv2.dilate(mask, kernel)
        mask = cv2.GaussianBlur(mask, (kernel_size, kernel_size), 0)
    return mask[..., None].astype(np.float32, copy=False)


def blend_with_anchor(warped: np.ndarray, anchor: np.ndarray, mask: np.ndarray, strength: float) -> np.ndarray:
    alpha = np.clip(mask * strength, 0.0, 1.0)
    if not np.any(alpha > 0):
        return warped

    blended = warped.astype(np.float32) * (1.0 - alpha) + anchor.astype(np.float32) * alpha
    if np.issubdtype(warped.dtype, np.integer):
        info = np.iinfo(warped.dtype)
        blended = np.clip(blended, info.min, info.max)
    return blended.astype(warped.dtype, copy=False)


def make_stereo_half_sbs(
    frame_bgr: np.ndarray,
    depth01: np.ndarray,
    output_width: int,
    output_height: int,
    max_disparity: float,
    convergence: float,
    depth_edge_radius: int,
    depth_edge_epsilon: float,
    stereo_warp_mode: str,
    occlusion_edge_blend: float,
    occlusion_edge_width: int,
    occlusion_edge_threshold: float,
) -> np.ndarray:
    eye_width = output_width // 2
    eye_height = output_height

    if frame_bgr.shape[1] == eye_width and frame_bgr.shape[0] == eye_height:
        src = frame_bgr
    else:
        shrinking = frame_bgr.shape[1] >= eye_width and frame_bgr.shape[0] >= eye_height
        interpolation = cv2.INTER_AREA if shrinking else cv2.INTER_LANCZOS4
        src = cv2.resize(frame_bgr, (eye_width, eye_height), interpolation=interpolation)
    if depth01.shape == (eye_height, eye_width):
        depth = depth01.astype(np.float32, copy=False)
    else:
        depth = cv2.resize(depth01, (eye_width, eye_height), interpolation=cv2.INTER_LINEAR)
    depth = refine_depth_edges(depth, src, depth_edge_radius, depth_edge_epsilon)

    # Positive near disparity, negative far disparity around convergence plane.
    disparity = (depth - convergence) * max_disparity
    h, w = depth.shape
    x, y = stereo_coordinate_maps(w, h)

    if stereo_warp_mode == "anchored":
        left_map_x = x
        right_map_x = x - disparity
    else:
        left_map_x = x + disparity / 2.0
        right_map_x = x - disparity / 2.0

    # Linear sampling avoids the overshoot/ringing that cubic remapping creates
    # around high-contrast silhouettes while retaining subpixel antialiasing
    # for fur, hair, diagonal edges, and thin limbs.
    left = cv2.remap(src, left_map_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    right = cv2.remap(src, right_map_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if occlusion_edge_blend > 0.0 and occlusion_edge_width > 0:
        mask = disparity_edge_mask(disparity, occlusion_edge_threshold, occlusion_edge_width)
        if stereo_warp_mode == "anchored":
            right = blend_with_anchor(right, src, mask, occlusion_edge_blend)
        else:
            left = blend_with_anchor(left, src, mask, occlusion_edge_blend)
            right = blend_with_anchor(right, src, mask, occlusion_edge_blend)
    return np.ascontiguousarray(np.concatenate([left, right], axis=1))


class DepthBatchRunner:
    def __init__(self, model_name: str, device: str):
        os.environ.setdefault("TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL", "1")

        import torch
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation

        hip_version = getattr(torch.version, "hip", None)
        cuda_version = getattr(torch.version, "cuda", None)

        if device == "cuda" and torch.cuda.is_available():
            self.device = torch.device("cuda:0")
            self.dtype = torch.float16
            print(f"[INFO] Depth backend   : GPU ({torch.cuda.get_device_name(0)})", flush=True)
        elif device == "cuda":
            print(
                f"[WARN] Requested cuda/ROCm, but torch.cuda.is_available() is false. "
                f"torch={torch.__version__}, hip={hip_version}, cuda={cuda_version}. Falling back to CPU.",
                flush=True,
            )
            self.device = torch.device("cpu")
            self.dtype = torch.float32
        else:
            print("[INFO] Depth backend   : CPU", flush=True)
            self.device = torch.device("cpu")
            self.dtype = torch.float32

        self.torch = torch
        self.image_processor = AutoImageProcessor.from_pretrained(model_name)
        self.model = AutoModelForDepthEstimation.from_pretrained(model_name, dtype=self.dtype)
        self.model.to(self.device)
        self.model.eval()

    def infer_batch(self, images: list, target_size: tuple[int, int] | None = None) -> list[dict]:
        inputs = self.image_processor(images=images, return_tensors="pt")
        inputs = inputs.to(device=self.device, dtype=self.dtype)
        if target_size is None:
            target_sizes = [image.size[::-1] for image in images]
        else:
            target_sizes = [target_size] * len(images)
        with self.torch.inference_mode():
            outputs = self.model(**inputs)
        return self.image_processor.post_process_depth_estimation(outputs, target_sizes)

    def __call__(self, images):
        if isinstance(images, list):
            results = self.infer_batch(images)
            return results
        return self.infer_batch([images])[0]


def infer_depth_batch(depth_pipe, images: list, target_size: tuple[int, int] | None = None) -> list[dict]:
    results = depth_pipe.infer_batch(images, target_size=target_size)
    return list(results)


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            # A concurrently removed temporary file is harmless here.
            continue
    return total


def enforce_work_limit(work_dir: Path, max_work_bytes: int) -> None:
    if max_work_bytes <= 0:
        return
    used = directory_size(work_dir)
    if used > max_work_bytes:
        raise RuntimeError(
            f"Work directory exceeded its limit: {used / 1024**3:.2f} GiB "
            f"> {max_work_bytes / 1024**3:.2f} GiB"
        )


def read_exact_frame(stream: BinaryIO, buffer: bytearray) -> bool:
    view = memoryview(buffer)
    offset = 0
    while offset < len(buffer):
        count = stream.readinto(view[offset:])
        if not count:
            break
        offset += count
    if offset == 0:
        return False
    if offset != len(buffer):
        raise RuntimeError(f"Decoder returned an incomplete frame: {offset}/{len(buffer)} bytes")
    return True


def write_all(stream: BinaryIO, data: memoryview) -> None:
    offset = 0
    while offset < len(data):
        count = stream.write(data[offset:])
        if not count:
            raise BrokenPipeError("Encoder accepted zero bytes")
        offset += count


class AsyncEncoderWriter:
    """Keep frame generation from idling while x265 drains its input pipe."""

    def __init__(self, encoder: subprocess.Popen, queue_frames: int) -> None:
        if encoder.stdin is None:
            raise RuntimeError("Encoder stdin is not available")
        self.encoder = encoder
        self.stdin = encoder.stdin
        self.frames: queue.Queue[object] = queue.Queue(maxsize=max(1, queue_frames))
        self.sentinel = object()
        self.error: BaseException | None = None
        self.thread = threading.Thread(target=self._run, name="x265-stdin-writer", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        try:
            while True:
                item = self.frames.get()
                if item is self.sentinel:
                    return
                write_all(self.stdin, memoryview(item).cast("B"))
        except BaseException as exc:
            self.error = exc

    def _raise_if_failed(self) -> None:
        if self.error is not None:
            code = self.encoder.poll()
            raise RuntimeError(f"H.265 encoder closed its input early with code {code}") from self.error

    def submit(self, frame: np.ndarray) -> float:
        started = time.monotonic()
        while True:
            self._raise_if_failed()
            if self.encoder.poll() is not None:
                raise RuntimeError(f"H.265 encoder exited early with code {self.encoder.returncode}")
            try:
                self.frames.put(frame, timeout=0.25)
                return time.monotonic() - started
            except queue.Full:
                continue

    def finish(self) -> None:
        while True:
            self._raise_if_failed()
            try:
                self.frames.put(self.sentinel, timeout=0.25)
                break
            except queue.Full:
                continue
        self.thread.join()
        self._raise_if_failed()

    def join_after_abort(self, timeout: float = 2.0) -> None:
        if self.thread.is_alive():
            try:
                self.frames.put_nowait(self.sentinel)
            except queue.Full:
                pass
            self.thread.join(timeout=timeout)


def close_pipe(stream: BinaryIO | None) -> None:
    if stream is None or stream.closed:
        return
    try:
        stream.close()
    except OSError:
        # The original encoder/decoder error is more useful than a close error.
        pass


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def mux_source_streams(
    *,
    video_only: Path,
    input_video: Path,
    partial_output: Path,
    source_info: VideoInfo,
    test_seconds: str,
    audio_codec: str,
    audio_bitrate: str,
    audio_channels: int,
) -> None:
    """Mux source streams only after the slow video encode has completed."""
    cmd = [
        "ffmpeg", "-y", "-v", "warning",
        "-i", str(video_only),
        "-i", str(input_video),
        "-map", "0:v:0",
        "-map", "1:a?",
        "-map", "1:s?",
        "-map", "1:t?",
        "-map_metadata", "1",
        "-map_chapters", "1",
        "-c:v", "copy",
    ]
    if source_info.has_audio:
        if audio_codec.lower() == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_codec]
            if audio_bitrate:
                cmd += ["-b:a", audio_bitrate]
            if audio_channels > 0:
                cmd += ["-ac", str(audio_channels)]
    if source_info.has_subtitles:
        cmd += ["-c:s", "copy"]
    cmd += ["-c:t", "copy"]
    if test_seconds:
        cmd += ["-t", test_seconds]
    cmd += [str(partial_output)]

    print("[STEP] Mux source audio, subtitles, chapters, and attachments", flush=True)
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def audio_packet_counts(path: Path) -> list[int]:
    data = json.loads(capture([
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-count_packets",
        "-show_entries", "stream=nb_read_packets",
        "-of", "json",
        str(path),
    ]))
    counts: list[int] = []
    for stream in data.get("streams", []):
        value = stream.get("nb_read_packets")
        if value in (None, "N/A"):
            raise RuntimeError(f"Could not count audio packets in {path}")
        counts.append(int(value))
    return counts


def verify_copied_audio(input_video: Path, output_video: Path) -> None:
    """Reject a completed file if any copied audio packets disappeared."""
    print("[STEP] Verify copied audio packet counts", flush=True)
    source_counts = audio_packet_counts(input_video)
    output_counts = audio_packet_counts(output_video)
    if not source_counts:
        raise RuntimeError(f"Input was reported to contain audio but no audio packets were found: {input_video}")
    if source_counts != output_counts:
        raise RuntimeError(
            "Copied audio verification failed: "
            f"source packets={source_counts}, output packets={output_counts}"
        )
    print(f"[INFO] Audio verified : {output_counts}", flush=True)


def reusable_video_only(path: Path, expected_duration: float, fps: float) -> bool:
    """Return true only for a finalized video-only file of the expected length."""
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        data = ffprobe_json(path)
        video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
        duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    except (KeyError, StopIteration, TypeError, ValueError, subprocess.CalledProcessError):
        return False
    tolerance = max(0.25, 2.0 / fps)
    return expected_duration > 0 and abs(duration - expected_duration) <= tolerance


def stream_convert(
    *,
    input_video: Path,
    partial_output: Path,
    work_dir: Path,
    depth_pipe,
    source_info: VideoInfo,
    fps: float,
    fps_expr: str,
    fps_is_source: bool,
    output_width: int,
    output_height: int,
    max_disparity: float,
    depth_gamma: float,
    convergence: float,
    depth_edge_radius: int,
    depth_edge_epsilon: float,
    occlusion_edge_blend: float,
    occlusion_edge_width: int,
    occlusion_edge_threshold: float,
    depth_temporal_response: float,
    depth_batch_frames: int,
    scene_cut_threshold: float,
    stereo_warp_mode: str,
    test_seconds: str,
    stereo_mode: str | None,
    video_codec: str,
    video_bitrate: str,
    rate_control: str,
    crf: int,
    preset: str,
    x265_params: str,
    threads: int,
    encoder_queue_frames: int,
    max_work_bytes: int,
) -> int:
    eye_width = output_width // 2
    # bgr48le keeps the source's 10-bit HDR precision through OpenCV's resize
    # and stereo remap. The model alone receives a derived 8-bit preview.
    # The model must see the source at its normal aspect ratio. Feeding the
    # already-squeezed Half-SBS eye view makes people and animals unnaturally
    # narrow and produces inaccurate depth around their silhouettes.
    frame_bytes = output_width * output_height * 3 * 2
    partial_output.parent.mkdir(parents=True, exist_ok=True)

    decoder_cmd = [
        "ffmpeg", "-v", "warning",
        "-i", str(input_video),
    ]
    if test_seconds:
        decoder_cmd += ["-t", test_seconds]
    decoder_cmd += [
        "-map", "0:v:0",
        "-an", "-sn", "-dn",
        "-vf", f"scale={output_width}:{output_height}:flags=lanczos+accurate_rnd+full_chroma_int",
    ]
    if not fps_is_source:
        decoder_cmd += ["-r", fps_expr, "-fps_mode", "cfr"]
    decoder_cmd += [
        "-f", "rawvideo",
        "-pix_fmt", "bgr48le",
        "pipe:1",
    ]

    encoder_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr48le",
        "-s:v", f"{output_width}x{output_height}",
        "-framerate", fps_expr,
        "-i", "pipe:0",
    ]
    encoder_cmd += [
        "-map", "0:v:0",
    ]
    if test_seconds:
        encoder_cmd += ["-t", test_seconds]

    x265_options = [
        "aq-mode=3",
        "aq-strength=0.8",
        "psy-rd=2.0",
        "psy-rdoq=1.0",
        "strong-intra-smoothing=0",
        "repeat-headers=1",
    ]
    x265_options += x265_color_params(source_info)
    if x265_params:
        x265_options += [option for option in x265_params.split(":") if option]
    x265_options = dedupe_x265_options(x265_options)

    encoder_cmd += [
        "-c:v", video_codec,
        "-pix_fmt", "yuv420p10le",
        "-preset", preset,
        "-x265-params", ":".join(x265_options),
    ]
    if stereo_mode:
        # Matroska StereoMode auto-detection is useful for some TVs, but some
        # software players flatten it during normal playback.
        encoder_cmd += ["-metadata:s:v:0", f"stereo_mode={stereo_mode}"]
    encoder_cmd += color_metadata_args(source_info)
    if video_bitrate:
        encoder_cmd += ["-b:v", video_bitrate]
        if rate_control == "cbr":
            encoder_cmd += ["-maxrate", video_bitrate, "-bufsize", video_bitrate]
    else:
        encoder_cmd += ["-crf", str(crf)]
    if threads > 0:
        encoder_cmd += ["-threads", str(threads)]
    encoder_cmd += ["-progress", "pipe:2", "-nostats", str(partial_output)]

    print("[STEP] Start streaming decoder", flush=True)
    print("+", " ".join(decoder_cmd), flush=True)
    print("[STEP] Start streaming H.265/HEVC encoder", flush=True)
    print("+", " ".join(encoder_cmd), flush=True)

    decoder: subprocess.Popen | None = None
    encoder: subprocess.Popen | None = None
    encoder_writer: AsyncEncoderWriter | None = None
    progress = None
    completed = False
    frame_count = 0
    timings = StageTimings()
    timing_interval = 300
    conversion_started = time.monotonic()
    depth_stabilizer = DepthScaleStabilizer(
        response=depth_temporal_response,
        scene_cut_threshold=scene_cut_threshold,
    )
    try:
        encoder = subprocess.Popen(encoder_cmd, stdin=subprocess.PIPE)
        decoder = subprocess.Popen(decoder_cmd, stdout=subprocess.PIPE)
        assert decoder.stdout is not None
        assert encoder.stdin is not None
        encoder_writer = AsyncEncoderWriter(encoder, queue_frames=encoder_queue_frames)
        encoder_writer.start()

        effective_duration = min(source_info.duration, float(test_seconds)) if test_seconds else source_info.duration
        expected_frames = math.ceil(effective_duration * fps) if effective_duration > 0 else None
        progress = tqdm(total=expected_frames, desc="2D->3D->H.265", unit="frame")
        frame_buffers = [bytearray(frame_bytes) for _ in range(depth_batch_frames)]

        while True:
            batch_frames = []
            batch_images = []
            reached_end = False

            for frame_buffer in frame_buffers:
                stage_started = time.monotonic()
                has_frame = read_exact_frame(decoder.stdout, frame_buffer)
                timings.read_decode += time.monotonic() - stage_started
                if not has_frame:
                    reached_end = True
                    break

                if encoder.poll() is not None:
                    raise RuntimeError(f"H.265 encoder exited early with code {encoder.returncode}")

                stage_started = time.monotonic()
                frame_bgr = np.frombuffer(frame_buffer, dtype="<u2").reshape(output_height, output_width, 3)
                model_bgr = np.right_shift(frame_bgr, 8).astype(np.uint8)
                frame_rgb = cv2.cvtColor(model_bgr, cv2.COLOR_BGR2RGB)
                batch_frames.append(frame_bgr)
                batch_images.append(Image.fromarray(frame_rgb))
                timings.model_prep += time.monotonic() - stage_started

            if not batch_frames:
                break

            stage_started = time.monotonic()
            results = infer_depth_batch(depth_pipe, batch_images, target_size=(output_height, eye_width))
            timings.depth_inference += time.monotonic() - stage_started
            if len(results) != len(batch_frames):
                raise RuntimeError(f"Depth model returned {len(results)} results for {len(batch_frames)} frames")

            for frame_bgr, result in zip(batch_frames, results, strict=True):
                stage_started = time.monotonic()
                raw_depth = depth_array(result)
                scale_range = depth_stabilizer.range_for(raw_depth, frame_bgr)
                depth01 = normalize_depth(
                    {"predicted_depth": raw_depth},
                    eye_width,
                    output_height,
                    depth_gamma,
                    scale_range,
                )
                timings.depth_postprocess += time.monotonic() - stage_started

                stage_started = time.monotonic()
                hsbs = make_stereo_half_sbs(
                    frame_bgr,
                    depth01,
                    output_width,
                    output_height,
                    max_disparity,
                    convergence,
                    depth_edge_radius,
                    depth_edge_epsilon,
                    stereo_warp_mode,
                    occlusion_edge_blend,
                    occlusion_edge_width,
                    occlusion_edge_threshold,
                )
                timings.stereo_synthesis += time.monotonic() - stage_started

                timings.encoder_write += encoder_writer.submit(hsbs)

                frame_count += 1
                timings.frames = frame_count
                progress.update(1)
                if frame_count % 100 == 0:
                    stage_started = time.monotonic()
                    enforce_work_limit(work_dir, max_work_bytes)
                    timings.work_limit += time.monotonic() - stage_started
                if frame_count % timing_interval == 0:
                    print(
                        timing_report(timings, time.monotonic() - conversion_started),
                        flush=True,
                    )

            if reached_end:
                break

        decoder.stdout.close()
        decoder_code = decoder.wait()
        if decoder_code != 0:
            raise subprocess.CalledProcessError(decoder_code, decoder_cmd)
        if frame_count == 0:
            raise RuntimeError("Decoder produced no video frames")

        stage_started = time.monotonic()
        encoder_writer.finish()
        try:
            encoder.stdin.close()
        except BrokenPipeError as exc:
            code = encoder.wait()
            timings.encoder_drain += time.monotonic() - stage_started
            raise RuntimeError(f"H.265 encoder failed while finalizing with code {code}") from exc
        encoder_code = encoder.wait()
        timings.encoder_drain += time.monotonic() - stage_started
        if encoder_code != 0:
            raise subprocess.CalledProcessError(encoder_code, encoder_cmd)
        elapsed = time.monotonic() - conversion_started
        print(timing_report(timings, elapsed), flush=True)
        enforce_work_limit(work_dir, max_work_bytes)
        speed = effective_duration / elapsed if elapsed > 0 else 0.0
        print(
            f"[DONE] Movie elapsed: {format_duration(elapsed)} | "
            f"source: {format_duration(effective_duration)} | "
            f"speed: {speed:.2f}x real-time",
            flush=True,
        )
        completed = True
        return frame_count
    finally:
        if progress is not None:
            progress.close()
        if encoder_writer is not None and not completed:
            encoder_writer.join_after_abort()
        if decoder is not None:
            close_pipe(decoder.stdout)
        if encoder is not None:
            close_pipe(encoder.stdin)
        stop_process(decoder)
        stop_process(encoder)
        if not completed and partial_output.exists():
            partial_output.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", default="./work_2d_to_3d")
    parser.add_argument("--depth-model", default="depth-anything/Depth-Anything-V2-Small-hf")
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--output-width", default="source", help="Output canvas width, or source to avoid artificial upscaling")
    parser.add_argument("--output-height", default="source", help="Output canvas height, or source to avoid artificial upscaling")
    parser.add_argument("--max-disparity", type=float, default=28)
    parser.add_argument("--depth-gamma", type=float, default=1.25)
    parser.add_argument("--convergence", type=float, default=0.52)
    parser.add_argument("--depth-edge-radius", type=int, default=4, help="Guided-filter radius for cleaner foreground silhouettes; 0 disables it")
    parser.add_argument("--depth-edge-epsilon", type=float, default=0.001, help="Guided-filter edge sensitivity; lower follows image edges more closely")
    parser.add_argument("--occlusion-edge-blend", type=float, default=0.0, help="Blend synthesized eyes back toward the source around hard disparity edges; 0 disables it")
    parser.add_argument("--occlusion-edge-width", type=int, default=0, help="Feather radius in pixels for occlusion-edge protection")
    parser.add_argument("--occlusion-edge-threshold", type=float, default=1.0, help="Disparity-gradient threshold in pixels for occlusion-edge protection")
    parser.add_argument("--depth-temporal-response", type=float, default=0.12, help="Response of the depth-range stabilizer; 1 disables temporal smoothing")
    parser.add_argument("--depth-batch-frames", type=int, default=4, help="Frames batched per depth model call; 1 keeps fully sequential inference")
    parser.add_argument("--scene-cut-threshold", type=float, default=0.18, help="Mean preview difference that resets depth stabilization at a scene cut")
    parser.add_argument("--stereo-warp-mode", choices=["anchored", "symmetric"], default="anchored", help="Anchor one eye for maximum clarity, or warp both eyes symmetrically")
    parser.add_argument("--test-seconds", default="")
    parser.add_argument("--output-fps", default="source", help="Output FPS, or source to preserve the input rate")
    parser.add_argument("--stereo-mode", default="", help="Optional Matroska stereo_mode tag; empty/off/none disables it")
    parser.add_argument("--video-codec", default="libx265", choices=["libx265"])
    parser.add_argument("--video-bitrate", default="source", help="Target H.265 bitrate, source to match the input video rate, or auto for CRF")
    parser.add_argument("--source-bitrate-multiplier", type=float, default=1.0, help="Multiplier when --video-bitrate=source")
    parser.add_argument("--rate-control", default="vbr", choices=["vbr", "cbr"], help="H.265 rate-control mode when --video-bitrate is set")
    parser.add_argument("--crf", type=int, default=16, help="H.265 constant-quality fallback; lower is higher quality")
    parser.add_argument("--preset", default="slow", help="x265 preset, for example medium, slow, or slower")
    parser.add_argument("--x265-params", default="", help="Additional colon-separated x265 options")
    parser.add_argument("--audio-codec", default="libopus")
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--audio-channels", type=int, default=2, help="Audio channel count for re-encoding; 0 preserves source layout")
    parser.add_argument("--remux-existing", action="store_true", help="Keep the existing 3D video and replace its audio/subtitle streams from the source")
    parser.add_argument("--ffmpeg-threads", type=int, default=0)
    parser.add_argument("--encoder-queue-frames", type=int, default=2, help="Frames buffered between stereo generation and x265 stdin")
    parser.add_argument("--max-work-gb", type=float, default=200.0, help="Maximum files allowed in the work directory; 0 disables the guard")
    parser.add_argument("--frame-ext", default="png", help=argparse.SUPPRESS)
    args = parser.parse_args()

    input_video = Path(args.input).expanduser().resolve()
    output_video = Path(args.output).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()

    if not input_video.is_file():
        raise FileNotFoundError(f"Input video not found: {input_video}")

    source_info = video_info(input_video)
    if args.remux_existing:
        if not output_video.is_file() or output_video.stat().st_size <= 0:
            raise FileNotFoundError(f"Existing output to remux was not found: {output_video}")
        if args.test_seconds:
            raise ValueError("--remux-existing cannot be combined with --test-seconds")
        output_suffix = output_video.suffix or ".mkv"
        repaired_output = output_video.with_name(f"{output_video.stem}.audio-repair.part{output_suffix}")
        if repaired_output.exists():
            repaired_output.unlink()
        repaired = False
        try:
            mux_source_streams(
                video_only=output_video,
                input_video=input_video,
                partial_output=repaired_output,
                source_info=source_info,
                test_seconds="",
                audio_codec=args.audio_codec,
                audio_bitrate=args.audio_bitrate,
                audio_channels=args.audio_channels,
            )
            if source_info.has_audio and args.audio_codec.lower() == "copy":
                verify_copied_audio(input_video, repaired_output)
            os.replace(repaired_output, output_video)
            repaired = True
        finally:
            if repaired_output.exists():
                repaired_output.unlink()
        if repaired:
            print(f"[DONE] Repaired source streams: {output_video}", flush=True)
        return 0

    if args.max_work_gb < 0:
        raise ValueError("max-work-gb cannot be negative")
    if args.encoder_queue_frames < 1:
        raise ValueError("encoder-queue-frames must be at least 1")
    if not 0 <= args.crf <= 63:
        raise ValueError("crf must be between 0 and 63")
    if args.source_bitrate_multiplier <= 0:
        raise ValueError("source-bitrate-multiplier must be positive")
    if args.max_disparity < 0:
        raise ValueError("max-disparity cannot be negative")
    if args.depth_gamma <= 0:
        raise ValueError("depth-gamma must be positive")
    if not 0 <= args.convergence <= 1:
        raise ValueError("convergence must be between 0 and 1")
    if args.depth_edge_radius < 0:
        raise ValueError("depth-edge-radius cannot be negative")
    if args.depth_edge_epsilon <= 0:
        raise ValueError("depth-edge-epsilon must be positive")
    if not 0 <= args.occlusion_edge_blend <= 1:
        raise ValueError("occlusion-edge-blend must be between 0 and 1")
    if args.occlusion_edge_width < 0:
        raise ValueError("occlusion-edge-width cannot be negative")
    if args.occlusion_edge_threshold <= 0:
        raise ValueError("occlusion-edge-threshold must be positive")
    if not 0 < args.depth_temporal_response <= 1:
        raise ValueError("depth-temporal-response must be greater than 0 and at most 1")
    if args.depth_batch_frames < 1:
        raise ValueError("depth-batch-frames must be at least 1")
    if not 0 < args.scene_cut_threshold <= 1:
        raise ValueError("scene-cut-threshold must be greater than 0 and at most 1")

    output_width = output_dimension(source_info.width, args.output_width, option_name="--output-width")
    output_height = output_dimension(source_info.height, args.output_height, option_name="--output-height")
    fps, fps_expr = output_frame_rate(source_info.fps_expr, args.output_fps)
    fps_is_source = args.output_fps.strip().lower() in AUTO_VALUES
    stereo_mode = normalize_stereo_mode(args.stereo_mode)
    video_bitrate = resolve_video_bitrate(
        args.video_bitrate,
        source_info,
        args.source_bitrate_multiplier,
    )
    max_work_bytes = int(args.max_work_gb * 1024**3)
    source_bitrate_label = f"{source_info.video_bitrate / 1_000_000:.2f} Mbps" if source_info.video_bitrate else "unknown"
    color_label = "/".join(filter(None, [source_info.color_primaries, source_info.color_transfer, source_info.color_space])) or "unspecified"
    print(f"[INFO] Duration       : {source_info.duration:.2f}s")
    print(f"[INFO] Source video   : {source_info.width}x{source_info.height}, {source_info.bit_depth}-bit, {source_bitrate_label}")
    print(f"[INFO] Output canvas  : {output_width}x{output_height} Half-SBS")
    print(f"[INFO] Source FPS     : {source_info.fps_expr} ({source_info.fps:.6f})")
    print(f"[INFO] Output FPS     : {fps_expr} ({fps:.6f})")
    if fps_is_source and source_info.fps_expr != source_info.r_fps_expr:
        print("[WARN] Variable-frame-rate input detected; the streaming pipeline uses its average source rate.", flush=True)
    if output_width > source_info.width or output_height > source_info.height:
        print("[WARN] Output exceeds the source canvas and will upscale existing detail.", flush=True)
    print("[INFO] Stereo layout  : Half-SBS left/right")
    print(f"[INFO] Stereo metadata: {stereo_mode or 'disabled'}")
    print(f"[INFO] Edge refinement: radius {args.depth_edge_radius}, epsilon {args.depth_edge_epsilon:g}")
    if args.occlusion_edge_blend > 0 and args.occlusion_edge_width > 0:
        print(
            f"[INFO] Edge occlusion : blend {args.occlusion_edge_blend:g}, "
            f"width {args.occlusion_edge_width}px, threshold {args.occlusion_edge_threshold:g}px"
        )
    else:
        print("[INFO] Edge occlusion : disabled")
    print(f"[INFO] Depth stability: response {args.depth_temporal_response:g}, scene cut {args.scene_cut_threshold:g}")
    print(f"[INFO] Stereo warp   : {args.stereo_warp_mode}")
    print(f"[INFO] Depth batch   : {args.depth_batch_frames} frame(s)")
    print(f"[INFO] Depth target  : {output_width // 2}x{output_height} eye map")
    requested_rate = args.video_bitrate.strip().lower()
    if requested_rate in {"source", "input"} and video_bitrate:
        rate_label = f"{video_bitrate} ({args.rate_control}, source x{args.source_bitrate_multiplier:.2f})"
    else:
        rate_label = f"{video_bitrate} ({args.rate_control})" if video_bitrate else f"CRF {args.crf} (fallback)"
    print(f"[INFO] Video codec    : H.265/HEVC Main 10 ({args.video_codec})")
    print(f"[INFO] Encode quality : {rate_label}, preset {args.preset}")
    print(f"[INFO] Color/HDR      : {color_label}; internal bgr48le -> yuv420p10le")
    print(f"[INFO] Audio          : {'copy/preserve, post-mux verified' if source_info.has_audio and args.audio_codec.lower() == 'copy' else source_info.has_audio}")
    print(f"[INFO] Subtitles      : {'copy/preserve' if source_info.has_subtitles else False}")
    print("[INFO] Frame storage  : streaming (no extracted frame files)")
    print(f"[INFO] Encoder queue  : {args.encoder_queue_frames} frame(s)")
    print(f"[INFO] Work dir limit : {args.max_work_gb:.2f} GiB" if max_work_bytes else "[INFO] Work dir limit : disabled")

    work_dir.mkdir(parents=True, exist_ok=True)
    enforce_work_limit(work_dir, max_work_bytes)

    output_suffix = output_video.suffix or ".mkv"
    video_only = output_video.with_name(f"{output_video.stem}.video-only.part{output_suffix}")
    partial_output = output_video.with_name(f"{output_video.stem}.part{output_suffix}")
    effective_duration = min(source_info.duration, float(args.test_seconds)) if args.test_seconds else source_info.duration
    reuse_video_only = reusable_video_only(video_only, effective_duration, fps)
    if not reuse_video_only and reusable_video_only(partial_output, effective_duration, fps):
        print(f"[INFO] Recover complete legacy partial as video-only: {partial_output}", flush=True)
        os.replace(partial_output, video_only)
        reuse_video_only = True
    if video_only.exists() and not reuse_video_only:
        print(f"[WARN] Discard incomplete video-only file: {video_only}", flush=True)
        video_only.unlink()
    if partial_output.exists():
        partial_output.unlink()
    completed = False
    try:
        if reuse_video_only:
            print(f"[INFO] Reuse encoded video-only file: {video_only}", flush=True)
            frame_count = 0
        else:
            load_processing_dependencies()
            print("[STEP] Load depth model", flush=True)
            depth_pipe = DepthBatchRunner(args.depth_model, args.device)
            frame_count = stream_convert(
                input_video=input_video,
                partial_output=video_only,
                work_dir=work_dir,
                depth_pipe=depth_pipe,
                source_info=source_info,
                fps=fps,
                fps_expr=fps_expr,
                fps_is_source=fps_is_source,
                output_width=output_width,
                output_height=output_height,
                max_disparity=args.max_disparity,
                depth_gamma=args.depth_gamma,
                convergence=args.convergence,
                depth_edge_radius=args.depth_edge_radius,
                depth_edge_epsilon=args.depth_edge_epsilon,
                occlusion_edge_blend=args.occlusion_edge_blend,
                occlusion_edge_width=args.occlusion_edge_width,
                occlusion_edge_threshold=args.occlusion_edge_threshold,
                depth_temporal_response=args.depth_temporal_response,
                depth_batch_frames=args.depth_batch_frames,
                scene_cut_threshold=args.scene_cut_threshold,
                stereo_warp_mode=args.stereo_warp_mode,
                test_seconds=args.test_seconds,
                stereo_mode=stereo_mode,
                video_codec=args.video_codec,
                video_bitrate=video_bitrate,
                rate_control=args.rate_control,
                crf=args.crf,
                preset=args.preset,
                x265_params=args.x265_params,
                threads=args.ffmpeg_threads,
                encoder_queue_frames=args.encoder_queue_frames,
                max_work_bytes=max_work_bytes,
            )
        mux_source_streams(
            video_only=video_only,
            input_video=input_video,
            partial_output=partial_output,
            source_info=source_info,
            test_seconds=args.test_seconds,
            audio_codec=args.audio_codec,
            audio_bitrate=args.audio_bitrate,
            audio_channels=args.audio_channels,
        )
        if source_info.has_audio and args.audio_codec.lower() == "copy" and not args.test_seconds:
            verify_copied_audio(input_video, partial_output)
        os.replace(partial_output, output_video)
        completed = True
    finally:
        if completed and video_only.exists():
            video_only.unlink()
        if partial_output.exists():
            partial_output.unlink()
        if not completed and video_only.exists():
            print(f"[WARN] Preserved encoded video-only file for mux retry: {video_only}", flush=True)
    print(f"[DONE] {output_video}", flush=True)
    if frame_count:
        print(f"[INFO] Encoded frames: {frame_count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
