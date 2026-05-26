from __future__ import annotations

from dataclasses import dataclass, field
import json
import subprocess
import time
from typing import Any, Callable, Protocol, runtime_checkable

from src.core.config.app_config import get_config_string, get_local_proxy_port, get_tunnel_dns_servers
from src.core.xray.config import XrayLocalProxySettings
from src.core.xray.process import XrayProcessManager


SELECTED_TUNNEL_BACKEND_ID = "xray-tun"
TUNNEL_ADAPTER_DESCRIPTION = "Xray Tunnel"
TUNNEL_ADAPTER_NAME_PREFIX = "xray"
TUNNEL_DEFAULT_ROUTE_PREFIX = "0.0.0.0/0"
TUNNEL_DEFAULT_ROUTE_NEXT_HOP = "0.0.0.0"
TUNNEL_DEFAULT_ROUTE_METRIC = 1
TUNNEL_DISCOVERY_INTERVAL_SECONDS = 0.2
TUNNEL_DISCOVERY_TIMEOUT_SECONDS = 6.0
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class TunnelBackendPlan:
    backend_id: str
    display_name: str
    rationale: str
    dns_strategy: str
    udp_supported: bool
    packaging_notes: tuple[str, ...]
    admin_requirements: tuple[str, ...]
    exclusion_notes: tuple[str, ...]


@dataclass(frozen=True)
class TunnelBackendPreparation:
    backend_id: str
    local_proxy_port: int
    upstream_connect_ip: str
    adapter_name: str = ""
    original_gateway: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TunnelBackendHealth:
    ok: bool
    detail: str
    adapter_name: str = ""
    backend_pid: int = 0


@dataclass(frozen=True)
class WindowsRouteRecord:
    destination_prefix: str
    next_hop: str
    interface_index: int
    interface_alias: str = ""
    route_metric: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "destination_prefix": self.destination_prefix,
            "next_hop": self.next_hop,
            "interface_index": self.interface_index,
            "interface_alias": self.interface_alias,
            "route_metric": self.route_metric,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> WindowsRouteRecord:
        destination_prefix = str(payload.get("destination_prefix", "")).strip()
        next_hop = str(payload.get("next_hop", "")).strip()
        interface_alias = str(payload.get("interface_alias", "")).strip()
        interface_index = int(payload.get("interface_index", 0))
        route_metric = int(payload.get("route_metric", 0))
        if not destination_prefix:
            raise ValueError("route payload destination_prefix must not be empty")
        if not next_hop:
            raise ValueError("route payload next_hop must not be empty")
        if interface_index < 1:
            raise ValueError("route payload interface_index must be positive")
        return cls(
            destination_prefix=destination_prefix,
            next_hop=next_hop,
            interface_index=interface_index,
            interface_alias=interface_alias,
            route_metric=route_metric,
        )


@dataclass(frozen=True)
class WindowsDnsServerState:
    interface_index: int
    interface_alias: str = ""
    server_addresses: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "interface_index": self.interface_index,
            "interface_alias": self.interface_alias,
            "server_addresses": list(self.server_addresses),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> WindowsDnsServerState:
        interface_index = int(payload.get("interface_index", 0))
        interface_alias = str(payload.get("interface_alias", "")).strip()
        raw_server_addresses = payload.get("server_addresses", [])
        if interface_index < 1:
            raise ValueError("dns payload interface_index must be positive")
        if isinstance(raw_server_addresses, str):
            server_addresses = (raw_server_addresses.strip(),) if raw_server_addresses.strip() else ()
        elif isinstance(raw_server_addresses, list):
            server_addresses = tuple(
                str(value).strip() for value in raw_server_addresses if str(value).strip()
            )
        else:
            raise ValueError("dns payload server_addresses must be a string or list")
        return cls(
            interface_index=interface_index,
            interface_alias=interface_alias,
            server_addresses=server_addresses,
        )


