#!/usr/bin/env bash
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
VENV_PYTHON="$PROJECT_DIR/venv/bin/python3"

# shellcheck source=/dev/null
source "$PROJECT_DIR/envsetup.env"

echo "=== Project ==="
echo "project: $PROJECT_DIR"
echo "venv python: $VENV_PYTHON"

echo
echo "=== ROCm version files ==="
if [[ -f /opt/rocm/.info/version ]]; then
    cat /opt/rocm/.info/version
elif [[ -f /opt/rocm/lib/rocm_version ]]; then
    cat /opt/rocm/lib/rocm_version
else
    echo "ROCm version file not found"
fi

echo
echo "=== hipconfig ==="
if command -v hipconfig >/dev/null 2>&1; then
    hipconfig --full || true
elif [[ -x /opt/rocm/bin/hipconfig ]]; then
    /opt/rocm/bin/hipconfig --full || true
else
    echo "hipconfig not found"
fi

echo
echo "=== Runtime libraries ==="
ldconfig -p 2>/dev/null | grep -E 'libamdhip64|libhsa-runtime64' || true

echo
echo "=== Environment ==="
printf 'LD_LIBRARY_PATH=%s\n' "${LD_LIBRARY_PATH-}"
printf 'ROCM_PATH=%s\n' "${ROCM_PATH-}"
printf 'HIP_PATH=%s\n' "${HIP_PATH-}"
printf 'HSA_OVERRIDE_GFX_VERSION=%s\n' "${HSA_OVERRIDE_GFX_VERSION-}"
printf 'HIP_VISIBLE_DEVICES=%s\n' "${HIP_VISIBLE_DEVICES-}"
printf 'ROCR_VISIBLE_DEVICES=%s\n' "${ROCR_VISIBLE_DEVICES-}"

echo
echo "=== ROCm device access ==="
envsetup_check_rocm

echo
echo "=== PyTorch package ==="
if [[ -x "$VENV_PYTHON" ]]; then
    "$VENV_PYTHON" -c "import torch; print('torch=', torch.__version__); print('hip=', getattr(torch.version, 'hip', None)); print('torch file=', torch.__file__)" 2>&1 || true
else
    echo "venv Python not found"
fi

echo
echo "=== PyTorch HIP library dependencies ==="
TORCH_HIP_LIBRARY="$("$VENV_PYTHON" -c "import pathlib, torch; print(pathlib.Path(torch.__file__).parent / 'lib' / 'libtorch_hip.so')" 2>/dev/null || true)"
if [[ -f "$TORCH_HIP_LIBRARY" ]]; then
    ldd "$TORCH_HIP_LIBRARY" | grep -E 'amdhip|hsa|not found' || true
else
    echo "libtorch_hip.so not found: $TORCH_HIP_LIBRARY"
fi
