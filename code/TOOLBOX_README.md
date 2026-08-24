# Small Toolbox

`toolbox.py` is a PyQt5 launcher that discovers tools from the folder matching
the current operating system:

- Linux/macOS: `toolbox_linux/*.sh`
- Windows: `toolbox_win/*.bat`

The displayed tool name is generated directly from the script filename stem.
For example, `toolbox_linux/A001_EngAudioInsertChNTTS.sh` appears as
`A001_EngAudioInsertChNTTS`. No registration file is required.

## Setup

From the repository root, run the setup script for your platform. It creates a
virtual environment at `code/.venv` and installs every package in
`code/requirements.txt`.

Linux/macOS:

```bash
./Envsetup/setup_env.sh
```

Windows:

```bat
Envsetup\setup_env.bat
```

## Linux

Start the launcher after setup:

```bash
./run_toolbox_linux.sh
```

The launcher runs each selected `.sh` file with `bash`, using the script folder
as its working directory. The scripts do not need the executable bit set.

## Windows

Run `run_toolbox_win.bat` after setup. The launcher runs each
selected `.bat` file through `cmd.exe`, using `toolbox_win` as its working
directory.

Use **Refresh** after adding or removing scripts. Each process has its own
output log and can be stopped from the selected tool page.