@dataclass(frozen=True)
class TunnelAdapterRecord:
    name: str
    interface_description: str
    status: str
    interface_index: int

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> TunnelAdapterRecord:
        name = str(payload.get("Name", "")).strip()
        interface_description = str(payload.get("InterfaceDescription", "")).strip()
        status = str(payload.get("Status", "")).strip()
        interface_index = int(payload.get("InterfaceIndex", 0))
        if not name:
            raise ValueError("tunnel adapter name must not be empty")
        if interface_index < 1:
            raise ValueError("tunnel adapter interface index must be positive")
        return cls(
            name=name,
            interface_description=interface_description,
            status=status,
            interface_index=interface_index,
        )


@runtime_checkable
class TunnelBackend(Protocol):
    def prepare(self, config: dict[str, object]) -> TunnelBackendPreparation:
        ...

    def start(self) -> None:
        ...

    def apply_routes(self) -> None:
        ...

    def apply_dns(self) -> None:
        ...

    def check_health(self) -> TunnelBackendHealth:
        ...

    def stop(self) -> None:
        ...

    def restore_routes(self) -> None:
        ...

    def restore_dns(self) -> None:
        ...

    def describe_state(self) -> dict[str, object]:
        ...


class XrayTunTunnelBackend:
    def __init__(
        self,
        xray_manager: XrayProcessManager,
        xray_settings: XrayLocalProxySettings,
        *,
        log_callback: LogCallback | None = None,
    ):
        if not xray_settings.uses_tun:
            raise ValueError("Xray TUN backend requires TUN-mode Xray settings")
        self.xray_manager = xray_manager
        self.xray_settings = xray_settings
        self.log_callback = log_callback
        self.preparation: TunnelBackendPreparation | None = None
        self.adapter: TunnelAdapterRecord | None = None
        self.original_default_route: WindowsRouteRecord | None = None
        self.original_dns_state: WindowsDnsServerState | None = None
        self._preexisting_adapter_indexes: set[int] = set()
        self._managed_routes: list[WindowsRouteRecord] = []
        self._dns_servers: tuple[str, ...] = ()

    def prepare(self, config: dict[str, object]) -> TunnelBackendPreparation:
        upstream_connect_ip = get_config_string(config, "CONNECT_IP").strip()
        if not upstream_connect_ip:
            raise ValueError("Tunnel backend requires CONNECT_IP")

        self.original_default_route = _get_active_default_route()
        self._dns_servers = get_tunnel_dns_servers(config)
        self._preexisting_adapter_indexes = {
            adapter.interface_index for adapter in _list_xray_tunnel_adapters()
        }
        self.preparation = TunnelBackendPreparation(
            backend_id=SELECTED_TUNNEL_BACKEND_ID,
            local_proxy_port=get_local_proxy_port(config),
            upstream_connect_ip=upstream_connect_ip,
            original_gateway=self.original_default_route.next_hop,
            metadata={
                "original_default_route": self.original_default_route.to_dict(),
                "preexisting_adapter_indexes": sorted(self._preexisting_adapter_indexes),
                "dns_servers": list(self._dns_servers),
            },
        )
        return self.preparation

    def start(self) -> None:
        if self.preparation is None:
            raise RuntimeError("Tunnel backend must be prepared before start")
        self.xray_manager.start()
        self.adapter = _wait_for_tunnel_adapter(self._preexisting_adapter_indexes)
        _emit_log(
            self.log_callback,
            f"[start] tunnel adapter ready: {self.adapter.name} (ifIndex {self.adapter.interface_index})",
        )

    def apply_routes(self) -> None:
        if self.preparation is None:
            raise RuntimeError("Tunnel backend must be prepared before route setup")
        if self.adapter is None:
            raise RuntimeError("Tunnel adapter is not available")
        if self.original_default_route is None:
            raise RuntimeError("Original default route is not available")

        exclusion_route = WindowsRouteRecord(
            destination_prefix=f"{self.preparation.upstream_connect_ip}/32",
            next_hop=self.original_default_route.next_hop,
            interface_index=self.original_default_route.interface_index,
            interface_alias=self.original_default_route.interface_alias,
            route_metric=self.original_default_route.route_metric,
        )
        tunnel_default_route = WindowsRouteRecord(
            destination_prefix=TUNNEL_DEFAULT_ROUTE_PREFIX,
            next_hop=TUNNEL_DEFAULT_ROUTE_NEXT_HOP,
            interface_index=self.adapter.interface_index,
            interface_alias=self.adapter.name,
            route_metric=TUNNEL_DEFAULT_ROUTE_METRIC,
        )

        for route in (exclusion_route, tunnel_default_route):
            if _route_exists(route):
                self._managed_routes.append(route)
                continue
            _add_route(route)
            self._managed_routes.append(route)

        _emit_log(
            self.log_callback,
            f"[start] preserved direct route to {self.preparation.upstream_connect_ip} via "
            f"{self.original_default_route.next_hop}",
        )
        _emit_log(
            self.log_callback,
            f"[start] default IPv4 route moved to tunnel adapter {self.adapter.name}",
        )

    def apply_dns(self) -> None:
        if self.adapter is None:
            raise RuntimeError("Tunnel adapter is not available")

        self.original_dns_state = _get_dns_server_state(self.adapter.interface_index)
        desired_dns_state = WindowsDnsServerState(
            interface_index=self.adapter.interface_index,
            interface_alias=self.adapter.name,
            server_addresses=self._dns_servers,
        )
        if self.original_dns_state.server_addresses == desired_dns_state.server_addresses:
            _emit_log(
                self.log_callback,
                f"[start] tunnel adapter DNS already set to {_format_dns_servers_for_log(self._dns_servers)}",
            )
            return

        _set_dns_server_state(desired_dns_state)
        _emit_log(
            self.log_callback,
            f"[start] tunnel adapter DNS set to {_format_dns_servers_for_log(self._dns_servers)}",
        )

    def check_health(self) -> TunnelBackendHealth:
        process = self.xray_manager.process
        if process is None or process.poll() is not None:
            return TunnelBackendHealth(ok=False, detail="xray process is not running")
        adapter = self.adapter
        if adapter is None:
            return TunnelBackendHealth(ok=False, detail="tunnel adapter is not initialized")

        current_adapter = _get_xray_tunnel_adapter_by_index(adapter.interface_index)
        if current_adapter is None:
            return TunnelBackendHealth(
                ok=False,
                detail="tunnel adapter is no longer present",
                adapter_name=adapter.name,
                backend_pid=process.pid,
            )
        if current_adapter.status.lower() != "up":
            return TunnelBackendHealth(
                ok=False,
                detail=f"tunnel adapter is {current_adapter.status}",
                adapter_name=current_adapter.name,
                backend_pid=process.pid,
            )
        if self.original_dns_state is not None:
            current_dns_state = _get_dns_server_state(current_adapter.interface_index)
            if current_dns_state.server_addresses != self._dns_servers:
                return TunnelBackendHealth(
                    ok=False,
                    detail=(
                        "tunnel adapter DNS does not match the configured DNS servers: "
                        f"{_format_dns_servers_for_log(current_dns_state.server_addresses)}"
                    ),
                    adapter_name=current_adapter.name,
                    backend_pid=process.pid,
                )

        return TunnelBackendHealth(
            ok=True,
            detail="tunnel adapter is up and xray is running",
            adapter_name=current_adapter.name,
            backend_pid=process.pid,
        )

    def stop(self) -> None:
        self.xray_manager.stop()
        self.adapter = None

    def restore_routes(self) -> None:
        while self._managed_routes:
            route = self._managed_routes.pop()
            _remove_route(route)

        if self.preparation is not None:
            _emit_log(
                self.log_callback,
                f"[stop] restored direct route ownership for {self.preparation.upstream_connect_ip}",
            )

    def restore_dns(self) -> None:
        if self.original_dns_state is None:
            return
        if not _interface_exists(self.original_dns_state.interface_index):
            return
        _restore_dns_server_state(self.original_dns_state)
        if self.original_dns_state.server_addresses:
            restored_detail = _format_dns_servers_for_log(self.original_dns_state.server_addresses)
        else:
            restored_detail = "automatic DNS"
        _emit_log(self.log_callback, f"[stop] restored tunnel adapter DNS to {restored_detail}")

    def describe_state(self) -> dict[str, object]:
        return {
            "backend_id": SELECTED_TUNNEL_BACKEND_ID,
            "adapter_name": "" if self.adapter is None else self.adapter.name,
            "adapter_interface_index": 0 if self.adapter is None else self.adapter.interface_index,
            "upstream_connect_ip": ""
            if self.preparation is None
            else self.preparation.upstream_connect_ip,
            "original_default_route": None
            if self.original_default_route is None
            else self.original_default_route.to_dict(),
            "original_dns_state": None
            if self.original_dns_state is None
            else self.original_dns_state.to_dict(),
            "dns_servers": list(self._dns_servers),
            "managed_routes": [route.to_dict() for route in self._managed_routes],
        }


