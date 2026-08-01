# Audio Filter Tools

PyQt5 desktop utility for cross-platform song synchronization and merge workflows.

## Features

- Windows and Ubuntu platform detection.
- English UI with QSS styling and 25px base font.
- Runtime logs in `logs/`.
- Temporary installer/cache files in `installed/`.
- Mode A: compare two folders and sync/delete songs that only exist on one side.
- Mode B: merge songs from up to five source folders into one selected source folder target, skipping duplicates by artist + song name and writing progress to the merge log. If only one source folder is selected, Mode B cleans that folder internally: deletes numbered-copy files like `(1)`, removes duplicate songs while preferring `.opus`, and renames leading track numbers away.
- Supported audio extensions: `.mp3`, `.flac`, `.opus`, `.aac`.
- Local paths and mounted Samba paths are handled as normal folders.
- ADB paths are supported with `adb:` prefixes.

## Path Examples

```text
C:\Music
/home/user/Music
\\server\share\Music
adb:/sdcard/Music
adb:DEVICE_SERIAL:/sdcard/Music
```

ADB requires `adb` in PATH.

## Setup

Windows:

```bat
EnvSetup\setup_env.bat
```

Ubuntu:

```bash
chmod +x EnvSetup/setup_env.sh
./EnvSetup/setup_env.sh
```

## Run

Windows:

```bat
.venv\Scripts\python main.py
```

Ubuntu:

```bash
.venv/bin/python main.py
```



