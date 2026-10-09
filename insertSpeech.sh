#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
CONFIG_FILE="$SCRIPT_DIR/InsertSpeech/config.ini"
DEPENDENCE_DIR="$(python3 - "$PROJECT_DIR" "$CONFIG_FILE" <<'PY'
import configparser
import sys
from pathlib import Path

root, config_path = map(Path, sys.argv[1:])
config = configparser.ConfigParser(interpolation=None)
with config_path.open(encoding="utf-8") as handle:
    config.read_file(handle)
value = config.get("RuntimeConfig", "env_folder", fallback="../DependenceLib").strip()
if not value:
    raise SystemExit("RuntimeConfig.env_folder must not be empty")
path = Path(value).expanduser()
print((root / path).resolve())
PY
)"
VENV_DIR="$DEPENDENCE_DIR/.venv"
INSTALLED_DIR="$DEPENDENCE_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
REQUIREMENTS="$SCRIPT_DIR/migration/requirements.txt"

COMPONENTS_DIR="$DEPENDENCE_DIR/components"
export PATH="$COMPONENTS_DIR/ffmpeg/bin:$COMPONENTS_DIR/ollama/bin:$PATH"
export HF_HOME="$DEPENDENCE_DIR/models/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export OLLAMA_MODELS="$DEPENDENCE_DIR/models/ollama"
export PIP_CACHE_DIR="$DEPENDENCE_DIR/cache/pip"
export XDG_CACHE_HOME="$DEPENDENCE_DIR/cache"
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
load_native_libraries() {
if [[ -d "$COMPONENTS_DIR/native" ]]; then
    while IFS= read -r library_dir; do
        export LD_LIBRARY_PATH="$library_dir:$LD_LIBRARY_PATH"
    done < <(find "$COMPONENTS_DIR/native" -type d -name '*lib*' -o -type d -name '*linux-gnu*' -o -type d -name 'openblas-pthread')
fi
}
load_native_libraries

native_components_ready() {
    local triplet
    triplet=""
    case "$(uname -m)" in
        x86_64) triplet=x86_64-linux-gnu ;;
        aarch64) triplet=aarch64-linux-gnu ;;
    esac
    [[ -f "$COMPONENTS_DIR/native/.complete" &&
       -f "$COMPONENTS_DIR/native/usr/lib/$triplet/libomp.so.5" &&
       -f "$COMPONENTS_DIR/native/usr/lib/$triplet/openblas-pthread/libopenblas.so.0" ]]
}

components_ready() {
    [[ -x "$COMPONENTS_DIR/ffmpeg/bin/ffmpeg" &&
       -x "$COMPONENTS_DIR/ffmpeg/bin/ffprobe" &&
       -x "$COMPONENTS_DIR/ollama/bin/ollama" &&
       -f "$COMPONENTS_DIR/ollama/.complete" &&
       -f "$COMPONENTS_DIR/native/.complete" ]] && native_components_ready &&
        "$COMPONENTS_DIR/ffmpeg/bin/ffmpeg" -version >/dev/null 2>&1 &&
        "$COMPONENTS_DIR/ffmpeg/bin/ffprobe" -version >/dev/null 2>&1
}

start_local_ollama() {
    # Each dependency directory owns a server and model store, separate from system Ollama.
    OLLAMA_HOST="$(python3 - "$DEPENDENCE_DIR" <<'PY'
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

root = Path(sys.argv[1])
run = root / "run"
run.mkdir(parents=True, exist_ok=True)
state_path = run / "ollama.json"
binary = root / "components/ollama/bin/ollama"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def healthy(host):
    try:
        with opener.open("http://" + host + "/api/tags", timeout=1) as response:
            return isinstance(json.load(response).get("models"), list)
    except Exception:
        return False

with (run / "ollama.lock").open("a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        state = json.loads(state_path.read_text())
        environment = Path(f"/proc/{int(state['pid'])}/environ").read_bytes().split(b"\0")
        executable = Path(f"/proc/{int(state['pid'])}/exe").resolve()
        expected = ("OLLAMA_MODELS=" + os.environ["OLLAMA_MODELS"]).encode()
        if executable == binary.resolve() and expected in environment and healthy(state["host"]):
            print(state["host"])
            raise SystemExit(0)
    except (OSError, ValueError, KeyError, TypeError):
        pass

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        host = "127.0.0.1:" + str(listener.getsockname()[1])
    env = dict(os.environ, OLLAMA_HOST=host)
    with (run / "ollama.log").open("ab") as log:
        process = subprocess.Popen([str(binary), "serve"], env=env,
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   start_new_session=True)
    for _ in range(60):
        if process.poll() is not None:
            raise SystemExit(f"Ollama exited; see {run / 'ollama.log'}")
        if healthy(host):
            state_path.write_text(json.dumps({"pid": process.pid, "host": host}))
            print(host)
            break
        time.sleep(0.5)
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise SystemExit(f"Ollama startup timed out; see {run / 'ollama.log'}")
PY
)"
    export OLLAMA_HOST
    export AUDIOSOURCE_OLLAMA_API="http://$OLLAMA_HOST/api/generate"
}


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
        if [[ ! -f "$ROCM_INSTALL_DIR/lib/libctranslate2.so.4" ||
              ! -f "$COMPONENTS_DIR/ollama/.rocm-complete" ]] ||
            ! cmp -s "$INSTALLED_DIR/ctranslate2/$extension" "$VENV_DIR/lib/python3.12/site-packages/ctranslate2/$extension"; then
            gpu_ready=0
        fi
    fi
    if ! environment_ready || ! components_ready || [[ "$gpu_ready" == 0 ]]; then
        PODCAST_SETUP_AUTO=1 bash "$SCRIPT_DIR/migration/$setup" --config "$CONFIG_FILE"
    fi
    source "$VENV_DIR/bin/activate"
    load_native_libraries
    if [[ -d "$ROCM_INSTALL_DIR/lib" ]]; then
        export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
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

export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
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

start_local_ollama
if ! ollama show "$AUDIOSOURCE_OLLAMA_MODEL" >/dev/null 2>&1; then
    ollama pull "$AUDIOSOURCE_OLLAMA_MODEL"
fi

cd "$SCRIPT_DIR"
exec python3 InsertSpeech/main_batch.py "$@"
