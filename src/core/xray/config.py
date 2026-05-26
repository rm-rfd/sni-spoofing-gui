from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import uuid


class XrayConfigError(ValueError):
    pass


XRAY_INBOUND_MODE_MIXED = "mixed"
XRAY_INBOUND_MODE_TUN = "tun"


@dataclass(frozen=True)
class XrayShareProfile:
    protocol: str
    address: str
    port: int
    credential: str
    query: dict[str, str]
    tag: str


@dataclass(frozen=True)
class XrayLocalProxySettings:
    binary_path: str
    mixed_host: str
    mixed_port: int
    log_level: str
    inbound_mode: str = XRAY_INBOUND_MODE_MIXED
    tun_address: str = "198.18.0.1"
    tun_network: str = "tcp,udp"
    tun_mtu: int = 1500

    @property
    def inbound_tag(self) -> str:
        if self.inbound_mode == XRAY_INBOUND_MODE_TUN:
            return "tun-in"
        return "mixed-in"

    @property
    def uses_tun(self) -> bool:
        return self.inbound_mode == XRAY_INBOUND_MODE_TUN


def _last_query_values(query: str) -> dict[str, str]:
    parsed = parse_qs(query, keep_blank_values=True)
    return {key: values[-1] for key, values in parsed.items()}


