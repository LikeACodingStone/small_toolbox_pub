#!/usr/bin/env python3
"""Convert a 2D video to 4K Half-SBS 3D and encode with AV1.

This is a practical trial pipeline:
  1. ffmpeg extracts frames.
  2. Depth Anything estimates depth on GPU when available.
  3. OpenCV warps each frame into left/right views.
  4. ffmpeg encodes 3840x2160 Half-SBS with CPU SVT-AV1.

It is not a magic Hollywood stereo conversion tool, but it is a solid
one-command baseline for testing depth, parallax, compression, and throughput.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


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


def video_info(input_path: Path) -> tuple[float, str, bool]:
    data = ffprobe_json(input_path)
    video_stream = next(s for s in data["streams"] if s["codec_type"] == "video")
    fps_expr = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "24000/1001"
    if "/" in fps_expr:
        num, den = fps_expr.split("/", 1)
        fps = float(num) / float(den)
    else:
        fps = float(fps_expr)
    duration = float(video_stream.get("duration") or data.get("format", {}).get("duration") or 0)
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    return duration, fps_expr, has_audio


def list_frames(frame_dir: Path, ext: str) -> list[Path]:
    return sorted(frame_dir.glob(f"*.{ext}"))


def normalize_depth(depth: Image.Image, width: int, height: int, gamma: float) -> np.ndarray:
    arr = np.array(depth.resize((width, height), Image.Resampling.BICUBIC)).astype(np.float32)
    if arr.ndim == 3:
        arr = arr[..., 0]
    arr -= arr.min()
    max_val = arr.max()
    if max_val > 0:
        arr /= max_val
    arr = np.power(arr, gamma)
    return arr


def make_stereo_half_sbs(
    frame_bgr: np.ndarray,
    depth01: np.ndarray,
    output_width: int,
    output_height: int,
    max_disparity: float,
    convergence: float,
) -> np.ndarray:
    eye_width = output_width // 2
    eye_height = output_height

    src = cv2.resize(frame_bgr, (eye_width, eye_height), interpolation=cv2.INTER_LANCZOS4)
    depth = cv2.resize(depth01, (eye_width, eye_height), interpolation=cv2.INTER_CUBIC)

    # Positive near disparity, negative far disparity around convergence plane.
    disparity = (depth - convergence) * max_disparity
    h, w = depth.shape
    x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))

    left_map_x = x + disparity / 2.0
    right_map_x = x - disparity / 2.0
    map_y = y

    left = cv2.remap(src, left_map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    right = cv2.remap(src, right_map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.concatenate([left, right], axis=1)


def load_depth_pipeline(model_name: str, device: str):
    import torch
    from transformers import pipeline

    if device == "cuda" and not torch.cuda.is_available():
        print("[WARN] Requested cuda/ROCm, but torch.cuda.is_available() is false. Falling back to CPU.", flush=True)
        device_arg = -1
    elif device == "cpu":
        device_arg = -1
    else:
        device_arg = 0

    dtype = torch.float16 if device_arg == 0 else torch.float32
    return pipeline("depth-estimation", model=model_name, device=device_arg, torch_dtype=dtype)


def encode_av1(
    hsbs_dir: Path,
    input_video: Path,
    output_video: Path,
    fps_expr: str,
    has_audio: bool,
    crf: int,
    preset: int,
    audio_codec: str,
    audio_bitrate: str,
    audio_channels: int,
    threads: int,
    frame_ext: str,
) -> None:
    output_video.parent.mkdir(parents=True, exist_ok=True)
    input_pattern = str(hsbs_dir / f"%08d.{frame_ext}")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", fps_expr,
        "-i", input_pattern,
    ]
    if has_audio:
        cmd += ["-i", str(input_video), "-map", "0:v:0", "-map", "1:a:0?"]
    else:
        cmd += ["-map", "0:v:0"]

    cmd += [
        "-c:v", "libsvtav1",
        "-pix_fmt", "yuv420p10le",
        "-crf", str(crf),
        "-preset", str(preset),
        "-svtav1-params", "tune=0:film-grain=6",
    ]
    if threads > 0:
        cmd += ["-threads", str(threads)]
    if has_audio:
        if audio_codec.lower() == "copy":
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", audio_codec]
            if audio_bitrate:
                cmd += ["-b:a", audio_bitrate]
            if audio_channels > 0:
                cmd += ["-ac", str(audio_channels)]
    cmd += ["-progress", "pipe:1", "-nostats", str(output_video)]

    print("+", " ".join(cmd), flush=True)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if line.startswith("frame=") or line.startswith("fps=") or line.startswith("out_time=") or line.startswith("speed="):
            print("[ENCODE]", line, flush=True)
        elif line.startswith("progress="):
            print("[ENCODE]", line, flush=True)
        elif line:
            print("[FFMPEG]", line, flush=True)
    code = process.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--depth-model", required=True)
    parser.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    parser.add_argument("--output-width", type=int, default=3840)
    parser.add_argument("--output-height", type=int, default=2160)
    parser.add_argument("--max-disparity", type=float, default=36)
    parser.add_argument("--depth-gamma", type=float, default=1.25)
    parser.add_argument("--convergence", type=float, default=0.52)
    parser.add_argument("--test-seconds", default="")
    parser.add_argument("--crf", type=int, default=24)
    parser.add_argument("--preset", type=int, default=5)
    parser.add_argument("--audio-codec", default="libopus")
    parser.add_argument("--audio-bitrate", default="192k")
    parser.add_argument("--audio-channels", type=int, default=2, help="Audio channel count for re-encoding; 0 preserves source layout")
    parser.add_argument("--ffmpeg-threads", type=int, default=0)
    parser.add_argument("--frame-ext", default="png", choices=["png", "jpg"])
    args = parser.parse_args()

    input_video = Path(args.input).expanduser().resolve()
    output_video = Path(args.output).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()
    raw_dir = work_dir / "frames_2d"
    hsbs_dir = work_dir / "frames_hsbs"

    if args.output_width != 3840 or args.output_height != 2160:
        print(f"[WARN] Requested output is {args.output_width}x{args.output_height}, not standard 4K Half-SBS.", flush=True)
    if args.output_width % 2 != 0:
        raise ValueError("output-width must be even")

    duration, fps_expr, has_audio = video_info(input_video)
    print(f"[INFO] Duration: {duration:.2f}s")
    print(f"[INFO] FPS     : {fps_expr}")
    print(f"[INFO] Audio   : {has_audio}")

    if work_dir.exists():
        shutil.rmtree(work_dir)
    raw_dir.mkdir(parents=True)
    hsbs_dir.mkdir(parents=True)

    print("[STEP] Extract frames", flush=True)
    extract_cmd = ["ffmpeg", "-y"]
    if args.test_seconds:
        extract_cmd += ["-t", str(args.test_seconds)]
    extract_cmd += [
        "-i", str(input_video),
        "-vf", f"scale={args.output_width // 2}:{args.output_height}:flags=lanczos",
        str(raw_dir / f"%08d.{args.frame_ext}"),
    ]
    run(extract_cmd)

    frames = list_frames(raw_dir, args.frame_ext)
    if not frames:
        raise RuntimeError("No frames extracted")
    print(f"[INFO] Extracted frames: {len(frames)}")

    print("[STEP] Load depth model", flush=True)
    depth_pipe = load_depth_pipeline(args.depth_model, args.device)

    print("[STEP] Generate Half-SBS frames", flush=True)
    for idx, frame_path in enumerate(tqdm(frames, desc="2D->3D", unit="frame"), start=1):
        pil = Image.open(frame_path).convert("RGB")
        result = depth_pipe(pil)
        depth_img = result["depth"]
        depth01 = normalize_depth(depth_img, args.output_width // 2, args.output_height, args.depth_gamma)
        frame_bgr = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        hsbs = make_stereo_half_sbs(
            frame_bgr,
            depth01,
            args.output_width,
            args.output_height,
            args.max_disparity,
            args.convergence,
        )
        cv2.imwrite(str(hsbs_dir / f"{idx:08d}.{args.frame_ext}"), hsbs)

    print("[STEP] Encode AV1", flush=True)
    encode_input = input_video
    if args.test_seconds:
        # Keep audio length aligned in preview mode.
        preview_audio = work_dir / "preview_audio_source.mkv"
        run(["ffmpeg", "-y", "-t", str(args.test_seconds), "-i", str(input_video), "-c", "copy", str(preview_audio)])
        encode_input = preview_audio
    encode_av1(
        hsbs_dir=hsbs_dir,
        input_video=encode_input,
        output_video=output_video,
        fps_expr=fps_expr,
        has_audio=has_audio,
        crf=args.crf,
        preset=args.preset,
        audio_codec=args.audio_codec,
        audio_bitrate=args.audio_bitrate,
        audio_channels=args.audio_channels,
        threads=args.ffmpeg_threads,
        frame_ext=args.frame_ext,
    )

    print(f"[DONE] {output_video}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
