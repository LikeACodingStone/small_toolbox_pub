#!/usr/bin/env bash
# =============================================================================
# run.sh - Launch book vocabulary insertion pipeline
# Usage: bash run.sh
# =============================================================================

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
CONFIG_FILE="$SCRIPT_DIR/config.ini"

read_config_core() {
    [[ -f "$CONFIG_FILE" ]] || { echo "CPU"; return; }
    awk -F= '
        /^[[:space:]]*\[/ {
            section=$0
            gsub(/^[[:space:]]*\[/, "", section)
            gsub(/\][[:space:]]*$/, "", section)
            next
        }
        section == "RuntimeConfig" && $1 ~ /^[[:space:]]*CaculateCore[[:space:]]*$/ {
            value=$2
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print toupper(value)
            exit
        }
        section == "RuntimeConfig" && $1 ~ /^[[:space:]]*CalculateCore[[:space:]]*$/ {
            value=$2
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print toupper(value)
            exit
        }
    ' "$CONFIG_FILE"
}

read_config_max_workers() {
    [[ -f "$CONFIG_FILE" ]] || { echo "0"; return; }
    awk -F= '
        /^[[:space:]]*\[/ {
            section=$0
            gsub(/^[[:space:]]*\[/, "", section)
            gsub(/\][[:space:]]*$/, "", section)
            next
        }
        section == "RuntimeConfig" && $1 ~ /^[[:space:]]*MaxWorkers[[:space:]]*$/ {
            value=$2
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print value
            exit
        }
    ' "$CONFIG_FILE"
}

CPU_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
CONFIG_CALCULATE_CORE="$(read_config_core)"
CONFIG_CALCULATE_CORE="${CONFIG_CALCULATE_CORE:-CPU}"
if [[ "$CONFIG_CALCULATE_CORE" != "GPU" ]]; then
    CONFIG_CALCULATE_CORE="CPU"
fi
CONFIG_MAX_WORKERS="$(read_config_max_workers)"
CONFIG_MAX_WORKERS="${CONFIG_MAX_WORKERS:-0}"
if [[ ! "$CONFIG_MAX_WORKERS" =~ ^[0-9]+$ ]] || [[ "$CONFIG_MAX_WORKERS" == "0" ]]; then
    EFFECTIVE_MAX_WORKERS="$CPU_COUNT"
else
    EFFECTIVE_MAX_WORKERS="$CONFIG_MAX_WORKERS"
fi

section "========== Loading environment =========="

if [[ "$CONFIG_CALCULATE_CORE" == "CPU" ]]; then
    export BOOKVOCAB_DEVICE="${BOOKVOCAB_DEVICE:-cpu}"
    export BOOKVOCAB_CPU_THREADS="${BOOKVOCAB_CPU_THREADS:-$CPU_COUNT}"
    export BOOKVOCAB_MAX_WORKERS="${BOOKVOCAB_MAX_WORKERS:-$EFFECTIVE_MAX_WORKERS}"
else
    export BOOKVOCAB_DEVICE="${BOOKVOCAB_DEVICE:-cuda}"
    export BOOKVOCAB_GPU_ENABLED="${BOOKVOCAB_GPU_ENABLED:-1}"
    export BOOKVOCAB_MAX_WORKERS="${BOOKVOCAB_MAX_WORKERS:-$EFFECTIVE_MAX_WORKERS}"
fi
export BOOKVOCAB_OLLAMA_MODEL="${BOOKVOCAB_OLLAMA_MODEL:-qwen2.5:7b}"

info "CONFIG CaculateCore : $CONFIG_CALCULATE_CORE"
info "BOOKVOCAB_DEVICE   : $BOOKVOCAB_DEVICE"
info "BOOKVOCAB_CPU_THREADS: ${BOOKVOCAB_CPU_THREADS:-}"
info "BOOKVOCAB_MAX_WORKERS: $BOOKVOCAB_MAX_WORKERS"
info "BOOKVOCAB_OLLAMA_MODEL: $BOOKVOCAB_OLLAMA_MODEL"

section "========== Activating venv =========="

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"
    success "venv activated: $(python3 --version)"
else
    info "venv not found: $VENV_DIR"
    info "Using system python. To create venv, run: bash EnvSetup/SetupCPU.sh"
fi

section "========== Checking Ollama =========="

if command -v ollama &>/dev/null; then
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
else
    info "ollama command not found. Translation will fail until EnvSetup installs it."
fi

section "========== Launching main_batch.py =========="

cd "$SCRIPT_DIR"
exec python3 main_batch.py "$@"
