#!/usr/bin/env bash
# =============================================================================
# stop.sh - Stop local and remote book vocabulary insertion processes
# Usage: bash stop.sh [--close-ssh]
# =============================================================================

set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC} $*"; }
section() { echo -e "${CYAN}$*${NC}"; }

close_ssh_sessions=0
case "${1:-}" in
    "")
        ;;
    --close-ssh)
        close_ssh_sessions=1
        ;;
    --help|-h)
        printf 'Usage: %s [--close-ssh]\n' "$0"
        printf '  Default: stop jobs and keep authenticated SSH sessions alive.\n'
        printf '  --close-ssh: also close the persistent SSH sessions.\n'
        exit 0
        ;;
    *)
        echo "Unknown option: $1" >&2
        printf 'Usage: %s [--close-ssh]\n' "$0" >&2
        exit 2
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR_REAL="$(readlink -f "$SCRIPT_DIR" 2>/dev/null || printf '%s' "$SCRIPT_DIR")"
CONFIG_FILE="$SCRIPT_DIR/config.ini"

read_config_value() {
    local target_section="$1"
    local target_key="$2"
    local default_value="$3"
    [[ -f "$CONFIG_FILE" ]] || { echo "$default_value"; return; }
    awk -F= -v wanted_section="$target_section" -v wanted_key="$target_key" -v default_value="$default_value" '
        function trim(text) {
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", text)
            return text
        }
        function finish() {
            if (found && !done) {
                print value
                done=1
                found=0
            }
        }
        BEGIN {
            section=""
            found=0
            done=0
            value=""
        }
        /^[[:space:]]*\[/ {
            finish()
            section=$0
            gsub(/^[[:space:]]*\[/, "", section)
            gsub(/\][[:space:]]*$/, "", section)
            next
        }
        found {
            if ($0 ~ /^[[:space:]]*$/) {
                finish()
                next
            }
            if ($0 ~ /^[[:space:]]+/ && $0 !~ /^[[:space:]]*#/) {
                continuation=$0
                sub(/^[[:space:]]+/, "", continuation)
                value=value continuation
                next
            }
            finish()
        }
        section == wanted_section {
            key=$1
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
            if (key == wanted_key) {
                value=$0
                sub(/^[^=]*=/, "", value)
                value=trim(value)
                found=1
                next
            }
        }
        END {
            finish()
            if (!done) print default_value
        }
    ' "$CONFIG_FILE"
}

split_csv() {
    tr ',' '\n' \
        | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' \
        | sed 's/^\\$//' \
        | sed 's/\\$//' \
        | sed '/^$/d'
}

remote_target_from_spec() {
    sed 's/:.*$//'
}

remote_project_from_spec() {
    sed 's/^[^:]*://'
}

REMOTE_WORKERS="$(read_config_value "RemoteConfig" "RemoteWorkers" "")"
REMOTE_SSH_OPTIONS="$(read_config_value "RemoteConfig" "RemoteSshOptions" "-o BatchMode=yes -o NumberOfPasswordPrompts=0 -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o ConnectionAttempts=1 -o ServerAliveInterval=30 -o ServerAliveCountMax=3")"
REMOTE_CONTROL_PATH="$(read_config_value "RemoteConfig" "RemoteSshControlPath" "/tmp/bookvocab_remote_ssh")"
REMOTE_CONTROL_PERSIST_SECONDS="$(read_config_value "RemoteConfig" "RemoteSshControlPersistSeconds" "259200")"
REMOTE_SSH_PASSWORD_RETRIES="$(read_config_value "RemoteConfig" "RemoteSshPasswordRetries" "1")"
REMOTE_WORK_PATH="$(read_config_value "RemoteConfig" "RemoteWorkPath" "/tmp/bookvocab_remote")"

regex_escape() {
    sed 's/[.[\*^$()+?{}|]/\\&/g'
}

is_local_work_process() {
    local pid="$1"
    local cmd cwd cwd_real
    [[ "$pid" != "$$" ]] || return 1
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ -n "$cmd" ]] || return 1
    case "$cmd" in
        ssh\ *|/usr/bin/ssh\ *|/bin/ssh\ *)
            return 1
            ;;
    esac
    [[ "$cmd" == *main_batch.py* || "$cmd" == *ebook-convert* || "$cmd" == *pdftoppm* || "$cmd" == *tesseract* || "$cmd" == *"--remote-worker-job"* || "$cmd" == *"$REMOTE_WORK_PATH"* ]] || return 1
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    cwd_real="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
    [[ "$cwd" == "$SCRIPT_DIR" || "$cwd" == "$SCRIPT_DIR/"* ]] && return 0
    [[ "$cwd_real" == "$SCRIPT_DIR_REAL" || "$cwd_real" == "$SCRIPT_DIR_REAL/"* ]] && return 0
    [[ "$cmd" == *"$SCRIPT_DIR"* || "$cmd" == *"$SCRIPT_DIR_REAL"* || "$cmd" == *"$REMOTE_WORK_PATH"* ]] && return 0
    return 1
}

