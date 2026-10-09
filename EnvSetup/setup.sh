#!/usr/bin/env bash
# =============================================================================
# setup.sh - Default environment setup entry.
# This project currently uses the CPU conversion path.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/SetupCPU.sh" "$@"
