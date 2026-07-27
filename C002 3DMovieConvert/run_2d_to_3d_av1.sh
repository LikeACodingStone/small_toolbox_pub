#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$PROJECT_DIR/config.env}"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_$(date '+%Y%m%d_%H%M%S').log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[INFO] Project: $PROJECT_DIR"
echo "[INFO] Config : $CONFIG_FILE"
echo "[INFO] Log    : $LOG_FILE"

[[ -f "$CONFIG_FILE" ]] || { echo "[ERROR] 配置文件不存在：$CONFIG_FILE"; exit 2; }
# shellcheck disable=SC1090
source "$CONFIG_FILE"

INPUT_VIDEO="${1:-${INPUT_VIDEO:-}}"
OUTPUT_DIR="${2:-${OUTPUT_DIR:-$PROJECT_DIR/output}}"
if [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="$PROJECT_DIR/${OUTPUT_DIR#./}"
fi

[[ -n "$INPUT_VIDEO" ]] || {
    echo "[ERROR] 未配置输入视频。请编辑 config.env 的 INPUT_VIDEO，或执行："
    echo "        bash run_2d_to_3d_av1.sh /path/movie.mkv"
    exit 2
}
[[ -f "$INPUT_VIDEO" ]] || { echo "[ERROR] 输入视频不存在：$INPUT_VIDEO"; exit 2; }

command -v ffmpeg >/dev/null 2>&1 || { echo "[ERROR] 找不到 ffmpeg"; exit 3; }
command -v ffprobe >/dev/null 2>&1 || { echo "[ERROR] 找不到 ffprobe"; exit 3; }

VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "[ERROR] venv/bin/python3 不存在。请先运行："
    echo "        bash migration/SetupRyzen7800GPU.sh"
    exit 3
fi

mkdir -p "$OUTPUT_DIR"

CONVERT_ARGS=(
    --input "$INPUT_VIDEO"
    --output-dir "$OUTPUT_DIR"
    --encoder "${AV1_ENCODER:-libsvtav1}"
    --crf "${CRF:-20}"
    --preset "${PRESET:-5}"
    --required-width "${REQUIRED_INPUT_WIDTH:-3840}"
    --required-height "${REQUIRED_INPUT_HEIGHT:-2160}"
    --eye-width "${EYE_WIDTH:-1920}"
    --eye-height "${EYE_HEIGHT:-2160}"
    --eye-shift "${EYE_SHIFT:-24}"
    --threads "${THREADS:-0}"
    --audio-mode "${AUDIO_MODE:-copy}"
)
if [[ "${OVERWRITE:-false}" == "true" ]]; then
    CONVERT_ARGS+=(--overwrite)
fi

exec "$VENV_PYTHON" "$PROJECT_DIR/tools/convert_2d_to_3d_hsbs.py" \
    "${CONVERT_ARGS[@]}"
