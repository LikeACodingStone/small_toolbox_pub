# Environment Setup

All generated Python environments live inside this `EnvSetup` folder.

## Windows / Samba share

1. Run `EnvSetup\Windows\setup_windows.bat` once.
2. Start the app with `run_av1_tool.bat`.

The Windows launcher uses `pushd`, so it can start from a UNC/Samba path such as `\\server\share\project`. If `EnvSetup\venv-windows` exists, the launcher uses it automatically.

## Ubuntu

1. Install the basic system packages if needed:
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv ffmpeg
   ```
2. Run the setup script once:
   ```bash
   bash EnvSetup/Ubuntu/setup_ubuntu.sh
   ```
3. Start the app:
   ```bash
   bash run_av1_tool_ubuntu.sh
   ```

If PyQt reports a missing Qt platform plugin on a minimal Ubuntu install, install the desktop Qt dependencies from your distribution packages.