import logging
from logging.handlers import RotatingFileHandler

from .config import LOG_DIR


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )

    app_handler = RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(fmt)

    debug_handler = RotatingFileHandler(
        LOG_DIR / "debug.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)

    root.addHandler(app_handler)
    root.addHandler(debug_handler)
    root.addHandler(console)
