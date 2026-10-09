#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/EnvSetup/venv-ubuntu/bin/python"

if [[ -x "$VENV_PYTHON" ]]; then
    PYTHON_EXE="$VENV_PYTHON"
else
    PYTHON_EXE="${PYTHON_EXE:-python3}"
fi

cd "$SCRIPT_DIR"
exec "$PYTHON_EXE" "$SCRIPT_DIR/av1_3d_video_tool.py"