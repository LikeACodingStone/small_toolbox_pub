#!/usr/bin/env bash
# Start the Linux player from any working directory.
set -euo pipefail

player_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
player_env="$player_dir/.venv-linux"
player_python="${QMEDIA_PYTHON:-python3}"

if ! command -v "$player_python" >/dev/null 2>&1; then
    echo 'Python 3 is required. Ubuntu/Debian: sudo apt install python3 python3-venv' >&2
    exit 1
fi
if ! "$player_python" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo 'Python 3.10 or newer is required (3.12 recommended).' >&2
    exit 1
fi
if [[ ! -x "$player_env/bin/python" ]]; then
    echo 'Creating the Linux Python environment...'
    if ! "$player_python" -m venv "$player_env"; then
        echo 'Cannot create environment. Ubuntu/Debian: sudo apt install python3-venv' >&2
        exit 1
    fi
fi

# Reinstall only on first launch or when requirements change.
if [[ ! -f "$player_env/.requirements-installed" ]] || ! cmp -s "$player_dir/requirements.txt" "$player_env/.requirements-installed"; then
    "$player_env/bin/python" -m pip install -r "$player_dir/requirements.txt"
    cp -- "$player_dir/requirements.txt" "$player_env/.requirements-installed"
fi

if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" && "${QT_QPA_PLATFORM:-}" != offscreen ]]; then
    echo 'A Linux graphical desktop session is required (DISPLAY or WAYLAND_DISPLAY).' >&2
    exit 1
fi
cd -- "$player_dir"
exec "$player_env/bin/python" "$player_dir/player.py" "$@"