def build_tunnel_backend(
    xray_manager: XrayProcessManager | None,
    xray_settings: XrayLocalProxySettings | None,
    *,
    log_callback: LogCallback | None = None,
) -> TunnelBackend:
    if xray_manager is None or xray_settings is None:
        raise ValueError("Tunnel backend requires an active Xray runtime")
    return XrayTunTunnelBackend(
        xray_manager,
        xray_settings,
        log_callback=log_callback,
    )


def cleanup_stale_tunnel_backend_state(
    state: dict[str, object],
    *,
    log_callback: LogCallback | None = None,
) -> None:
    raw_original_dns_state = state.get("original_dns_state")
    raw_routes = state.get("managed_routes", [])
    if not isinstance(raw_routes, list):
        raise ValueError("stale tunnel backend managed_routes must be a list")

    original_dns_state = None
    if isinstance(raw_original_dns_state, dict):
        original_dns_state = WindowsDnsServerState.from_dict(raw_original_dns_state)
        _restore_dns_server_state(original_dns_state)

    managed_routes = [WindowsRouteRecord.from_dict(route) for route in raw_routes if isinstance(route, dict)]
    for route in reversed(managed_routes):
        _remove_route(route)

    upstream_connect_ip = str(state.get("upstream_connect_ip", "")).strip()
    if original_dns_state is not None:
        _emit_log(log_callback, "[start] repaired stale tunnel adapter DNS state")
    if upstream_connect_ip:
        _emit_log(log_callback, f"[start] repaired stale tunnel routes for {upstream_connect_ip}")


