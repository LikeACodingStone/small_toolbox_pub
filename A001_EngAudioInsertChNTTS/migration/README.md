# Dependency installation

Run either setup script from any working directory:

```bash
bash migration/SetupCPU.sh
# Or, for the bundled Python 3.12 / x86_64 ROCm build:
bash migration/SetupRyzen7800GPU.sh
```

The scripts resolve `../DependenceLib` relative to the project root.
The dependency directory is alongside the project in its parent directory.
They create `DependenceLib/.venv` for Python packages and use
`DependenceLib/installed` for extracted CTranslate2 ROCm libraries.
The migration scripts, requirements, offline wheels and archive stay here.
System packages, Ollama and model caches keep their existing locations.

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
the three application configuration files.

Setup can install missing system packages with sudo, start Ollama, download
models, and update the existing podcast environment block in `~/.bashrc`.
It finishes by loading Whisper to verify the selected backend.

The original setup and launcher scripts contain their own environment checks;
no additional shell helper or test file is required to run them.
