# Project Libraries and Technologies

This inventory describes the application source and `migration/requirements.txt`. Versions below are declared requirements, not a report of packages installed on this machine. See [the architecture diagram](software_architecture.svg) for the overall structure.

## Application workflows

| Entry point | Main function | Main dependencies |
| --- | --- | --- |
| `insertSpeech.sh` | Transcribe source audio, select difficult vocabulary, translate it, synthesize speech, and combine audio. | faster-whisper, cefrpy, wordfreq, requests, edge-tts, pydub, Ollama, FFmpeg |
| `subtitleOnly.sh` | Improve punctuation and vocabulary content in existing Markdown subtitles without producing audio. | requests, Ollama, vocabulary helpers from its local transcribe_module |
| `translateAudio.sh` | Generate speech audio from vocabulary sentences in Markdown. | edge-tts, pydub, FFmpeg |

The two `transcribe_module.py` files import the recognition and vocabulary libraries at module load time. Importing a helper from those modules therefore also requires those packages, even when a particular operation does not perform speech recognition.

## Direct application libraries

These six third-party packages are imported explicitly by application code.

| Package | Required version | Function in this project |
| --- | --- | --- |
| faster-whisper | 1.2.1 | Provides `WhisperModel` for audio transcription with timestamps. Runs Whisper through CTranslate2, with CPU and GPU execution paths. |
| cefrpy | 1.0.2 | Provides `CEFRAnalyzer` to classify English vocabulary difficulty. Its results contribute to selecting words for translation. |
| wordfreq | 3.1.1 | Provides `word_frequency` estimates. Frequency thresholds help distinguish common vocabulary from difficult or unusual words. |
| requests | 2.34.0 | Sends HTTP requests to the local Ollama API for contextual vocabulary translation and subtitle punctuation improvement. |
| edge-tts | 7.2.8 | Imported as `edge_tts`; asynchronously requests synthesized speech from the online Edge TTS service. It is a network client, not a bundled local speech model. |
| pydub | 0.25.1 | Provides `AudioSegment` for audio operations. The TTS modules also invoke FFmpeg directly for efficient conversion and concatenation. |

Source locations: `InsertSpeech/transcribe_module.py`, `InsertSpeech/tts_module.py`, `SubtitleOnly/transcribe_module.py`, `SubtitleOnly/subtitle_improve.py`, and `TranslateAudio/tts_module.py`.

## Supporting packages in requirements.txt

Every remaining pinned package is listed below. These packages are not imported directly by the application. Their descriptions explain their library role and likely supporting purpose; the requirements file alone does not establish an exact dependency tree. Inclusion does not prove that a package is exercised by every workflow.

### Recognition, model storage, and language data

| Package | Required version | Function and relevance |
| --- | --- | --- |
| ctranslate2 | 4.7.1 | Native neural-network inference engine used by faster-whisper. GPU setup replaces its Python extension with the bundled ROCm build and loads external native libraries. |
| av | 17.0.1 | PyAV bindings to FFmpeg libraries; supports decoding audio for the recognition stack. Distinct from the system `ffmpeg` executable. |
| numpy | 2.4.6 | Numerical arrays and operations used by audio processing and inference dependencies. |
| onnxruntime | 1.26.0 | Executes ONNX models, including the voice-activity detection capability available in faster-whisper. Installation does not mean VAD is enabled in every transcription call. |
| tokenizers | 0.23.1 | Efficient token encoding and decoding used by the Whisper pipeline. |
| huggingface_hub | 1.14.0 | Downloads and caches model artifacts, including models resolved by faster-whisper. |
| hf-xet | 1.5.0 | Transfer support for Hugging Face repositories using Xet storage. |
| fsspec | 2026.4.0 | Common filesystem interface for local and remote data access in supporting packages. |
| filelock | 3.29.0 | File-based locking used by caches and tooling to coordinate concurrent access. |
| flatbuffers | 25.12.19 | Binary serialization support used in model-runtime ecosystems such as ONNX Runtime. |
| protobuf | 7.34.1 | Protocol Buffers serialization used by model and tooling ecosystems. No explicit application-level use. |
| ftfy | 6.3.1 | Repairs malformed Unicode text; supports text normalization in the wordfreq ecosystem. |
| langcodes | 3.5.1 | Interprets and normalizes language identifiers for multilingual language-data tooling. |
| locate | 1.1.1 | Utility for locating paths and resources. Listed in the environment; its exact consumer is not established by the application source. |
| msgpack | 1.1.2 | Compact binary serialization used for data such as wordfreq's frequency resources. |
| regex | 2026.5.9 | Enhanced regular expressions with Unicode capabilities for language-processing dependencies. Distinct from Python's built-in `re`. |
| PyYAML | 6.0.3 | YAML parsing and serialization available to dependencies. The application's own configuration uses INI files instead. |

### Networking and asynchronous support

