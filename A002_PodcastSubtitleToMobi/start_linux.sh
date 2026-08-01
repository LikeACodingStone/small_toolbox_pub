#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export APP_HOST="127.0.0.1"
export APP_OPEN_BROWSER="1"
unset APP_PORT

exec python3 app_ui.py
