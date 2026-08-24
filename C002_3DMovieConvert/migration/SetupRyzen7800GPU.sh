#!/usr/bin/env bash
# =============================================================================
# SetupRyzen7800GPU.sh
#
# Offline AMD RX/RZ 7800 ROCm deployment script.
# It uses the prepared files in migration/:
#   - pip_packages/
#   - requirements.txt
#   - installed/ctranslate2-rocm/
#   - installed/ctranslate2/_ext.cpython-312-x86_64-linux-gnu.so
#   - or ctranslate2-rocm.tar.gz as fallback
#
# Usage:
#   cd /home/dpc/usr/bin/3DMovie
#   bash migration/SetupRyzen7800GPU.sh
# =============================================================================

set -euo pipefail

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
section() { echo -e "\n${CYAN}========== $* ==========${NC}"; }

MIGRATION_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="$(dirname "$MIGRATION_DIR")"
VENV_DIR="${VENV_DIR:-$CODE_DIR/venv}"
INSTALLED_DIR="$MIGRATION_DIR/installed"
ROCM_INSTALL_DIR="$INSTALLED_DIR/ctranslate2-rocm"
ROCM_TAR="$MIGRATION_DIR/ctranslate2-rocm.tar.gz"
REQUIREMENTS="$MIGRATION_DIR/requirements.txt"
PIP_PACKAGES="$MIGRATION_DIR/pip_packages"
EXT_DIR="$INSTALLED_DIR/ctranslate2"
ROCM_PATH="${ROCM_PATH:-/opt/rocm}"

fix_dpkg_dkms_blockers() {
    if [[ -f /var/crash/virtualbox-dkms.0.crash ]]; then
        warn "Removing stale VirtualBox DKMS crash report."
        sudo rm -f /var/crash/virtualbox-dkms.0.crash
    fi

    if command -v dpkg >/dev/null 2>&1 && dpkg --audit | grep -q .; then
        warn "dpkg has unfinished package configuration. Trying to repair it."
        sudo dpkg --configure -a || {
            warn "If this mentions virtualbox-dkms, run:"
            warn "  sudo apt-get remove --purge virtualbox-dkms virtualbox virtualbox-*"
            warn "  sudo apt-get -f install"
            return 1
        }
    fi
}

section "0. System / ROCm information"
info "CODE_DIR      : $CODE_DIR"
info "MIGRATION_DIR : $MIGRATION_DIR"
info "Python3       : $(python3 --version 2>&1 || true)"
info "ROCM_PATH     : $ROCM_PATH"

if [[ -f "$ROCM_PATH/.info/version" ]]; then
    info "ROCm version  : $(cat "$ROCM_PATH/.info/version")"
elif [[ -f "$ROCM_PATH/lib/rocm_version" ]]; then
    info "ROCm version  : $(cat "$ROCM_PATH/lib/rocm_version")"
else
    warn "ROCm version file not found. Continuing; hipcc/rocm-smi check follows."
fi

if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --showproductname || true
else
    warn "rocm-smi not found in PATH"
fi

if [[ -x "$ROCM_PATH/bin/hipcc" ]]; then
    "$ROCM_PATH/bin/hipcc" --version | head -5
else
    warn "hipcc not found at $ROCM_PATH/bin/hipcc. ROCm runtime may be incomplete."
fi

section "1. Check offline package files"
[[ -f "$REQUIREMENTS" ]] || die "Missing: $REQUIREMENTS"
[[ -d "$PIP_PACKAGES" ]] || die "Missing directory: $PIP_PACKAGES"
[[ -d "$ROCM_INSTALL_DIR" || -f "$ROCM_TAR" ]] || die "Missing $ROCM_INSTALL_DIR and fallback tar $ROCM_TAR"
[[ -d "$EXT_DIR" || -f "$ROCM_TAR" ]] || die "Missing $EXT_DIR and fallback tar $ROCM_TAR"
success "Offline package files are ready"

section "2. Install system dependencies"
fix_dpkg_dkms_blockers
sudo apt-get update
sudo apt-get install -y \
    libopenblas-dev \
    libomp-dev \
    python3 \
    python3-dev \
    python3-venv \
    python3-pip \
    ffmpeg
success "System dependencies installed"

section "3. Create Python venv"
if [[ -d "$VENV_DIR" ]]; then
    warn "venv already exists, reusing: $VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    success "venv created: $VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python3"
[[ -x "$VENV_PYTHON" ]] || die "venv python3 not found: $VENV_PYTHON"
"$VENV_PYTHON" -m ensurepip --upgrade || true
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel --quiet
success "venv ready: $("$VENV_PYTHON" --version)"

section "4. Install Python packages from migration/pip_packages"
if "$VENV_PYTHON" -m pip install \
    --no-index \
    --find-links="$PIP_PACKAGES" \
    -r "$REQUIREMENTS"; then
    success "Offline Python package installation complete"
else
    warn "Strict offline install failed. Retrying with online fallback plus local wheels."
    "$VENV_PYTHON" -m pip install \
        --find-links="$PIP_PACKAGES" \
        -r "$REQUIREMENTS"
    success "Python package installation complete"
fi