is_local_ssh_control_process() {
    local pid="$1"
    local cmd
    [[ "$pid" != "$$" ]] || return 1
    cmd="$(tr '\0' ' ' <"/proc/$pid/cmdline" 2>/dev/null || true)"
    [[ -n "$cmd" ]] || return 1
    [[ "$cmd" == ssh* && "$cmd" == *"$REMOTE_CONTROL_PATH"* ]] || return 1
    return 0
}

local_work_pids() {
    local pid
    while IFS= read -r pid; do
        if is_local_work_process "$pid"; then
            printf '%s\n' "$pid"
        fi
    done < <(pgrep -f 'main_batch.py|ebook-convert|pdftoppm|tesseract|--remote-worker-job|bookvocab_remote' 2>/dev/null || true)
}

local_ssh_control_pids() {
    local pid
    while IFS= read -r pid; do
        if is_local_ssh_control_process "$pid"; then
            printf '%s\n' "$pid"
        fi
    done < <(pgrep -f "$REMOTE_CONTROL_PATH" 2>/dev/null || true)
}

kill_pid_list() {
    local signal="$1"
    shift
    (($# > 0)) || return 0
    kill "-$signal" "$@" 2>/dev/null || true
}

stop_local_project_processes() {
    section "========== Stopping local project processes =========="
    mapfile -t pids < <(local_work_pids)
    if ((${#pids[@]} == 0)); then
        success "No local project processes found"
        return 0
    fi
    info "Stopping local PID(s): ${pids[*]}"
    kill_pid_list TERM "${pids[@]}"
    sleep 2
    mapfile -t pids < <(local_work_pids)
    kill_pid_list KILL "${pids[@]}"
    success "Local project processes stopped"
}

stop_local_ssh_control_processes() {
    section "========== Closing local SSH control processes =========="
    mapfile -t pids < <(local_ssh_control_pids)
    if ((${#pids[@]} == 0)); then
        success "No local SSH control processes found"
        return 0
    fi
    info "Stopping SSH control PID(s): ${pids[*]}"
    kill_pid_list TERM "${pids[@]}"
    sleep 1
    mapfile -t pids < <(local_ssh_control_pids)
    kill_pid_list KILL "${pids[@]}"
    success "Local SSH control processes stopped"
}

control_socket_for_target() {
    local target="$1"
    local label hash
    label="$(printf '%s' "$target" | sed 's/[^A-Za-z0-9_.-]/_/g; s/^[._]*//; s/[._]*$//')"
    hash="$(printf '%s' "$target" | sha1sum | awk '{print substr($1, 1, 12)}')"
    printf '%s/%s_%s.sock\n' "$REMOTE_CONTROL_PATH" "$label" "$hash"
}

legacy_control_socket_for_spec() {
    local spec="$1"
    local target label hash
    target="$(printf '%s' "$spec" | remote_target_from_spec)"
    label="$(printf '%s' "$target" | sed 's/[^A-Za-z0-9_.-]/_/g; s/^[._]*//; s/[._]*$//')"
    hash="$(printf '%s' "$spec" | sha1sum | awk '{print substr($1, 1, 12)}')"
    printf '%s/%s_%s.sock\n' "$REMOTE_CONTROL_PATH" "$label" "$hash"
}

open_control_connection_if_needed() {
    local target="$1"
    local socket="$2"
    local spec="$3"
    mkdir -p "$REMOTE_CONTROL_PATH"

    local opts
    # shellcheck disable=SC2206
    opts=($REMOTE_SSH_OPTIONS)

    local label legacy_socket candidate
    label="$(printf '%s' "$target" | sed 's/[^A-Za-z0-9_.-]/_/g; s/^[._]*//; s/[._]*$//')"
    legacy_socket="$(legacy_control_socket_for_spec "$spec")"
    local candidates=("$socket" "$legacy_socket")
    shopt -s nullglob
    candidates+=("$REMOTE_CONTROL_PATH"/"$label"_*.sock)
    shopt -u nullglob

    for candidate in "${candidates[@]}"; do
        [[ -S "$candidate" ]] || continue
        if ssh "${opts[@]}" -o ControlMaster=auto -S "$candidate" -O check "$target" >/dev/null 2>&1; then
            ACTIVE_CONTROL_SOCKET="$candidate"
            info "Reusing SSH control connection to $target"
            return 0
        fi
        warn "Removing stale SSH control socket for $target"
        rm -f "$candidate"
    done

    local retries attempt
    retries="$REMOTE_SSH_PASSWORD_RETRIES"
    [[ "$retries" =~ ^[0-9]+$ ]] || retries=3
    ((retries > 0)) || retries=3

    for ((attempt = 1; attempt <= retries; attempt++)); do
        info "Open non-interactive SSH control connection to $target (attempt $attempt/$retries)"
        if ssh "${opts[@]}" -M -S "$socket" -o "ControlPersist=$REMOTE_CONTROL_PERSIST_SECONDS" -fN "$target"; then
            ACTIVE_CONTROL_SOCKET="$socket"
            return 0
        fi
        rm -f "$socket"
        if ((attempt < retries)); then
            warn "Non-interactive SSH failed for $target. Check SSH key authentication."
        fi
    done
    return 1
}

stop_remote_worker() {
    local spec="$1"
    local target project socket
    target="$(printf '%s' "$spec" | remote_target_from_spec)"
    project="$(printf '%s' "$spec" | remote_project_from_spec)"
    socket="$(control_socket_for_target "$target")"
    ACTIVE_CONTROL_SOCKET="$socket"

    section "========== Stopping remote $target =========="
    if ! open_control_connection_if_needed "$target" "$socket" "$spec"; then
        warn "Cannot connect to $target; skipping"
        return 0
    fi
    socket="$ACTIVE_CONTROL_SOCKET"

    local ssh_cmd=(ssh)
    # shellcheck disable=SC2206
    local opts=($REMOTE_SSH_OPTIONS)
    ssh_cmd+=("${opts[@]}")
    ssh_cmd+=(-o ControlMaster=auto -S "$socket")
    ssh_cmd+=("$target")

    local quoted_project quoted_remote_work
    printf -v quoted_project '%q' "$project"
    printf -v quoted_remote_work '%q' "$REMOTE_WORK_PATH"

    "${ssh_cmd[@]}" "PROJECT_PATH=$quoted_project REMOTE_WORK_PATH=$quoted_remote_work bash -s" <<'REMOTE_STOP' || true
set +e
if [[ "$PROJECT_PATH" == "~" ]]; then
    PROJECT_PATH="$HOME"
elif [[ "$PROJECT_PATH" == "~/"* ]]; then
    PROJECT_PATH="$HOME/${PROJECT_PATH:2}"
fi
PROJECT_RE="$(printf '%s' "$PROJECT_PATH" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
WORK_RE="$(printf '%s' "$REMOTE_WORK_PATH" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
pkill -TERM -f "$PROJECT_RE.*main_batch.py" 2>/dev/null
pkill -TERM -f "main_batch.py.*--remote-worker-job.*$WORK_RE" 2>/dev/null
pkill -TERM -f "ebook-convert.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
pkill -TERM -f "pdftoppm.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
pkill -TERM -f "tesseract.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
sleep 2
pkill -KILL -f "$PROJECT_RE.*main_batch.py" 2>/dev/null
pkill -KILL -f "main_batch.py.*--remote-worker-job.*$WORK_RE" 2>/dev/null
pkill -KILL -f "ebook-convert.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
pkill -KILL -f "pdftoppm.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
pkill -KILL -f "tesseract.*($PROJECT_RE|$WORK_RE)" 2>/dev/null
REMOTE_STOP

    if ((close_ssh_sessions)); then
        local exit_cmd=(ssh)
        exit_cmd+=("${opts[@]}")
        exit_cmd+=(-S "$socket" -O exit "$target")
        "${exit_cmd[@]}" >/dev/null 2>&1 || true
        success "Remote project processes stopped and SSH session closed on $target"
    else
        success "Remote project processes stopped; SSH session kept alive on $target"
    fi
}

stop_remote_project_processes() {
    section "========== Stopping remote project processes =========="
    if [[ -z "$REMOTE_WORKERS" ]]; then
        warn "No RemoteWorkers configured"
        return 0
    fi

    local worker_specs=()
    local spec
    mapfile -t worker_specs < <(printf '%s' "$REMOTE_WORKERS" | split_csv)
    info "Configured remote workers: ${#worker_specs[@]}"

    for spec in "${worker_specs[@]}"; do
        stop_remote_worker "$spec"
    done
}

stop_local_project_processes
stop_remote_project_processes
if ((close_ssh_sessions)); then
    stop_local_ssh_control_processes
else
    info "Keeping SSH control sessions alive for ${REMOTE_CONTROL_PERSIST_SECONDS} seconds"
fi
success "Stop command complete"
