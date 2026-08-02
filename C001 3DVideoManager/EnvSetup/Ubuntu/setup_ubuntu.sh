#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_ROOT="$PROJECT_DIR/EnvSetup"
VENV_DIR="$ENV_ROOT/venv-ubuntu"
REQUIREMENTS="$ENV_ROOT/requirements.txt"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Install it with: sudo apt update && sudo apt install -y python3 python3-venv" >&2
    exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS"

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo "ffmpeg/ffprobe were not found. Install them with: sudo apt update && sudo apt install -y ffmpeg" >&2
fi

echo "Ubuntu environment is ready: $VENV_DIR"
echo "Run the tool with: bash $PROJECT_DIR/run_av1_tool_ubuntu.sh"