section "5. Deploy prepared ROCm CTranslate2 files"
if [[ ! -d "$ROCM_INSTALL_DIR" || ! -d "$EXT_DIR" ]]; then
    info "Prepared installed/ tree is incomplete. Extracting fallback tar: $ROCM_TAR"
    mkdir -p "$INSTALLED_DIR"
    tar -xzf "$ROCM_TAR" -C "$INSTALLED_DIR"

    EXTRACTED_ROCM="$INSTALLED_DIR/home/dpc/opt/ctranslate2-rocm"
    EXTRACTED_EXT_SRC_DIR="$INSTALLED_DIR/home/dpc/src/CTranslate2/python/build/lib.linux-x86_64-cpython-312/ctranslate2"

    [[ -d "$EXTRACTED_ROCM" ]] || die "Expected extracted ROCm dir not found: $EXTRACTED_ROCM"
    [[ -d "$EXTRACTED_EXT_SRC_DIR" ]] || die "Expected extracted Python ext dir not found: $EXTRACTED_EXT_SRC_DIR"

    rm -rf "$ROCM_INSTALL_DIR" "$EXT_DIR"
    mkdir -p "$EXT_DIR"
    mv "$EXTRACTED_ROCM" "$ROCM_INSTALL_DIR"
    cp "$EXTRACTED_EXT_SRC_DIR"/_ext.cpython-*.so "$EXT_DIR/"
    rm -rf "$INSTALLED_DIR/home"
fi

[[ -f "$ROCM_INSTALL_DIR/lib/libctranslate2.so.4" ]] || die "Missing ROCm lib: $ROCM_INSTALL_DIR/lib/libctranslate2.so.4"
ROCM_EXT_SO="$(find "$EXT_DIR" -maxdepth 1 -name '_ext.cpython-*.so' | head -1)"
[[ -n "$ROCM_EXT_SO" && -f "$ROCM_EXT_SO" ]] || die "Missing prepared ROCm ctranslate2 _ext.so in $EXT_DIR"
success "Prepared ROCm CTranslate2 files confirmed"

section "6. Replace venv ctranslate2 extension with ROCm build"
SITE_PACKAGES="$("$VENV_PYTHON" - <<'PY'
import site
paths = site.getsitepackages()
print(paths[0])
PY
)"
VENV_CT2_DIR="$SITE_PACKAGES/ctranslate2"
TARGET_EXT_SO="$(find "$VENV_CT2_DIR" -maxdepth 1 -name '_ext.cpython-*.so' | head -1 || true)"

[[ -d "$VENV_CT2_DIR" ]] || die "venv ctranslate2 package not found: $VENV_CT2_DIR"
[[ -n "$TARGET_EXT_SO" && -f "$TARGET_EXT_SO" ]] || die "venv ctranslate2 _ext.so not found in $VENV_CT2_DIR"

if [[ ! -f "${TARGET_EXT_SO}.bak_original" ]]; then
    cp "$TARGET_EXT_SO" "${TARGET_EXT_SO}.bak_original"
    info "Backed up original extension: ${TARGET_EXT_SO}.bak_original"
fi

cp "$ROCM_EXT_SO" "$TARGET_EXT_SO"
success "ROCm ctranslate2 extension installed: $TARGET_EXT_SO"

section "7. Write ROCm runtime env into venv activate"
ACTIVATE_FILE="$VENV_DIR/bin/activate"
MARKER="# >>> 3dmovie-rocm-env >>>"
MARKER_END="# <<< 3dmovie-rocm-env <<<"

"$VENV_PYTHON" - "$ACTIVATE_FILE" "$MARKER" "$MARKER_END" <<'PY'
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
PY

cat >> "$ACTIVATE_FILE" <<EOF

$MARKER
export ROCM_PATH="$ROCM_PATH"
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:$ROCM_PATH/lib:/usr/lib/llvm-18/lib\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
export PATH="$ROCM_PATH/bin:$ROCM_PATH/llvm/bin:\$PATH"
export AUDIOSOURCE_WHISPER_DEVICE=cuda
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=float16
export AUDIOSOURCE_MAX_WORKERS=1
$MARKER_END
EOF

export ROCM_PATH="$ROCM_PATH"
export LD_LIBRARY_PATH="$ROCM_INSTALL_DIR/lib:$ROCM_PATH/lib:/usr/lib/llvm-18/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$ROCM_PATH/bin:$ROCM_PATH/llvm/bin:$PATH"
export AUDIOSOURCE_WHISPER_DEVICE=cuda
export AUDIOSOURCE_WHISPER_COMPUTE_TYPE=float16
export AUDIOSOURCE_MAX_WORKERS=1
success "Runtime environment written to venv activate"

section "8. Verify"
"$VENV_PYTHON" - <<'PY'
import ctranslate2
print("ctranslate2:", ctranslate2.__version__)
print("cuda device count:", ctranslate2.get_cuda_device_count())
print("cuda compute types:", ctranslate2.get_supported_compute_types("cuda"))
PY

if "$VENV_PYTHON" - <<'PY'
from faster_whisper import WhisperModel
print("Loading tiny model on ROCm via device='cuda' ...")
model = WhisperModel("tiny", device="cuda", compute_type="float16")
print("faster-whisper GPU load OK")
PY
then
    success "GPU verification passed"
else
    warn "faster-whisper model load failed. ctranslate2 may still be installed, but model download/GPU runtime needs checking."
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  AMD RX/RZ 7800 ROCm offline setup complete${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "Activate:"
echo "  source \"$VENV_DIR/bin/activate\""
