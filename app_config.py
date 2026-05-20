from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
import uuid

from utils.xray import parse_xray_share_url


XRAY_LOG_LEVELS = ("debug", "info", "warning", "error", "none")
XRAY_PROFILES_KEY = "XRAY_PROFILES"
XRAY_ACTIVE_PROFILE_ID_KEY = "XRAY_ACTIVE_PROFILE_ID"
GUI_EDITABLE_FIELDS = (
    "CONNECT_IP",
    "FAKE_SNI",
    "XRAY_SOCKS_PORT",
    "XRAY_HTTP_PORT",
    "XRAY_LOG_LEVEL",
)


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parent)


def get_config_path(config_path: str | None = None) -> str:
    if config_path:
        return os.path.abspath(config_path)
    return os.path.join(get_app_dir(), "config.json")


def load_config(config_path: str | None = None) -> dict[str, Any]:
    with open(get_config_path(config_path), "r", encoding="utf-8") as config_file:
        config = json.load(config_file)
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    return normalize_config(config)


def save_config(config: dict[str, Any], config_path: str | None = None) -> None:
    config_to_save = normalize_config(config)
    config_path = Path(get_config_path(config_path))
    with config_path.open("w", encoding="utf-8", newline="\n") as config_file:
        json.dump(config_to_save, config_file, ensure_ascii=True, indent=2)
        config_file.write("\n")


def build_xray_profile_record(
    share_url: str,
    *,
    profile_id: str | None = None,
) -> dict[str, Any]:
    normalized_share_url = share_url.strip()
    if not normalized_share_url:
        raise ValueError("XRAY share URL must not be empty")

    share_profile = parse_xray_share_url(normalized_share_url)
    network = (share_profile.query.get("type") or "tcp").strip().lower()
    default_security = "tls" if share_profile.protocol == "trojan" else "none"
    security = (share_profile.query.get("security") or default_security).strip().lower()

    normalized_profile_id = (profile_id or "").strip() or uuid.uuid4().hex
    return {
        "id": normalized_profile_id,
        "url": normalized_share_url,
        "tag": share_profile.tag,
        "protocol": share_profile.protocol,
        "address": share_profile.address,
        "port": share_profile.port,
        "transport": network,
        "security": security,
    }


def get_xray_profiles(config: dict[str, Any]) -> list[dict[str, Any]]:
    normalized_config = normalize_config(config)
    profiles = normalized_config.get(XRAY_PROFILES_KEY, [])
    if not isinstance(profiles, list):
        raise ValueError(f"{XRAY_PROFILES_KEY} must be a list")
    return [dict(profile) for profile in profiles]


def get_active_xray_profile(config: dict[str, Any]) -> dict[str, Any] | None:
    normalized_config = normalize_config(config)
    active_profile_id = get_config_string(
        normalized_config,
        XRAY_ACTIVE_PROFILE_ID_KEY,
        "",
    ).strip()
    if not active_profile_id:
        return None

    for profile in get_xray_profiles(normalized_config):
        if profile["id"] == active_profile_id:
            return profile
    return None


def get_active_xray_share_url(
    config: dict[str, Any],
) -> str:
    active_profile = get_active_xray_profile(config)
    if active_profile is not None:
        return str(active_profile["url"])
    return ""


def resolve_connect_port(config: dict[str, Any]) -> int:
    if get_config_bool(config, "FORCE_CONNECT_PORT", False):
        return get_config_port(config, "CONNECT_PORT", 443)

    share_url = get_active_xray_share_url(config)
    if share_url:
        return parse_xray_share_url(share_url).port
    return get_config_port(config, "CONNECT_PORT", 443)


def replace_xray_profiles(
    config: dict[str, Any],
    profiles: list[dict[str, Any]],
    *,
    active_profile_id: str | None = None,
) -> dict[str, Any]:
    normalized_profiles: list[dict[str, Any]] = []
    for index, raw_profile in enumerate(profiles):
        normalized_profiles.append(_normalize_xray_profile(raw_profile, index))

    resolved_active_profile: dict[str, Any] | None = None
    normalized_active_profile_id = (active_profile_id or "").strip()
    if normalized_active_profile_id:
        for profile in normalized_profiles:
            if profile["id"] == normalized_active_profile_id:
                resolved_active_profile = profile
                break

    if resolved_active_profile is None and normalized_profiles:
        resolved_active_profile = normalized_profiles[0]

    updated_config = dict(config)
    updated_config[XRAY_PROFILES_KEY] = normalized_profiles
    updated_config[XRAY_ACTIVE_PROFILE_ID_KEY] = (
        "" if resolved_active_profile is None else resolved_active_profile["id"]
    )
    return normalize_config(updated_config)


def normalize_config(config: dict[str, Any]) -> dict[str, Any]:
    normalized_config = dict(config)
    raw_profiles = normalized_config.get(XRAY_PROFILES_KEY)

    if raw_profiles is None:
        profiles = []
    else:
        profiles = _normalize_xray_profiles(raw_profiles)

    active_profile = _resolve_active_xray_profile(normalized_config, profiles)
    normalized_config[XRAY_PROFILES_KEY] = profiles
    normalized_config[XRAY_ACTIVE_PROFILE_ID_KEY] = "" if active_profile is None else active_profile["id"]
    return normalized_config


def _normalize_xray_profiles(raw_profiles: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_profiles, list):
        raise ValueError(f"{XRAY_PROFILES_KEY} must be a list")

    normalized_profiles: list[dict[str, Any]] = []
    seen_profile_ids: set[str] = set()

    for index, raw_profile in enumerate(raw_profiles):
        normalized_profile = _normalize_xray_profile(raw_profile, index)
        if normalized_profile["id"] in seen_profile_ids:
            normalized_profile = build_xray_profile_record(normalized_profile["url"])
        seen_profile_ids.add(str(normalized_profile["id"]))
        normalized_profiles.append(normalized_profile)

    return normalized_profiles


def _normalize_xray_profile(raw_profile: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw_profile, dict):
        raise ValueError(f"{XRAY_PROFILES_KEY}[{index}] must be an object")

    raw_profile_id = raw_profile.get("id", "")
    if raw_profile_id is not None and not isinstance(raw_profile_id, str):
        raise ValueError(f"{XRAY_PROFILES_KEY}[{index}].id must be a string")

    raw_share_url = raw_profile.get("url", "")
    if not isinstance(raw_share_url, str):
        raise ValueError(f"{XRAY_PROFILES_KEY}[{index}].url must be a string")

    return build_xray_profile_record(raw_share_url, profile_id=raw_profile_id)


def _resolve_active_xray_profile(
    config: dict[str, Any],
    profiles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not profiles:
        return None

    active_profile_id = get_config_string(config, XRAY_ACTIVE_PROFILE_ID_KEY, "").strip()
    if active_profile_id:
        for profile in profiles:
            if profile["id"] == active_profile_id:
                return profile

    return profiles[0]


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


def get_config_bool(config: dict[str, Any], name: str, default: bool = False) -> bool:
    value = config.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", ""}:
            return False
    raise ValueError(f"{name} must be a boolean")


def normalize_xray_log_level(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized not in XRAY_LOG_LEVELS:
        raise ValueError(
            f"XRAY_LOG_LEVEL must be one of: {', '.join(XRAY_LOG_LEVELS)}"
        )
    return normalized