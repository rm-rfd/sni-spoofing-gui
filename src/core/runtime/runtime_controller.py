from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from typing import Callable

from src.core.config.app_config import get_app_dir, get_connection_mode, get_local_proxy_port
from src.core.runtime import runtime_state
from src.core.runtime.system_proxy import (
    WindowsSystemProxyState,
    build_clear_system_proxy_state,
    build_local_system_proxy_state,
    get_system_proxy_state,
    restore_system_proxy_state,
)
from src.core.runtime.tunnel_backend import (
    TunnelBackend,
    build_tunnel_backend,
    cleanup_stale_tunnel_backend_state,
)
from src.core.xray.config import XrayLocalProxySettings
from src.core.xray.process import XrayProcessManager

RUNTIME_OWNERSHIP_STATE_FILE = ".rm-sni-spoofer-runtime-state.json"
LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class RuntimeOwnershipState:
    pid: int
    connection_mode: str
    listen_host: str
    listen_port: int
    local_proxy_port: int
    config_path: str
    created_at: str
    owns_system_proxy: bool = False
    original_system_proxy_state: WindowsSystemProxyState | None = None
    tunnel_backend_state: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "pid": self.pid,
            "connection_mode": self.connection_mode,
            "listen_host": self.listen_host,
            "listen_port": self.listen_port,
            "local_proxy_port": self.local_proxy_port,
            "config_path": self.config_path,
            "created_at": self.created_at,
            "owns_system_proxy": self.owns_system_proxy,
            "original_system_proxy_state": None
            if self.original_system_proxy_state is None
            else self.original_system_proxy_state.to_dict(),
            "tunnel_backend_state": self.tunnel_backend_state,
        }


def get_runtime_ownership_state_path() -> Path:
    return Path(get_app_dir()) / RUNTIME_OWNERSHIP_STATE_FILE


def load_runtime_ownership_state(
    ownership_path: Path | None = None,
) -> RuntimeOwnershipState | None:
    resolved_path = get_runtime_ownership_state_path() if ownership_path is None else ownership_path
    if not resolved_path.is_file():
        return None

    with resolved_path.open("r", encoding="utf-8") as ownership_file:
        payload = json.load(ownership_file)

    if not isinstance(payload, dict):
        raise ValueError("runtime ownership state must contain a JSON object")

    pid = payload.get("pid")
    listen_port = payload.get("listen_port")
    local_proxy_port = payload.get("local_proxy_port")
    connection_mode = payload.get("connection_mode")
    listen_host = payload.get("listen_host")
    config_path = payload.get("config_path", "")
    created_at = payload.get("created_at", "")
    owns_system_proxy = payload.get("owns_system_proxy", False)
    original_system_proxy_payload = payload.get("original_system_proxy_state")
    tunnel_backend_state = payload.get("tunnel_backend_state")

    if not isinstance(pid, int) or pid < 1:
        raise ValueError("runtime ownership state pid must be a positive integer")
    if not isinstance(listen_port, int) or listen_port < 1:
        raise ValueError("runtime ownership state listen_port must be a positive integer")
    if not isinstance(local_proxy_port, int) or local_proxy_port < 1:
        raise ValueError("runtime ownership state local_proxy_port must be a positive integer")
    if not isinstance(connection_mode, str) or not connection_mode.strip():
        raise ValueError("runtime ownership state connection_mode must be a non-empty string")
    if not isinstance(listen_host, str) or not listen_host.strip():
        raise ValueError("runtime ownership state listen_host must be a non-empty string")
    if not isinstance(config_path, str):
        raise ValueError("runtime ownership state config_path must be a string")
    if not isinstance(created_at, str):
        raise ValueError("runtime ownership state created_at must be a string")
    if not isinstance(owns_system_proxy, bool):
        raise ValueError("runtime ownership state owns_system_proxy must be a boolean")
    if tunnel_backend_state is not None and not isinstance(tunnel_backend_state, dict):
        raise ValueError("runtime ownership state tunnel_backend_state must be an object")

    original_system_proxy_state: WindowsSystemProxyState | None = None
    if original_system_proxy_payload is not None:
        if not isinstance(original_system_proxy_payload, dict):
            raise ValueError("runtime ownership state original_system_proxy_state must be an object")
        original_system_proxy_state = WindowsSystemProxyState.from_dict(original_system_proxy_payload)

    return RuntimeOwnershipState(
        pid=pid,
        connection_mode=connection_mode.strip(),
        listen_host=listen_host.strip(),
        listen_port=listen_port,
        local_proxy_port=local_proxy_port,
        config_path=config_path.strip(),
        created_at=created_at.strip(),
        owns_system_proxy=owns_system_proxy,
        original_system_proxy_state=original_system_proxy_state,
        tunnel_backend_state=None if tunnel_backend_state is None else dict(tunnel_backend_state),
    )


