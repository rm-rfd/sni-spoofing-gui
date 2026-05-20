from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


XRAY_LOG_LEVELS = ("debug", "info", "warning", "error", "none")
GUI_EDITABLE_FIELDS = (
    "CONNECT_IP",
    "FAKE_SNI",
    "XRAY_URL",
    "XRAY_SOCKS_PORT",
    "XRAY_HTTP_PORT",
    "XRAY_LOG_LEVEL",
)


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parent)


def get_config_path() -> str:
    return os.path.join(get_app_dir(), "config.json")


def load_config() -> dict[str, Any]:
    with open(get_config_path(), "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    return config


def save_config(config: dict[str, Any]) -> None:
    config_path = Path(get_config_path())
    with config_path.open("w", encoding="utf-8", newline="\n") as config_file:
        json.dump(config, config_file, ensure_ascii=True, indent=2)
        config_file.write("\n")


def get_config_string(config: dict[str, Any], name: str, default: str = "") -> str:
    value = config.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def get_config_port(config: dict[str, Any], name: str, default: int) -> int:
    value = config.get(name, default)
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid TCP port") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{name} must be between 1 and 65535")
    return port


def normalize_xray_log_level(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized not in XRAY_LOG_LEVELS:
        raise ValueError(
            f"XRAY_LOG_LEVEL must be one of: {', '.join(XRAY_LOG_LEVELS)}"
        )
    return normalized