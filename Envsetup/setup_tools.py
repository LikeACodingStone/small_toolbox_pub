#!/usr/bin/env python3
"""Prepare per-tool Linux Python environments independently of source worktrees."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
TOOLS = ['English01_AudioInsertChTTS', 'English02_SubtitlesToMobi', 'English03_BookEngInsertCh', 'Audio04_QMeiaPlayer', 'Audio01_AudioFilterTools', 'Audio02_Mp3ToOpusFiles', 'Audio03_ClassifyMusic', 'Video01_3DVideoManager']


def run(command):
    print('[RUN]', ' '.join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    def tool(value):
        # Accept a full branch name or its short form, e.g. Audio04.
        for name in TOOLS:
            if value.lower() in (name.lower(), name.split('_', 1)[0].lower()):
                return name
        if value == 'all':
            return value
        raise argparse.ArgumentTypeError('Unknown tool. Use one of: ' + ', '.join(TOOLS) + ', all')
    parser.add_argument('tool', type=tool)
    args = parser.parse_args()
    for code in (list(TOOLS) if args.tool == 'all' else [args.tool]):
        env = ROOT / 'environments' / code
        python = env / '.venv/bin/python'
        if not python.exists():
            run([sys.executable, '-m', 'venv', env / '.venv'])
        run([python, '-m', 'pip', 'install', '-r', ROOT / 'requirements/build.txt',
             '-r', ROOT / f'requirements/{code}.txt'])
        required = {'English01_AudioInsertChTTS': ['ffmpeg', 'ffprobe', 'ollama'], 'English02_SubtitlesToMobi': ['ebook-convert'],
                    'English03_BookEngInsertCh': ['ebook-convert', 'pdftoppm', 'pdftotext', 'tesseract', 'ollama'], 'Audio04_QMeiaPlayer': [], 'Audio01_AudioFilterTools': [], 'Audio02_Mp3ToOpusFiles': ['ffmpeg', 'ffprobe'],
                    'Audio03_ClassifyMusic': [], 'Video01_3DVideoManager': []}[code]
        missing = []
        for name in required:
            installed = shutil.which(name)
            if not installed:
                missing.append(name)
                continue
            # English01's runtime uses explicit component paths; other tools use PATH.
            component = 'ffmpeg' if name in ('ffmpeg', 'ffprobe') else 'ollama'
            folder = env / 'components' / (component + '/bin' if code == 'English01_AudioInsertChTTS' else 'bin')
            folder.mkdir(parents=True, exist_ok=True)
            link = folder / name
            if not link.exists() and not link.is_symlink():
                link.symlink_to(installed)
        if missing:
            raise RuntimeError(f'{code}: missing system tools: {", ".join(missing)}. See Envsetup/README.md.')
        print(f'[OK] {code}: {env}')


if __name__ == '__main__':
    main()
