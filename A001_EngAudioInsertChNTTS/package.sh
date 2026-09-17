#!/usr/bin/env bash
# Compile application modules only; runtime dependencies remain in env_folder.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$PROJECT_DIR" "$@" <<'BUILD_PY'
import ast
import configparser
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

PROJECT = Path(sys.argv[1])
FEATURES = {
    "InsertSpeech": ("insert-speech", "main_batch"),
    "SubtitleOnly": ("subtitle-only", "subtitle_improve"),
    "TranslateAudio": ("translate-audio", "translate_audio"),
}
JOBS = min(4, os.cpu_count() or 1)
OUTPUT = PROJECT.parent / "A001_Pkg_EngAudioInsertChNTTS"
if platform.system() != "Linux":
    raise SystemExit("This release builder currently supports Linux only.")


def run(command, **kwargs):
    print("[RUN] " + " ".join(map(str, command)), flush=True)
    return subprocess.run(list(map(str, command)), check=True, **kwargs)


def read_config(path):
    config = configparser.ConfigParser(interpolation=None)
    with path.open(encoding="utf-8-sig") as handle:
        config.read_file(handle)
    return config


def runtime_environment(folder):
    env = os.environ.copy()
    native = folder / "components/native"
    libraries = [folder / "installed/ctranslate2-rocm/lib"]
    if native.is_dir():
        libraries.extend(sorted({p.parent for p in native.rglob("*.so*") if p.is_file()}))
    # Host ROCm drivers/runtime are prerequisites for the existing custom GPU build.
    libraries.extend([Path("/opt/rocm/lib"), Path("/usr/lib/llvm-18/lib")])
    env["LD_LIBRARY_PATH"] = ":".join(str(p) for p in libraries if p.is_dir())
    env["PATH"] = ":".join(map(str, [folder / ".venv/bin", folder / "components/ffmpeg/bin", folder / "components/ollama/bin"])) + ":" + os.environ.get("PATH", "")
    env["HF_HOME"] = str(folder / "models/huggingface")
    env["HF_HUB_CACHE"] = str(folder / "models/huggingface/hub")
    env["PIP_CACHE_DIR"] = str(folder / "cache/pip")
    env["NUITKA_CACHE_DIR"] = str(folder / "cache/nuitka")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return env


configs = {}
environments = {}
for feature in FEATURES:
    path = PROJECT / feature / "config.ini"
    config = read_config(path)
    value = config.get("RuntimeConfig", "env_folder", fallback="../DependenceLib").strip()
    if not value:
        raise SystemExit(f"Empty RuntimeConfig.env_folder in {path}")
    folder = (PROJECT / Path(value).expanduser()).resolve()
    core = config.get("RuntimeConfig", "CaculateCore", fallback=config.get("RuntimeConfig", "CalculateCore", fallback="GPU")).upper()
    configs[feature] = (path, config, folder, core)
    environments.setdefault(folder, []).append(feature)
    print(f"[CONFIG] {feature}: {folder} ({core})", flush=True)

# Prepare build tools in the external environment without installing runtime dependencies.
if not shutil.which("gcc"):
    raise SystemExit("Missing C compiler. Install build-essential on the build machine.")
for folder in environments:
    python = folder / ".venv/bin/python"
    if not python.is_file():
        if (folder / ".venv").exists():
            raise SystemExit(f"Existing virtual environment is incomplete: {python}. Repair it before packaging.")
        folder.mkdir(parents=True, exist_ok=True)
        run([sys.executable, "-m", "venv", folder / ".venv"], env=runtime_environment(folder))
    env = runtime_environment(folder)
    result = subprocess.run(
        [str(python), "-c", "import sys, sysconfig; from pathlib import Path; assert sys.prefix != sys.base_prefix, 'Not a virtual environment'; assert (Path(sysconfig.get_path('include')) / 'Python.h').is_file(), 'Install matching Python development headers (for example python3.12-dev)'"],
        env=env, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"Build prerequisites missing in {folder}:\n{result.stderr}")
    missing = []
    for module in ("Cython", "setuptools", "wheel"):
        check = subprocess.run([str(python), "-c", f"import {module}"],
                               env=env, capture_output=True, text=True)
        if check.returncode:
            missing.append(module)
    if missing:
        print(f"[BUILD] Installing missing build packages in {folder}: {', '.join(missing)}", flush=True)
        pip_check = subprocess.run([str(python), "-m", "pip", "--version"],
                                   env=env, capture_output=True, text=True)
        if pip_check.returncode:
            run([python, "-m", "ensurepip", "--upgrade"], env=env)
        run([python, "-m", "pip", "--isolated", "install", *missing], env=env)
    run([python, "-c", "import Cython, setuptools, wheel"], env=env)

