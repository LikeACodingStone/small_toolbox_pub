#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

[[ -f "$VENV_DIR/bin/activate" ]] || {
    echo "venv not found: $VENV_DIR"
    exit 1
}
source "$VENV_DIR/bin/activate"

cd "$SCRIPT_DIR"
exec python3 TranslateAudio/translate_audio.py "$@"
