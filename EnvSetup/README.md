# Environment Setup

This folder contains dependency and deployment files for the project. The project root keeps the app code and launch scripts.

## Ubuntu

Run from the project root:

```bash
bash EnvSetup/install_ubuntu.sh
```

The script creates a project-local virtual environment at `.venv` and installs packages from `EnvSetup/requirements.txt`. This avoids Ubuntu's `externally-managed-environment` / PEP 668 error and keeps system Python unchanged.

If Ubuntu reports that `venv` is unavailable, install the OS package first:

```bash
sudo apt install python3-venv python3-pip
```

After setup, run the web UI with:

```bash
bash start_linux.sh
```

Run the CLI directly with:

```bash
.venv/bin/python subtitle_to_ebook.py /path/to/subtitle_folder --title Rick_Beato
```

Use `PYTHON_BIN` to choose a Python interpreter:

```bash
PYTHON_BIN=python3.12 bash EnvSetup/install_ubuntu.sh
```

Use `VENV_DIR` to choose where the virtual environment is created:

```bash
VENV_DIR=/path/to/venv bash EnvSetup/install_ubuntu.sh
```

## Windows

Run from the project root:

```bat
EnvSetup\install_windows.bat
```

The script creates a project-local virtual environment at `.venv` and installs packages from `EnvSetup\requirements.txt`.

After setup, run the web UI with:

```bat
start_windows.bat
```

Use `PYTHON_BIN` to choose a Python interpreter:

```bat
set PYTHON_BIN=py -3.12
EnvSetup\install_windows.bat
```

Use `VENV_DIR` to choose where the virtual environment is created:

```bat
set VENV_DIR=C:\path\to\venv
EnvSetup\install_windows.bat
```

## Docker

Build the lightweight image from the project root:

```bash
docker build -f EnvSetup/Dockerfile -t subtitle-to-ebook .
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
docker build -f EnvSetup/Dockerfile.calibre -t subtitle-to-ebook-calibre .
```