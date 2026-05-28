from __future__ import annotations

import ipaddress
import json
import os
import sys
from pathlib import Path
from typing import Any
import uuid

from src.core.xray.config import parse_xray_share_url


XRAY_LOG_LEVELS = ("debug", "info", "warning", "error", "none")
CONNECTION_MODES = (
    "clear system proxy",
    "set system proxy",
    "tunnel whole system",
)
DEFAULT_CONNECTION_MODE = CONNECTION_MODES[0]
DEFAULT_LOCAL_PROXY_PORT = 10809
DEFAULT_LOCAL_PROXY_BIND_HOST = "127.0.0.1"
LOCAL_PROXY_BIND_ALL_HOST = "0.0.0.0"
DEFAULT_TUNNEL_DNS_SERVERS = ("1.1.1.1", "1.0.0.1")
DELAY_TEST_RESULTS_KEY = "DELAY_TEST_RESULTS"
XRAY_PROFILES_KEY = "XRAY_PROFILES"
XRAY_ACTIVE_PROFILE_ID_KEY = "XRAY_ACTIVE_PROFILE_ID"
GUI_EDITABLE_FIELDS = (
    "CONNECT_IP",
    "FAKE_SNI",
    "CONNECTION_MODE",
    "LOCAL_PROXY_PORT",
    "XRAY_LOG_LEVEL",
)


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parents[3])


def get_asset_root() -> Path:
    app_dir = Path(get_app_dir())
    if getattr(sys, "frozen", False):
        return app_dir

    src_assets_dir = app_dir / "src" / "assets"
    if src_assets_dir.is_dir():
        return src_assets_dir
    return app_dir


def get_asset_path(*parts: str) -> Path:
    asset_root = get_asset_root()
    if not parts:
        return asset_root

    candidate = asset_root.joinpath(*parts)
    if candidate.exists():
        return candidate

    if getattr(sys, "frozen", False):
        return candidate

    return Path(get_app_dir()).joinpath(*parts)


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


def get_active_xray_share_url(config: dict[str, Any]) -> str:
    active_profile = get_active_xray_profile(config)
    if active_profile is not None:
        return str(active_profile["url"])
    return ""


