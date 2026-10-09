#!/usr/bin/env python3
"""Exercise published modules after relocation, without reading source worktrees."""
import configparser
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def run(command, **kwargs):
    return subprocess.run(list(map(str, command)), check=True, timeout=120, **kwargs)


def main():
    with tempfile.TemporaryDirectory(prefix='toolbox release test ') as folder:
        relocated = Path(folder)
        shutil.copytree(ROOT / 'tools', relocated / 'tools', ignore=shutil.ignore_patterns('*.backup-*'))
        (relocated / 'Envsetup').mkdir()
        (relocated / 'Envsetup/environments').symlink_to(ROOT / 'Envsetup/environments', target_is_directory=True)
        env = dict(os.environ, QT_QPA_PLATFORM='offscreen', SDL_AUDIODRIVER='dummy')
        env.pop('PYTHONPATH', None)
        env.pop('PYTHONHOME', None)
        releases = {}
        for manifest in (relocated / 'tools').glob('*/*/build-manifest.json'):
            data = json.loads(manifest.read_text())
            code = data['tool']
            release = manifest.parent
            releases[code] = release
            assert not any(p.suffix in {'.py', '.pyc', '.pyx', '.c'} for p in release.rglob('*'))
            commands = [[release / 'run', '--self-check']] if code != 'A001' else [
                [release / 'podcast', feature, '--self-check']
                for feature in ('insert-speech', 'subtitle-only', 'translate-audio')]
            for command in commands:
                run(command, cwd=relocated, env=env)
            print(f'PASS {code}: relocated release self-check', flush=True)
        assert set(releases) == {'A001', 'A002', 'A003', 'A004'}

        # Exercise the compiled subtitle converter, including its dataclass options.
        source = relocated / 'subtitle input'
        source.mkdir()
        (source / 'sample.srt').write_text('1\n00:00:00,000 --> 00:00:02,000\nThe cat and the dog are here.\n')
        a002 = releases['A002']
        snippet = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import subtitle_to_ebook as app
assert app.__file__.endswith('.so')
options = app.ConversionOptions(folder=Path(sys.argv[2]), output_dir=Path(sys.argv[3]), title='Packaging test', yes=True)
result = app.convert_from_options(options, interactive=False)
assert result.epub_path.is_file(), result
print('PASS A002: actual subtitle-to-EPUB conversion')
'''
        run([ROOT / 'Envsetup/environments/A002/.venv/bin/python', '-c', snippet,
             a002 / 'lib', source, relocated / 'ebooks'], cwd=relocated, env=env)

        # Launch the actual browser UI, poll its HTTP endpoint, then stop it.
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        ui_env = dict(env, APP_OPEN_BROWSER='0', APP_HOST='127.0.0.1', APP_PORT=str(port),
                      APP_LOG_FILE=str(relocated / 'ui.log'), APP_STATE_FILE=str(relocated / 'ui-state.json'),
                      GRADIO_ANALYTICS_ENABLED='False')
        with (relocated / 'ui-process.log').open('w') as log:
            process = subprocess.Popen([str(a002 / 'run')], cwd=relocated, env=ui_env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError((relocated / 'ui-process.log').read_text() + (relocated / 'ui.log').read_text())
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}', timeout=1) as response:
                            assert response.status == 200
                            break
                    except OSError:
                        time.sleep(0.3)
                else:
                    raise RuntimeError('A002 HTTP server did not start')
                print('PASS A002: browser UI serves HTTP', flush=True)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

        # Use only common words and disable external AI/name recognition for this test.
        a003 = releases['A003']
        cfg = configparser.ConfigParser(interpolation=None)
        cfg.read(a003 / 'config.ini')
        cfg.set('ProperNounConfig', 'SkipProperNouns', '0')
        cfg.set('DifficultyConfig', 'MinCandidateLength', '100')
        cfg.set('BookOutputConfig', 'OutputFormat', 'azw3')
        with (a003 / 'config.ini').open('w') as f:
            cfg.write(f)
        book = relocated / 'sample.txt'
        book.write_text('The cat and the dog are here.\n')
        run([a003 / 'run', '--input', book, '--output-dir', relocated / 'books'], cwd=relocated, env=env)
        assert list((relocated / 'books').glob('*.azw3')), 'No A003 AZW3 produced'
        print('PASS A003: actual local book conversion', flush=True)


if __name__ == '__main__':
    main()
