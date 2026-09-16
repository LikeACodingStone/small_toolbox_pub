#!/usr/bin/env bash
# =============================================================================
# SetupRyzen7800GPU.sh - Podcast toolchain GPU/ROCm environment deployment script
# Usage: run "bash SetupRyzen7800GPU.sh" from the migration/ directory
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
DEPENDENCE_DIR="$(cd "$CODE_DIR/.." && pwd)/DependenceLib"
VENV_DIR="$DEPENDENCE_DIR/.venv"
INSTALLED_DIR="$DEPENDENCE_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"

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
    for package in libopenblas-dev libomp-dev python3-venv python3-pip curl ffmpeg; do
        if [[ "$(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true)" != "install ok installed" ]]; then
            missing+=("$package")
        fi
    done
    if (( ${#missing[@]} )); then
        sudo apt-get update -qq
        sudo apt-get install -y "${missing[@]}"
    fi
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

ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
ROCM_TAR="$MIGRATION_DIR/ctranslate2-rocm.tar.gz"
REQUIREMENTS="$MIGRATION_DIR/requirements.txt"
PIP_PACKAGES="$MIGRATION_DIR/pip_packages"
EXT_SO_NAME="_ext.cpython-312-x86_64-linux-gnu.so"
BASHRC="$HOME/.bashrc"
FASTER_WHISPER_VERSION="1.2.1"
OLLAMA_MODEL="qwen2.5:7b"

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

python3 -c 'import sys, platform; assert sys.version_info[:2] == (3, 12) and platform.machine() == "x86_64", "ROCm archive requires Python 3.12 on x86_64"'

# =============================================================================
# 0. System / GPU / ROCm info
# =============================================================================
echo ""
section "========== 0. System Information =========="
info "Hostname      : $(hostname)"
info "OS            : $(lsb_release -sd 2>/dev/null || grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '"')"
info "Kernel        : $(uname -r)"
info "Python        : $(python3 --version 2>&1)"
info "MIGRATION_DIR : $MIGRATION_DIR"
info "CODE_DIR      : $CODE_DIR"
info "INSTALLED_DIR : $INSTALLED_DIR"

echo ""
section "--- ROCm Version ---"
if [[ -f /opt/rocm/.info/version ]]; then
    info "ROCm version  : $(cat /opt/rocm/.info/version)"
elif [[ -f /opt/rocm/lib/rocm_version ]]; then
    info "ROCm version  : $(cat /opt/rocm/lib/rocm_version)"
else
    warn "ROCm version file not found"
fi

echo ""
section "--- GPU Info (rocm-smi) ---"
if command -v rocm-smi &>/dev/null; then
    rocm-smi --showproductname 2>/dev/null || warn "rocm-smi --showproductname failed"
    rocm-smi 2>/dev/null || warn "rocm-smi failed"
else
    warn "rocm-smi not found in PATH"
fi

echo ""
section "--- hipcc version ---"
if command -v hipcc &>/dev/null; then
    hipcc --version 2>&1 | head -3
else
    warn "hipcc not found in PATH"
fi
echo ""

# =============================================================================
# 1. Check required files
# =============================================================================
section "========== 1. Checking required files =========="

[[ -f "$ROCM_TAR" ]]      || die "Not found: $ROCM_TAR"
[[ -f "$REQUIREMENTS" ]]  || die "Not found: $REQUIREMENTS"
[[ -d "$PIP_PACKAGES" ]]  || die "Not found: $PIP_PACKAGES directory"

success "All required files present"

# =============================================================================
# 2. Install system dependencies
# =============================================================================
section "========== 2. Installing system dependencies =========="

install_system_dependencies
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

# Start ollama service if not running
if ! pgrep -x "ollama" &>/dev/null; then
    info "Starting Ollama service..."
    ollama serve &>/dev/null &
    # Wait for service to be ready
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

# Pull model if not present
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

create_environment
python3 -c 'import sys; assert sys.version_info[:2] == (3, 12), "Existing virtual environment must use Python 3.12 for ROCm"'
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

# =============================================================================
# 5b. Install faster-whisper
# =============================================================================
section "========== 5b. Installing faster-whisper==$FASTER_WHISPER_VERSION =========="

if pip show faster-whisper 2>/dev/null | grep -q "Version: $FASTER_WHISPER_VERSION"; then
    success "faster-whisper==$FASTER_WHISPER_VERSION already installed, skipping"
else
    pip install "faster-whisper==$FASTER_WHISPER_VERSION"
    success "faster-whisper==$FASTER_WHISPER_VERSION installed"
fi

# =============================================================================
# 6. Extract and relocate CTranslate2 ROCm
# =============================================================================
section "========== 6. Deploying CTranslate2 ROCm =========="

mkdir -p "$INSTALLED_DIR"
info "Created installed dir: $INSTALLED_DIR"

if [[ ! -f "$ROCM_INSTALL_DIR/lib/libctranslate2.so.4" || ! -f "$INSTALLED_DIR/ctranslate2/$EXT_SO_NAME" ]]; then
tar -xzf "$ROCM_TAR" -C "$INSTALLED_DIR"
success "Extraction complete"

# Relocate from embedded absolute path to installed/
EXTRACTED_ROCM="$INSTALLED_DIR/home/dpc/opt/ctranslate2-rocm"
EXTRACTED_EXT_SRC="$INSTALLED_DIR/home/dpc/src/CTranslate2/python/build/lib.linux-x86_64-cpython-312/ctranslate2/$EXT_SO_NAME"
EXTRACTED_EXT="$INSTALLED_DIR/ctranslate2/$EXT_SO_NAME"

[[ -d "$EXTRACTED_ROCM" ]]    || die "Expected extracted path not found: $EXTRACTED_ROCM"
[[ -f "$EXTRACTED_EXT_SRC" ]] || die "Expected _ext.so not found: $EXTRACTED_EXT_SRC"

# Relocate ctranslate2-rocm
rm -rf "$ROCM_INSTALL_DIR"
mv "$EXTRACTED_ROCM" "$ROCM_INSTALL_DIR"
info "Relocated ctranslate2-rocm to: $ROCM_INSTALL_DIR"

# Relocate _ext.so to installed/ctranslate2/
mkdir -p "$INSTALLED_DIR/ctranslate2"
mv "$EXTRACTED_EXT_SRC" "$EXTRACTED_EXT"
info "Relocated _ext.so to: $EXTRACTED_EXT"

# Clean up leftover extracted skeleton
rm -rf "$INSTALLED_DIR/home"
info "Cleaned up temporary extraction paths"

[[ -f "$ROCM_INSTALL_DIR/lib/libctranslate2.so.4" ]] \
    || die "libctranslate2.so.4 not found after relocation"
success "libctranslate2.so.4 confirmed"
fi
EXTRACTED_EXT="$INSTALLED_DIR/ctranslate2/$EXT_SO_NAME"

# =============================================================================
# 7. Replace _ext.so with ROCm build
# =============================================================================
section "========== 7. Replacing ctranslate2 _ext.so =========="

VENV_CT2_DIR="$VENV_DIR/lib/python3.12/site-packages/ctranslate2"
TARGET_EXT_SO="$VENV_CT2_DIR/$EXT_SO_NAME"

[[ -d "$VENV_CT2_DIR" ]] || die "venv ctranslate2 directory not found: $VENV_CT2_DIR"

if ! cmp -s "$EXTRACTED_EXT" "$TARGET_EXT_SO"; then
cp "$TARGET_EXT_SO" "${TARGET_EXT_SO}.bak_cuda"
info "Original CUDA _ext.so backed up"

cp "$EXTRACTED_EXT" "$TARGET_EXT_SO"
success "_ext.so replaced with ROCm build"
fi

# =============================================================================
# 8. Write environment variables to ~/.bashrc
# =============================================================================
section "========== 8. Writing environment variables =========="

MARKER="# >>> podcast-rocm-env >>>"
MARKER_END="# <<< podcast-rocm-env <<<"
CPU_MARKER="# >>> podcast-cpu-env >>>"
CPU_MARKER_END="# <<< podcast-cpu-env <<<"

remove_bashrc_block "$MARKER" "$MARKER_END"
remove_bashrc_block "$CPU_MARKER" "$CPU_MARKER_END"

cat >> "$BASHRC" << EOF

$MARKER
export LD_LIBRARY_PATH=$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export AUDIOSOURCE_WHISPER_DEVICE=cuda
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=float16
export AUDIOSOURCE_MAX_WORKERS=1
export AUDIOSOURCE_OLLAMA_MODEL=qwen2.5:7b
$MARKER_END
EOF
success "Environment variables written to $BASHRC"

# Apply to current shell immediately
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export AUDIOSOURCE_WHISPER_DEVICE=cuda
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=float16
export AUDIOSOURCE_MAX_WORKERS=1
export AUDIOSOURCE_OLLAMA_MODEL=qwen2.5:7b

python3 - "$CODE_DIR" << 'PYEOF'
import configparser
import os
import sys
from pathlib import Path

if os.getenv("PODCAST_SETUP_AUTO") != "1":
    for folder in ("InsertSpeech", "SubtitleOnly", "TranslateAudio"):
        config_path = Path(sys.argv[1]) / folder / "config.ini"
        parser = configparser.ConfigParser()
        parser.read(config_path, encoding="utf-8")
        if not parser.has_section("RuntimeConfig"):
            parser.add_section("RuntimeConfig")
        parser.set("RuntimeConfig", "CaculateCore", "GPU")
        with config_path.open("w", encoding="utf-8") as handle:
            parser.write(handle)
PYEOF
success "GPU environment configured"

# =============================================================================
# 9. Verify
# =============================================================================
section "========== 9. Verification =========="

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
    warn "Ollama not responding — you may need to run 'ollama serve' manually"
fi

info "--- GPU (WhisperModel load) ---"
python3 - << 'PYEOF'
from faster_whisper import WhisperModel
print("Loading WhisperModel large-v3 on cuda...")
m = WhisperModel("large-v3", device="cuda", compute_type="float16")
print("GPU OK")
PYEOF

success "GPU verification passed"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  Deployment complete!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "To run:"
echo "  cd $CODE_DIR"
echo "  bash insertSpeech.sh"
echo ""
echo "Note: environment variables load automatically in new terminals (written to ~/.bashrc)"
