#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

# shellcheck source=/dev/null
source "$PROJECT_DIR/envsetup.env"

echo "=== PyTorch ROCm index: $ROCM_TORCH_INDEX_URL ==="
if [[ -x "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" -m pip index versions torch --index-url "$ROCM_TORCH_INDEX_URL" || true
else
    echo "venv python not found: $VENV_PYTHON"
fi
