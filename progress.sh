#!/usr/bin/env bash
# Show percentage progress from the newest coordinator log.
# Usage: bash progress.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/Log"
COORDINATOR_PATTERN='Found [0-9]+ book\(s\)|Remote workers configured|Remote batch progress|Batch progress|Dynamic scheduling|Remote preflight OK'
PERCENT_PROGRESS_PATTERN='(Remote chunk progress|Remote batch progress|Batch progress|OCR progress|Text annotation progress|EPUB annotation progress|Remote text chunk annotation progress).* [0-9]+/[0-9]+ \([0-9]+(\.[0-9]+)?%\)'
STATUS_PROGRESS_PATTERN='Distributed worker pool ready|Dynamic scheduling|Dynamic dispatch|Remote book complete|Book complete|Remote batch finished|Batch finished'
PROGRESS_PATTERN="${PERCENT_PROGRESS_PATTERN}|${STATUS_PROGRESS_PATTERN}"

if [[ ! -d "$LOG_DIR" ]]; then
    echo "Log directory not found: $LOG_DIR" >&2
    exit 1
fi

latest_log_by_name() {
    find "$LOG_DIR" -maxdepth 1 -type f -name 'book_batch_*.log' -printf '%p\n' \
        | sort -r \
        | head -1
}

latest_coordinator_log() {
    local candidate
    while IFS= read -r candidate; do
        if grep -Eq "$COORDINATOR_PATTERN" "$candidate"; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done < <(find "$LOG_DIR" -maxdepth 1 -type f -name 'book_batch_*.log' -printf '%p\n' | sort -r)
    return 1
}

LATEST_LOG="$(latest_coordinator_log || true)"
if [[ -z "$LATEST_LOG" ]]; then
    LATEST_LOG="$(latest_log_by_name || true)"
fi

if [[ -z "$LATEST_LOG" ]]; then
    echo "No book batch log found in $LOG_DIR" >&2
    exit 1
fi

echo "Watching coordinator progress: $LATEST_LOG"
echo "Press Ctrl+C to stop watching. Processing will continue."

LAST_PROGRESS="$(grep -Ei "$PERCENT_PROGRESS_PATTERN" "$LATEST_LOG" | tail -1 || true)"
if [[ -n "$LAST_PROGRESS" ]]; then
    echo "Last percentage progress:"
    printf '%s\n' "$LAST_PROGRESS"
else
    echo "No percentage progress line found yet; waiting for updates."
fi

tail -n 0 -F "$LATEST_LOG" \
    | grep --line-buffered -Ei "$PROGRESS_PATTERN"
