#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-${PROJECT_DIR}/.venv}"

"${PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 10):
    version = ".".join(map(str, sys.version_info[:3]))
    raise SystemExit(f"Python 3.10+ is required. Current version: {version}")
PY

if ! "${PYTHON_BIN}" -m venv --help >/dev/null 2>&1; then
  echo "Python venv is not available for ${PYTHON_BIN}."
  echo "Install it on Ubuntu, then run this script again:"
  echo "  sudo apt install python3-venv python3-pip"
  exit 1
fi

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

VENV_PYTHON="${VENV_DIR}/bin/python"
"${VENV_PYTHON}" -m pip install --upgrade pip
"${VENV_PYTHON}" -m pip install -r "${SCRIPT_DIR}/requirements.txt"

cat <<EOF
Python dependencies are ready.
Virtual environment: ${VENV_DIR}

Run CLI example:
  ${VENV_PYTHON} ${PROJECT_DIR}/subtitle_to_ebook.py /path/to/subtitle_folder --title Lex_Fridman_Podcast

Run web UI:
  bash ${PROJECT_DIR}/start_linux.sh
EOF