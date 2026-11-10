#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
TOOL="$ROOT/tools/English03_BookEngInsertCh/linux-$(uname -m)/open-terminal"
if [[ ! -x "$TOOL" ]]; then
    echo "Tool is not packaged. Run: ./package.sh English03 --setup" >&2
    exit 1
fi
exec "$TOOL"  "$@"
