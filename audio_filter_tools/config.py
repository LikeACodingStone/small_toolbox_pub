from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
INSTALLED_DIR = PROJECT_ROOT / "installed"

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".opus", ".aac"}
BASE_FONT_SIZE = 20

