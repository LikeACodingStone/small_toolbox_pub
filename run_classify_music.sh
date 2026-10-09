#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/EnvSetup/linux_venv"
PYTHON_EXE="$VENV_DIR/bin/python"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [ ! -x "$PYTHON_EXE" ]; then
    echo "Creating the Linux Python environment..."
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "Python 3 was not found. Install Python 3 with venv support, then try again." >&2
        exit 1
    fi
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$PYTHON_EXE" -c 'import PyQt5' >/dev/null 2>&1; then
    echo "Installing PyQt5. This is needed only once per environment..."
    "$PYTHON_EXE" -m pip install --disable-pip-version-check -r "$SCRIPT_DIR/requirements.txt"
fi

exec "$PYTHON_EXE" "$SCRIPT_DIR/music_file_list_gui.py"
