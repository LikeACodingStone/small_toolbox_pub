#!/usr/bin/env python3
"""Print PyTorch ROCm diagnostics for the 3DMovie runtime."""

from __future__ import annotations

import os
import sys
import traceback


def main() -> int:
    print("python:", sys.executable)
    print("env HIP_VISIBLE_DEVICES:", os.environ.get("HIP_VISIBLE_DEVICES"))
    print("env ROCR_VISIBLE_DEVICES:", os.environ.get("ROCR_VISIBLE_DEVICES"))
    print("env HSA_OVERRIDE_GFX_VERSION:", os.environ.get("HSA_OVERRIDE_GFX_VERSION"))

    try:
        import torch
    except Exception:
        print("torch import failed:")
        traceback.print_exc()
        return 1

    print("torch:", torch.__version__)
    print("torch.version.hip:", getattr(torch.version, "hip", None))
    print("torch.version.cuda:", getattr(torch.version, "cuda", None))

    try:
        print("cuda/rocm available:", torch.cuda.is_available())
    except Exception:
        print("torch.cuda.is_available failed:")
        traceback.print_exc()

    try:
        print("device count:", torch.cuda.device_count())
    except Exception:
        print("torch.cuda.device_count failed:")
        traceback.print_exc()

    try:
        if torch.cuda.is_available():
            print("device name:", torch.cuda.get_device_name(0))
        else:
            print("device name: none")
    except Exception:
        print("torch.cuda.get_device_name failed:")
        traceback.print_exc()

    try:
        tensor = torch.empty(1, device="cuda")
        print("cuda tensor:", tensor)
    except Exception:
        print("cuda tensor allocation failed:")
        traceback.print_exc()
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