# The helper is compiled as an extension; only the bootstrap launcher remains readable.
RUNTIME = r'''
import configparser
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys

FEATURE = __FEATURE__
COMMAND = __COMMAND__
ROOT = Path(os.environ["PODCAST_PACKAGE_ROOT"])
CONFIG_DIR = ROOT / "config" / FEATURE

def configure():
    config = configparser.ConfigParser(interpolation=None)
    with (CONFIG_DIR / "config.ini").open(encoding="utf-8") as handle:
        config.read_file(handle)
    value = config.get("RuntimeConfig", "env_folder", fallback="../DependenceLib").strip()
    if not value:
        raise SystemExit("RuntimeConfig.env_folder must not be empty")
    dependency = (ROOT / Path(value).expanduser()).resolve()
    native = dependency / "components/native"
    libraries = [dependency / "installed/ctranslate2-rocm/lib"]
    if native.is_dir():
        libraries.extend(sorted({p.parent for p in native.rglob("*.so*") if p.is_file()}))
    old = os.environ.get("LD_LIBRARY_PATH", "")
    paths = [str(p) for p in libraries if p.is_dir()]
    for path in old.split(":"):
        if path and path not in paths:
            paths.append(path)
    os.environ["PATH"] = str(dependency / "components/ffmpeg/bin") + ":" + str(dependency / "components/ollama/bin") + ":" + os.environ.get("PATH", "")
    os.environ["HF_HOME"] = str(dependency / "models/huggingface")
    os.environ["HF_HUB_CACHE"] = str(dependency / "models/huggingface/hub")
    os.environ["OLLAMA_MODELS"] = str(dependency / "models/ollama")
    os.environ["XDG_CACHE_HOME"] = str(dependency / "cache")
    os.environ["PODCAST_FEATURE_DIR"] = str(CONFIG_DIR)
    os.environ["PODCAST_LOG_DIR"] = str(ROOT / "output" / FEATURE / "Log")
    os.environ["PODCAST_EXECUTABLE"] = str(ROOT / "podcast")
    os.environ["PODCAST_COMMAND"] = COMMAND
    os.environ.setdefault("AUDIOSOURCE_SUBTITLE_DIR", str(ROOT / "input/subtitles"))
    core = config.get("RuntimeConfig", "CaculateCore", fallback=config.get("RuntimeConfig", "CalculateCore", fallback="GPU")).strip().upper()
    cpu = core == "CPU"
    defaults = {
        "AUDIOSOURCE_WHISPER_DEVICE": "cpu" if cpu else "cuda",
        "AUDIOSOURCE_WHISPER_COMPUTE_TYPE": "int8" if cpu else "float16",
        "AUDIOSOURCE_WHISPER_CHUNK_SECONDS": "0" if cpu else "300",
        "AUDIOSOURCE_WHISPER_CPU_THREADS": str(os.cpu_count() or 1),
        "AUDIOSOURCE_MAX_WORKERS": "1",
        "AUDIOSOURCE_WHISPER_SUBPROCESS_TIMEOUT_SECONDS": "1200",
        "AUDIOSOURCE_WHISPER_GPU_RETRIES": "1",
        "AUDIOSOURCE_WHISPER_RETRY_SLEEP_SECONDS": "45",
        "AUDIOSOURCE_WHISPER_FALLBACK_CPU": "1",
        "AUDIOSOURCE_CLEAR_LOGS": "1",
        "AUDIOSOURCE_OLLAMA_MODEL": "qwen2.5:7b",
    }
    if cpu:
        defaults["AUDIOSOURCE_USE_PROCESS_POOL"] = "0"
    for name, value in defaults.items():
        os.environ.setdefault(name, value)
    return dependency

def start_ollama(dependency):
    # This function body is taken from the original launcher at build time.
    __OLLAMA_BODY__

def main():
    multiprocessing.freeze_support()
    if "--help" in sys.argv[1:] and "--transcribe-chunk" not in sys.argv[1:] and FEATURE == "InsertSpeech":
        print("Usage: podcast insert-speech [--self-check]\nPaths and processing options are configured in config/InsertSpeech/config.ini.")
        return 0
    dependency = configure()
    if sys.argv[1:] == ["--self-check"]:
        import importlib
        for module in (__CHECK_MODULES__):
            importlib.import_module(module)
        for tool in ("ffmpeg", "ffprobe"):
            subprocess.run([str(dependency / "components/ffmpeg/bin" / tool), "-version"], check=True, stdout=subprocess.DEVNULL)
        if FEATURE != "TranslateAudio" and not (dependency / "components/ollama/bin/ollama").is_file():
            raise SystemExit("Ollama is missing from env_folder")
        print(json.dumps({"feature": FEATURE, "env_folder": str(dependency), "python": sys.executable, "status": "ok"}))
        return 0
    if "--transcribe-chunk" in sys.argv[1:]:
        import transcribe_module
        return transcribe_module.main_cli()
    if FEATURE != "TranslateAudio" and "--help" not in sys.argv[1:]:
        start_ollama(dependency)
        binary = str(dependency / "components/ollama/bin/ollama")
        model = os.environ["AUDIOSOURCE_OLLAMA_MODEL"]
        if subprocess.run([binary, "show", model], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            subprocess.run([binary, "pull", model], check=True)
    __APP_IMPORT__
    return app.main()

if __name__ == "__main__":
    sys.exit(main())
'''

