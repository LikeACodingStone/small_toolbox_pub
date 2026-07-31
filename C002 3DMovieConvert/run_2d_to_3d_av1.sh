#!/usr/bin/env bash
# Recursive 2D video folder -> 4K Half-SBS 3D AV1 converter.
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
OVERWRITE_EXISTING="${OVERWRITE_EXISTING:-0}"
RUN_ID="$(date +%Y%m%d_%H%M%S)"

[[ -n "${INPUT_FOLDER:-}" ]] || die "INPUT_FOLDER is not set"
[[ -n "${OUTPUT_FOLDER:-}" ]] || die "OUTPUT_FOLDER is not set"
[[ -d "$INPUT_FOLDER" ]] || die "Input folder not found: $INPUT_FOLDER"

mkdir -p "$LOG_DIR" "$WORK_DIR" "$OUTPUT_FOLDER"
INPUT_FOLDER="$(cd "$INPUT_FOLDER" && pwd -P)"
OUTPUT_FOLDER="$(cd "$OUTPUT_FOLDER" && pwd -P)"
LOG_DIR="$(cd "$LOG_DIR" && pwd -P)"
WORK_DIR="$(cd "$WORK_DIR" && pwd -P)"
if [[ -d "$VENV_DIR" ]]; then
    VENV_DIR="$(cd "$VENV_DIR" && pwd -P)"
elif [[ "$VENV_DIR" != /* ]]; then
    VENV_DIR="$SCRIPT_DIR/${VENV_DIR#./}"
fi
LOG_FILE="$LOG_DIR/convert_$RUN_ID.log"
[[ "$INPUT_FOLDER" != "$OUTPUT_FOLDER" ]] || die "Input and output folders must be different"

exec > >(tee -a "$LOG_FILE") 2>&1

section "2D -> 3D Half-SBS AV1 batch"
info "Config       : $CONFIG_FILE"
info "Input folder : $INPUT_FOLDER"
info "Output folder: $OUTPUT_FOLDER"
info "Work dir     : $WORK_DIR"
info "Log          : $LOG_FILE"
info "Depth model  : $DEPTH_MODEL"
info "Device       : $DEVICE"

mapfile -d '' -t INPUT_FILES < <(
    find "$INPUT_FOLDER" \
        \( -path "$OUTPUT_FOLDER" -o \
           -path "$LOG_DIR" -o -path "$WORK_DIR" -o -path "$VENV_DIR" -o \
           -path "$SCRIPT_DIR/installed" -o -path "$SCRIPT_DIR/migration" -o \
           -path "$SCRIPT_DIR/tools" -o -path "$SCRIPT_DIR/.git" \) -prune -o \
        -type f \
        ! -iname 'output_*' \
        ! -iname '*_3D.*' \
        ! -iname '*.part.*' \
        \( -iname '*.mkv' -o -iname '*.mp4' -o -iname '*.mov' -o \
           -iname '*.m4v' -o -iname '*.avi' -o -iname '*.webm' -o \
           -iname '*.ts' -o -iname '*.m2ts' -o -iname '*.mts' -o \
           -iname '*.mpg' -o -iname '*.mpeg' \) \
        -print0 | sort -z
)

TOTAL_FILES="${#INPUT_FILES[@]}"
(( TOTAL_FILES > 0 )) || die "No supported video files found under: $INPUT_FOLDER"
info "Videos found : $TOTAL_FILES"

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

section "Batch convert"
completed=0
skipped=0
failed=0
index=0
declare -A OUTPUT_TARGETS=()

for input_video in "${INPUT_FILES[@]}"; do
    ((index += 1))
    relative_path="${input_video#"$INPUT_FOLDER"/}"
    relative_dir="$(dirname "$relative_path")"
    file_name="$(basename "$relative_path")"
    file_stem="${file_name%.*}"

    if [[ "$relative_dir" == "." ]]; then
        output_dir="$OUTPUT_FOLDER"
    else
        output_dir="$OUTPUT_FOLDER/$relative_dir"
    fi
    output_video="$output_dir/${file_stem}_3D.mkv"

    if [[ -n "${OUTPUT_TARGETS[$output_video]:-}" ]]; then
        warn "[$index/$TOTAL_FILES] Output name collision; skipped: $input_video"
        warn "Target already assigned from: ${OUTPUT_TARGETS[$output_video]}"
        ((skipped += 1))
        continue
    fi
    OUTPUT_TARGETS["$output_video"]="$input_video"

    section "Video $index/$TOTAL_FILES"
    info "Input : $input_video"
    info "Output: $output_video"

    if [[ -s "$output_video" && "$OVERWRITE_EXISTING" != "1" ]]; then
        warn "Output already exists; skipped (set OVERWRITE_EXISTING=1 to replace it)."
        ((skipped += 1))
        continue
    fi

    mkdir -p "$output_dir"
    if "$VENV_PYTHON" "$SCRIPT_DIR/tools/convert_2d_to_3d_hsbs.py" \
        --input "$input_video" \
        --output "$output_video" \
        --work-dir "$WORK_DIR/run_${RUN_ID}_$index" \
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
        --max-work-gb "${MAX_WORK_GB:-200}"
    then
        success "Done: $output_video"
        ((completed += 1))
    else
        warn "Failed: $input_video"
        ((failed += 1))
    fi
done

section "Batch summary"
info "Total    : $TOTAL_FILES"
success "Completed: $completed"
info "Skipped  : $skipped"
if (( failed > 0 )); then
    warn "Failed   : $failed"
    warn "See log: $LOG_FILE"
    exit 1
fi
success "All queued videos handled."
echo "Log: $LOG_FILE"