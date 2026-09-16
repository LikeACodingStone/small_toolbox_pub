#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

[[ -f "$VENV_DIR/bin/activate" ]] || {
    echo "venv not found: $VENV_DIR"
    exit 1
}
source "$VENV_DIR/bin/activate"
export AUDIOSOURCE_OLLAMA_MODEL="${AUDIOSOURCE_OLLAMA_MODEL:-qwen2.5:7b}"

if ! pgrep -x "ollama" >/dev/null 2>&1; then
    ollama serve >/dev/null 2>&1 &
    for _ in {1..15}; do
        if curl -s http://localhost:11434 >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi

cd "$SCRIPT_DIR"
exec python3 SubtitleOnly/subtitle_improve.py "$@"
