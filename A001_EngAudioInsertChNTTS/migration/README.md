# Dependency installation

Run either setup script from any working directory:

```bash
bash migration/SetupCPU.sh
# Or, for the bundled Python 3.12 / x86_64 ROCm build:
bash migration/SetupRyzen7800GPU.sh
```

Each feature's `config.ini` selects its dependency directory:

```ini
[RuntimeConfig]
env_folder=../DependenceLib
```

Relative paths are resolved against the project root, not the config directory
or the terminal's working directory. Absolute paths and spaces are supported.
Missing settings default to `../DependenceLib`; empty values are rejected.
Use the same value in all three configs to share one installation.

Explicit setup defaults to `InsertSpeech/config.ini`. Select another config with:

```bash
bash migration/SetupCPU.sh --config SubtitleOnly/config.ini
```

The selected directory contains `.venv/` for Python packages, `installed/` for
CTranslate2 ROCm artifacts, `components/ffmpeg/` for static FFmpeg/ffprobe,
`components/ollama/` for the official Ollama distribution, and `components/native/`
for extracted OpenBLAS/OpenMP runtime packages and their supporting libraries.
Downloads, caches, model stores, and Ollama runtime logs also stay inside this directory.
The migration scripts, requirements, offline wheels, and ROCm archive stay here.

The host still provides Python, libc, the OS loader, GPU drivers and the ROCm
platform required by CTranslate2. Setup installs missing bootstrap tools through
apt (python3-venv, curl, xz-utils, zstd). Runtime native packages are downloaded
with apt and extracted locally; the native package selection targets Ubuntu 24.04
with libomp5-18, matching the existing GPU build. This is not yet a standalone binary.

Existing valid environments and matching package versions are reused.
Missing packages use the local wheels first, with an online fallback.
Invalid existing virtual environments produce an error rather than being deleted.
GPU setup checks the Python ABI and reuses extracted libraries and the patched
extension when present. A Python virtual environment should be recreated at its
destination, not moved, because its scripts can contain absolute paths.

All three project launchers load the external environment automatically. When
dependencies are missing, they run setup before starting the application.
InsertSpeech and SubtitleOnly select setup using their own runtime configuration;
TranslateAudio uses CPU setup when initialization is needed. Automatic setup
preserves application configuration. Explicit setup sets the compute mode in
the selected application configuration file only.

Setup can install missing bootstrap packages with sudo and download components
and models. Existing model caches and system Ollama installations are not moved
or deleted; the new local model store may require a fresh model download.
Launchers prefer the selected component binaries and set model/cache paths.
Ollama uses a private loopback port recorded in `run/ollama.json`; repeated starts
reuse the matching process, and different dependency directories use separate
servers. Application requests receive that endpoint through `AUDIOSOURCE_OLLAMA_API`.
Direct Python execution retains the legacy localhost:11434 fallback.
Setup removes the old podcast environment blocks from `~/.bashrc` and leaves
runtime configuration to the launchers. It finishes by loading Whisper to verify
the selected backend. First setup requires network access for missing components.

The original setup and launcher scripts contain their own environment checks;
no additional shell helper or test file is required to run them.
