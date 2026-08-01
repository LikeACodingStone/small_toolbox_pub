#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p installed/pip_cache installed/tmp
export PIP_CACHE_DIR="$PWD/installed/pip_cache"
export TMPDIR="$PWD/installed/tmp"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 was not found. Please install Python 3.9+ first."
    exit 1
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

. .venv/bin/activate
python3 -m pip install --upgrade pip --cache-dir "$PIP_CACHE_DIR"
python3 -m pip install -r requirements.txt --cache-dir "$PIP_CACHE_DIR"

echo "Environment setup complete."
echo "Run: .venv/bin/python main.py"