def _emit_log(log_callback: LogCallback | None, message: str) -> None:
    if log_callback is not None:
        log_callback(message)


def _run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    if result.returncode == 0:
        return result

    details = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
    raise RuntimeError(f"PowerShell command failed:\n{details}")


def _run_powershell_json(script: str) -> object | None:
    result = _run_powershell(script)
    output = result.stdout.strip()
    if not output:
        return None
    return json.loads(output)


def _get_active_default_route() -> WindowsRouteRecord:
    payload = _run_powershell_json(
        "$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
        "| Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.InterfaceAlias -notlike 'xray*' } "
        "| Sort-Object { $_.RouteMetric + $_.InterfaceMetric } "
        "| Select-Object -First 1 DestinationPrefix, NextHop, InterfaceIndex, InterfaceAlias, RouteMetric; "
        "if ($null -eq $route) { '' } else { $route | ConvertTo-Json -Compress }"
    )
    if not isinstance(payload, dict):
        raise RuntimeError("Could not determine the current IPv4 default route")
    return WindowsRouteRecord.from_dict(
        {
            "destination_prefix": payload.get("DestinationPrefix", ""),
            "next_hop": payload.get("NextHop", ""),
            "interface_index": payload.get("InterfaceIndex", 0),
            "interface_alias": payload.get("InterfaceAlias", ""),
            "route_metric": payload.get("RouteMetric", 0),
        }
    )


