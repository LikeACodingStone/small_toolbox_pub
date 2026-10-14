#!/usr/bin/env bash
# Usage: ./package.sh {English01|English02|English03|Audio04|all} [options]
# Full current branch names are also accepted. Sources are resolved by branch;
# run ./add_worktrees.sh first to create/update them from origin.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON_BIN:-python3}" "$ROOT/packaging/package.py" "$@"
