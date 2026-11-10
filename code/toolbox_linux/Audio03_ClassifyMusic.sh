#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/tools/Audio03_ClassifyMusic/linux-$(uname -m)/run"
if [[ ! -x "$TOOL" ]]; then
    echo "Tool is not packaged. Run: ./package.sh Audio03 --setup" >&2
    exit 1
fi
exec "$TOOL"  "$@"
