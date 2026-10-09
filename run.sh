#!/usr/bin/env bash
# =============================================================================
# run.sh - Launch book vocabulary insertion pipeline
# Usage: bash run.sh [main_batch.py arguments]
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
section() { echo -e "${CYAN}$*${NC}"; }

print_main_arguments() {
    section "========== main_batch.py arguments =========="
    cat <<'EOF'
Accepted arguments:
  --input PATH              Process one input book file instead of scanning OriginalBookPath.
  --input-dir PATH          Override [OriginalConfigPath] OriginalBookPath for this run.
  --output-dir PATH         Override [OriginalConfigPath] OutputBookPath for this run.
  --keep-work               Keep intermediate work files as configured for this run.
  --skip-existing           Do not overwrite existing output files.
  --run-mode local|remote   Override [RuntimeConfig] RunMode for this run.
  --local-only              Force local mode; normally used internally by remote workers.
  --remote-preflight        Check, sync, and set up remote workers, then exit.
  --remote-worker-job PATH  Process one distributed worker job; internal use only.

Main execution paths:
  load_config               Reads config.ini and applies default values.
  apply_runtime_env         Exports CPU/GPU, worker, and Ollama environment settings.
  remote_preflight          Validates remote SSH workers without processing books.
  process_book_remote       Splits a book into chunks and dispatches remote/local workers.
  process_book              Processes a book locally.
  run_remote_worker_job     Runs one chunk job created by the remote coordinator.

Permanent local mode:
  Set [RuntimeConfig] RunMode = local in config.ini.
EOF
}

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

read_config_run_mode() {
    [[ -f "$CONFIG_FILE" ]] || { echo "local"; return; }
    awk -F= '
        /^[[:space:]]*\[/ {
            section=$0
            gsub(/^[[:space:]]*\[/, "", section)
            gsub(/\][[:space:]]*$/, "", section)
            next
        }
        section == "RuntimeConfig" && $1 ~ /^[[:space:]]*RunMode[[:space:]]*$/ {
            value=$2
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
            print tolower(value)
            exit
        }
    ' "$CONFIG_FILE"
}

read_config_ollama_api() {
    [[ -f "$CONFIG_FILE" ]] || { echo "http://localhost:11434/api/generate"; return; }
    awk -F= '
        /^[[:space:]]*\[/ {
            section=$0
            gsub(/^[[:space:]]*\[/, "", section)
            gsub(/\][[:space:]]*$/, "", section)
            next
        }
        section == "TranslationConfig" && $1 ~ /^[[:space:]]*OllamaApi[[:space:]]*$/ {
            value=$0
            sub(/^[^=]*=/, "", value)
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
CONFIG_RUN_MODE="$(read_config_run_mode)"
CONFIG_RUN_MODE="${CONFIG_RUN_MODE:-local}"
if [[ "$CONFIG_RUN_MODE" != "remote" ]]; then
    CONFIG_RUN_MODE="local"
fi
CONFIG_OLLAMA_API="$(read_config_ollama_api)"
CONFIG_OLLAMA_API="${CONFIG_OLLAMA_API:-http://localhost:11434/api/generate}"
if [[ ! "$CONFIG_MAX_WORKERS" =~ ^[0-9]+$ ]] || [[ "$CONFIG_MAX_WORKERS" == "0" ]]; then
    EFFECTIVE_MAX_WORKERS="$CPU_COUNT"
else
    EFFECTIVE_MAX_WORKERS="$CONFIG_MAX_WORKERS"
fi

section "========== Loading environment =========="

if [[ "$CONFIG_CALCULATE_CORE" == "CPU" ]]; then
    export BOOKVOCAB_DEVICE="${BOOKVOCAB_DEVICE:-cpu}"
    export BOOKVOCAB_CPU_THREADS="${BOOKVOCAB_CPU_THREADS:-$CPU_COUNT}"
    if [[ "$CONFIG_MAX_WORKERS" == "0" ]]; then
        export BOOKVOCAB_MAX_WORKERS="$EFFECTIVE_MAX_WORKERS"
    else
        export BOOKVOCAB_MAX_WORKERS="${BOOKVOCAB_MAX_WORKERS:-$EFFECTIVE_MAX_WORKERS}"
    fi
else
    export BOOKVOCAB_DEVICE="${BOOKVOCAB_DEVICE:-cuda}"
    export BOOKVOCAB_GPU_ENABLED="${BOOKVOCAB_GPU_ENABLED:-1}"
    if [[ "$CONFIG_MAX_WORKERS" == "0" ]]; then
        export BOOKVOCAB_MAX_WORKERS="$EFFECTIVE_MAX_WORKERS"
    else
        export BOOKVOCAB_MAX_WORKERS="${BOOKVOCAB_MAX_WORKERS:-$EFFECTIVE_MAX_WORKERS}"
    fi
fi
export BOOKVOCAB_OLLAMA_MODEL="${BOOKVOCAB_OLLAMA_MODEL:-qwen2.5:7b}"
export BOOKVOCAB_OLLAMA_API="${BOOKVOCAB_OLLAMA_API:-$CONFIG_OLLAMA_API}"

info "CONFIG CaculateCore : $CONFIG_CALCULATE_CORE"
info "BOOKVOCAB_DEVICE   : $BOOKVOCAB_DEVICE"
info "BOOKVOCAB_CPU_THREADS: ${BOOKVOCAB_CPU_THREADS:-}"
info "BOOKVOCAB_MAX_WORKERS: $BOOKVOCAB_MAX_WORKERS"
info "BOOKVOCAB_OLLAMA_MODEL: $BOOKVOCAB_OLLAMA_MODEL"
info "BOOKVOCAB_OLLAMA_API: $BOOKVOCAB_OLLAMA_API"
info "RUN_MODE           : $CONFIG_RUN_MODE"
print_main_arguments

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
exec python3 main_batch.py --run-mode "$CONFIG_RUN_MODE" "$@"