shell = (PROJECT / "insertSpeech.sh").read_text()
match = re.search(r'OLLAMA_HOST="\$\(python3 - "\$DEPENDENCE_DIR" <<\x27PY\x27\n(.*?)\nPY', shell, re.S)
if not match:
    raise SystemExit("Cannot locate the managed Ollama startup implementation in insertSpeech.sh")
ollama = match.group(1).replace('root = Path(sys.argv[1])', 'root = dependency')
ollama = ollama.replace('            print(state["host"])\n            raise SystemExit(0)', '            os.environ["OLLAMA_HOST"] = state["host"]\n            os.environ["AUDIOSOURCE_OLLAMA_API"] = "http://" + state["host"] + "/api/generate"\n            return')
ollama = ollama.replace('            print(host)', '            os.environ["OLLAMA_HOST"] = host\n            os.environ["AUDIOSOURCE_OLLAMA_API"] = "http://" + host + "/api/generate"')

build_parent = next(iter(environments)) / "build/package"
build_parent.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="cython-", dir=build_parent))
stage_release = work / "release"
stage_release.mkdir()
print(f"[BUILD] Work files: {work}", flush=True)
manifest = {"platform": platform.platform(), "architecture": platform.machine(), "features": {}, "environments": {}}

for index, (folder, features) in enumerate(environments.items(), 1):
    python = folder / ".venv/bin/python"
    env = runtime_environment(folder)
    env_key = "shared" if len(environments) == 1 else f"env{index}"
    manifest["environments"][env_key] = {"external": True, "path": os.path.relpath(folder, OUTPUT)}

    for feature in features:
        command, module = FEATURES[feature]
        source_dir = work / feature / "source"
        source_dir.mkdir(parents=True)
        for source_path in (PROJECT / feature).glob("*.py"):
            source = source_path.read_text(encoding="utf-8-sig")
            if not any(isinstance(node, ast.Import) and any(alias.name == "os" for alias in node.names)
                       for node in ast.parse(source).body):
                source = "import os\n" + source
            # Data/log paths must refer to release configuration, not compiled module locations.
            source = source.replace('Path(__file__).resolve().parent', 'Path(os.environ["PODCAST_FEATURE_DIR"])')
            source = source.replace('LOG_DIR = SCRIPT_DIR / "Log"', 'LOG_DIR = Path(os.environ["PODCAST_LOG_DIR"])')
            source = source.replace('log_dir = script_dir / "Log"', 'log_dir = Path(os.environ["PODCAST_LOG_DIR"])')
            source = source.replace('        sys.executable,\n        str(Path(__file__).resolve()),', '        os.environ["PODCAST_EXECUTABLE"],\n        os.environ["PODCAST_COMMAND"],')
            if source_path.name == "transcribe_module.py" and 'str(Path(__file__).resolve())' in source:
                raise SystemExit("Unrecognized transcription subprocess entry point")
            ast.parse(source)
            (source_dir / source_path.name).write_text(source)
        checks = ["edge_tts", "pydub", module]
        if feature != "TranslateAudio":
            checks += ["faster_whisper", "ctranslate2", "cefrpy", "wordfreq", "requests", "transcribe_module"]
        wrapper = RUNTIME.replace("__FEATURE__", repr(feature)).replace("__COMMAND__", repr(command))
        wrapper = wrapper.replace("    __OLLAMA_BODY__", "\n".join("    " + line for line in ollama.splitlines()))
        wrapper = wrapper.replace("__CHECK_MODULES__", repr(tuple(checks))).replace("__APP_IMPORT__", f"import {module} as app")
        ast.parse(wrapper)
        entry = source_dir / "podcast_entry.py"
        entry.write_text(wrapper)
        build = work / feature / "compiled"
        runtime_dir = stage_release / "lib" / feature
        runtime_dir.mkdir(parents=True)
        # Compile only this project's modules. Third-party imports stay external.
        build_script = source_dir / "_compile.py"
        build_script.write_text("""
from pathlib import Path
from setuptools import Extension, setup
from Cython.Build import cythonize
modules = [Extension(p.stem, [str(p)]) for p in Path(".").glob("*.py") if p.name != "_compile.py"]
setup(name="podcast-application", ext_modules=cythonize(
    modules, compiler_directives={"language_level": 3, "binding": True},
    annotate=False))
""")
        run([python, build_script, "build_ext", "--build-lib", runtime_dir,
             "--build-temp", build, "--parallel", str(JOBS)], env=env, cwd=source_dir)
        binaries = list(runtime_dir.glob("*.so"))
        if len(binaries) != len(list(source_dir.glob("*.py"))) - 1:
            raise SystemExit(f"Not all application modules were compiled: {feature}")
        config_dir = stage_release / "config" / feature
        config_dir.mkdir(parents=True)
        config = configs[feature][1]
        if not config.has_section("RuntimeConfig"):
            config.add_section("RuntimeConfig")
        config.set("RuntimeConfig", "env_folder", os.path.relpath(folder, OUTPUT))
        # Release paths are editable and no longer point at the developer's output directories.
        if config.has_section("OriginalConfigPath"):
            config.set("OriginalConfigPath", "OriginalAudioPath", "../../input/audio")
            config.set("OriginalConfigPath", "TranslatePath", "../../output/translate")
            output = "translateAudio" if feature == "TranslateAudio" else "chineseTTS"
            config.set("OriginalConfigPath", "AudioTranslatedPath", "../../output/" + output)
        with (config_dir / "config.ini").open("w") as handle:
            config.write(handle)
        if (PROJECT / feature / "filter.txt").is_file():
            shutil.copy2(PROJECT / feature / "filter.txt", config_dir / "filter.txt")
        manifest["features"][feature] = {"command": command, "environment": env_key}