| Package | Required version | Function and relevance |
| --- | --- | --- |
| aiohttp | 3.13.5 | Asynchronous HTTP and WebSocket client/server library; supports edge-tts network communication. |
| aiohappyeyeballs | 2.6.1 | Connection racing across network address families for aiohttp connections. |
| aiosignal | 1.4.0 | Asynchronous signal/callback support used by aiohttp. |
| frozenlist | 1.8.0 | Lists that can be frozen against modification, used by asynchronous networking infrastructure. |
| multidict | 6.7.1 | Dictionary structures that allow repeated keys, suitable for HTTP headers and query parameters. |
| yarl | 1.23.0 | URL parsing and construction used in aiohttp. |
| propcache | 0.5.2 | Cached-property helpers used by supporting networking libraries. |
| attrs | 26.1.0 | Declarative Python classes, attribute validation, and boilerplate reduction for supporting libraries. |
| anyio | 4.13.0 | Common asynchronous concurrency interface used by networking libraries such as HTTPX. |
| httpx | 0.28.1 | Synchronous and asynchronous HTTP client used by supporting tools and model download libraries. Application Ollama calls use requests. |
| httpcore | 1.0.9 | Low-level transport and connection pooling underlying HTTPX. |
| h11 | 0.16.0 | HTTP/1.1 protocol implementation used by HTTP transports. |
| urllib3 | 2.7.0 | HTTP connection pooling and transport support underlying requests. |
| certifi | 2026.4.22 | Certificate-authority bundle for verifying HTTPS connections. |
| charset-normalizer | 3.4.7 | Detects text encodings for response decoding, including in requests. |
| idna | 3.14 | Encodes internationalized domain names for network clients. |

### Packaging, environments, and terminal tooling

These packages are present in the installation manifest, but many serve installation or dependency command-line interfaces rather than audio processing.

| Package | Required version | Function and relevance |
| --- | --- | --- |
| build | 1.5.0 | Builds Python distributions through standard build backends. No direct application use. |
| setuptools | 82.0.1 | Python packaging/build infrastructure. |
| wheel | 0.47.0 | Tooling for the wheel distribution format used by the offline package directory. |
| pyproject_hooks | 1.2.0 | Calls Python build-backend hooks, supporting tools such as build. |
| packaging | 26.2 | Parses versions, requirement specifiers, and distribution compatibility tags. |
| distlib | 0.4.1 | Packaging utilities, including executable script generation used by environment tooling. |
| virtualenv | 21.4.2 | Third-party virtual-environment creator. The setup scripts actually create this project's environment with the standard-library `venv` module. |
| python-discovery | 1.4.0 | Finds Python interpreters for environment tooling such as virtualenv. |
| platformdirs | 4.10.0 | Determines platform-specific cache, data, and configuration locations for tools. |
| conda-pack | 0.9.1 | Archives Conda environments for relocation. The current migration scripts do not call it and do not create a Conda environment. |
| click | 8.3.3 | Command-line interface framework used by dependency tools; application CLIs use argparse. |
| typer | 0.25.1 | Type-annotation-based CLI framework used by dependency tools. |
| shellingham | 1.5.4 | Detects the active shell for CLI tooling. |
| annotated-doc | 0.0.4 | Documentation metadata for annotated Python interfaces, used by supporting tooling. |
| typing_extensions | 4.15.0 | Backports and extensions for Python typing APIs. |
| rich | 15.0.0 | Styled terminal output, tables, tracebacks, and progress displays for supporting tools. |
| markdown-it-py | 4.2.0 | Markdown parser used by terminal/document tooling such as Rich. Application Markdown processing uses its own text parsing. |
| mdurl | 0.1.2 | URL parsing helpers for markdown-it-py. |
| Pygments | 2.20.0 | Syntax highlighting for terminal and document rendering tools. |
| tabulate | 0.10.0 | Formats plain-text tables for command-line tools. |
| tqdm | 4.67.3 | Progress bars, including those used by model download and processing dependencies. |
| wcwidth | 0.7.0 | Measures terminal display widths for Unicode characters, supporting aligned text output. |

## Optional library and model

| Component | Function | Current installation behavior |
| --- | --- | --- |
| spaCy, imported as `spacy` | Named-entity recognition to exclude proper names such as people, places, and organizations from vocabulary translation. | Imported on demand. Missing library or model disables that filtering with a warning. Not listed in requirements.txt. |
| en_core_web_sm | English language model loaded by spaCy for entity recognition. | Configured in application INI files; not automatically installed by the migration scripts. |

## Python standard library

These modules ship with Python and do not require individual pip installations.

