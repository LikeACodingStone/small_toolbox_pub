#!/usr/bin/env bash
# =============================================================================
# SetupRyzen7800GPU.sh - Reserved GPU setup entry.
# Current implementation intentionally runs the book pipeline on CPU.
# =============================================================================

set -euo pipefail

YELLOW='\033[1;33m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo -e "${YELLOW}[WARN] GPU setup is reserved for a later implementation.${NC}"
echo -e "${YELLOW}[WARN] Running CPU setup now.${NC}"
exec bash "$SCRIPT_DIR/SetupCPU.sh" "$@"
