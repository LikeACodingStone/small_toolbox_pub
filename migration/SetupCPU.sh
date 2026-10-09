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
VENV_DIR="$CODE_DIR/venv"
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

sudo apt-get update -qq
sudo apt-get install -y libopenblas-dev libomp-dev python3-venv python3-pip curl ffmpeg
success "System dependencies installed"

# =============================================================================
# 3. Install Ollama
# =============================================================================
section "========== 3. Installing Ollama =========="

if command -v ollama &>/dev/null; then
    success "Ollama already installed: $(ollama --version 2>&1)"
else
    info "Downloading and installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    success "Ollama installed"
fi

if ! pgrep -x "ollama" &>/dev/null; then
    info "Starting Ollama service..."
    ollama serve &>/dev/null &
    for i in {1..15}; do
        if curl -s http://localhost:11434 &>/dev/null; then
            success "Ollama service is up"
            break
        fi
        info "Waiting for Ollama to start... ($i/15)"
        sleep 2
    done
else
    success "Ollama service already running"
fi

if ollama list 2>/dev/null | grep -q "$OLLAMA_MODEL"; then
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

if [[ -d "$VENV_DIR" ]]; then
    warn "venv already exists, skipping creation: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    success "venv created: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
success "venv activated: $(python3 --version)"

# =============================================================================
# 5. Install Python dependencies (offline, with online fallback)
# =============================================================================
section "========== 5. Installing Python dependencies =========="

pip install --upgrade pip --quiet

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

if pip show faster-whisper 2>/dev/null | grep -q "Version: $FASTER_WHISPER_VERSION"; then
    success "faster-whisper==$FASTER_WHISPER_VERSION already installed, skipping"
else
    pip install "faster-whisper==$FASTER_WHISPER_VERSION"
    success "faster-whisper==$FASTER_WHISPER_VERSION installed"
fi

# =============================================================================
# 6. Write CPU environment variables
# =============================================================================
section "========== 6. Writing CPU environment variables =========="

MARKER="# >>> podcast-cpu-env >>>"
MARKER_END="# <<< podcast-cpu-env <<<"
ROCM_MARKER="# >>> podcast-rocm-env >>>"
ROCM_MARKER_END="# <<< podcast-rocm-env <<<"

remove_bashrc_block "$MARKER" "$MARKER_END"
remove_bashrc_block "$ROCM_MARKER" "$ROCM_MARKER_END"

cat >> "$BASHRC" << EOF

$MARKER
export AUDIOSOURCE_WHISPER_DEVICE=cpu
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=int8
export AUDIOSOURCE_WHISPER_CPU_THREADS=$CPU_THREADS
export AUDIOSOURCE_WHISPER_CHUNK_SECONDS=0
export AUDIOSOURCE_MAX_WORKERS=1
export AUDIOSOURCE_USE_PROCESS_POOL=0
export AUDIOSOURCE_OLLAMA_MODEL=qwen2.5:7b
$MARKER_END
EOF
success "CPU environment variables written to $BASHRC"

export AUDIOSOURCE_WHISPER_DEVICE=cpu
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=int8
export AUDIOSOURCE_WHISPER_CPU_THREADS="$CPU_THREADS"
export AUDIOSOURCE_WHISPER_CHUNK_SECONDS=0
export AUDIOSOURCE_MAX_WORKERS=1
export AUDIOSOURCE_USE_PROCESS_POOL=0
export AUDIOSOURCE_OLLAMA_MODEL=qwen2.5:7b

python3 - "$CODE_DIR/config.ini" << 'PYEOF'
import configparser
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
parser = configparser.ConfigParser()
parser.read(config_path, encoding="utf-8")
if not parser.has_section("RuntimeConfig"):
    parser.add_section("RuntimeConfig")
parser.set("RuntimeConfig", "CaculateCore", "CPU")
with config_path.open("w", encoding="utf-8") as handle:
    parser.write(handle)
PYEOF
success "config.ini RuntimeConfig.CaculateCore set to CPU"

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
if curl -s http://localhost:11434/api/generate \
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
echo "  bash run.sh"
echo ""
