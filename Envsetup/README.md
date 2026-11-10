# Environments

All deployment recipes live here on main. Source worktrees are not needed when
installing a published release on another machine.

```bash
bash Envsetup/setup_system.sh all  # Ubuntu 24.04 prerequisites; uses sudo
bash Envsetup/setup_tools.sh all   # isolated Python runtime + compiler packages
bash Envsetup/setup_env.sh        # toolbox UI runtime
```

Use a tool name (e.g. Audio04) instead of `all` to prepare one tool. System packages
are installed into the OS, not copied into this folder. On older Ubuntu versions,
replace `libasound2t64` with `libasound2`. Install Ollama from its official download
page if needed. The scripts link installed CLI tools into each environment;
rerun setup on a new machine rather than copying virtual environments or symlinks.

`requirements/` holds version-controlled dependency recipes. Actual runtimes are
under `environments/<ID>/.venv`; compiler staging is under `build/<ID>`. These large
and machine-specific directories are ignored by Git. Build manifests record the
exact installed package versions and Python version used for each release.

English01 uses CPU-compatible pip wheels by default. Its release configuration selects
CPU; source configuration is unchanged. AMD ROCm and NVIDIA GPU environments need
separate, compatible driver/runtime preparation before changing that setting.
Whisper models download on first use. English01 manages Ollama on launch and may download
its configured model. English03 expects a running Ollama endpoint; start the service
and pull the model named by the release config, for example `ollama pull qwen2.5:7b`.
Model downloads and real AI inference are not part of packaging smoke tests.

English03 optional enhanced IPA/name recognition dependencies:

```bash
Envsetup/environments/English03_BookEngInsertCh/.venv/bin/python -m pip install pronouncing eng-to-ipa spacy
Envsetup/environments/English03_BookEngInsertCh/.venv/bin/python -m spacy download en_core_web_sm
```

Without these optional packages/models, the application's existing fallback paths
apply. Audio04 needs a graphical desktop session and working audio for normal use.
Python Tk bindings are optional for English02's native directory picker; users can
also type paths into its browser UI.

The executable launchers use only the published modules and these environments.
They do not install packages on launch. Linux artifacts require the same Python
major/minor, architecture and a compatible system ABI. Windows setup for the
existing toolbox UI is retained; these application builds currently target Linux.
