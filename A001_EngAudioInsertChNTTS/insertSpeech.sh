#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPENDENCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)/DependenceLib"
VENV_DIR="$DEPENDENCE_DIR/.venv"
INSTALLED_DIR="$DEPENDENCE_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
REQUIREMENTS="$SCRIPT_DIR/migration/requirements.txt"

environment_ready() {
    [[ -x "$VENV_DIR/bin/python" ]] || return 1
    "$VENV_DIR/bin/python" - "$REQUIREMENTS" <<'PY'
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

if sys.prefix == sys.base_prefix:
    raise SystemExit(1)
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    name, expected = line.strip().split("==", 1)
    try:
        if version(name) != expected:
            raise SystemExit(1)
    except PackageNotFoundError:
        raise SystemExit(1)
PY
}

activate_project_environment() {
    local core="${1:-GPU}"
    local setup=SetupCPU.sh
    local extension=_ext.cpython-312-x86_64-linux-gnu.so
    local gpu_ready=1
    if [[ "$core" == GPU ]]; then
        setup=SetupRyzen7800GPU.sh
        if [[ ! -f "$ROCM_INSTALL_DIR/lib/libctranslate2.so.4" ]] ||
            ! cmp -s "$INSTALLED_DIR/ctranslate2/$extension" "$VENV_DIR/lib/python3.12/site-packages/ctranslate2/$extension"; then
            gpu_ready=0
        fi
    fi
    if ! environment_ready || [[ "$gpu_ready" == 0 ]]; then
        PODCAST_SETUP_AUTO=1 bash "$SCRIPT_DIR/migration/$setup"
    fi
    source "$VENV_DIR/bin/activate"
    if [[ -d "$ROCM_INSTALL_DIR/lib" ]]; then
        export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
}

CONFIG_FILE="$SCRIPT_DIR/InsertSpeech/config.ini"
MIGRATION_DIR="$SCRIPT_DIR/migration"

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

activate_project_environment "$CALCULATE_CORE"

if ! pgrep -x "ollama" >/dev/null 2>&1; then
    ollama serve >/dev/null 2>&1 &
    for _ in {1..15}; do
        if curl -s http://localhost:11434 >/dev/null 2>&1; then break; fi
        sleep 2
    done
fi

cd "$SCRIPT_DIR"
exec python3 InsertSpeech/main_batch.py "$@"
