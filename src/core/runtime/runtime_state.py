from __future__ import annotations

import os

from src.core.config.app_config import (
    get_active_xray_share_url,
    get_app_dir,
    get_connection_mode,
    get_config_port,
    get_local_proxy_bind_host,
    get_local_proxy_port,
    get_config_string,
    load_config,
    resolve_connect_port,
)
from src.utils.network_tools import get_default_interface_ipv4
from src.core.xray.config import (
    XRAY_INBOUND_MODE_MIXED,
    XRAY_INBOUND_MODE_TUN,
    XrayLocalProxySettings,
    build_xray_config,
    parse_xray_share_url,
)
from src.core.xray.process import XrayProcessManager


config: dict[str, object] = {}
CONFIG_PATH_OVERRIDE: str | None = None
LISTEN_HOST = ""
LISTEN_PORT = 0
FAKE_SNI = b""
CONNECT_IP = ""
CONNECT_PORT = 0
INTERFACE_IPV4 = ""
DATA_MODE = "tls"
BYPASS_METHOD = "wrong_seq"

fake_injective_connections: dict[tuple, object] = {}


def set_config_path_override(config_path: str | None) -> None:
    global CONFIG_PATH_OVERRIDE
    CONFIG_PATH_OVERRIDE = config_path


def load_runtime_settings(config_path: str | None = None) -> None:
    global config, LISTEN_HOST, LISTEN_PORT, FAKE_SNI, CONNECT_IP, CONNECT_PORT, INTERFACE_IPV4

    config = load_config(config_path or CONFIG_PATH_OVERRIDE)
    LISTEN_HOST = get_config_string(config, "LISTEN_HOST", "0.0.0.0")
    LISTEN_PORT = get_config_port(config, "LISTEN_PORT", 40443)

    connect_ip = get_config_string(config, "CONNECT_IP").strip()
    if not connect_ip:
        raise ValueError("CONNECT_IP must not be empty")

    fake_sni = get_config_string(config, "FAKE_SNI").strip()
    if not fake_sni:
        raise ValueError("FAKE_SNI must not be empty")

    CONNECT_IP = connect_ip
    CONNECT_PORT = resolve_connect_port(config)
    FAKE_SNI = fake_sni.encode()
    INTERFACE_IPV4 = get_default_interface_ipv4(CONNECT_IP)
    if not INTERFACE_IPV4:
        raise ValueError(f"Could not determine a local IPv4 route for CONNECT_IP={CONNECT_IP}")


def ensure_runtime_settings_loaded() -> None:
    if config:
        return
    load_runtime_settings(CONFIG_PATH_OVERRIDE)


def resolve_runtime_path(relative_or_absolute_path: str) -> str:
    if os.path.isabs(relative_or_absolute_path):
        return relative_or_absolute_path
    return os.path.normpath(os.path.join(get_app_dir(), relative_or_absolute_path))


def get_xray_relay_host(
    config_override: dict[str, object] | None = None,
    listen_host: str | None = None,
) -> str:
    resolved_config = config if config_override is None else config_override
    resolved_listen_host = LISTEN_HOST if listen_host is None else listen_host

    explicit_relay_host = get_config_string(resolved_config, "XRAY_RELAY_HOST", "").strip()
    if explicit_relay_host:
        return explicit_relay_host
    if resolved_listen_host == "0.0.0.0":
        return "127.0.0.1"
    if resolved_listen_host == "::":
        return "::1"
    return resolved_listen_host


def _hosts_share_listener_space(left_host: str, right_host: str) -> bool:
    if left_host == right_host:
        return True
    if left_host in {"0.0.0.0", "::"}:
        return True
    if right_host in {"0.0.0.0", "::"}:
        return True
    return False


def build_xray_manager(
    config_override: dict[str, object] | None = None,
) -> tuple[XrayProcessManager | None, XrayLocalProxySettings | None]:
    ensure_runtime_settings_loaded()
    resolved_config = config if config_override is None else config_override
    share_url = get_active_xray_share_url(resolved_config)
    if not share_url:
        return None, None

    connection_mode = get_connection_mode(resolved_config)
    inbound_mode = (
        XRAY_INBOUND_MODE_TUN
        if connection_mode == "tunnel whole system"
        else XRAY_INBOUND_MODE_MIXED
    )

    xray_settings = XrayLocalProxySettings(
        binary_path=resolve_runtime_path(
            get_config_string(resolved_config, "XRAY_BINARY_PATH", os.path.join("xray", "xray.exe"))
        ),
        mixed_host="127.0.0.1",
        shared_mixed_host=get_local_proxy_bind_host(resolved_config),
        mixed_port=get_local_proxy_port(resolved_config),
        log_level=get_config_string(resolved_config, "XRAY_LOG_LEVEL", "warning"),
        inbound_mode=inbound_mode,
    )
    if LISTEN_PORT == xray_settings.mixed_port and any(
        _hosts_share_listener_space(LISTEN_HOST, mixed_host)
        for mixed_host in xray_settings.mixed_bind_hosts
    ):
        raise ValueError("LISTEN_PORT must be different from LOCAL_PROXY_PORT")

    share_profile = parse_xray_share_url(share_url)
    relay_host = get_xray_relay_host(resolved_config, LISTEN_HOST)
    xray_config = build_xray_config(share_profile, xray_settings, relay_host, LISTEN_PORT)
    return XrayProcessManager(xray_settings.binary_path, xray_config), xray_settings


def maybe_start_xray_proxy() -> tuple[XrayProcessManager | None, XrayLocalProxySettings | None]:
    load_runtime_settings(CONFIG_PATH_OVERRIDE)
    xray_manager, xray_settings = build_xray_manager()
    if xray_manager is None:
        return None, None
    xray_manager.start()
    return xray_manager, xray_settings


def stop_xray_proxy(xray_manager: XrayProcessManager | None) -> None:
    if xray_manager is None:
        return
    xray_manager.stop()


__all__ = [
    "config",
    "CONFIG_PATH_OVERRIDE",
    "LISTEN_HOST",
    "LISTEN_PORT",
    "FAKE_SNI",
    "CONNECT_IP",
    "CONNECT_PORT",
    "INTERFACE_IPV4",
    "DATA_MODE",
    "BYPASS_METHOD",
    "fake_injective_connections",
    "set_config_path_override",
    "load_runtime_settings",
    "ensure_runtime_settings_loaded",
    "resolve_runtime_path",
    "get_xray_relay_host",
    "build_xray_manager",
    "maybe_start_xray_proxy",
    "stop_xray_proxy",
]
