#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" - <<'PY'
import sys

if sys.version_info < (3, 10):
    version = ".".join(map(str, sys.version_info[:3]))
    raise SystemExit(f"Python 3.10+ is required. Current version: {version}")
PY

if ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
  echo "pip is not available for ${PYTHON_BIN}."
  echo "Install python3-pip on Ubuntu, then run this script again."
  exit 1
fi

"${PYTHON_BIN}" -m pip install -r "${SCRIPT_DIR}/requirement.txt"

echo "Python dependencies are ready."
echo "Run example:"
echo "  ${PYTHON_BIN} ${SCRIPT_DIR}/subtitle_to_ebook.py /path/to/subtitle_folder --title Lex_Fridman_Podcast"

