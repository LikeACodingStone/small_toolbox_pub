#!/usr/bin/env bash
# Restart wrapper for long GPU runs. It preserves logs and relies on
# main_batch.py resume checks to skip completed outputs.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/Log"
mkdir -p "$LOG_DIR"

WATCHDOG_LOG="$LOG_DIR/watchdog_$(date +%Y%m%d_%H%M%S).log"
MAX_RESTARTS="${AUDIOSOURCE_WATCHDOG_MAX_RESTARTS:-0}"
RESTART_SLEEP_SECONDS="${AUDIOSOURCE_WATCHDOG_RESTART_SLEEP_SECONDS:-120}"

export AUDIOSOURCE_CLEAR_LOGS="${AUDIOSOURCE_CLEAR_LOGS:-0}"

log() {
    printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$WATCHDOG_LOG"
}

attempt=0
while true; do
    attempt=$((attempt + 1))
    start_epoch="$(date +%s)"

    log "Starting attempt #$attempt"
    log "WATCHDOG_LOG=$WATCHDOG_LOG"
    log "AUDIOSOURCE_CLEAR_LOGS=$AUDIOSOURCE_CLEAR_LOGS"
    log "Runtime defaults are loaded by run.sh from config.ini"

    set +e
    bash "$SCRIPT_DIR/run.sh" "$@" 2>&1 | tee -a "$WATCHDOG_LOG"
    exit_code="${PIPESTATUS[0]}"
    set -e

    end_epoch="$(date +%s)"
    elapsed=$((end_epoch - start_epoch))
    log "Attempt #$attempt exited code=$exit_code elapsed=${elapsed}s"

    if [[ "$exit_code" -eq 0 ]]; then
        log "Batch completed successfully"
        exit 0
    fi

    if [[ "$MAX_RESTARTS" != "0" && "$attempt" -ge "$MAX_RESTARTS" ]]; then
        log "Reached AUDIOSOURCE_WATCHDOG_MAX_RESTARTS=$MAX_RESTARTS; giving up"
        exit "$exit_code"
    fi

    log "Sleeping ${RESTART_SLEEP_SECONDS}s before restart"
    sleep "$RESTART_SLEEP_SECONDS"
done