launcher = r'''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "${1:---help}" in
    insert-speech) feature=InsertSpeech ;;
    subtitle-only) feature=SubtitleOnly ;;
    translate-audio) feature=TranslateAudio ;;
    --help|-h) printf 'Usage: podcast {insert-speech|subtitle-only|translate-audio} [options]\\n'; exit 0 ;;
    *) printf 'Unknown command: %s\\n' "$1" >&2; exit 2 ;;
esac
shift
exec python3 - "$ROOT" "$feature" "$@" <<'BOOTSTRAP'
import configparser
import os
from pathlib import Path
import sys

root, feature = Path(sys.argv[1]), sys.argv[2]
config = configparser.ConfigParser(interpolation=None)
with (root / "config" / feature / "config.ini").open(encoding="utf-8") as handle:
    config.read_file(handle)
value = config.get("RuntimeConfig", "env_folder", fallback="../DependenceLib").strip()
if not value:
    raise SystemExit("RuntimeConfig.env_folder must not be empty")
dependency = (root / Path(value).expanduser()).resolve()
python = dependency / ".venv/bin/python"
if not python.is_file():
    raise SystemExit(f"External Python environment not found: {python}. Prepare env_folder separately.")
libraries = [dependency / "installed/ctranslate2-rocm/lib"]
native = dependency / "components/native"
if native.is_dir():
    libraries.extend(sorted({p.parent for p in native.rglob("*.so*") if p.is_file()}))
env = os.environ.copy()
env.pop("PYTHONPATH", None)
env.pop("PYTHONHOME", None)
env["LD_LIBRARY_PATH"] = ":".join(str(p) for p in libraries if p.is_dir()) + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
env["PODCAST_PACKAGE_ROOT"] = str(root)
env["PODCAST_FEATURE"] = feature
code = "import os,sys; from pathlib import Path; sys.path.insert(0,str(Path(os.environ['PODCAST_PACKAGE_ROOT'])/'lib'/os.environ['PODCAST_FEATURE'])); import podcast_entry; sys.exit(podcast_entry.main())"
os.execve(str(python), [str(python), "-c", code, *sys.argv[3:]], env)
BOOTSTRAP
'''
(stage_release / "podcast").write_text(launcher)
(stage_release / "podcast").chmod(0o755)
for name in ("input/audio", "input/subtitles", "output"):
    (stage_release / name).mkdir(parents=True, exist_ok=True)