def load_delay_results(config: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    normalized_config = normalize_config(load_config() if config is None else config)
    raw_delay_results = normalized_config.get(DELAY_TEST_RESULTS_KEY, {})
    if raw_delay_results is None:
        return {}
    if not isinstance(raw_delay_results, dict):
        raise ValueError(f"{DELAY_TEST_RESULTS_KEY} must be an object")

    delay_results: dict[str, dict[str, str]] = {}
    for profile_id, raw_result in raw_delay_results.items():
        if not isinstance(profile_id, str):
            raise ValueError(f"{DELAY_TEST_RESULTS_KEY} keys must be strings")
        if not isinstance(raw_result, dict):
            raise ValueError(f"{DELAY_TEST_RESULTS_KEY}[{profile_id}] must be an object")

        delay_value = raw_result.get("delay_value", "")
        delay_status = raw_result.get("delay_status", "")
        delay_state = raw_result.get("delay_state", "")
        if not isinstance(delay_value, str):
            raise ValueError(f"{DELAY_TEST_RESULTS_KEY}[{profile_id}].delay_value must be a string")
        if not isinstance(delay_status, str):
            raise ValueError(f"{DELAY_TEST_RESULTS_KEY}[{profile_id}].delay_status must be a string")
        if not isinstance(delay_state, str):
            raise ValueError(f"{DELAY_TEST_RESULTS_KEY}[{profile_id}].delay_state must be a string")

        normalized_delay_state = delay_state.strip().lower()
        if normalized_delay_state not in {"success", "error"}:
            continue

        delay_results[profile_id] = {
            "delay_value": delay_value.strip(),
            "delay_status": delay_status.strip(),
            "delay_state": normalized_delay_state,
        }

    return delay_results


def save_delay_result(
    profile_id: str,
    delay_value: str,
    delay_status: str,
    delay_state: str,
    config_path: str | None = None,
) -> None:
    normalized_profile_id = profile_id.strip()
    if not normalized_profile_id:
        raise ValueError("profile_id must not be empty")

    config = load_config(config_path)
    delay_results = load_delay_results(config)
    normalized_delay_state = delay_state.strip().lower()
    if normalized_delay_state not in {"success", "error"}:
        delay_results.pop(normalized_profile_id, None)
    else:
        delay_results[normalized_profile_id] = {
            "delay_value": delay_value.strip(),
            "delay_status": delay_status.strip(),
            "delay_state": normalized_delay_state,
        }

    updated_config = dict(config)
    updated_config[DELAY_TEST_RESULTS_KEY] = delay_results
    save_config(updated_config, config_path)


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
    normalized_config["CONNECTION_MODE"] = get_connection_mode(normalized_config)
    normalized_config["LOCAL_PROXY_BIND_HOST"] = get_local_proxy_bind_host(normalized_config)
    normalized_config["LOCAL_PROXY_PORT"] = get_local_proxy_port(normalized_config)
    normalized_config["TUNNEL_DNS_SERVERS"] = list(get_tunnel_dns_servers(normalized_config))
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


def normalize_connection_mode(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized not in CONNECTION_MODES:
        raise ValueError(
            f"CONNECTION_MODE must be one of: {', '.join(CONNECTION_MODES)}"
        )
    return normalized


def get_connection_mode(
    config: dict[str, Any],
    default: str = DEFAULT_CONNECTION_MODE,
) -> str:
    raw_value = get_config_string(config, "CONNECTION_MODE", default)
    return normalize_connection_mode(raw_value)


def get_local_proxy_port(
    config: dict[str, Any],
    default: int = DEFAULT_LOCAL_PROXY_PORT,
) -> int:
    return get_config_port(config, "LOCAL_PROXY_PORT", default)


def normalize_local_proxy_bind_host(
    raw_value: str,
    default: str = DEFAULT_LOCAL_PROXY_BIND_HOST,
) -> str:
    normalized = raw_value.strip()
    if not normalized:
        return default

    try:
        parsed = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise ValueError(
            "LOCAL_PROXY_BIND_HOST must be a valid IPv4 address or the wildcard 0.0.0.0"
        ) from exc

    if parsed.version != 4:
        raise ValueError("LOCAL_PROXY_BIND_HOST currently supports IPv4 only")

    return str(parsed)


def get_local_proxy_bind_host(
    config: dict[str, Any],
    default: str = DEFAULT_LOCAL_PROXY_BIND_HOST,
) -> str:
    raw_value = get_config_string(config, "LOCAL_PROXY_BIND_HOST", default)
    return normalize_local_proxy_bind_host(raw_value, default)


def get_local_proxy_bind_host_warning(bind_host: str) -> str | None:
    if normalize_local_proxy_bind_host(bind_host) != LOCAL_PROXY_BIND_ALL_HOST:
        return None
    return (
        "Binding the local mixed proxy to 0.0.0.0 exposes an unauthenticated proxy to "
        "other devices on the local network."
    )


def get_tunnel_dns_servers(
    config: dict[str, Any],
    default: tuple[str, ...] = DEFAULT_TUNNEL_DNS_SERVERS,
) -> tuple[str, ...]:
    raw_value = config.get("TUNNEL_DNS_SERVERS")
    if raw_value is None:
        return tuple(default)

    if isinstance(raw_value, str):
        values = [item.strip() for item in raw_value.split(",") if item.strip()]
    elif isinstance(raw_value, list):
        if any(not isinstance(item, str) for item in raw_value):
            raise ValueError("TUNNEL_DNS_SERVERS must contain only strings")
        values = [item.strip() for item in raw_value if item.strip()]
    else:
        raise ValueError("TUNNEL_DNS_SERVERS must be a comma-separated string or a list of strings")

    if not values:
        raise ValueError("TUNNEL_DNS_SERVERS must not be empty")

    normalized_values: list[str] = []
    for value in values:
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"TUNNEL_DNS_SERVERS contains an invalid IP address: {value}") from exc
        if parsed.version != 4:
            raise ValueError(f"TUNNEL_DNS_SERVERS currently supports IPv4 only: {value}")
        normalized_values.append(str(parsed))

    return tuple(normalized_values)


def normalize_xray_log_level(raw_value: str) -> str:
    normalized = raw_value.strip().lower()
    if normalized not in XRAY_LOG_LEVELS:
        raise ValueError(
            f"XRAY_LOG_LEVEL must be one of: {', '.join(XRAY_LOG_LEVELS)}"
        )
    return normalized


__all__ = [name for name in globals() if not name.startswith("_")]
