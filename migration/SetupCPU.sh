#!/usr/bin/env bash
# =============================================================================
# SetupCPU.sh - Podcast toolchain CPU environment deployment script
# Usage: run "bash SetupCPU.sh" from the migration/ directory
# =============================================================================

set -euo pipefail

# ---------- Color output ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
section() { echo -e "${CYAN}$*${NC}"; }

# ---------- Path configuration ----------
MIGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$(dirname "$MIGRATION_DIR")"
PROJECT_DIR="$CODE_DIR"
CONFIG_FILE="$CODE_DIR/InsertSpeech/config.ini"
if (( $# )); then
    [[ $# == 2 && "$1" == --config ]] || die "Usage: bash ${0##*/} [--config PATH]"
    CONFIG_FILE="$2"
fi
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

install_system_dependencies() {
    local package
    local missing=()
    for package in python3-venv curl xz-utils zstd; do
        if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" != "install ok installed" ]]; then
            missing+=("$package")
        fi
    done
    if (( ${#missing[@]} )); then
        sudo apt-get update -qq
        sudo apt-get install -y "${missing[@]}"
    fi
}

install_local_components() {
    local arch archive stage package
    case "$(uname -m)" in
        x86_64) arch=amd64 ;;
        aarch64) arch=arm64 ;;
        *) die "Unsupported component architecture: $(uname -m)" ;;
    esac
    mkdir -p "$DEPENDENCE_DIR/downloads" "$COMPONENTS_DIR" "$OLLAMA_MODELS" "$HF_HOME"

    if [[ ! -x "$COMPONENTS_DIR/ffmpeg/bin/ffmpeg" || ! -x "$COMPONENTS_DIR/ffmpeg/bin/ffprobe" ]] ||
        ! "$COMPONENTS_DIR/ffmpeg/bin/ffmpeg" -version >/dev/null 2>&1 ||
        ! "$COMPONENTS_DIR/ffmpeg/bin/ffprobe" -version >/dev/null 2>&1; then
        archive="$DEPENDENCE_DIR/downloads/ffmpeg-$arch-static.tar.xz"
        if [[ ! -f "$archive" ]]; then
            info "Downloading FFmpeg: https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-$arch-static.tar.xz"
            curl -fL --retry 3 "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-$arch-static.tar.xz" -o "$archive.part"
            mv "$archive.part" "$archive"
        fi
        stage="$(mktemp -d "$DEPENDENCE_DIR/downloads/ffmpeg.XXXXXX")"
        tar -xJf "$archive" -C "$stage" --strip-components=1
        mkdir -p "$COMPONENTS_DIR/ffmpeg/bin"
        install -m 755 "$stage/ffmpeg" "$stage/ffprobe" "$COMPONENTS_DIR/ffmpeg/bin/"
        # Keep the extracted distribution, including license information, under env_folder.
        mv "$stage" "$COMPONENTS_DIR/ffmpeg/distribution-$(date +%s)"
    fi

    if ! native_components_ready; then
        mkdir -p "$COMPONENTS_DIR/native"
        stage="$(mktemp -d "$DEPENDENCE_DIR/downloads/native.XXXXXX")"
        # Resolve runtime packages locally; libc and the OS loader remain host prerequisites.
        python3 - "$stage" "$COMPONENTS_DIR/native" <<'PY'
import re
import subprocess
import sys
from pathlib import Path

download, destination = map(Path, sys.argv[1:])
pending = ["libopenblas0-pthread", "libomp5-18"]
seen = set()
while pending:
    package = pending.pop()
    if package in seen or re.fullmatch(r"libc6|libgcc-s1|libstdc\+\+6|gcc-.*-base", package):
        continue
    seen.add(package)
    dependencies = subprocess.check_output(
        ["apt-cache", "depends", "--no-recommends", "--no-suggests", "--no-conflicts",
         "--no-breaks", "--no-replaces", "--no-enhances", package], text=True)
    for line in dependencies.splitlines():
        match = re.match(r"\s*(?:PreDepends|Depends): ([a-z0-9.+-]+)(?::\w+)?$", line)
        if match:
            pending.append(match.group(1))
    subprocess.run(["apt-get", "download", package], cwd=download, check=True)
for archive in sorted(download.glob("*.deb")):
    subprocess.run(["dpkg-deb", "-x", str(archive), str(destination)], check=True)
PY
        touch "$COMPONENTS_DIR/native/.complete"
    fi
    # The custom CTranslate2 build requests libomp.so, while runtime packages ship .so.5.
    while IFS= read -r omp_library; do
        if [[ ! -e "${omp_library%.5}" && ! -L "${omp_library%.5}" ]]; then
            ln -s "$(basename "$omp_library")" "${omp_library%.5}"
        fi
    done < <(find "$COMPONENTS_DIR/native" -name libomp.so.5)
    load_native_libraries

    if [[ ! -f "$COMPONENTS_DIR/ollama/.complete" || ! -x "$COMPONENTS_DIR/ollama/bin/ollama" ]]; then
        download_ollama_archive "ollama-linux-$arch"
        touch "$COMPONENTS_DIR/ollama/.complete"
    fi
    if [[ "${SETUP_CORE:-CPU}" == GPU && ! -f "$COMPONENTS_DIR/ollama/.rocm-complete" ]]; then
        download_ollama_archive "ollama-linux-$arch-rocm"
        touch "$COMPONENTS_DIR/ollama/.rocm-complete"
    fi
    hash -r
    components_ready || die "Local components failed validation: $COMPONENTS_DIR"
}

download_ollama_archive() {
    local name="$1" archive stage
    archive="$DEPENDENCE_DIR/downloads/$name.tar.zst"
    if [[ ! -f "$archive" ]]; then
        curl -fL --retry 3 "https://ollama.com/download/$name.tar.zst" -o "$archive.part"
        mv "$archive.part" "$archive"
    fi
    stage="$(mktemp -d "$DEPENDENCE_DIR/downloads/ollama.XXXXXX")"
    tar --zstd -xf "$archive" -C "$stage"
    mkdir -p "$COMPONENTS_DIR/ollama"
    cp -a "$stage/." "$COMPONENTS_DIR/ollama/"
}


create_environment() {
    mkdir -p "$DEPENDENCE_DIR"
    if [[ ! -e "$VENV_DIR" ]]; then
        python3 -m venv "$VENV_DIR"
    elif ! "$VENV_DIR/bin/python" -c 'import sys; assert sys.prefix != sys.base_prefix' 2>/dev/null; then
        echo "Invalid virtual environment: $VENV_DIR. Repair it before continuing." >&2
        return 1
    fi
    source "$VENV_DIR/bin/activate"
    python -m pip --version >/dev/null 2>&1 || python -m ensurepip
}

REQUIREMENTS="$MIGRATION_DIR/requirements.txt"
PIP_PACKAGES="$MIGRATION_DIR/pip_packages"
BASHRC="$HOME/.bashrc"
FASTER_WHISPER_VERSION="1.2.1"
OLLAMA_MODEL="qwen2.5:7b"
CPU_THREADS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"

clear_legacy_env_prefix() {
    local legacy_prefix="JOE""ROGAN"
    local name
    while IFS= read -r name; do
        if [[ "$name" == "${legacy_prefix}_"* ]]; then
            unset "$name"
        fi
    done < <(compgen -v)
}

remove_bashrc_block() {
    local marker="$1"
    local marker_end="$2"
    [[ -f "$BASHRC" ]] || return 0
    python3 - "$BASHRC" "$marker" "$marker_end" << 'PYEOF'
import sys
from pathlib import Path

path = Path(sys.argv[1])
marker = sys.argv[2]
marker_end = sys.argv[3]
text = path.read_text(encoding="utf-8", errors="ignore")
start = text.find(marker)
while start != -1:
    end = text.find(marker_end, start)
    if end == -1:
        break
    end += len(marker_end)
    if end < len(text) and text[end:end + 1] == "\n":
        end += 1
    text = text[:start].rstrip() + "\n" + text[end:].lstrip()
    start = text.find(marker)
path.write_text(text, encoding="utf-8")
PYEOF
}

clear_legacy_env_prefix

# =============================================================================
# 0. System info
# =============================================================================
echo ""
section "========== 0. System Information =========="
info "Hostname      : $(hostname)"
info "OS            : $(lsb_release -sd 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
info "Kernel        : $(uname -r)"
info "Python        : $(python3 --version 2>&1)"
info "CPU threads   : $CPU_THREADS"
info "MIGRATION_DIR : $MIGRATION_DIR"
info "CODE_DIR      : $CODE_DIR"
info "CONFIG_FILE   : $CONFIG_FILE"
info "env_folder    : $DEPENDENCE_DIR"

# =============================================================================
# 1. Check required files
# =============================================================================
section "========== 1. Checking required files =========="

[[ -f "$REQUIREMENTS" ]] || die "Not found: $REQUIREMENTS"
[[ -d "$PIP_PACKAGES" ]] || die "Not found: $PIP_PACKAGES directory"

success "All required files present"

# =============================================================================
# 2. Install system dependencies
# =============================================================================
section "========== 2. Installing system dependencies =========="

install_system_dependencies
SETUP_CORE=CPU
install_local_components
success "System dependencies installed"

# =============================================================================
# 3. Install Ollama
# =============================================================================
section "========== 3. Installing Ollama =========="

start_local_ollama

if ollama show "$OLLAMA_MODEL" >/dev/null 2>&1; then
    success "Model $OLLAMA_MODEL already present"
else
    info "Pulling model $OLLAMA_MODEL (this may take a while)..."
    ollama pull "$OLLAMA_MODEL"
    success "Model $OLLAMA_MODEL pulled"
fi

# =============================================================================
# 4. Create venv
# =============================================================================
section "========== 4. Creating Python venv =========="

create_environment
if [[ -d "$ROCM_INSTALL_DIR/lib" ]]; then
    export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
success "venv activated: $(python3 --version)"

# =============================================================================
# 5. Install Python dependencies (offline, with online fallback)
# =============================================================================
section "========== 5. Installing Python dependencies =========="

if environment_ready; then
    success "Python dependencies already satisfy requirements"
else

if pip install \
    --no-index \
    --find-links="$PIP_PACKAGES" \
    -r "$REQUIREMENTS" \
    --quiet; then
    success "Offline installation complete"
else
    warn "Offline install incomplete, falling back to online..."
    pip install \
        --find-links="$PIP_PACKAGES" \
        -r "$REQUIREMENTS" \
        --quiet
    success "Hybrid installation complete"
fi
fi

if pip show faster-whisper 2>/dev/null | grep -q "Version: $FASTER_WHISPER_VERSION"; then
    success "faster-whisper==$FASTER_WHISPER_VERSION already installed, skipping"
else
    pip install "faster-whisper==$FASTER_WHISPER_VERSION"
    success "faster-whisper==$FASTER_WHISPER_VERSION installed"
fi

# =============================================================================
# 6. Apply CPU environment and remove legacy global settings
# =============================================================================
section "========== 6. Configuring CPU environment =========="

MARKER="# >>> podcast-cpu-env >>>"
MARKER_END="# <<< podcast-cpu-env <<<"
ROCM_MARKER="# >>> podcast-rocm-env >>>"
ROCM_MARKER_END="# <<< podcast-rocm-env <<<"

remove_bashrc_block "$MARKER" "$MARKER_END"
remove_bashrc_block "$ROCM_MARKER" "$ROCM_MARKER_END"

# Runtime paths and mode are loaded by the launchers, not persisted globally.

export AUDIOSOURCE_WHISPER_DEVICE=cpu
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=int8
export AUDIOSOURCE_WHISPER_CPU_THREADS="$CPU_THREADS"
export AUDIOSOURCE_WHISPER_CHUNK_SECONDS=0
export AUDIOSOURCE_MAX_WORKERS=1
export AUDIOSOURCE_USE_PROCESS_POOL=0
export AUDIOSOURCE_OLLAMA_MODEL=qwen2.5:7b

python3 - "$CONFIG_FILE" << 'PYEOF'
import configparser
import os
import sys
from pathlib import Path

if os.getenv("PODCAST_SETUP_AUTO") != "1":
    for config_path in (Path(sys.argv[1]),):
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(config_path, encoding="utf-8")
        if not parser.has_section("RuntimeConfig"):
            parser.add_section("RuntimeConfig")
        parser.set("RuntimeConfig", "CaculateCore", "CPU")
        with config_path.open("w", encoding="utf-8") as handle:
            parser.write(handle)
PYEOF
success "CPU environment configured"

# =============================================================================
# 7. Verification
# =============================================================================
section "========== 7. Verification =========="

info "--- Python packages ---"
pip show faster-whisper | grep -E "Name|Version"
pip show ctranslate2    | grep -E "Name|Version"
pip show edge-tts       | grep -E "Name|Version"
pip show pydub          | grep -E "Name|Version"

info "--- ffmpeg ---"
ffmpeg  -version 2>&1 | head -1 || warn "ffmpeg not found"
ffprobe -version 2>&1 | head -1 || warn "ffprobe not found"

info "--- Ollama ---"
if curl -s "$AUDIOSOURCE_OLLAMA_API" \
    -d "{\"model\":\"$OLLAMA_MODEL\",\"prompt\":\"hi\",\"stream\":false}" \
    --max-time 15 | grep -q "response"; then
    success "Ollama $OLLAMA_MODEL responding"
else
    warn "Ollama not responding - you may need to run 'ollama serve' manually"
fi

info "--- CPU (WhisperModel load) ---"
python3 - << 'PYEOF'
from faster_whisper import WhisperModel
import os
threads = int(os.getenv("AUDIOSOURCE_WHISPER_CPU_THREADS", "1"))
print(f"Loading WhisperModel large-v3 on CPU with {threads} thread(s)...")
m = WhisperModel("large-v3", device="cpu", compute_type="int8", cpu_threads=threads)
print("CPU OK")
PYEOF

success "CPU verification passed"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  CPU deployment complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "To run:"
echo "  cd $CODE_DIR"
echo "  bash insertSpeech.sh"
echo ""
