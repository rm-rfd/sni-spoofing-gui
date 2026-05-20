from __future__ import annotations

from dataclasses import dataclass
import ipaddress
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
import json
import subprocess
import tempfile
import uuid


class XrayConfigError(ValueError):
    pass


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
    socks_host: str
    socks_port: int
    http_host: str
    http_port: int
    log_level: str


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
        raise XrayConfigError("XRAY_URL must start with vless:// or trojan://")
    if not parsed.username:
        if protocol == "vless":
            raise XrayConfigError("XRAY_URL is missing the UUID")
        raise XrayConfigError("XRAY_URL is missing the password")
    if not parsed.hostname:
        raise XrayConfigError("XRAY_URL is missing the host")

    raw_credential = unquote(parsed.username)
    if protocol == "vless":
        try:
            credential = str(uuid.UUID(raw_credential))
        except ValueError as exc:
            raise XrayConfigError("XRAY_URL contains an invalid UUID") from exc
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
        "inbounds": [
            {
                "tag": "socks-in",
                "listen": proxy_settings.socks_host,
                "port": proxy_settings.socks_port,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": False},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            },
            {
                "tag": "http-in",
                "listen": proxy_settings.http_host,
                "port": proxy_settings.http_port,
                "protocol": "http",
                "settings": {},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            },
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [
                {
                    "type": "field",
                    "inboundTag": ["socks-in", "http-in"],
                    "outboundTag": "proxy",
                }
            ],
        },
        "outbounds": [
            _build_proxy_outbound(profile, relay_host, relay_port, stream_settings),
            {"tag": "direct", "protocol": "freedom", "settings": {}},
        ],
    }


class XrayProcessManager:
    def __init__(self, binary_path: str, config: dict[str, Any]):
        self.binary_path = Path(binary_path).expanduser().resolve()
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.runtime_config_path: Path | None = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        if not self.binary_path.is_file():
            raise FileNotFoundError(f"xray binary not found: {self.binary_path}")
        self.runtime_config_path = self._write_runtime_config()
        self._validate_runtime_config()
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [str(self.binary_path), "run", "-c", str(self.runtime_config_path)],
            cwd=str(self.binary_path.parent),
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        try:
            self.process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            return
        raise RuntimeError(f"xray exited immediately with code {self.process.returncode}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None
        self._cleanup_runtime_config()

    def _write_runtime_config(self) -> Path:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix="sni-spoofing-xray-",
            encoding="utf-8",
            newline="\n",
            delete=False,
        )
        with temp_file:
            json.dump(self.config, temp_file, ensure_ascii=True, indent=2)
            temp_file.write("\n")
        return Path(temp_file.name)

    def _validate_runtime_config(self) -> None:
        if self.runtime_config_path is None:
            raise RuntimeError("runtime xray config path is not initialized")
        result = subprocess.run(
            [str(self.binary_path), "run", "-test", "-c", str(self.runtime_config_path)],
            cwd=str(self.binary_path.parent),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return
        self._cleanup_runtime_config()
        details = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        raise XrayConfigError(f"xray rejected the generated config:\n{details}")

    def _cleanup_runtime_config(self) -> None:
        if self.runtime_config_path is not None:
            self.runtime_config_path.unlink(missing_ok=True)
            self.runtime_config_path = None