def write_runtime_ownership_state(
    state: RuntimeOwnershipState,
    ownership_path: Path | None = None,
) -> Path:
    resolved_path = get_runtime_ownership_state_path() if ownership_path is None else ownership_path
    with resolved_path.open("w", encoding="utf-8", newline="\n") as ownership_file:
        json.dump(state.to_dict(), ownership_file, ensure_ascii=True, indent=2)
        ownership_file.write("\n")
    return resolved_path


def cleanup_runtime_ownership_state(ownership_path: Path | None = None) -> None:
    resolved_path = get_runtime_ownership_state_path() if ownership_path is None else ownership_path
    resolved_path.unlink(missing_ok=True)


def repair_stale_runtime_ownership_state(
    *,
    ownership_path: Path | None = None,
    log_callback: LogCallback | None = None,
) -> RuntimeOwnershipState | None:
    resolved_path = get_runtime_ownership_state_path() if ownership_path is None else ownership_path
    if not resolved_path.is_file():
        return None

    try:
        state = load_runtime_ownership_state(resolved_path)
    except Exception:
        cleanup_runtime_ownership_state(resolved_path)
        if log_callback is not None:
            log_callback("[start] removed unreadable runtime ownership state")
        return None

    if state is None:
        return None

    if _is_process_running(state.pid):
        raise RuntimeError(
            "Another relay runtime already appears to own the runtime state "
            f"(PID {state.pid}, mode={state.connection_mode}). Stop it before starting a new relay."
        )

    if state.owns_system_proxy and state.original_system_proxy_state is not None:
        restore_system_proxy_state(state.original_system_proxy_state)
        if log_callback is not None:
            log_callback("[start] restored previous system proxy from stale runtime state")

    if state.tunnel_backend_state is not None:
        cleanup_stale_tunnel_backend_state(state.tunnel_backend_state, log_callback=log_callback)

    cleanup_runtime_ownership_state(resolved_path)
    if log_callback is not None:
        log_callback(
            f"[start] repaired stale runtime ownership state from PID {state.pid} "
            f"({state.connection_mode})"
        )
    return state


