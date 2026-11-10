#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/tools/Audio01_AudioFilterTools/linux-$(uname -m)/run"
if [[ ! -x "$TOOL" ]]; then
    echo "Tool is not packaged. Run: ./package.sh Audio01 --setup" >&2
    exit 1
fi
exec "$TOOL"  "$@"