def _list_xray_tunnel_adapters() -> list[TunnelAdapterRecord]:
    payload = _run_powershell_json(
        "$adapters = Get-NetAdapter -IncludeHidden -ErrorAction SilentlyContinue "
        "| Where-Object { ($_.Name -like 'xray*' -or $_.InterfaceDescription -eq 'Xray Tunnel') -and $_.Status -eq 'Up' } "
        "| Select-Object Name, InterfaceDescription, Status, InterfaceIndex; "
        "if ($null -eq $adapters) { '' } else { $adapters | ConvertTo-Json -Compress }"
    )
    if payload is None:
        return []
    if isinstance(payload, dict):
        return [TunnelAdapterRecord.from_dict(payload)]
    if isinstance(payload, list):
        return [TunnelAdapterRecord.from_dict(item) for item in payload if isinstance(item, dict)]
    raise RuntimeError("Unexpected PowerShell payload while listing Xray tunnel adapters")


def _wait_for_tunnel_adapter(preexisting_indexes: set[int]) -> TunnelAdapterRecord:
    deadline = time.monotonic() + TUNNEL_DISCOVERY_TIMEOUT_SECONDS
    last_seen: list[TunnelAdapterRecord] = []
    while time.monotonic() < deadline:
        adapters = _list_xray_tunnel_adapters()
        if not adapters:
            time.sleep(TUNNEL_DISCOVERY_INTERVAL_SECONDS)
            continue
        last_seen = adapters
        new_adapters = [
            adapter for adapter in adapters if adapter.interface_index not in preexisting_indexes
        ]
        if len(new_adapters) == 1:
            return new_adapters[0]
        if not preexisting_indexes and len(adapters) == 1:
            return adapters[0]
        if len(new_adapters) > 1:
            raise RuntimeError("Multiple new Xray tunnel adapters were detected")
        time.sleep(TUNNEL_DISCOVERY_INTERVAL_SECONDS)

    if len(last_seen) == 1 and not preexisting_indexes:
        return last_seen[0]
    raise RuntimeError("Timed out while waiting for the Xray tunnel adapter")


def _get_xray_tunnel_adapter_by_index(interface_index: int) -> TunnelAdapterRecord | None:
    for adapter in _list_xray_tunnel_adapters():
        if adapter.interface_index == interface_index:
            return adapter
    return None


def _get_dns_server_state(interface_index: int) -> WindowsDnsServerState:
    payload = _run_powershell_json(
        "$state = Get-DnsClientServerAddress "
        f"-InterfaceIndex {interface_index} -AddressFamily IPv4 -ErrorAction SilentlyContinue "
        "| Select-Object -First 1 InterfaceAlias, InterfaceIndex, ServerAddresses; "
        "if ($null -eq $state) { '' } else { $state | ConvertTo-Json -Compress }"
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"Could not determine DNS client state for interface {interface_index}")
    return WindowsDnsServerState.from_dict(
        {
            "interface_index": payload.get("InterfaceIndex", 0),
            "interface_alias": payload.get("InterfaceAlias", ""),
            "server_addresses": payload.get("ServerAddresses", []),
        }
    )


def _set_dns_server_state(state: WindowsDnsServerState) -> None:
    if not _interface_exists(state.interface_index):
        raise RuntimeError(f"Could not find interface {state.interface_index} for DNS update")
    if state.server_addresses:
        script = (
            "Set-DnsClientServerAddress "
            f"-InterfaceIndex {state.interface_index} "
            f"-ServerAddresses {_format_ps_array(state.server_addresses)} "
            "-ErrorAction Stop"
        )
        _run_powershell(script)
        return

    script = (
        "Set-DnsClientServerAddress "
        f"-InterfaceIndex {state.interface_index} -ResetServerAddresses -ErrorAction Stop"
    )
    _run_powershell(script)


def _restore_dns_server_state(state: WindowsDnsServerState) -> None:
    if not _interface_exists(state.interface_index):
        return
    _set_dns_server_state(state)


def _interface_exists(interface_index: int) -> bool:
    result = _run_powershell(
        "$adapter = Get-NetAdapter -IncludeHidden -InterfaceIndex "
        f"{interface_index} -ErrorAction SilentlyContinue; "
        "if ($null -eq $adapter) { '0' } else { '1' }"
    )
    return result.stdout.strip() == "1"