(stage_release / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
(stage_release / "README.md").write_text("""# Podcast Tool

Run ./podcast insert-speech, ./podcast subtitle-only, or ./podcast translate-audio.
This package contains compiled application modules only. No Python runtime,
third-party libraries, tools, or models are bundled.

Each config/<Feature>/config.ini selects the external environment through
RuntimeConfig.env_folder, resolved relative to this package root.
The launcher uses env_folder/.venv/bin/python and that environment's libraries,
components and model stores. System python3 is used only to read bootstrap
configuration. A compatible Python version, architecture, and prepared runtime
environment are required. Missing dependencies are not installed automatically.

Place source audio in input/audio or edit configuration. Output defaults to output/.
Append --self-check to verify runtime imports and tools without processing audio.
Moving the application is supported; update env_folder if its relative location
changes. Original application source is not shipped. Compilation does not prevent
reverse engineering. Manage dependencies independently with migration.
""")

# A relocated smoke test catches accidental build-directory and source-file dependencies.
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
verification = Path(tempfile.mkdtemp(prefix=".podcast verify ", dir=OUTPUT.parent))
candidate = verification / OUTPUT.name
shutil.move(str(stage_release), candidate)
# The verification directory has a different parent depth than the final release.
# Temporarily point configs at their actual external environments for smoke tests.
for feature in FEATURES:
    path = candidate / "config" / feature / "config.ini"
    config = read_config(path)
    config.set("RuntimeConfig", "env_folder", str(configs[feature][2]))
    with path.open("w") as handle:
        config.write(handle)
print(f"[VERIFY] Relocated candidate: {candidate}", flush=True)
for feature, (command, _) in FEATURES.items():
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("PYTHON", "PODCAST_", "AUDIOSOURCE_")) or key in ("LD_LIBRARY_PATH", "VIRTUAL_ENV"):
            env.pop(key, None)
    run([candidate / "podcast", command, "--self-check"], cwd="/tmp", env=env)
    if feature != "InsertSpeech":
        run([candidate / "podcast", command, "--help"], cwd="/tmp", env=env, stdout=subprocess.DEVNULL)
    if feature != "TranslateAudio":
        run([candidate / "podcast", command, "--transcribe-chunk", "input.wav", "output.json", "--help"], cwd="/tmp", env=env, stdout=subprocess.DEVNULL)
for file in candidate.rglob("*"):
    if file.is_file() and file.suffix in {".py", ".pyc", ".pyx"}:
        raise SystemExit(f"Release contains a Python source/bytecode file; inspect before distributing: {file}")
for feature in FEATURES:
    path = candidate / "config" / feature / "config.ini"
    config = read_config(path)
    config.set("RuntimeConfig", "env_folder", os.path.relpath(configs[feature][2], OUTPUT))
    with path.open("w") as handle:
        config.write(handle)
backup = None
if OUTPUT.exists() or OUTPUT.is_symlink():
    backup = OUTPUT.with_name(OUTPUT.name + ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    OUTPUT.rename(backup)
try:
    candidate.rename(OUTPUT)
except OSError:
    if backup is not None:
        backup.rename(OUTPUT)
    raise
verification.rmdir()
if backup is not None:
    print(f"[BACKUP] Previous release preserved: {backup}")
print(f"[OK] Release ready: {OUTPUT}\nRun: {OUTPUT}/podcast --help\nPrivate build intermediates remain in {work}; do not distribute that directory.")
BUILD_PY
