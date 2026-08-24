#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODE_DIR="${SCRIPT_DIR}/code"
PYTHON="${CODE_DIR}/.venv/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
    echo "Virtual environment not found. Run Envsetup/setup_env.sh first." >&2
    exit 1
fi

exec "${PYTHON}" "${CODE_DIR}/toolbox.py" "$@"
