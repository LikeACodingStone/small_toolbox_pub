#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
CONFIG_FILE="$SCRIPT_DIR/InsertSpeech/config.ini"
MIGRATION_DIR="$SCRIPT_DIR/migration"
ROCM_INSTALL_DIR="$MIGRATION_DIR/installed/ctranslate2-rocm"

read_config_core() {
    [[ -f "$CONFIG_FILE" ]] || { printf 'GPU\n'; return; }
    awk -F= '
        /^[[:space:]]*\[/ { section=$0; gsub(/^[[:space:]]*\[/, "", section); gsub(/\][[:space:]]*$/, "", section); next }
        section == "RuntimeConfig" && $1 ~ /^[[:space:]]*(CaculateCore|CalculateCore)[[:space:]]*$/ {
            value=$2; gsub(/^[[:space:]]+|[[:space:]]+$/, "", value); print toupper(value); exit
        }
    ' "$CONFIG_FILE"
}

CPU_COUNT="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || printf '1\n')"
CALCULATE_CORE="$(read_config_core)"
CALCULATE_CORE="${CALCULATE_CORE:-GPU}"
[[ "$CALCULATE_CORE" == "CPU" ]] || CALCULATE_CORE="GPU"

export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [[ "$CALCULATE_CORE" == "CPU" ]]; then
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

[[ -f "$VENV_DIR/bin/activate" ]] || {
    echo "venv not found: $VENV_DIR"
    exit 1
}
source "$VENV_DIR/bin/activate"

if ! pgrep -x "ollama" >/dev/null 2>&1; then
    ollama serve >/dev/null 2>&1 &
    for _ in {1..15}; do
        if curl -s http://localhost:11434 >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi

cd "$SCRIPT_DIR"
exec python3 InsertSpeech/main_batch.py "$@"
