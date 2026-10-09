from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VENV_DIR = PROJECT_ROOT / ".venv"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"


def run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def venv_python(venv_dir: Path) -> Path:
    if platform.system().lower() == "windows":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def create_venv(venv_dir: Path) -> Path:
    if not venv_dir.exists():
        print(f"Creating virtual environment: {venv_dir}")
        venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
    else:
        print(f"Virtual environment already exists: {venv_dir}")

    python_path = venv_python(venv_dir)
    if not python_path.exists():
        raise RuntimeError(f"Python executable not found in virtual environment: {python_path}")
    return python_path


def install_python_dependencies(python_path: Path) -> None:
    run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"])
    if REQUIREMENTS_FILE.exists():
        run([str(python_path), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)])
    else:
        print("requirements.txt not found; skipped Python dependency installation.")


def check_ffmpeg() -> None:
    missing = [name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None]
    if not missing:
        print("FFmpeg check passed: ffmpeg and ffprobe are available in PATH.")
        return

    system_name = platform.system().lower()
    print()
    print("FFmpeg tools are missing from PATH: " + ", ".join(missing))
    print("Please install FFmpeg before converting audio.")
    if system_name == "windows":
        print("Windows: install FFmpeg, then add the bin folder to PATH.")
        print("If winget is available: winget install Gyan.FFmpeg")
    elif system_name == "darwin":
        print("macOS: brew install ffmpeg")
    else:
        print("Ubuntu/Debian: sudo apt update && sudo apt install ffmpeg")
        print("Fedora: sudo dnf install ffmpeg")
        print("Arch: sudo pacman -S ffmpeg")


def write_activation_hint(venv_dir: Path) -> None:
    system_name = platform.system().lower()
    print()
    print("Environment setup finished.")
    if system_name == "windows":
        print(f"Activate: {venv_dir}\\Scripts\\activate")
        print("Run app:  python main.py")
    else:
        print(f"Activate: source {venv_dir}/bin/activate")
        print("Run app:  python main.py")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the Music Resampler Qt environment.")
    parser.add_argument(
        "--venv",
        default=str(DEFAULT_VENV_DIR),
        help="Virtual environment path. Default: project .venv",
    )
    parser.add_argument(
        "--skip-ffmpeg-check",
        action="store_true",
        help="Skip checking whether ffmpeg and ffprobe are available in PATH.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    venv_dir = Path(args.venv).expanduser()
    if not venv_dir.is_absolute():
        venv_dir = PROJECT_ROOT / venv_dir

    try:
        python_path = create_venv(venv_dir)
        install_python_dependencies(python_path)
        if not args.skip_ffmpeg_check:
            check_ffmpeg()
        write_activation_hint(venv_dir)
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}", file=sys.stderr)
        return exc.returncode
    except Exception as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
