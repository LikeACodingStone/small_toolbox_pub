#!/usr/bin/env bash
# =============================================================================
# setup.sh — Podcast toolchain environment deployment script
# Usage: run "bash setup.sh" from the migration/ directory
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
INSTALLED_DIR="$MIGRATION_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
ROCM_TAR="$MIGRATION_DIR/ctranslate2-rocm.tar.gz"
REQUIREMENTS="$MIGRATION_DIR/requirements.txt"
PIP_PACKAGES="$MIGRATION_DIR/pip_packages"
EXT_SO_NAME="_ext.cpython-312-x86_64-linux-gnu.so"
BASHRC="$HOME/.bashrc"
FASTER_WHISPER_VERSION="1.2.1"
OLLAMA_MODEL="qwen2.5:7b"

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

sudo apt-get update -qq
sudo apt-get install -y libopenblas-dev libomp-dev python3-venv python3-pip curl
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

# =============================================================================
# 7. Replace _ext.so with ROCm build
# =============================================================================
section "========== 7. Replacing ctranslate2 _ext.so =========="

VENV_CT2_DIR="$VENV_DIR/lib/python3.12/site-packages/ctranslate2"
TARGET_EXT_SO="$VENV_CT2_DIR/$EXT_SO_NAME"

[[ -d "$VENV_CT2_DIR" ]] || die "venv ctranslate2 directory not found: $VENV_CT2_DIR"

cp "$TARGET_EXT_SO" "${TARGET_EXT_SO}.bak_cuda"
info "Original CUDA _ext.so backed up"

cp "$EXTRACTED_EXT" "$TARGET_EXT_SO"
success "_ext.so replaced with ROCm build"

# =============================================================================
# 8. Write environment variables to ~/.bashrc
# =============================================================================
section "========== 8. Writing environment variables =========="

MARKER="# >>> podcast-rocm-env >>>"
MARKER_END="# <<< podcast-rocm-env <<<"

if grep -q "$MARKER" "$BASHRC" 2>/dev/null; then
    warn "Environment variables already present in $BASHRC — skipping (remove the block manually to update)"
else
    cat >> "$BASHRC" << EOF

$MARKER
export LD_LIBRARY_PATH=$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}
export JOEROGAN_WHISPER_DEVICE=cuda
export JOEROGAN_WHISPER_COMPUTE_TYPE=float16
export JOEROGAN_MAX_WORKERS=1
export JOEROGAN_OLLAMA_MODEL=qwen2.5:7b
$MARKER_END
EOF
    success "Environment variables written to $BASHRC"
fi

# Apply to current shell immediately
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export JOEROGAN_WHISPER_DEVICE=cuda
export JOEROGAN_WHISPER_COMPUTE_TYPE=float16
export JOEROGAN_MAX_WORKERS=1
export JOEROGAN_OLLAMA_MODEL=qwen2.5:7b

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
echo "  source venv/bin/activate"
echo "  python3 main_batch.py"
echo ""
echo "Note: environment variables load automatically in new terminals (written to ~/.bashrc)"
