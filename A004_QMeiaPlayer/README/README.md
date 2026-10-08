# QMediaPlayer

Windows and Linux music player for sorting songs into genre folders. All application messages and tooltips are in English.

## Windows

Install Python 3.10 or newer (3.12 recommended), then run:

```bat
py -3 -m pip install -r requirements.txt
py -3 player.py
```

After installing dependencies, double-click `run_player.bat` to start.

## Linux

From a graphical desktop terminal:

```bash
bash run_player.sh
```

The launcher creates `.venv-linux` and installs dependencies on first launch. Later launches reuse the environment; changes to `requirements.txt` trigger dependency installation. You can invoke the script by absolute path from another directory. To select a Python version:

```bash
QMEDIA_PYTHON=python3.12 bash run_player.sh
```

Ubuntu/Debian prerequisites, if missing:

```bash
sudo apt install python3 python3-venv
```

If Qt reports missing xcb libraries:

```bash
sudo apt install libxcb-xinerama0 libxcb-cursor0 libxkbcommon-x11-0 libegl1
```

A graphical session and audio output are required. For xrdp, the system must provide an active remote audio sink. The player repairs a missing `XDG_RUNTIME_DIR` when the current user's runtime directory exists, but does not install or load system audio modules.

## Controls

- **OPEN** selects a source folder and scans subfolders, excluding `tmp_trash`, `classify`, hidden audio files and symbolic links. The player remembers the folder and track, and starts the track from the beginning next time.
- **Genre buttons** immediately move the current file to `../classify/<genre>/` relative to the source folder. Playback continues uninterrupted to the end, then advances. Paused tracks remain paused. Repeated classification is ignored. Playback uses a private temporary file so Windows does not lock the original; this requires temporary disk space for one audio file.
- **VOL- / VOL+** change player volume by 10 percentage points.
- **Previous / Play-Pause / Next** control playback. Random-mode Previous follows navigation history.
- **SEQ / RANDOM** are mutually exclusive; the selected button is red. Sequential playback loops. Random playback shuffles using a timestamp seed, avoids repeats within each round, and avoids repeating the last track at the start of the next round when possible. The random queue is persisted across restarts.
- **DEL** moves the current unclassified track into `<source>/tmp_trash` without confirmation, then advances.
- **DEL PRE** deletes the last actually played track without interrupting the current one. Classified or unavailable previous tracks are not deleted.
- **RESTORE** restores the most recently deleted track to its original location without interrupting playback. Each source folder independently retains up to 10 deleted tracks. Deleting an 11th permanently removes the oldest retained track without confirmation. Restore records survive restarts.
- **SHOW / HIDE** switch between full and compact layouts.
- **X** closes the player. Drag the blue background to move the window.

Moves and restores add a numeric suffix if the destination exists; existing files are never overwritten. Classified tracks leave the pending list immediately; the counter can show `0/N` while that track finishes.

The track name first reduces letter spacing, then font size, then uses an ellipsis if needed. Long folder paths omit leading components. Hover to see full text. The log field shows the most recent brief message; hover to view error details. In compact mode, hover over the background for the latest message.

## Storage and formats

Settings and restore records use SQLite:

- Windows: `%LOCALAPPDATA%\QMediaClassifier\player.db`
- Linux: `$XDG_DATA_HOME/QMediaClassifier/player.db`, defaulting to `~/.local/share/QMediaClassifier/player.db`.

Audio uses pygame/SDL_mixer. MP3, WAV, OGG, Opus (`.opus`) and FLAC are supported by common builds. M4A, AAC and WMA decoding depends on the installed SDL_mixer build. Undecodable files are skipped without deleting them; playback stops if none can be decoded.

## Project files

- `player.py`: UI, playback and application entry point.
- `library.py`: scanning, database, shuffle queue and file operations.
- `Icons/`: only the 27 PNGs used by buttons, including active-mode states.
- `tools/generate_icons.py`: rebuilds high-resolution button artwork; requires Pillow only for development.
- `tests/`: temporary-file and offscreen playback tests.
- `run_player.sh` / `run_player.bat`: Linux / Windows launchers.
- `QMediaPlayer.spec`: Windows PyInstaller configuration.

## Tests

```bash
.venv-linux/bin/python -m unittest discover -s tests -v
```

On Windows:

```bat
py -3 -m unittest discover -s tests -v
```

Tests use temporary directories, generated WAV files and dummy audio, without accessing your music library.

## Windows executable

Build on Windows:

```bat
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --clean QMediaPlayer.spec
```

Output: `dist\QMediaPlayer.exe`. Icons are bundled; the database remains in the user data directory.
