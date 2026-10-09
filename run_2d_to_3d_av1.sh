#!/usr/bin/env bash
# Recursive 2D video folder -> source-sized Half-SBS 3D H.265/HEVC converter.
#
# Edit envsetup.env and config.env, then run:
#   bash run_2d_to_3d_av1.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="${BASH_SOURCE[0]}"
if [[ "$SCRIPT_PATH" != /* ]]; then
    SCRIPT_PATH="$SCRIPT_DIR/$(basename "$SCRIPT_PATH")"
fi
ENVSETUP_FILE="${ENVSETUP_FILE:-$SCRIPT_DIR/envsetup.env}"
CONFIG_FILE="${CONFIG_FILE:-$SCRIPT_DIR/config.env}"

ensure_render_group_access() {
    if [[ "${THREEDMOVIE_RENDER_WRAPPED:-0}" == "1" ]]; then
        return 0
    fi

    local current_user current_groups configured_groups bash_bin reexec_cmd arg

    current_user="$(id -un)"
    current_groups="$(id -nG 2>/dev/null || true)"
    case " $current_groups " in
        *" render "*) return 0 ;;
    esac

    configured_groups="$(id -nG "$current_user" 2>/dev/null || true)"
    case " $configured_groups " in
        *" render "*) ;;
        *) return 0 ;;
    esac

    if ! command -v sg >/dev/null 2>&1; then
        echo "[WARN] render group is available, but sg was not found; GPU access may still fail."
        return 0
    fi

    bash_bin="$(command -v bash)"
    printf -v reexec_cmd 'THREEDMOVIE_RENDER_WRAPPED=1 PATH=%q ENVSETUP_FILE=%q CONFIG_FILE=%q %q %q' \
        "$PATH" "$ENVSETUP_FILE" "$CONFIG_FILE" "$bash_bin" "$SCRIPT_PATH"
    for arg in "$@"; do
        printf -v reexec_cmd '%s %q' "$reexec_cmd" "$arg"
    done
    echo "[INFO] Re-executing under the render group so ROCm can access the GPU."
    exec sg render -c "$reexec_cmd"
}

ensure_render_group_access "$@"

if [[ -f "$ENVSETUP_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$ENVSETUP_FILE"
fi

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

format_duration() {
    local total_seconds="${1:-0}"
    local hours=$(( total_seconds / 3600 ))
    local minutes=$(( (total_seconds % 3600) / 60 ))
    local seconds=$(( total_seconds % 60 ))

    if (( hours > 0 )); then
        printf '%dh%02dm%02ds' "$hours" "$minutes" "$seconds"
    elif (( minutes > 0 )); then
        printf '%dm%02ds' "$minutes" "$seconds"
    else
        printf '%ds' "$seconds"
    fi
}

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
OUTPUT_TAG="${OUTPUT_TAG:-_3D_H265}"
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
BATCH_START_SECONDS=$SECONDS
[[ "$INPUT_FOLDER" != "$OUTPUT_FOLDER" ]] || die "Input and output folders must be different"

exec > >(tee -a "$LOG_FILE") 2>&1

section "2D -> 3D Half-SBS H.265/HEVC batch"
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

FFMPEG_BIN="$(command -v ffmpeg || true)"
[[ -n "$FFMPEG_BIN" ]] || die "ffmpeg was not found in PATH."
info "ffmpeg path  : $FFMPEG_BIN"

FFMPEG_ENCODERS="$("$FFMPEG_BIN" -hide_banner -encoders 2>/dev/null || true)"
if ! grep -q '[[:space:]]libx265[[:space:]]' <<<"$FFMPEG_ENCODERS"; then
    die "ffmpeg was built without libx265 H.265/HEVC encoding support."
fi

python3 --version
"$FFMPEG_BIN" -version | sed -n '1p'
if [[ "${REPAIR_EXISTING_AUDIO:-0}" == "1" ]]; then
    info "Audio repair mode: model and H.265 encoder checks are skipped."
    VENV_PYTHON="$(command -v python3)"
else
    X265_HELP="$("$FFMPEG_BIN" -hide_banner -h encoder=libx265 2>/dev/null || true)"
    grep -q 'yuv420p10le' <<<"$X265_HELP" \
        || die "libx265 does not support required 10-bit yuv420p10le output."

    envsetup_check_rocm

    section "Python environment"
    VENV_PYTHON="$VENV_DIR/bin/python3"
    if ! envsetup_prepare_python "$VENV_DIR"; then
        warn "GPU is unavailable; the converter will fall back to CPU until the ROCm stack is fixed."
    fi
fi

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
    output_video="$output_dir/${file_stem}${OUTPUT_TAG}.mkv"

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

    remux_args=()
    if [[ "${REPAIR_EXISTING_AUDIO:-0}" == "1" && ! -s "$output_video" ]]; then
        warn "No existing output to repair; skipped."
        ((skipped += 1))
        continue
    elif [[ -s "$output_video" && "${REPAIR_EXISTING_AUDIO:-0}" == "1" ]]; then
        info "Existing output will keep its video and refresh source audio/subtitles."
        remux_args+=(--remux-existing)
    elif [[ -s "$output_video" && "$OVERWRITE_EXISTING" != "1" ]]; then
        warn "Output already exists; skipped (set OVERWRITE_EXISTING=1 to replace it)."
        ((skipped += 1))
        continue
    fi

    mkdir -p "$output_dir"
    movie_start_seconds=$SECONDS
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
        --depth-edge-radius "${DEPTH_EDGE_RADIUS:-4}" \
        --depth-edge-epsilon "${DEPTH_EDGE_EPSILON:-0.001}" \
        --occlusion-edge-blend "${OCCLUSION_EDGE_BLEND:-0}" \
        --occlusion-edge-width "${OCCLUSION_EDGE_WIDTH:-0}" \
        --occlusion-edge-threshold "${OCCLUSION_EDGE_THRESHOLD:-1.0}" \
        --depth-temporal-response "${DEPTH_TEMPORAL_RESPONSE:-0.12}" \
        --depth-batch-frames "${DEPTH_BATCH_FRAMES:-2}" \
        --scene-cut-threshold "${SCENE_CUT_THRESHOLD:-0.18}" \
        --stereo-warp-mode "${STEREO_WARP_MODE:-anchored}" \
        --test-seconds "${TEST_SECONDS:-}" \
        --output-fps "${OUTPUT_FPS:-source}" \
        --stereo-mode "${STEREO_MODE:-}" \
        --video-codec "libx265" \
        --video-bitrate "${VIDEO_BITRATE:-}" \
        --source-bitrate-multiplier "${SOURCE_BITRATE_MULTIPLIER:-1.00}" \
        --rate-control "${RATE_CONTROL:-vbr}" \
        --crf "$H265_CRF" \
        --preset "$H265_PRESET" \
        --x265-params "${H265_PARAMS:-}" \
        --audio-codec "$AUDIO_CODEC" \
        --audio-bitrate "$AUDIO_BITRATE" \
        --audio-channels "${AUDIO_CHANNELS:-2}" \
        --ffmpeg-threads "$FFMPEG_THREADS" \
        --encoder-queue-frames "${ENCODER_QUEUE_FRAMES:-2}" \
        --max-work-gb "${MAX_WORK_GB:-200}" \
        "${remux_args[@]}"
    then
        movie_elapsed=$((SECONDS - movie_start_seconds))
        success "Done: $output_video (elapsed: $(format_duration "$movie_elapsed"))"
        ((completed += 1))
    else
        movie_elapsed=$((SECONDS - movie_start_seconds))
        warn "Failed: $input_video (elapsed: $(format_duration "$movie_elapsed"))"
        ((failed += 1))
    fi
done

section "Batch summary"
info "Total    : $TOTAL_FILES"
success "Completed: $completed"
info "Skipped  : $skipped"
batch_elapsed=$((SECONDS - BATCH_START_SECONDS))
info "Elapsed  : $(format_duration "$batch_elapsed")"
if (( failed > 0 )); then
    warn "Failed   : $failed"
    warn "See log: $LOG_FILE"
    exit 1
fi
success "All queued videos handled in $(format_duration "$batch_elapsed")."
echo "Log: $LOG_FILE"
