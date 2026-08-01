# Subtitle Notes To Ebook

## Install dependencies on Ubuntu

Run this from the package folder:

```bash
bash install_ubuntu.sh
```

The command line converter mostly uses the Python standard library. Optional
YAML config and the local web UI use packages from `requirement.txt`.

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

## Config file

You can put common options in a JSON or YAML config:

```bash
python3 subtitle_to_ebook.py --config config.example.yaml
```

Command line arguments override config values when both are provided:

```bash
python3 subtitle_to_ebook.py /data/input --config config.example.yaml --title Rick_Beato --yes
```

## Phonetics

Enable phonetic annotations with:

```bash
python3 subtitle_to_ebook.py /data/input --title Rick_Beato --phonetics --yes
```

The bundled `cmudict` package is used automatically and covers roughly 126,000
English words. To override or extend it, pass a local CMUdict-style dictionary:

```bash
python3 subtitle_to_ebook.py /data/input --phonetics --phonetic-dictionary /data/cmudict.txt --yes
```

The source vocabulary list is not changed. Only the generated text is annotated,
for example `soundtrack /ˈsaʊndtræk/[电影配乐]`.

## Local web UI

Run:

```bash
python3 app_ui.py
```

The local launcher automatically opens the browser. When starting `app_ui.py`
directly, open the local URL printed in the terminal. It starts at port `7860`
and automatically uses the next available port if `7860` is already occupied.

On Windows, double-click:

```text
start_windows.bat
```

The Windows launcher uses `pythonw.exe`, so the server runs without leaving a
Command Prompt window open.

If the browser does not open after several seconds, inspect these files in the
project folder:

```text
start_windows_debug.log
app_ui_debug.log
```

The first records launcher/Python discovery, and the second records the server
environment, selected port, HTTP startup events, and uncaught tracebacks.

On Linux, run:

```bash
bash start_linux.sh
```

The UI has `Browse...` folder picker buttons for local Windows/Linux use. In Docker or other
headless environments, mount host folders and type the container paths in the UI,
such as `/data/input` and `/data/output`.

Conversion progress and timestamped processing/output logs are streamed into the
UI. Generated books stay in the selected output folder; temporary copies are
placed in the system temp directory only for the UI download links.

The local UI remembers the last input and output folders in `app_ui_state.json`.
Folder picker selections and manually entered paths used for conversion are
restored automatically the next time the UI starts.

## Docker

Build the lightweight image:

```bash
docker build -t subtitle-to-ebook .
```

Run the web UI:

```bash
docker run --rm -p 7860:7860 \
  -v /your/subtitles:/data/input \
  -v /your/output:/data/output \
  subtitle-to-ebook
```

Run the CLI:

```bash
docker run --rm \
  -v /your/subtitles:/data/input \
  -v /your/output:/data/output \
  subtitle-to-ebook \
  python subtitle_to_ebook.py /data/input --output-dir /data/output --title Rick_Beato --phonetics --yes
```

For richer MOBI conversion with Calibre:

```bash
docker build -f Dockerfile.calibre -t subtitle-to-ebook-calibre .
```
