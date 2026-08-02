#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

export APP_HOST="127.0.0.1"
export APP_OPEN_BROWSER="1"
unset APP_PORT

if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
  exec "${SCRIPT_DIR}/.venv/bin/python" app_ui.py
fi

exec python3 app_ui.py