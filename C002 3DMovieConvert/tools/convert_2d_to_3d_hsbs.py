#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path


def fail(message: str, code: int = 1) -> None:
    print(f"[ERROR] {message}", flush=True)
    raise SystemExit(code)


def probe(path: Path) -> tuple[dict, float]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height,duration:format=duration",
            "-of", "json", str(path),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        fail(f"ffprobe 检测失败：{result.stderr.strip()}", 4)
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams:
        fail("输入文件没有视频流。", 4)
    stream = streams[0]
    duration = float(stream.get("duration") or payload.get("format", {}).get("duration") or 0)
    return stream, duration


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="4K 2D to 4K Half-SBS AV1 converter")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--encoder", default="libsvtav1")
    parser.add_argument("--crf", type=float, default=20.0)
    parser.add_argument("--preset", type=int, default=5)
    parser.add_argument("--required-width", type=int, default=3840)
    parser.add_argument("--required-height", type=int, default=2160)
    parser.add_argument("--eye-width", type=int, default=1920)
    parser.add_argument("--eye-height", type=int, default=2160)
    parser.add_argument("--eye-shift", type=int, default=24)
    parser.add_argument("--threads", type=int, default=0)
    parser.add_argument("--audio-mode", choices=("copy", "opus", "aac"), default="copy")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def encoder_available(name: str) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return result.returncode == 0 and name in result.stdout


def progress_seconds(key: str, value: str) -> float | None:
    try:
        if key == "out_time_us":
            return int(value) / 1_000_000
        if key == "out_time_ms":
            # FFmpeg historically labels this field ms although its value is microseconds.
            return int(value) / 1_000_000
        if key == "out_time":
            hours, minutes, seconds = value.split(":")
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (TypeError, ValueError):
        return None
    return None


def main() -> int:
    args = parse_args()
    source = args.input.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()

    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        fail("ffmpeg/ffprobe 不在 PATH 中。", 3)
    if not source.is_file():
        fail(f"输入视频不存在：{source}", 2)
    if not 0 <= args.crf <= 63:
        fail(f"CRF 必须在 0-63，当前值：{args.crf}", 2)
    if args.eye_shift < 0 or args.eye_shift >= args.required_width:
        fail("EYE_SHIFT 超出有效范围。", 2)
    if not encoder_available(args.encoder):
        fail(f"当前 FFmpeg 不包含编码器：{args.encoder}", 3)

    video, duration = probe(source)
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    print(f"[INFO] 输入分辨率：{width}x{height}", flush=True)
    if (width, height) != (args.required_width, args.required_height):
        fail(
            f"视频格式不符合要求：必须是 {args.required_width}x{args.required_height} UHD 4K，"
            f"实际为 {width}x{height}，不予执行。",
            5,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{source.stem}_4K_Half-SBS_AV1_CRF{args.crf:g}.mkv"
    if output.exists() and not args.overwrite:
        fail(f"输出文件已存在：{output}；如需覆盖，请在 config.env 设置 OVERWRITE=true。", 6)

    crop_width = args.required_width - args.eye_shift
    filters = (
        f"[0:v:0]split=2[left][right];"
        f"[left]crop={crop_width}:{args.required_height}:0:0,"
        f"scale={args.eye_width}:{args.eye_height}:flags=lanczos[left_eye];"
        f"[right]crop={crop_width}:{args.required_height}:{args.eye_shift}:0,"
        f"scale={args.eye_width}:{args.eye_height}:flags=lanczos[right_eye];"
        f"[left_eye][right_eye]hstack=inputs=2,setsar=1[stereo]"
    )
    command = [
        "ffmpeg", "-hide_banner", "-y" if args.overwrite else "-n",
        "-i", str(source),
        "-filter_complex", filters,
        "-map", "[stereo]", "-map", "0:a?", "-map", "0:s?",
        "-map_metadata", "0", "-map_chapters", "0",
        "-c:v", args.encoder, "-crf", f"{args.crf:g}",
        "-preset", str(args.preset), "-pix_fmt", "yuv420p10le",
        "-threads", str(args.threads),
    ]
    if args.audio_mode == "copy":
        command += ["-c:a", "copy"]
    elif args.audio_mode == "opus":
        command += ["-c:a", "libopus", "-b:a", "192k"]
    else:
        command += ["-c:a", "aac", "-b:a", "256k"]
    command += [
        "-c:s", "copy", "-metadata:s:v:0", "stereo_mode=left_right",
        "-progress", "pipe:1", "-nostats", str(output),
    ]

    print(f"[INFO] 输出：{output}", flush=True)
    print(f"[INFO] AV1：encoder={args.encoder}, CRF={args.crf:g}, preset={args.preset}", flush=True)
    print(f"[INFO] Half-SBS：{args.eye_width}x{args.eye_height} + {args.eye_width}x{args.eye_height}", flush=True)
    started = time.monotonic()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    last_percent = -1
    assert process.stdout is not None
    for raw in process.stdout:
        line = raw.strip()
        if "=" in line:
            key, value = line.split("=", 1)
            seconds = progress_seconds(key, value)
            if seconds is not None and duration > 0:
                percent = min(99, max(0, int(seconds * 100 / duration)))
                if percent != last_percent:
                    elapsed = time.monotonic() - started
                    print(f"\r[PROGRESS] {percent:3d}%  elapsed={elapsed / 60:.1f} min", end="", flush=True)
                    last_percent = percent
            elif key == "progress" and value == "end":
                print("\r[PROGRESS] 100%  转换完成                         ", flush=True)
        elif "error" in line.lower() or "failed" in line.lower():
            print(f"\n[FFMPEG] {line}", flush=True)

    return_code = process.wait()
    if return_code != 0:
        if output.exists():
            output.unlink()
        fail(f"FFmpeg 转换失败，退出码：{return_code}", 7)

    out_video, _ = probe(output)
    out_width = int(out_video.get("width") or 0)
    out_height = int(out_video.get("height") or 0)
    if (out_width, out_height) != (args.eye_width * 2, args.eye_height):
        fail(f"输出校验失败：得到 {out_width}x{out_height}", 8)
    print(f"[OK] 输出校验通过：{out_width}x{out_height}, AV1 CRF {args.crf:g}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
