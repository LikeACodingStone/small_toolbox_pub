#!/usr/bin/env python3
"""Compile worktree applications and publish source-free Linux releases."""
from __future__ import annotations

import argparse
import ast
import configparser
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from terminal import add_terminal_entry

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {
    'A001': ('A001_EngAudioInsertChNTTS', (), ''),
    'A002': ('A002_PodcastSubtitleToMobi', ('app_ui', 'subtitle_to_ebook'), 'app_ui'),
    'A003': ('A003_BookEnglishInsertCh', ('main_batch', 'book_vocab_module'), 'main_batch'),
    'A004': ('A004_QMeiaPlayer', ('player', 'library'), 'player'),
}


def run(args, **kwargs):
    print('[RUN]', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def source_for(code, worktrees):
    name = TOOLS[code][0]
    # Detect registered worktrees by branch, rather than assuming their folder names.
    result = subprocess.check_output(['git', '-C', str(ROOT), 'worktree', 'list', '--porcelain'], text=True)
    candidates = []
    for block in result.split('\n\n'):
        fields = dict(line.split(' ', 1) for line in block.splitlines() if ' ' in line)
        if fields.get('branch') == 'refs/heads/' + name:
            candidates.append(Path(fields['worktree']))
    candidates += [worktrees / code, worktrees / name]
    for base in candidates:
        for source in (base / name, base):
            marker = 'InsertSpeech/main_batch.py' if code == 'A001' else TOOLS[code][1][0] + '.py'
            if (source / marker).is_file():
                return source.resolve()
    raise RuntimeError(f'{code}: source worktree not found. Create a worktree for branch {name}.')


def compile_modules(code, source, candidate, work, python):
    _, modules, entry = TOOLS[code]
    staged = work / 'source'
    staged.mkdir()
    for module in modules:
        text = (source / (module + '.py')).read_text(encoding='utf-8-sig')
        if code == 'A002' and module == 'app_ui':
            old = 'if __name__ == "__main__":'
            if text.count(old) != 1:
                raise RuntimeError('A002 entry point changed; update packaging adapter.')
            text = text.replace(old, 'def main():')
        if code == 'A003':
            text = text.replace('Path(__file__).resolve().parent', 'Path(os.environ["TOOLBOX_PACKAGE_ROOT"])')
            if module == 'main_batch':
                old = 'sys.executable,\n        str(SCRIPT_DIR / "main_batch.py"),'
                if old not in text:
                    raise RuntimeError('A003 local worker entry point changed; update packaging adapter.')
                text = text.replace(old, 'str(SCRIPT_DIR / "run"),')
                # Existing remote source workers remain usable. Never rsync a binary
                # release over their source checkout using the original --delete path.
                old = 'def sync_project_to_worker(worker, remote_config):\n'
                text = text.replace(old, old + '    if remote_config.get("sync_project") or remote_config.get("setup_if_missing"):\n        raise RuntimeError("Packaged remote mode requires preconfigured source workers; set RemoteSyncProject=0 and RemoteSetupIfMissing=0. Use the source branch to deploy workers.")\n')
        if code == 'A004' and module == 'player':
            text = text.replace('BASE = Path(__file__).resolve().parent', 'BASE = Path(os.environ["TOOLBOX_PACKAGE_ROOT"])')
        ast.parse(text)
        (staged / (module + '.py')).write_text(text)
    (staged / '_build.py').write_text('''from pathlib import Path
from setuptools import setup, Extension
from Cython.Build import cythonize
modules = [Extension(p.stem, [str(p)]) for p in Path('.').glob('*.py') if p.name != '_build.py']
setup(ext_modules=cythonize(modules, compiler_directives={'language_level': 3, 'binding': True, 'annotation_typing': False}))
''')
    lib = candidate / 'lib'
    lib.mkdir()
    run([python, staged / '_build.py', 'build_ext', '--build-lib', lib,
         '--build-temp', work / 'objects', '--parallel', '2'], cwd=staged)
    if len(list(lib.glob('*.so'))) != len(modules):
        raise RuntimeError('Some application modules were not compiled')
    if code == 'A004':
        shutil.copytree(source / 'Icons', candidate / 'Icons')
    if code == 'A003':
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(source / 'config.ini')
        cfg.set('RuntimeConfig', 'RunMode', 'local')
        cfg.set('RemoteConfig', 'RemoteWorkers', '')
        cfg.set('RemoteConfig', 'RemoteSyncProject', '0')
        cfg.set('RemoteConfig', 'RemoteSetupIfMissing', '0')
        for key, value in [('OriginalBookPath', './input'), ('OutputBookPath', './output'), ('WorkPath', './cache')]:
            cfg.set('OriginalConfigPath', key, value)
        with (candidate / 'config.ini').open('w') as f:
            cfg.write(f)
        shutil.copy2(source / 'filter.txt', candidate / 'filter.txt')
        for folder in ('input', 'output', 'cache'):
            (candidate / folder).mkdir()
    return entry


def launcher(code, entry, env_relative):
    return '''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export TOOLBOX_PACKAGE_ROOT="$ROOT"
ENV_DIR="${TOOLBOX_ENV_ROOT:-$ROOT/''' + env_relative + '''}"
PYTHON="$ENV_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo "Missing runtime: $PYTHON. Run Envsetup/setup_tools.sh ''' + code + '''." >&2
    exit 1
fi
export PATH="$ENV_DIR/components/bin:$PATH"
unset PYTHONHOME PYTHONPATH
cd "$ROOT"
exec "$PYTHON" - "$@" <<'BOOTSTRAP'
import importlib, json, os, sys
from pathlib import Path
root = Path(os.environ['TOOLBOX_PACKAGE_ROOT'])
sys.path.insert(0, str(root / 'lib'))
os.environ.setdefault('APP_HOST', '127.0.0.1')
os.environ.setdefault('APP_OPEN_BROWSER', '1')
os.environ.setdefault('APP_LOG_FILE', str(root / 'app_ui_debug.log'))
os.environ.setdefault('APP_STATE_FILE', str(root / 'app_ui_state.json'))
module = importlib.import_module(''' + repr(entry) + ''')
if sys.argv[1:] == ['--self-check']:
    ''' + ({'A002': "module.build_ui()", 'A003': "module.load_config()", 'A004': "assert (root / 'Icons/Play.png').is_file()"}[code]) + '''
    print(json.dumps({'status': 'ok', 'tool': ''' + repr(code) + ''', 'module': module.__file__}))
else:
    sys.exit(module.main())
BOOTSTRAP
'''


def package(code, args):
    source = source_for(code, args.worktrees)
    name = TOOLS[code][0]
    target = args.output / name / ('linux-' + platform.machine())
    env = ROOT / 'Envsetup/environments' / code
    print(f'{code}: {source}\n  -> {target}\n  runtime: {env}', flush=True)
    if args.dry_run:
        return
    if args.setup:
        run([sys.executable, ROOT / 'Envsetup/setup_tools.py', code])
    python = env / '.venv/bin/python'
    if not python.exists():
        raise RuntimeError(f'{code}: run ./Envsetup/setup_tools.sh {code}, or package with --setup')
    run([python, '-c', 'import Cython, setuptools; import sysconfig; from pathlib import Path; assert (Path(sysconfig.get_path("include"))/"Python.h").is_file(), "Install matching Python development headers"'])
    if not shutil.which('gcc'):
        raise RuntimeError('Install build-essential before packaging')
    build = ROOT / 'Envsetup/build' / code
    build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='build-', dir=build))
    candidate = work / 'release'
    if code == 'A001':
        run([sys.executable, ROOT / 'packaging/build_a001.py', source, candidate, env])
        # A001 compiler writes paths relative to its output; adjust at publication.
        for path in (candidate / 'config').glob('*/config.ini'):
            cfg = configparser.ConfigParser(interpolation=None)
            cfg.read(path)
            cfg.set('RuntimeConfig', 'env_folder', os.path.relpath(env, target))
            with path.open('w') as f:
                cfg.write(f)
    else:
        candidate.mkdir()
        entry = compile_modules(code, source, candidate, work, python)
        # Verify the candidate before replacing any published release.
        script = candidate / 'run'
        script.write_text(launcher(code, entry, os.path.relpath(env, candidate)))
        script.chmod(0o755)
        check_env = dict(os.environ, QT_QPA_PLATFORM='offscreen', SDL_AUDIODRIVER='dummy')
        run([script, '--self-check'], cwd='/tmp', env=check_env)
        if code == 'A003':
            run([script, '--help'], cwd='/tmp', env=check_env, stdout=subprocess.DEVNULL)
        script.write_text(launcher(code, entry, os.path.relpath(env, target)))
    add_terminal_entry(candidate, code)
    for binary in candidate.rglob('*.so'):
        if binary.stat().st_size == 0:
            raise RuntimeError(f'Empty compiled module: {binary}')
    executable = candidate / ('podcast' if code == 'A001' else 'run')
    if not executable.read_bytes().startswith(b'#!/usr/bin/env bash\n'):
        raise RuntimeError(f'Invalid executable launcher: {executable}')
    forbidden = [p for p in candidate.rglob('*') if p.suffix in ('.py', '.pyc', '.pyx', '.c')]
    if forbidden:
        raise RuntimeError(f'Unexpected source files in release: {forbidden}')
    manifest = {
        'tool': code, 'branch': name,
        'launch_mode': 'terminal' if code in ('A001', 'A003') else 'ui',
        'source_commit': subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
        'source_dirty': bool(subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()),
        'built_at': datetime.now(timezone.utc).isoformat(),
        'platform': platform.platform(), 'architecture': platform.machine(),
        'runtime': os.path.relpath(env, target),
        'python': subprocess.check_output([str(python), '--version'], text=True).strip(),
        'runtime_packages': subprocess.check_output([str(python), '-m', 'pip', 'freeze'], text=True).splitlines(),
        'sha256': {str(p.relative_to(candidate)): hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in candidate.rglob('*') if p.is_file() and p.name != 'build-manifest.json'},
    }
    (candidate / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        backup = target.with_name(target.name + '.backup-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        target.rename(backup)
    try:
        candidate.rename(target)
    except OSError:
        if backup:
            backup.rename(target)
        raise
    print(f'[OK] Published {target}' + (f'\nPrevious release and its data: {backup}' if backup else ''), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tools', nargs='+', type=lambda value: 'A' + value if value in ('001', '002', '003', '004') else value.upper() if value.lower() != 'all' else 'all', choices=[*TOOLS, 'all'])
    parser.add_argument('--worktrees', type=Path, default=ROOT / '.worktrees')
    parser.add_argument('--output', type=Path, default=ROOT / 'tools')
    parser.add_argument('--setup', action='store_true', help='Install isolated build/runtime dependencies first')
    parser.add_argument('--dry-run', action='store_true', help='Show detected sources and destinations without changes')
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.worktrees = args.worktrees.resolve()
    if platform.system() != 'Linux':
        parser.error('This compiler currently targets Linux. Windows binaries must be built with a Windows adapter.')
    codes = list(TOOLS) if 'all' in args.tools else list(dict.fromkeys(args.tools))
    failures = []
    if not args.dry_run:
        lock_dir = ROOT / 'Envsetup/build'
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = (lock_dir / '.package.lock').open('w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('Another package build is running; wait for it to finish.')
    for code in codes:
        try:
            package(code, args)
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            print(f'[FAILED] {code}: {exc}', file=sys.stderr, flush=True)
            failures.append(code)
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
