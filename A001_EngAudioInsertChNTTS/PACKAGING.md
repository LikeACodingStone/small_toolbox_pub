# Building a Binary Release

`package.sh` compiles all three application workflows with Nuitka standalone mode.
The default output is `../A001_Pkg_EngAudioInsertChNTTS`, alongside the source project.
The source project and its configuration files are not rewritten.

```bash
bash package.sh
```

Each workflow's `[RuntimeConfig] env_folder` selects its build environment. Relative
paths are resolved against the source project root. The builder uses that environment's
`.venv/bin/python` and obtains components, native libraries, and available models from
the same directory. Different environments are supported and remain separate in the
release. Dependencies are never silently substituted from a global Python installation.

No parameters are needed. Each run automatically invokes the existing migration scripts,
which check and reuse installed dependencies, use sudo when necessary, download missing components
and models, and verify CPU/GPU inference before compilation. Automatic preparation
preserves source configuration. GPU setup requires the existing compatible ROCm host.

Missing C compiler and matching Python development headers are installed automatically through apt.
Nuitka, patchelf, ordered-set, and zstandard are installed into the configured virtual
environment when needed. Compiler parallelism is selected automatically, up to four jobs.
System package installation may require your sudo password.

After the new release passes verification, any existing output directory is preserved
under a timestamped `.backup-...` name before the new release is published.
Build intermediates and reports stay
under the first configured environment's `build/package/`; they contain source and
generated C files and must not be distributed. A failed verification retains its candidate
directory for inspection and does not publish it as the requested output directory.

## Release Layout

```text
A001_Pkg_EngAudioInsertChNTTS/
|-- podcast                         # Small Bash dispatcher; no business logic
|-- config/
|   |-- InsertSpeech/config.ini
|   |-- InsertSpeech/filter.txt
|   |-- SubtitleOnly/config.ini
|   |-- SubtitleOnly/filter.txt
|   `-- TranslateAudio/config.ini
|-- lib/
|   |-- InsertSpeech/               # Compiled executable and bundled Python runtime
|   |-- SubtitleOnly/
|   |-- TranslateAudio/
|   `-- env/shared/                 # Separate env1/env2 directories if configs differ
|       |-- components/             # FFmpeg, Ollama, native runtime libraries
|       |-- installed/              # CTranslate2 ROCm artifacts
|       |-- models/                 # Available model caches copied from env_folder
|       |-- cache/
|       `-- run/
|-- input/audio/
|-- input/subtitles/
|-- output/
|-- licenses/
|-- build-manifest.json
`-- README.md
```

Copy the entire release directory to a compatible Linux machine or another folder:

```bash
./podcast insert-speech
./podcast subtitle-only
./podcast translate-audio
./podcast insert-speech --self-check
```

All release configurations use package-relative `env_folder` values. This setting selects
components, models, and native libraries at runtime. Python packages have already been
compiled or bundled under `lib/<Feature>`; changing env_folder does not replace those
packages with an external venv. Rebuild to change bundled Python dependencies.

Release input/output defaults are portable: source audio in `input/audio`, generated data
under `output`. Edit release configs to use other paths. Existing source absolute paths
are not copied into the release defaults. Original processing parameters, filtering rules,
and CPU/GPU selections are retained. Log files are stored under `output/<Feature>/Log`.

The builder verifies relocated executables from `/tmp`, imports runtime packages, runs
FFmpeg/ffprobe, and checks CLI and transcription-worker entry points before publishing.
These checks do not perform full audio processing, call online TTS, or validate GPU
inference. Target GPU drivers and ROCm still need to be compatible. Edge TTS needs a
network connection; absent model caches download on first use. This is a Linux build,
not a Windows/macOS binary, and is not independent of host system ABI compatibility.
An environment containing the custom ROCm CTranslate2 extension retains its native
ROCm dependencies even if the application configuration later selects CPU execution.
Build from a CPU-only environment when targeting machines without ROCm.

The release is checked for Python source and bytecode files. Original application code
and compiler intermediates are excluded; compilation does not prevent all reverse
engineering. Third-party notices are included under `licenses` and component directories.
