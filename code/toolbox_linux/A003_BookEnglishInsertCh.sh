#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/tools/A003_BookEnglishInsertCh/linux-$(uname -m)/open-terminal"
if [[ ! -x "$TOOL" ]]; then
    echo "Tool is not packaged. Run: ./package.sh A003 --setup" >&2
    exit 1
fi
exec "$TOOL"  "$@"