def _route_exists(route: WindowsRouteRecord) -> bool:
    script = (
        "$route = Get-NetRoute -AddressFamily IPv4 "
        f"-DestinationPrefix {_quote_ps(route.destination_prefix)} "
        f"-InterfaceIndex {route.interface_index} "
        f"-NextHop {_quote_ps(route.next_hop)} "
        "-ErrorAction SilentlyContinue | Select-Object -First 1 DestinationPrefix; "
        "if ($null -eq $route) { '0' } else { '1' }"
    )
    result = _run_powershell(script)
    return result.stdout.strip() == "1"


def _add_route(route: WindowsRouteRecord) -> None:
    script = (
        "New-NetRoute -AddressFamily IPv4 "
        f"-DestinationPrefix {_quote_ps(route.destination_prefix)} "
        f"-InterfaceIndex {route.interface_index} "
        f"-NextHop {_quote_ps(route.next_hop)} "
        f"-RouteMetric {route.route_metric} "
        "-PolicyStore ActiveStore -ErrorAction Stop | Out-Null"
    )
    _run_powershell(script)


def _remove_route(route: WindowsRouteRecord) -> None:
    if not _route_exists(route):
        return
    script = (
        "Remove-NetRoute -AddressFamily IPv4 "
        f"-DestinationPrefix {_quote_ps(route.destination_prefix)} "
        f"-InterfaceIndex {route.interface_index} "
        f"-NextHop {_quote_ps(route.next_hop)} "
        "-Confirm:$false -ErrorAction SilentlyContinue"
    )
    _run_powershell(script)


def _quote_ps(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _format_ps_array(values: tuple[str, ...]) -> str:
    return "@(" + ", ".join(_quote_ps(value) for value in values) + ")"


def _format_dns_servers_for_log(values: tuple[str, ...]) -> str:
    if not values:
        return "automatic DNS"
    return ", ".join(values)


def get_selected_tunnel_backend_plan() -> TunnelBackendPlan:
    return TunnelBackendPlan(
        backend_id=SELECTED_TUNNEL_BACKEND_ID,
        display_name="Bundled Xray TUN with Wintun",
        rationale=(
            "The bundled Xray runtime in this repository now accepts the Windows TUN configuration "
            "and can create the adapter in an elevated session, so Phase 8 should build around the "
            "bundled Xray TUN backend instead of a separate tun2socks runtime."
        ),
        dns_strategy=(
            "Prefer Xray TUN-owned DNS configuration and keep app-owned restore and exclusion logic "
            "around it during tunnel mode."
        ),
        udp_supported=False,
        packaging_notes=(
            "Bundle a TUN-capable xray.exe with the Windows distribution.",
            "Bundle matching wintun.dll beside xray.exe.",
            "Do not add a separate tun2socks dependency unless later Phase 8 validation proves the bundled Xray path is insufficient.",
        ),
        admin_requirements=(
            "Administrator rights are required to create or manage the tunnel adapter.",
            "Administrator rights are required to install and remove routes.",
            "Administrator rights are required to change adapter DNS settings.",
        ),
        exclusion_notes=(
            "Keep app-owned control traffic and any required loopback endpoints outside the tunnel capture path.",
            "Install explicit host routes for CONNECT_IP and backend bootstrap or control traffic through the pre-tunnel gateway before the default tunnel route is enabled.",
            "If route or DNS exclusions cannot be installed deterministically, fail startup and roll back.",
        ),
    )


def get_tunnel_mode_unavailable_message() -> str:
    plan = get_selected_tunnel_backend_plan()
    return (
        "Tunnel whole system mode is reserved for the planned "
        f"{plan.display_name} backend and is not implemented yet."
    )


__all__ = [
    "SELECTED_TUNNEL_BACKEND_ID",
    "TunnelBackendPlan",
    "TunnelBackendPreparation",
    "TunnelBackendHealth",
    "TunnelBackend",
    "build_tunnel_backend",
    "cleanup_stale_tunnel_backend_state",
    "get_selected_tunnel_backend_plan",
    "get_tunnel_mode_unavailable_message",
]