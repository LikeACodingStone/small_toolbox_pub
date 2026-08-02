#!/usr/bin/env bash
# Improve generated markdown subtitles without creating vocabulary audio.
# Usage: bash subtitle_improve.sh

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
section() { echo -e "${CYAN}$*${NC}"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

section "========== Activating venv =========="

[[ -f "$VENV_DIR/bin/activate" ]] || {
    echo "venv not found: $VENV_DIR"
    echo "Run one setup script first:"
    echo "  bash migration/SetupRyzen7800GPU.sh"
    echo "  bash migration/SetupCPU.sh"
    exit 1
}
source "$VENV_DIR/bin/activate"
success "venv activated: $(python3 --version)"

section "========== Checking Ollama =========="

export AUDIOSOURCE_OLLAMA_MODEL="${AUDIOSOURCE_OLLAMA_MODEL:-qwen2.5:7b}"
info "AUDIOSOURCE_OLLAMA_MODEL: $AUDIOSOURCE_OLLAMA_MODEL"

if ! pgrep -x "ollama" &>/dev/null; then
    info "Ollama not running, starting..."
    ollama serve &>/dev/null &
    for i in {1..15}; do
        if curl -s http://localhost:11434 &>/dev/null; then
            success "Ollama service is up"
            break
        fi
        info "Waiting for Ollama... ($i/15)"
        sleep 2
    done
else
    success "Ollama already running"
fi

section "========== Improving subtitles =========="

cd "$SCRIPT_DIR"
exec python3 subtitle_improve.py "$@"