def _parse_bool(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise XrayConfigError(f"invalid boolean value: {raw_value}")


def _parse_csv(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [item.strip() for item in raw_value.split(",") if item.strip()]


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def parse_xray_share_url(share_url: str) -> XrayShareProfile:
    parsed = urlparse(share_url.strip())
    protocol = parsed.scheme.lower()
    if protocol not in {"vless", "trojan"}:
        raise XrayConfigError("Xray share URL must start with vless:// or trojan://")
    if not parsed.username:
        if protocol == "vless":
            raise XrayConfigError("Xray share URL is missing the UUID")
        raise XrayConfigError("Xray share URL is missing the password")
    if not parsed.hostname:
        raise XrayConfigError("Xray share URL is missing the host")

    raw_credential = unquote(parsed.username)
    if protocol == "vless":
        try:
            credential = str(uuid.UUID(raw_credential))
        except ValueError as exc:
            raise XrayConfigError("Xray share URL contains an invalid UUID") from exc
    else:
        credential = raw_credential

    query = _last_query_values(parsed.query)
    return XrayShareProfile(
        protocol=protocol,
        address=parsed.hostname,
        port=parsed.port or 443,
        credential=credential,
        query=query,
        tag=unquote(parsed.fragment or f"{protocol}-profile"),
    )


def parse_vless_url(vless_url: str) -> XrayShareProfile:
    return parse_xray_share_url(vless_url)


def _build_tls_settings(query: dict[str, str], default_server_name: str | None = None) -> dict[str, Any]:
    tls_settings: dict[str, Any] = {}
    server_name = query.get("sni") or query.get("serverName") or default_server_name
    if server_name:
        tls_settings["serverName"] = server_name
    fingerprint = query.get("fp") or query.get("fingerprint")
    if fingerprint:
        tls_settings["fingerprint"] = fingerprint
    if "allowInsecure" in query or "insecure" in query:
        tls_settings["allowInsecure"] = _parse_bool(
            query.get("allowInsecure"),
            default=_parse_bool(query.get("insecure"), default=False),
        )
    alpn = _parse_csv(query.get("alpn"))
    if alpn:
        tls_settings["alpn"] = alpn
    return tls_settings


def _build_transport_settings(network: str, query: dict[str, str]) -> dict[str, Any]:
    path = query.get("path")
    host = query.get("host")
    if network in {"tcp", "raw"}:
        return {}
    if network == "ws":
        ws_settings: dict[str, Any] = {}
        if path:
            ws_settings["path"] = path
        if host:
            ws_settings["headers"] = {"Host": host}
        return {"wsSettings": ws_settings}
    if network == "grpc":
        grpc_settings: dict[str, Any] = {}
        service_name = query.get("serviceName")
        authority = query.get("authority")
        if service_name:
            grpc_settings["serviceName"] = service_name
        if authority:
            grpc_settings["authority"] = authority
        return {"grpcSettings": grpc_settings}
    if network == "httpupgrade":
        httpupgrade_settings: dict[str, Any] = {}
        if host:
            httpupgrade_settings["host"] = host
        if path:
            httpupgrade_settings["path"] = path
        return {"httpupgradeSettings": httpupgrade_settings}
    if network == "xhttp":
        xhttp_settings: dict[str, Any] = {}
        if host:
            xhttp_settings["host"] = host
        if path:
            xhttp_settings["path"] = path
        mode = query.get("mode")
        if mode:
            xhttp_settings["mode"] = mode
        return {"xhttpSettings": xhttp_settings}
    raise XrayConfigError(f"unsupported transport type: {network}")


def _build_proxy_outbound(
    profile: XrayShareProfile,
    relay_host: str,
    relay_port: int,
    stream_settings: dict[str, Any],
) -> dict[str, Any]:
    flow = profile.query.get("flow")

    if profile.protocol == "vless":
        user: dict[str, Any] = {
            "id": profile.credential,
            "encryption": profile.query.get("encryption", "none"),
        }
        if flow:
            user["flow"] = flow
        settings: dict[str, Any] = {
            "vnext": [
                {
                    "address": relay_host,
                    "port": relay_port,
                    "users": [user],
                }
            ]
        }
    elif profile.protocol == "trojan":
        server: dict[str, Any] = {
            "address": relay_host,
            "port": relay_port,
            "password": profile.credential,
        }
        if flow:
            server["flow"] = flow
        settings = {"servers": [server]}
    else:
        raise XrayConfigError(f"unsupported share link protocol: {profile.protocol}")

    return {
        "tag": "proxy",
        "protocol": profile.protocol,
        "settings": settings,
        "streamSettings": stream_settings,
    }


def _build_inbound(proxy_settings: XrayLocalProxySettings) -> dict[str, Any]:
    if proxy_settings.inbound_mode == XRAY_INBOUND_MODE_MIXED:
        return {
            "tag": proxy_settings.inbound_tag,
            "listen": proxy_settings.mixed_host,
            "port": proxy_settings.mixed_port,
            "protocol": "mixed",
            "settings": {"auth": "noauth", "udp": False},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        }

    if proxy_settings.inbound_mode == XRAY_INBOUND_MODE_TUN:
        return {
            "tag": proxy_settings.inbound_tag,
            "protocol": "tun",
            "port": 0,
            "settings": {
                "address": proxy_settings.tun_address,
                "net": proxy_settings.tun_network,
                "mtu": proxy_settings.tun_mtu,
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
        }

    raise XrayConfigError(f"unsupported xray inbound mode: {proxy_settings.inbound_mode}")


def build_xray_config(
    profile: XrayShareProfile,
    proxy_settings: XrayLocalProxySettings,
    relay_host: str,
    relay_port: int,
) -> dict[str, Any]:
    query = profile.query
    network = (query.get("type") or "tcp").strip().lower()
    default_security = "tls" if profile.protocol == "trojan" else "none"
    security = (query.get("security") or default_security).strip().lower()

    if profile.protocol == "trojan" and security != "tls":
        raise XrayConfigError("Trojan share links must use security=tls")

    stream_settings: dict[str, Any] = {"network": network, "security": security}
    if security == "tls":
        default_server_name = None if _is_ip_address(profile.address) else profile.address
        tls_settings = _build_tls_settings(query, default_server_name=default_server_name)
        if tls_settings:
            stream_settings["tlsSettings"] = tls_settings
    elif security != "none":
        raise XrayConfigError(f"unsupported security type: {security}")

    stream_settings.update(_build_transport_settings(network, query))

    return {
        "log": {"loglevel": proxy_settings.log_level},
        "inbounds": [_build_inbound(proxy_settings)],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": [proxy_settings.inbound_tag],
                    "outboundTag": "proxy",
                }
            ],
        },
        "outbounds": [
            _build_proxy_outbound(profile, relay_host, relay_port, stream_settings),
            {"tag": "direct", "protocol": "freedom", "settings": {}},
        ],
    }


__all__ = [
    "XrayConfigError",
    "XRAY_INBOUND_MODE_MIXED",
    "XRAY_INBOUND_MODE_TUN",
    "XrayShareProfile",
    "XrayLocalProxySettings",
    "parse_xray_share_url",
    "parse_vless_url",
    "build_xray_config",
]
