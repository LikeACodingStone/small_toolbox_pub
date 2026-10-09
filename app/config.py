from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UiConfig:
    font_size: int = 20
    log_font_size: int = 20
    table_row_height: int = 54
    log_max_height: int = 260


def _config_paths() -> tuple[Path, ...]:
    app_dir = Path(__file__).resolve().parent
    project_root = app_dir.parent
    return (
        project_root / "config.evn",
        project_root / "config.env",
        app_dir / "config.evn",
        app_dir / "config.env",
    )


def _read_config_file() -> dict[str, str]:
    values: dict[str, str] = {}
    for config_path in _config_paths():
        if not config_path.exists():
            continue
        for raw_line in config_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip().upper()] = value.strip()
    return values


def _int_value(values: dict[str, str], key: str, default: int, minimum: int = 1) -> int:
    try:
        value = int(values.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(minimum, value)


def load_ui_config() -> UiConfig:
    values = _read_config_file()
    return UiConfig(
        font_size=_int_value(values, "FONT_SIZE", UiConfig.font_size),
        log_font_size=_int_value(values, "LOG_FONT_SIZE", UiConfig.log_font_size),
        table_row_height=_int_value(values, "TABLE_ROW_HEIGHT", UiConfig.table_row_height),
        log_max_height=_int_value(values, "LOG_MAX_HEIGHT", UiConfig.log_max_height, minimum=80),
    )
