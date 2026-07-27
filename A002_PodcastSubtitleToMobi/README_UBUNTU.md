# Subtitle Notes To Ebook

## Install dependencies on Ubuntu

Run this from the package folder:

```bash
bash install_ubuntu.sh
```

The current program uses only the Python standard library, so `requirement.txt`
is intentionally empty except for comments. It is still included so the setup is
pip-based and easy to extend later.

## Run

```bash
python3 subtitle_to_ebook.py /path/to/subtitle_folder --title Lex_Fridman_Podcast
```

The program first writes a proofread TXT file and pauses. Type `y` only when you
want it to generate EPUB/MOBI.

Chapters are sorted by the last number in each source filename. For files like
`Lex Fridman Podcast #361.md`, chapter order follows the podcast number.

## Parallel processing

By default, the program processes multiple source files concurrently using the
current CPU core count:

```bash
python3 subtitle_to_ebook.py /path/to/subtitle_folder --title Lex_Fridman_Podcast
```

You can override the worker count:

```bash
python3 subtitle_to_ebook.py /path/to/subtitle_folder --title Lex_Fridman_Podcast --workers 8
```

## Paragraph splitting

`--segments-per-paragraph` is a target paragraph length. The program will not
split immediately in the middle of a sentence; it waits until a sentence-ending
mark such as `.`, `?`, or `!` before starting the next paragraph.

## Optional richer MOBI conversion

The script can create a basic MOBI by itself. If Calibre is installed and
`ebook-convert` is available on PATH, the script will automatically use it for a
richer Kindle conversion.
