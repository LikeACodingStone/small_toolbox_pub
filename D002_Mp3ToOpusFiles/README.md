# Music Resampler Qt

PyQt5 desktop tool for scanning music folders, inspecting audio sample rates, converting audio to Opus, and safely deleting original FLAC/MP3 files only when matching Opus outputs exist.

## Features

- Opens any folder and recursively scans audio files.
- Supports `.mp3` and `.flac` inputs. Existing `.opus` files are ignored in the scan list.
- Uses `ffprobe` to detect original sample rate and bitrate.
- Generates an original sample-rate list in the UI table.
- Converts to Opus with `ffmpeg`.
- Automatic target sample-rate mapping based on the previous script:
  - `<= 8 kHz -> 8000 Hz`
  - `<= 12 kHz -> 12000 Hz`
  - `<= 16 kHz -> 16000 Hz`
  - `<= 24 kHz -> 24000 Hz`
  - higher rates -> `48000 Hz`
- Manual max sample-rate selection: `8000`, `12000`, `16000`, `24000`, `48000`. This is an upper limit, not a forced output rate.
- Multi-core scanning and conversion with adjustable worker count.
- Cross-platform support for Windows, Linux, and macOS.
- Independent safe delete function:
  - scans the current table data,
  - checks whether same-name `.opus` exists,
  - deletes only `.flac` and `.mp3`,
  - never deletes source files without a matching Opus output.

## Requirements

- Python 3.10+
- PyQt5
- FFmpeg tools in `PATH`:
  - `ffmpeg`
  - `ffprobe`

## Environment Setup

Use the `EnvSetup` folder for automated dependency setup on Windows, Linux, or macOS.

Windows:

```bat
EnvSetup\setup_windows.bat
```

Linux / macOS:

```bash
bash EnvSetup/setup_unix.sh
```

The setup creates `.venv`, upgrades `pip`, installs `requirements.txt`, and checks whether FFmpeg tools are available. If FFmpeg is missing, it prints the recommended install command for the current platform.

Manual Python dependency install is still possible:

```bash
pip install -r requirements.txt
```

## Run

```bash
python main.py
```

## Workflow

1. Click `Open Folder`.
2. The app scans recursively and fills the table.
3. Choose `Auto mapping` or a max sample-rate limit.
4. Adjust `Workers` if needed. The default is based on CPU core count.
5. Click `Convert to Opus`.
6. After conversion, click `Delete FLAC/MP3 with Opus` if you want to remove original source files.

## Output Rules

- `.mp3 -> .opus`
- `.flac -> .opus`
- Existing `.opus` files are ignored during scanning.

By default, existing Opus outputs are not overwritten. Enable `Overwrite existing opus` to replace them.
