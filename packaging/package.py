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
    'English01_AudioInsertChTTS': ('English01_AudioInsertChTTS', (), ''),
    'English02_SubtitlesToMobi': ('English02_SubtitlesToMobi', ('app_ui', 'subtitle_to_ebook'), 'app_ui'),
    'English03_BookEngInsertCh': ('English03_BookEngInsertCh', ('main_batch', 'book_vocab_module'), 'main_batch'),
    'Audio04_QMeiaPlayer': ('Audio04_QMeiaPlayer', ('player', 'library'), 'player'),
    # A module entry is a top-level file (name) or a package folder (compiled recursively).
    'Audio01_AudioFilterTools': ('Audio01_AudioFilterTools', ('audio_filter_tools',), 'audio_filter_tools.app'),
    'Audio02_Mp3ToOpusFiles': ('Audio02_Mp3ToOpusFiles', ('app', 'main'), 'main'),
    'Audio03_ClassifyMusic': ('Audio03_ClassifyMusic', ('music_file_list_gui', 'recurse_musicfiles', 'extract_musicfiles'),
             'music_file_list_gui'),
    'Video01_3DVideoManager': ('Video01_3DVideoManager', ('av1_3d_video_tool',), 'av1_3d_video_tool'),
}
# Generic PyQt applications: rewrite __file__-relative paths to the release root.
GENERIC = ('Audio01_AudioFilterTools', 'Audio02_Mp3ToOpusFiles', 'Audio03_ClassifyMusic', 'Video01_3DVideoManager')
SELF_CHECK = {'English02_SubtitlesToMobi': 'module.build_ui()', 'English03_BookEngInsertCh': 'module.load_config()',
              'Audio04_QMeiaPlayer': "assert (root / 'Icons/Play.png').is_file()"}
for _code in GENERIC:
    SELF_CHECK[_code] = 'assert callable(module.main)'


BRANCHES = {
    'English01_AudioInsertChTTS': 'English01_AudioInsertChTTS',
    'English02_SubtitlesToMobi': 'English02_SubtitlesToMobi',
    'English03_BookEngInsertCh': 'English03_BookEngInsertCh',
    'Audio04_QMeiaPlayer': 'Audio04_QMeiaPlayer',
    'Audio01_AudioFilterTools': 'Audio01_AudioFilterTools',
    'Audio02_Mp3ToOpusFiles': 'Audio02_Mp3ToOpusFiles',
    'Audio03_ClassifyMusic': 'Audio03_ClassifyMusic',
    'Video01_3DVideoManager': 'Video01_3DVideoManager',
}
# Folder names inside recovered sources, from before tools were named after their branches.
LEGACY_FOLDERS = {'English01_AudioInsertChTTS': 'A001_EngAudioInsertChNTTS'}


def tool_id(value):
    if value.lower() == 'all':
        return 'all'
    for code, branch in BRANCHES.items():
        aliases = (branch, branch.split('_', 1)[0])
        if value.lower() in (alias.lower() for alias in aliases):
            return code
    raise argparse.ArgumentTypeError('Unknown tool. Use ' + ', '.join(b.split('_', 1)[0] for b in BRANCHES.values()) + ' or all.')