| Module | Function in this project |
| --- | --- |
| argparse | Parses command-line options and worker arguments. |
| asyncio | Runs asynchronous speech synthesis. |
| concurrent.futures | Coordinates thread pools, process pools, submitted jobs, and completion handling. |
| configparser | Reads and writes INI configuration. |
| datetime | Produces timestamps for logs and output metadata. |
| faulthandler | Helps diagnose interpreter crashes and stalled execution. |
| gc | Supports explicit cleanup of Python objects around processing. |
| hashlib | Computes hashes used by TTS caching and identifiers. |
| json | Encodes and decodes structured data, including service and subprocess payloads. |
| logging | Records processing progress, diagnostics, and errors. |
| multiprocessing | Supports process-based batch execution and process configuration. |
| os | Reads environment variables and accesses process/operating-system facilities. |
| pathlib | Represents and manipulates filesystem paths. |
| platform | Reports platform details for diagnostics. |
| re | Parses and cleans text, subtitle content, and vocabulary with regular expressions. |
| resource | Reports process resource information on Unix-like systems. |
| shutil | Locates external executables and performs filesystem operations. |
| subprocess | Starts FFmpeg/ffprobe and isolated transcription workers. |
| sys | Supplies the current Python executable, process arguments, and interpreter information. |
| tempfile | Creates temporary working files and directories. |
| threading | Coordinates concurrent subtitle processing and synchronization. |
| time | Measures elapsed time and implements waits/retries. |
| types | Provides `SimpleNamespace` for lightweight attribute-based objects. |
| unicodedata | Normalizes Unicode text in the vocabulary-audio workflow. |
| importlib.metadata | Reads installed package versions during shell-script dependency checks. |
| venv | Creates the external Python virtual environment during setup. |
| ensurepip | Bootstraps pip if the virtual environment lacks it. |

## Native libraries, services, tools, and models

These are separate from Python packages. Models are data artifacts, not application frameworks.

| Component | Software category | Function |
| --- | --- | --- |
| CTranslate2 native library and Python extension | Library / inference engine | Executes Whisper inference. The bundled ROCm archive supplies the GPU-specific binary components. |
| OpenBLAS (`libopenblas-dev`) | Native library | CPU linear-algebra support installed as a system dependency. |
| OpenMP (`libomp-dev`) | Native runtime library | Native parallel execution support. The GPU loader path also references `/usr/lib/llvm-18/lib`. |
| AMD ROCm / HIP | Platform / SDK / runtime | Provides the AMD GPU execution platform expected by the bundled CTranslate2 build. Setup checks ROCm-related tools; it does not install the complete ROCm stack. |
| FFmpeg | Standalone software | Audio decoding, conversion, segmentation, concatenation, and encoding. |
| ffprobe | Standalone tool | Reads audio duration, codec, and stream metadata. |
| Ollama | Local service | Hosts the language model at `http://localhost:11434`; handles translation and punctuation requests. |
| Edge TTS online service | Remote service | Produces synthesized speech requested by edge-tts; requires network access. |
| Whisper large-v3 | Speech model | Default model loaded for speech recognition and setup verification. |
| qwen2.5:7b | Language model | Default Ollama model selected by setup and launcher environment settings. |
| pip | Package-management tool | Installs Python requirements using offline wheels first and an online fallback. |
| Bash | Shell language / runtime | Executes installation and launcher logic. |
| apt / dpkg / sudo | System administration tools | Detect and install missing system packages with appropriate privileges. |
| curl / tar | Deployment tools | Download resources, probe services, and unpack the ROCm archive. |
| CPython | Runtime | Executes Python code; the bundled GPU extension specifically targets Python 3.12 on Linux x86_64. |
| Linux | Operating system | Hosts the application; deployment scripts target apt/dpkg-based environments such as Ubuntu and Debian. |

The GPU build uses the Python argument `device="cuda"` even though the supplied native backend is ROCm for AMD hardware. That interface name does not make this an NVIDIA deployment.

## Dependency locations and installation

Paths are computed relative to the project directory, independently of the terminal's working directory:

```text
podcast/
|-- A001_EngAudioInsertChNTTS/
|   |-- insertSpeech.sh
|   |-- subtitleOnly.sh
|   |-- translateAudio.sh
|   |-- InsertSpeech/
|   |-- SubtitleOnly/
|   |-- TranslateAudio/
|   `-- migration/
|       |-- SetupCPU.sh
|       |-- SetupRyzen7800GPU.sh
|       |-- requirements.txt
|       |-- pip_packages/
|       `-- ctranslate2-rocm.tar.gz
`-- DependenceLib/
    |-- .venv/
    `-- installed/
        |-- ctranslate2-rocm/
        `-- ctranslate2/
```

The install destination is `../DependenceLib` relative to the project root. Python packages live in `.venv`; extracted ROCm-specific CTranslate2 artifacts live in `installed`. Original migration scripts and offline installation inputs stay in the project. Each original shell script contains its own environment checks; no additional environment helper is required.

Setup checks existing packages against pinned versions and reuses matching installations. GPU setup reuses extracted artifacts and replaces the environment's CTranslate2 extension when needed. System packages, Ollama, and model caches keep their existing system or user locations. An invalid virtual environment raises an error rather than being silently deleted.

## Classification notes

The application is a collection of Python modules and Bash launchers, not a Django/Spring-style application. It has no dedicated message broker or middleware layer. CTranslate2 is both a native library and an inference engine. Ollama is a separate service accessed through HTTP. Installed build and CLI tools should not be confused with frameworks used to implement the application itself.
