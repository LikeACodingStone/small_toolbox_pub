#!/usr/bin/env python3
"""Stream a 2D video through depth estimation into a 4K Half-SBS AV1 file.

Decoded and generated frames stay in memory. Only the encoded output is written
to disk, so temporary storage does not grow with the input video's duration.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from pathlib import Path
from typing import BinaryIO

import cv2
import numpy as np
from PIL import Image
from tqdm import tqdm


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


def video_info(input_path: Path) -> tuple[float, float, str, bool]:
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
    return duration, fps, fps_expr, has_audio


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
    left = cv2.remap(src, left_map_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    right = cv2.remap(src, right_map_x, y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return np.ascontiguousarray(np.concatenate([left, right], axis=1))


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


def stream_convert(
    *,
    input_video: Path,
    partial_output: Path,
    work_dir: Path,
    depth_pipe,
    duration: float,
    fps: float,
    fps_expr: str,
    has_audio: bool,
    output_width: int,
    output_height: int,
    max_disparity: float,
    depth_gamma: float,
    convergence: float,
    test_seconds: str,
    crf: int,
    preset: int,
    audio_codec: str,
    audio_bitrate: str,
    audio_channels: int,
    threads: int,
    max_work_bytes: int,
) -> int:
    eye_width = output_width // 2
    frame_bytes = eye_width * output_height * 3
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
        "-vf", f"scale={eye_width}:{output_height}:flags=lanczos",
        "-r", fps_expr,
        "-fps_mode", "cfr",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "pipe:1",
    ]

    encoder_cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s:v", f"{output_width}x{output_height}",
        "-framerate", fps_expr,
        "-i", "pipe:0",
    ]
    if has_audio:
        if test_seconds:
            encoder_cmd += ["-t", test_seconds]
        encoder_cmd += ["-i", str(input_video), "-map", "0:v:0", "-map", "1:a:0?"]
    else:
        encoder_cmd += ["-map", "0:v:0"]

    encoder_cmd += [
        "-c:v", "libsvtav1",
        "-pix_fmt", "yuv420p10le",
        "-crf", str(crf),
        "-preset", str(preset),
        "-svtav1-params", "tune=0:film-grain=6",
    ]
    if threads > 0:
        encoder_cmd += ["-threads", str(threads)]
    if has_audio:
        if audio_codec.lower() == "copy":
            encoder_cmd += ["-c:a", "copy"]
        else:
            encoder_cmd += ["-c:a", audio_codec]
            if audio_bitrate:
                encoder_cmd += ["-b:a", audio_bitrate]
            if audio_channels > 0:
                encoder_cmd += ["-ac", str(audio_channels)]
        encoder_cmd += ["-shortest"]
    encoder_cmd += ["-progress", "pipe:2", "-nostats", str(partial_output)]

    print("[STEP] Start streaming decoder", flush=True)
    print("+", " ".join(decoder_cmd), flush=True)
    print("[STEP] Start streaming AV1 encoder", flush=True)
    print("+", " ".join(encoder_cmd), flush=True)

    decoder: subprocess.Popen | None = None
    encoder: subprocess.Popen | None = None
    progress = None
    completed = False
    frame_count = 0
    try:
        encoder = subprocess.Popen(encoder_cmd, stdin=subprocess.PIPE)
        decoder = subprocess.Popen(decoder_cmd, stdout=subprocess.PIPE)
        assert decoder.stdout is not None
        assert encoder.stdin is not None

        effective_duration = min(duration, float(test_seconds)) if test_seconds else duration
        expected_frames = math.ceil(effective_duration * fps) if effective_duration > 0 else None
        progress = tqdm(total=expected_frames, desc="2D->3D->AV1", unit="frame")
        frame_buffer = bytearray(frame_bytes)

        while read_exact_frame(decoder.stdout, frame_buffer):
            if encoder.poll() is not None:
                raise RuntimeError(f"AV1 encoder exited early with code {encoder.returncode}")

            frame_bgr = np.frombuffer(frame_buffer, dtype=np.uint8).reshape(output_height, eye_width, 3)
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            result = depth_pipe(Image.fromarray(frame_rgb))
            depth01 = normalize_depth(result["depth"], eye_width, output_height, depth_gamma)
            hsbs = make_stereo_half_sbs(
                frame_bgr,
                depth01,
                output_width,
                output_height,
                max_disparity,
                convergence,
            )
            try:
                write_all(encoder.stdin, memoryview(hsbs).cast("B"))
            except BrokenPipeError as exc:
                code = encoder.wait()
                raise RuntimeError(f"AV1 encoder closed its input early with code {code}") from exc

            frame_count += 1
            progress.update(1)
            if frame_count % 100 == 0:
                enforce_work_limit(work_dir, max_work_bytes)

        decoder.stdout.close()
        decoder_code = decoder.wait()
        if decoder_code != 0:
            raise subprocess.CalledProcessError(decoder_code, decoder_cmd)
        if frame_count == 0:
            raise RuntimeError("Decoder produced no video frames")

        try:
            encoder.stdin.close()
        except BrokenPipeError as exc:
            code = encoder.wait()
            raise RuntimeError(f"AV1 encoder failed while finalizing with code {code}") from exc
        encoder_code = encoder.wait()
        if encoder_code != 0:
            raise subprocess.CalledProcessError(encoder_code, encoder_cmd)
        enforce_work_limit(work_dir, max_work_bytes)
        completed = True
        return frame_count
    finally:
        if progress is not None:
            progress.close()
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
    parser.add_argument("--max-work-gb", type=float, default=200.0, help="Maximum files allowed in the work directory; 0 disables the guard")
    parser.add_argument("--frame-ext", default="png", help=argparse.SUPPRESS)
    args = parser.parse_args()

    input_video = Path(args.input).expanduser().resolve()
    output_video = Path(args.output).expanduser().resolve()
    work_dir = Path(args.work_dir).expanduser().resolve()

    if not input_video.is_file():
        raise FileNotFoundError(f"Input video not found: {input_video}")
    if args.output_width % 2 != 0:
        raise ValueError("output-width must be even")
    if args.output_width != 3840 or args.output_height != 2160:
        print(f"[WARN] Requested output is {args.output_width}x{args.output_height}, not standard 4K Half-SBS.", flush=True)
    if args.max_work_gb < 0:
        raise ValueError("max-work-gb cannot be negative")

    duration, fps, fps_expr, has_audio = video_info(input_video)
    max_work_bytes = int(args.max_work_gb * 1024**3)
    print(f"[INFO] Duration       : {duration:.2f}s")
    print(f"[INFO] FPS            : {fps_expr}")
    print(f"[INFO] Audio          : {has_audio}")
    print("[INFO] Frame storage  : streaming (no extracted frame files)")
    print(f"[INFO] Work dir limit : {args.max_work_gb:.2f} GiB" if max_work_bytes else "[INFO] Work dir limit : disabled")

    work_dir.mkdir(parents=True, exist_ok=True)
    enforce_work_limit(work_dir, max_work_bytes)

    print("[STEP] Load depth model", flush=True)
    depth_pipe = load_depth_pipeline(args.depth_model, args.device)

    output_suffix = output_video.suffix or ".mkv"
    partial_output = output_video.with_name(f"{output_video.stem}.part{output_suffix}")
    frame_count = stream_convert(
        input_video=input_video,
        partial_output=partial_output,
        work_dir=work_dir,
        depth_pipe=depth_pipe,
        duration=duration,
        fps=fps,
        fps_expr=fps_expr,
        has_audio=has_audio,
        output_width=args.output_width,
        output_height=args.output_height,
        max_disparity=args.max_disparity,
        depth_gamma=args.depth_gamma,
        convergence=args.convergence,
        test_seconds=args.test_seconds,
        crf=args.crf,
        preset=args.preset,
        audio_codec=args.audio_codec,
        audio_bitrate=args.audio_bitrate,
        audio_channels=args.audio_channels,
        threads=args.ffmpeg_threads,
        max_work_bytes=max_work_bytes,
    )

    os.replace(partial_output, output_video)
    print(f"[DONE] {output_video}", flush=True)
    print(f"[INFO] Encoded frames: {frame_count}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