def run(args, **kwargs):
    print('[RUN]', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


MARKERS = {'English01_AudioInsertChTTS': 'InsertSpeech/main_batch.py', 'Audio01_AudioFilterTools': 'audio_filter_tools/__init__.py',
           'Audio02_Mp3ToOpusFiles': 'app/__init__.py'}


def source_marker(code):
    """File whose presence identifies a usable source folder."""
    return MARKERS[code] if code in MARKERS else TOOLS[code][1][0] + '.py'


def source_for(code, worktrees):
    name = LEGACY_FOLDERS.get(code, code)
    # Detect registered worktrees by branch, rather than assuming their folder names.
    result = subprocess.check_output(['git', '-C', str(ROOT), 'worktree', 'list', '--porcelain', '-z'], text=True)
    registered = {}
    for block in result.split('\0\0'):
        fields = dict(line.split(' ', 1) for line in block.split('\0') if ' ' in line)
        if 'branch' in fields:
            registered[fields['branch']] = Path(fields['worktree'])
    branch = BRANCHES[code]
    short = branch.split('_', 1)[0]
    # An exact branch match takes precedence over folder naming conventions.
    registered_source = registered.get('refs/heads/' + branch)
    candidates = ([registered_source] if registered_source else
                  [worktrees / short, worktrees / branch])
    for base in candidates:
        if not base.is_dir():
            continue
        actual_branch = subprocess.check_output(
            ['git', '-C', str(base), 'branch', '--show-current'], text=True).strip()
        if actual_branch != branch:
            raise RuntimeError(f'{base}: expected branch {branch}, found {actual_branch or "detached HEAD"}')
        # Current branches are flat; recovered English01 still uses its old folder.
        for source in (base, base / name):
            marker = source_marker(code)
            if (source / marker).is_file():
                return source.resolve()
    raise RuntimeError(f'{short}: source worktree not found. Create a worktree for branch {branch}.')


def rewrite_paths(text, relative):
    """Point __file__-relative lookups at the release, where only .so files exist in lib/."""
    root = '__import__("os").environ["TOOLBOX_PACKAGE_ROOT"]'
    folder = '/'.join(relative.parts[:-1])
    here = f'(Path({root}) / {folder!r})' if folder else f'Path({root})'
    text = text.replace('Path(__file__).resolve().parent.parent', f'Path({root})' if len(relative.parts) == 2 else f'({here}).parent')
    return text.replace('Path(__file__).resolve().parent', here)


def compile_modules(code, source, candidate, work, python):
    _, modules, entry = TOOLS[code]
    staged = work / 'source'
    staged.mkdir()
    expected = 0
    for module in modules:
        package_dir = source / module
        if package_dir.is_dir():
            files = sorted(p for p in package_dir.rglob('*.py') if '__pycache__' not in p.parts)
            for data in package_dir.rglob('*'):
                # Keep user-editable data (e.g. config.env) beside the compiled package.
                if data.is_file() and data.suffix not in ('.py', '.pyc') and '__pycache__' not in data.parts:
                    target = candidate / data.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(data, target)
        else:
            files = [source / (module + '.py')]
        for path in files:
            text = path.read_text(encoding='utf-8-sig')
            relative = path.relative_to(source)
            if code == 'English02_SubtitlesToMobi' and module == 'app_ui':
                old = 'if __name__ == "__main__":'
                if text.count(old) != 1:
                    raise RuntimeError('English02 entry point changed; update packaging adapter.')
                text = text.replace(old, 'def main():')
            if code == 'English03_BookEngInsertCh':
                text = text.replace('Path(__file__).resolve().parent', 'Path(os.environ["TOOLBOX_PACKAGE_ROOT"])')
                if module == 'main_batch':
                    old = 'sys.executable,\n        str(SCRIPT_DIR / "main_batch.py"),'
                    if old not in text:
                        raise RuntimeError('English03 local worker entry point changed; update packaging adapter.')
                    text = text.replace(old, 'str(SCRIPT_DIR / "run"),')
                    # Existing remote source workers remain usable. Never rsync a binary
                    # release over their source checkout using the original --delete path.
                    old = 'def sync_project_to_worker(worker, remote_config):\n'
                    text = text.replace(old, old + '    if remote_config.get("sync_project") or remote_config.get("setup_if_missing"):\n        raise RuntimeError("Packaged remote mode requires preconfigured source workers; set RemoteSyncProject=0 and RemoteSetupIfMissing=0. Use the source branch to deploy workers.")\n')
            if code == 'Audio04_QMeiaPlayer' and module == 'player':
                text = text.replace('BASE = Path(__file__).resolve().parent', 'BASE = Path(os.environ["TOOLBOX_PACKAGE_ROOT"])')
            if code in GENERIC:
                text = rewrite_paths(text, relative)
            ast.parse(text)
            out = staged / relative
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding='utf-8')
            expected += 1
    (staged / '_build.py').write_text('''from pathlib import Path
from setuptools import setup, Extension
from Cython.Build import cythonize
modules = []
for p in sorted(Path('.').rglob('*.py')):
    if p.name != '_build.py':
        modules.append(Extension('.'.join(p.with_suffix('').parts), [str(p)]))
setup(ext_modules=cythonize(modules, compiler_directives={'language_level': 3, 'binding': True, 'annotation_typing': False}))
''')
    lib = candidate / 'lib'
    lib.mkdir()
    run([python, staged / '_build.py', 'build_ext', '--build-lib', lib,
         '--build-temp', work / 'objects', '--parallel', '2'], cwd=staged)
    if len(list(lib.rglob('*.so'))) != expected:
        raise RuntimeError('Some application modules were not compiled')
    if code == 'Audio04_QMeiaPlayer':
        shutil.copytree(source / 'Icons', candidate / 'Icons')
    if code == 'English03_BookEngInsertCh':
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
    ''' + (SELF_CHECK[code]) + '''
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
    print(f'{BRANCHES[code]}: {source}\n  -> {target}\n  runtime: {env}', flush=True)
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
    if code == 'English01_AudioInsertChTTS':
        run([sys.executable, ROOT / 'packaging/build_english01.py', source, candidate, env])
        # English01 compiler writes paths relative to its output; adjust at publication.
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
        if code == 'English03_BookEngInsertCh':
            run([script, '--help'], cwd='/tmp', env=check_env, stdout=subprocess.DEVNULL)
        script.write_text(launcher(code, entry, os.path.relpath(env, target)))
    add_terminal_entry(candidate, code)
    for binary in candidate.rglob('*.so'):
        if binary.stat().st_size == 0:
            raise RuntimeError(f'Empty compiled module: {binary}')
    executable = candidate / ('podcast' if code == 'English01_AudioInsertChTTS' else 'run')
    if not executable.read_bytes().startswith(b'#!/usr/bin/env bash\n'):
        raise RuntimeError(f'Invalid executable launcher: {executable}')
    forbidden = [p for p in candidate.rglob('*') if p.suffix in ('.py', '.pyc', '.pyx', '.c')]
    if forbidden:
        raise RuntimeError(f'Unexpected source files in release: {forbidden}')
    manifest = {
        'tool': code, 'branch': subprocess.check_output(
            ['git', '-C', str(source), 'branch', '--show-current'], text=True).strip(),
        'launch_mode': 'terminal' if code in ('English01_AudioInsertChTTS', 'English03_BookEngInsertCh') else 'ui',
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
    parser.add_argument('tools', nargs='+', type=tool_id, metavar='TOOL',
                        help='English01, English02, English03, Audio04 or all (full branch names also accepted)')
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
