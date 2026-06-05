#!/usr/bin/env bash
# =============================================================================
# run.sh — Launch podcast toolchain with full ROCm/GPU environment
# Usage: bash run.sh
# =============================================================================

set -euo pipefail

# ---------- Color output ----------
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
section() { echo -e "${CYAN}$*${NC}"; }

# ---------- Paths ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_DIR="$SCRIPT_DIR/migration"
INSTALLED_DIR="$MIGRATION_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
VENV_DIR="$SCRIPT_DIR/venv"

# =============================================================================
# Environment variables
# =============================================================================
section "========== Loading environment =========="

export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export JOEROGAN_WHISPER_DEVICE=cuda
export JOEROGAN_WHISPER_COMPUTE_TYPE=float16
export JOEROGAN_MAX_WORKERS=1
export JOEROGAN_OLLAMA_MODEL=qwen2.5:7b

info "LD_LIBRARY_PATH        : $LD_LIBRARY_PATH"
info "JOEROGAN_WHISPER_DEVICE: $JOEROGAN_WHISPER_DEVICE"
info "JOEROGAN_WHISPER_COMPUTE_TYPE: $JOEROGAN_WHISPER_COMPUTE_TYPE"
info "JOEROGAN_MAX_WORKERS   : $JOEROGAN_MAX_WORKERS"
info "JOEROGAN_OLLAMA_MODEL  : $JOEROGAN_OLLAMA_MODEL"

# =============================================================================
# Activate venv
# =============================================================================
section "========== Activating venv =========="

[[ -f "$VENV_DIR/bin/activate" ]] || { echo "venv not found: $VENV_DIR — run setup.sh first"; exit 1; }
source "$VENV_DIR/bin/activate"
success "venv activated: $(python3 --version)"

# =============================================================================
# Ensure Ollama is running
# =============================================================================
section "========== Checking Ollama =========="

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

# =============================================================================
# Launch
# =============================================================================
section "========== Launching main_batch.py =========="

cd "$SCRIPT_DIR"
exec python3 main_batch.py "$@"
