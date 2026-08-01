# Music Resampler Qt

PyQt5 desktop tool for scanning music folders, inspecting audio sample rates, converting audio to Opus, and safely deleting original FLAC/MP3 files only when matching Opus outputs exist.

## Features

- Opens any folder and recursively scans audio files.
- Supports `.mp3`, `.flac`, and `.opus` inputs.
- Uses `ffprobe` to detect original sample rate and bitrate.
- Generates an original sample-rate list in the UI table.
- Converts to Opus with `ffmpeg`.
- Supports Opus-to-Opus resampling. Existing `.opus` files are written as `name.resampled.opus`.
- Automatic target sample-rate mapping based on the previous script:
  - `<= 8 kHz -> 8000 Hz`
  - `<= 12 kHz -> 12000 Hz`
  - `<= 16 kHz -> 16000 Hz`
  - `<= 24 kHz -> 24000 Hz`
  - higher rates -> `48000 Hz`
- Manual target sample-rate selection: `8000`, `12000`, `16000`, `24000`, `48000`.
- Multi-core scanning and conversion with adjustable worker count.
- Cross-platform support for Windows and Linux.
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

Install Python dependency:

```bash
pip install -r requirements.txt
```

Install FFmpeg:

```bash
# Ubuntu / Debian
sudo apt update
sudo apt install ffmpeg
```

On Windows, install FFmpeg and add the `bin` folder containing `ffmpeg.exe` and `ffprobe.exe` to `PATH`.

## Run

```bash
python main.py
```

## Workflow

1. Click `Open Folder`.
2. The app scans recursively and fills the table.
3. Choose `Auto mapping` or a manual target sample rate.
4. Adjust `Workers` if needed. The default is based on CPU core count.
5. Click `Convert to Opus`.
6. After conversion, click `Delete FLAC/MP3 with Opus` if you want to remove original source files.

## Output Rules

- `.mp3 -> .opus`
- `.flac -> .opus`
- `.opus -> .resampled.opus`

By default, existing Opus outputs are not overwritten. Enable `Overwrite existing opus` to replace them.
