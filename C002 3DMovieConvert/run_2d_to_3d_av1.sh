#!/usr/bin/env bash
# One-click 2D video -> 4K Half-SBS 3D AV1 converter.
#
# Edit config.env, then run:
#   bash run_2d_to_3d_av1.sh

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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/config.env}"
cd "$SCRIPT_DIR"

[[ -f "$CONFIG_FILE" ]] || die "Config file not found: $CONFIG_FILE"
set -a
source "$CONFIG_FILE"
set +a

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/venv}"
LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
WORK_DIR="${WORK_DIR:-$SCRIPT_DIR/work_2d_to_3d}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/convert_$RUN_ID.log"

mkdir -p "$LOG_DIR" "$WORK_DIR"

exec > >(tee -a "$LOG_FILE") 2>&1

section "2D -> 3D Half-SBS AV1"
info "Config      : $CONFIG_FILE"
info "Input       : $INPUT_VIDEO"
info "Output      : $OUTPUT_VIDEO"
info "Work dir    : $WORK_DIR"
info "Log         : $LOG_FILE"
info "Depth model : $DEPTH_MODEL"
info "Device      : $DEVICE"

[[ -f "$INPUT_VIDEO" ]] || die "Input video not found: $INPUT_VIDEO"

section "System check"
command -v python3 >/dev/null 2>&1 || die "python3 not found"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg not found. Install ffmpeg first."
command -v ffprobe >/dev/null 2>&1 || die "ffprobe not found. Install ffmpeg first."

python3 --version
ffmpeg -version | head -1

if command -v rocm-smi >/dev/null 2>&1; then
    rocm-smi --showproductname || true
else
    warn "rocm-smi not found; GPU may still work if PyTorch ROCm is installed."
fi

section "Python venv"
if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
    success "Created venv: $VENV_DIR"
else
    success "Using existing venv: $VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
VENV_PYTHON="$VENV_DIR/bin/python3"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

section "Python dependencies"
"$VENV_PYTHON" -m pip install numpy pillow opencv-python tqdm transformers accelerate safetensors

if ! "$VENV_PYTHON" - <<'PY'
import torch
print(torch.__version__)
PY
then
    warn "PyTorch is not installed. Installing ROCm PyTorch wheels."
    "$VENV_PYTHON" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/rocm6.3
fi

"$VENV_PYTHON" - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda/rocm available:", torch.cuda.is_available())
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY

section "Convert"
"$VENV_PYTHON" "$SCRIPT_DIR/tools/convert_2d_to_3d_hsbs.py" \
    --input "$INPUT_VIDEO" \
    --output "$OUTPUT_VIDEO" \
    --work-dir "$WORK_DIR/run_$RUN_ID" \
    --depth-model "$DEPTH_MODEL" \
    --device "$DEVICE" \
    --output-width "$OUTPUT_WIDTH" \
    --output-height "$OUTPUT_HEIGHT" \
    --max-disparity "$MAX_DISPARITY" \
    --depth-gamma "$DEPTH_GAMMA" \
    --convergence "$CONVERGENCE" \
    --test-seconds "${TEST_SECONDS:-}" \
    --crf "$AV1_CRF" \
    --preset "$AV1_PRESET" \
    --audio-codec "$AUDIO_CODEC" \
    --audio-bitrate "$AUDIO_BITRATE" \
    --audio-channels "${AUDIO_CHANNELS:-2}" \
    --ffmpeg-threads "$FFMPEG_THREADS" \
    --frame-ext "$FRAME_EXT"

success "Done: $OUTPUT_VIDEO"
echo "Log: $LOG_FILE"
