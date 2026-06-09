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

clear_legacy_env_prefix() {
    local legacy_prefix="JOE""ROGAN"
    local name
    while IFS= read -r name; do
        if [[ "$name" == "${legacy_prefix}_"* ]]; then
            unset "$name"
        fi
    done < <(compgen -v)
}

# ---------- Paths ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATION_DIR="$SCRIPT_DIR/migration"
INSTALLED_DIR="$MIGRATION_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
VENV_DIR="$SCRIPT_DIR/venv"
CONFIG_FILE="$SCRIPT_DIR/config.ini"

read_config_core() {
    [[ -f "$CONFIG_FILE" ]] || { echo "GPU"; return; }
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

CPU_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
CONFIG_CALCULATE_CORE="$(read_config_core)"
CONFIG_CALCULATE_CORE="${CONFIG_CALCULATE_CORE:-GPU}"
if [[ "$CONFIG_CALCULATE_CORE" != "CPU" ]]; then
    CONFIG_CALCULATE_CORE="GPU"
fi

# =============================================================================
# Environment variables
# =============================================================================
section "========== Loading environment =========="

clear_legacy_env_prefix
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ "$CONFIG_CALCULATE_CORE" == "CPU" ]]; then
    export AUDIOSOURCE_WHISPER_DEVICE="${AUDIOSOURCE_WHISPER_DEVICE:-cpu}"
    export AUDIOSOURCE_WHISPER_COMPUTE_TYPE="${AUDIOSOURCE_WHISPER_COMPUTE_TYPE:-int8}"
    export AUDIOSOURCE_WHISPER_CPU_THREADS="${AUDIOSOURCE_WHISPER_CPU_THREADS:-$CPU_COUNT}"
    export AUDIOSOURCE_WHISPER_CHUNK_SECONDS="${AUDIOSOURCE_WHISPER_CHUNK_SECONDS:-0}"
    export AUDIOSOURCE_MAX_WORKERS="${AUDIOSOURCE_MAX_WORKERS:-1}"
    export AUDIOSOURCE_USE_PROCESS_POOL="${AUDIOSOURCE_USE_PROCESS_POOL:-0}"
else
    export AUDIOSOURCE_WHISPER_DEVICE="${AUDIOSOURCE_WHISPER_DEVICE:-cuda}"
    export AUDIOSOURCE_WHISPER_COMPUTE_TYPE="${AUDIOSOURCE_WHISPER_COMPUTE_TYPE:-float16}"
    export AUDIOSOURCE_WHISPER_CHUNK_SECONDS="${AUDIOSOURCE_WHISPER_CHUNK_SECONDS:-300}"
    export AUDIOSOURCE_MAX_WORKERS="${AUDIOSOURCE_MAX_WORKERS:-1}"
fi
export AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS="${AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS:-1200}"
export AUDIOSOURCE_WHISPER_GPU_RETRIES="${AUDIOSOURCE_WHISPER_GPU_RETRIES:-1}"
export AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS="${AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS:-45}"
export AUDIOSOURCE_WHISPER_FALLBACK_CPU="${AUDIOSOURCE_WHISPER_FALLBACK_CPU:-1}"
export AUDIOSOURCE_CLEAR_LOGS="${AUDIOSOURCE_CLEAR_LOGS:-1}"
export AUDIOSOURCE_OLLAMA_MODEL="${AUDIOSOURCE_OLLAMA_MODEL:-qwen2.5:7b}"

info "LD_LIBRARY_PATH        : $LD_LIBRARY_PATH"
info "CONFIG CaculateCore   : $CONFIG_CALCULATE_CORE"
info "AUDIOSOURCE_WHISPER_DEVICE: $AUDIOSOURCE_WHISPER_DEVICE"
info "AUDIOSOURCE_WHISPER_COMPUTE_TYPE: $AUDIOSOURCE_WHISPER_COMPUTE_TYPE"
info "AUDIOSOURCE_WHISPER_CPU_THREADS: ${AUDIOSOURCE_WHISPER_CPU_THREADS:-}"
info "AUDIOSOURCE_WHISPER_CHUNK_SECONDS: $AUDIOSOURCE_WHISPER_CHUNK_SECONDS"
info "AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS: $AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS"
info "AUDIOSOURCE_WHISPER_GPU_RETRIES: $AUDIOSOURCE_WHISPER_GPU_RETRIES"
info "AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS: $AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS"
info "AUDIOSOURCE_WHISPER_FALLBACK_CPU: $AUDIOSOURCE_WHISPER_FALLBACK_CPU"
info "AUDIOSOURCE_MAX_WORKERS   : $AUDIOSOURCE_MAX_WORKERS"
info "AUDIOSOURCE_CLEAR_LOGS    : $AUDIOSOURCE_CLEAR_LOGS"
info "AUDIOSOURCE_OLLAMA_MODEL  : $AUDIOSOURCE_OLLAMA_MODEL"

# =============================================================================
# Activate venv
# =============================================================================
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
