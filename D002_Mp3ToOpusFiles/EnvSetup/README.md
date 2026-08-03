# EnvSetup

Cross-platform environment setup for Music Resampler Qt.

## Windows

```bat
EnvSetup\setup_windows.bat
```

## Linux / macOS

```bash
bash EnvSetup/setup_unix.sh
```

## What it does

- Creates a project virtual environment at `.venv`.
- Upgrades `pip`.
- Installs Python dependencies from `requirements.txt`.
- Checks whether `ffmpeg` and `ffprobe` are available in `PATH`.

FFmpeg itself is not installed automatically because the safest installer depends on the OS and package manager. The setup script prints the recommended install command when FFmpeg is missing.

## Options

```bash
python EnvSetup/setup_env.py --venv .venv
python EnvSetup/setup_env.py --skip-ffmpeg-check
```
