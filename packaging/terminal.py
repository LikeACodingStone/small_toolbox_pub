"""Generate a release-local interactive terminal entry, without starting a job."""
from pathlib import Path


def add_terminal_entry(release: Path, code: str):
    if code not in ('A001', 'A003'):
        return
    commands = ('./podcast insert-speech\n./podcast subtitle-only\n./podcast translate-audio'
                if code == 'A001' else './run --help\n./run\n./run --input /path/to/book')
    (release / 'terminal.rc').write_text('''# Interactive shell for this release. No application runs automatically.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || return
printf '\\n%s\\n' 'Available commands (run one yourself):'
cat <<'COMMANDS'
''' + commands + '''
COMMANDS
printf '\\nWorking directory: %s\\n\\n' "$PWD"
PS1='[toolbox \\W]\\$ '
''')
    script = release / 'open-terminal'
    script.write_text('''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# --shell also works over SSH, or when already inside a terminal.
if [[ "${1:-}" == --shell ]]; then
    exec bash --noprofile --rcfile "$ROOT/terminal.rc" -i
fi
if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
    echo "No graphical session. In your terminal run: '$ROOT/open-terminal' --shell" >&2
    exit 1
fi
if [[ -n "${TOOLBOX_TERMINAL:-}" ]]; then
    # An executable name/path, not a command string; it must support -e.
    exec "$TOOLBOX_TERMINAL" -e "$ROOT/open-terminal" --shell
fi
for terminal in x-terminal-emulator gnome-terminal konsole xfce4-terminal xterm; do
    if command -v "$terminal" >/dev/null 2>&1; then
        case "$terminal" in
            gnome-terminal) exec "$terminal" --window -- "$ROOT/open-terminal" --shell ;;
            xfce4-terminal) exec "$terminal" --disable-server --execute "$ROOT/open-terminal" --shell ;;
            *) exec "$terminal" -e "$ROOT/open-terminal" --shell ;;
        esac
    fi
done
echo "No supported terminal found. Install xterm or set TOOLBOX_TERMINAL." >&2
exit 1
''')
    script.chmod(0o755)
