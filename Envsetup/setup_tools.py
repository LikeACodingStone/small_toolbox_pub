#!/usr/bin/env python3
"""Prepare per-tool Linux Python environments independently of source worktrees."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def run(command):
    print('[RUN]', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tool', choices=['A001', 'A002', 'A003', 'A004', 'all'])
    args = parser.parse_args()
    for code in (['A001', 'A002', 'A003', 'A004'] if args.tool == 'all' else [args.tool]):
        env = ROOT / 'environments' / code
        python = env / '.venv/bin/python'
        if not python.exists():
            run([sys.executable, '-m', 'venv', env / '.venv'])
        run([python, '-m', 'pip', 'install', '-r', ROOT / 'requirements/build.txt',
             '-r', ROOT / f'requirements/{code}.txt'])
        required = {'A001': ['ffmpeg', 'ffprobe', 'ollama'], 'A002': ['ebook-convert'],
                    'A003': ['ebook-convert', 'pdftoppm', 'pdftotext', 'tesseract', 'ollama'], 'A004': []}[code]
        missing = []
        for name in required:
            installed = shutil.which(name)
            if not installed:
                missing.append(name)
                continue
            # A001's runtime uses explicit component paths; other tools use PATH.
            component = 'ffmpeg' if name in ('ffmpeg', 'ffprobe') else 'ollama'
            folder = env / 'components' / (component + '/bin' if code == 'A001' else 'bin')
            folder.mkdir(parents=True, exist_ok=True)
            link = folder / name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(installed)
        if missing:
            raise RuntimeError(f'{code}: missing system tools: {", ".join(missing)}. See Envsetup/README.md.')
        print(f'[OK] {code}: {env}')


if __name__ == '__main__':
    main()