@dataclass
class RelayRuntimeController:
    config_path: str | None = None
    log_callback: LogCallback | None = None

    def __post_init__(self) -> None:
        self._atexit_registered = False
        self._stopped = False
        self.ownership_state: RuntimeOwnershipState | None = None
        self.xray_manager: XrayProcessManager | None = None
        self.xray_settings: XrayLocalProxySettings | None = None
        self.tunnel_backend: TunnelBackend | None = None
        self.packet_injector: object | None = None

    @property
    def connection_mode(self) -> str:
        if self.ownership_state is None:
            return ""
        return self.ownership_state.connection_mode

    def start(self) -> XrayLocalProxySettings | None:
        repair_stale_runtime_ownership_state(log_callback=self.log_callback)
        runtime_state.load_runtime_settings(self.config_path)

        connection_mode = get_connection_mode(runtime_state.config)
        if connection_mode == "tunnel whole system":
            _ensure_tunnel_mode_prerequisites()

        self.ownership_state = RuntimeOwnershipState(
            pid=os.getpid(),
            connection_mode=connection_mode,
            listen_host=runtime_state.LISTEN_HOST,
            listen_port=runtime_state.LISTEN_PORT,
            local_proxy_port=get_local_proxy_port(runtime_state.config),
            config_path="" if not self.config_path else os.path.abspath(self.config_path),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        write_runtime_ownership_state(self.ownership_state)
        try:
            self.xray_manager, self.xray_settings = runtime_state.build_xray_manager()
            if connection_mode == "tunnel whole system":
                self._start_tunnel_backend()
            else:
                if self.xray_manager is not None:
                    self.xray_manager.start()
                self._apply_connection_mode()
        except Exception:
            self.stop()
            raise

        if not self._atexit_registered:
            atexit.register(self.stop)
            self._atexit_registered = True
        self._stopped = False
        return self.xray_settings

    def start_packet_injector(self) -> object:
        from src.core.packet_injection.tcp_injector import FakeTcpInjector

        packet_filter = (
            "tcp and "
            + "("
            + "(ip.SrcAddr == " + runtime_state.INTERFACE_IPV4 + " and ip.DstAddr == " + runtime_state.CONNECT_IP + ")"
            + " or "
            + "(ip.SrcAddr == " + runtime_state.CONNECT_IP + " and ip.DstAddr == " + runtime_state.INTERFACE_IPV4 + ")"
            + ")"
        )
        packet_injector = FakeTcpInjector(packet_filter, runtime_state.fake_injective_connections)
        threading.Thread(target=packet_injector.run, daemon=True).start()
        self.packet_injector = packet_injector
        return packet_injector

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._reload_ownership_state_from_disk()
        cleanup_marker = True
        try:
            self._restore_system_proxy_if_owned()
        except Exception as exc:
            cleanup_marker = False
            if self.log_callback is not None:
                self.log_callback(f"[stop] failed to restore previous system proxy: {exc}")
        try:
            self._restore_tunnel_backend_if_owned()
        except Exception as exc:
            cleanup_marker = False
            if self.log_callback is not None:
                self.log_callback(f"[stop] failed to restore tunnel backend routes: {exc}")
        finally:
            if self.tunnel_backend is not None:
                self.tunnel_backend.stop()
            else:
                runtime_state.stop_xray_proxy(self.xray_manager)
            self.tunnel_backend = None
            self.xray_manager = None
            self.xray_settings = None
            self.packet_injector = None
            if cleanup_marker:
                cleanup_runtime_ownership_state()

    def _start_tunnel_backend(self) -> None:
        if self.xray_manager is None or self.xray_settings is None:
            raise ValueError("Tunnel whole system mode requires an active Xray profile")

        self.tunnel_backend = build_tunnel_backend(
            self.xray_manager,
            self.xray_settings,
            log_callback=self.log_callback,
        )
        self.tunnel_backend.prepare(runtime_state.config)
        self._update_ownership_state(tunnel_backend_state=self.tunnel_backend.describe_state())
        self.tunnel_backend.start()
        self.tunnel_backend.apply_routes()
        self.tunnel_backend.apply_dns()
        health = self.tunnel_backend.check_health()
        self._update_ownership_state(tunnel_backend_state=self.tunnel_backend.describe_state())
        if not health.ok:
            raise RuntimeError(f"Tunnel backend failed health check: {health.detail}")
        if self.log_callback is not None:
            self.log_callback(
                f"[start] tunnel backend healthy on {health.adapter_name or 'xray tunnel'}"
            )

    def _reload_ownership_state_from_disk(self) -> None:
        if self.ownership_state is None:
            return
        latest_state = load_runtime_ownership_state()
        if latest_state is None:
            return
        if latest_state.pid != self.ownership_state.pid:
            return
        self.ownership_state = latest_state

    def _apply_connection_mode(self) -> None:
        if self.ownership_state is None:
            return

        connection_mode = self.ownership_state.connection_mode
        if connection_mode == "clear system proxy":
            current_proxy_state = get_system_proxy_state()
            desired_proxy_state = build_clear_system_proxy_state()
            if current_proxy_state == desired_proxy_state:
                if self.log_callback is not None:
                    self.log_callback("[start] system proxy already clear")
                return

            self._update_ownership_state(
                owns_system_proxy=True,
                original_system_proxy_state=current_proxy_state,
            )
            try:
                restore_system_proxy_state(desired_proxy_state)
            except Exception:
                self._best_effort_restore_system_proxy(current_proxy_state)
                raise

            if self.log_callback is not None:
                self.log_callback("[start] system proxy cleared")
            return

        if connection_mode == "set system proxy":
            current_proxy_state = get_system_proxy_state()
            desired_proxy_state = build_local_system_proxy_state(
                self.ownership_state.local_proxy_port,
                proxy_bypass=current_proxy_state.proxy_bypass,
            )
            if current_proxy_state == desired_proxy_state:
                if self.log_callback is not None:
                    self.log_callback(
                        f"[start] system proxy already set to 127.0.0.1:{self.ownership_state.local_proxy_port}"
                    )
                return

            self._update_ownership_state(
                owns_system_proxy=True,
                original_system_proxy_state=current_proxy_state,
            )
            try:
                restore_system_proxy_state(desired_proxy_state)
            except Exception:
                self._best_effort_restore_system_proxy(current_proxy_state)
                raise

            if self.log_callback is not None:
                self.log_callback(
                    f"[start] system proxy set to 127.0.0.1:{self.ownership_state.local_proxy_port}"
                )

    def _restore_system_proxy_if_owned(self) -> None:
        if self.ownership_state is None:
            return
        if not self.ownership_state.owns_system_proxy:
            return
        if self.ownership_state.original_system_proxy_state is None:
            return

        restore_system_proxy_state(self.ownership_state.original_system_proxy_state)
        if self.log_callback is not None:
            self.log_callback("[stop] restored previous system proxy")

    def _restore_tunnel_backend_if_owned(self) -> None:
        if self.tunnel_backend is None:
            return
        self.tunnel_backend.restore_dns()
        self.tunnel_backend.restore_routes()

    def _best_effort_restore_system_proxy(self, state: WindowsSystemProxyState) -> None:
        try:
            restore_system_proxy_state(state)
        except Exception:
            return

    def _update_ownership_state(self, **changes: object) -> None:
        if self.ownership_state is None:
            raise RuntimeError("runtime ownership state is not initialized")
        self.ownership_state = replace(self.ownership_state, **changes)
        write_runtime_ownership_state(self.ownership_state)


def sync_connection_mode_change(
    connection_mode: str,
    local_proxy_port: int,
    *,
    runtime_is_running: bool,
    runtime_pid: int | None = None,
    log_callback: LogCallback | None = None,
) -> None:
    if runtime_is_running:
        if runtime_pid is None:
            raise ValueError("runtime_pid is required while the relay is running")
        _sync_running_connection_mode_change(
            connection_mode,
            local_proxy_port,
            runtime_pid=runtime_pid,
            log_callback=log_callback,
        )
        return

    if connection_mode != "clear system proxy":
        return

    current_proxy_state = get_system_proxy_state()
    desired_proxy_state = build_clear_system_proxy_state()
    if current_proxy_state == desired_proxy_state:
        return

    restore_system_proxy_state(desired_proxy_state)
    if log_callback is not None:
        log_callback("[start] system proxy cleared")


def _sync_running_connection_mode_change(
    connection_mode: str,
    local_proxy_port: int,
    *,
    runtime_pid: int,
    log_callback: LogCallback | None = None,
) -> None:
    state = load_runtime_ownership_state()
    if state is None:
        raise RuntimeError("The active relay runtime ownership state is missing")
    if state.pid != runtime_pid:
        raise RuntimeError(
            "The active relay runtime ownership state does not match the running relay process"
        )

    if connection_mode == "clear system proxy":
        desired_proxy_state = build_clear_system_proxy_state()
        _apply_running_system_proxy_change(
            state,
            connection_mode=connection_mode,
            local_proxy_port=local_proxy_port,
            desired_proxy_state=desired_proxy_state,
            log_message="[start] system proxy cleared",
            log_callback=log_callback,
        )
        return

    if connection_mode == "set system proxy":
        current_proxy_state = get_system_proxy_state()
        desired_proxy_state = build_local_system_proxy_state(
            local_proxy_port,
            proxy_bypass=current_proxy_state.proxy_bypass,
        )
        _apply_running_system_proxy_change(
            state,
            connection_mode=connection_mode,
            local_proxy_port=local_proxy_port,
            desired_proxy_state=desired_proxy_state,
            log_message=f"[start] system proxy set to 127.0.0.1:{local_proxy_port}",
            log_callback=log_callback,
        )
        return

    _release_running_system_proxy_ownership(
        state,
        connection_mode=connection_mode,
        local_proxy_port=local_proxy_port,
        log_callback=log_callback,
    )


def _apply_running_system_proxy_change(
    state: RuntimeOwnershipState,
    *,
    connection_mode: str,
    local_proxy_port: int,
    desired_proxy_state: WindowsSystemProxyState,
    log_message: str,
    log_callback: LogCallback | None = None,
) -> None:
    current_proxy_state = get_system_proxy_state()
    original_proxy_state = current_proxy_state
    if state.owns_system_proxy and state.original_system_proxy_state is not None:
        original_proxy_state = state.original_system_proxy_state

    updated_state = replace(
        state,
        connection_mode=connection_mode,
        local_proxy_port=local_proxy_port,
        owns_system_proxy=True,
        original_system_proxy_state=original_proxy_state,
    )

    write_runtime_ownership_state(updated_state)
    try:
        if current_proxy_state != desired_proxy_state:
            restore_system_proxy_state(desired_proxy_state)
    except Exception:
        try:
            write_runtime_ownership_state(state)
        except Exception:
            pass
        raise

    if log_callback is not None and current_proxy_state != desired_proxy_state:
        log_callback(log_message)


def _release_running_system_proxy_ownership(
    state: RuntimeOwnershipState,
    *,
    connection_mode: str,
    local_proxy_port: int,
    log_callback: LogCallback | None = None,
) -> None:
    if state.owns_system_proxy and state.original_system_proxy_state is not None:
        restore_system_proxy_state(state.original_system_proxy_state)
        if log_callback is not None:
            log_callback("[stop] restored previous system proxy")

    updated_state = replace(
        state,
        connection_mode=connection_mode,
        local_proxy_port=local_proxy_port,
        owns_system_proxy=False,
        original_system_proxy_state=None,
    )
    write_runtime_ownership_state(updated_state)


def _is_process_running(pid: int) -> bool:
    if pid < 1:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _is_process_running_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _ensure_tunnel_mode_prerequisites() -> None:
    if _is_running_as_administrator():
        return
    raise ValueError(
        "Tunnel whole system mode requires Administrator rights. "
        "Restart the app as Administrator."
    )


def _is_running_as_administrator() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _is_process_running_windows(pid: int) -> bool:
    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    still_active = 259

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize,
        False,
        pid,
    )
    if not handle:
        return False

    try:
        exit_code = wintypes.DWORD()
        if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) == 0:
            return True
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)


__all__ = [
    "RuntimeOwnershipState",
    "RelayRuntimeController",
    "get_runtime_ownership_state_path",
    "load_runtime_ownership_state",
    "write_runtime_ownership_state",
    "cleanup_runtime_ownership_state",
    "repair_stale_runtime_ownership_state",
    "sync_connection_mode_change",
]