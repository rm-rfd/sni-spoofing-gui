from __future__ import annotations

import subprocess
import threading
from typing import Any
from tkinter import messagebox

from src.core.config.app_config import (
    get_active_xray_profile,
    get_app_dir,
    get_config_port,
    load_config,
    normalize_connection_mode,
    save_delay_result,
    normalize_xray_log_level,
    replace_xray_profiles,
)
from src.core.runtime.runtime_controller import sync_connection_mode_change
from src.services.delay_test import measure_delay_with_temporary_runtime
from src.services import relay_runtime

__all__ = [
    "prepare_profiles_for_delay_test",
    "build_delay_test_jobs",
    "parse_port_value",
    "handle_connection_mode_changed",
    "build_updated_config",
    "cleanup_runtime_config",
    "write_runtime_config",
    "build_headless_command",
    "start_relay",
    "test_delay",
    "run_delay_tests",
    "stop_relay",
    "read_process_output",
    "monitor_process",
    "run_taskkill",
    "kill_process_tree",
]


def prepare_profiles_for_delay_test(panel: Any, selected_profile_ids: tuple[str, ...]) -> None:
    for profile_id in selected_profile_ids:
        panel._set_profile_delay_state(
            profile_id,
            delay_text="",
            status_text="Queued",
            status_state="queued",
        )


def build_delay_test_jobs(
    panel: Any,
    selected_profile_ids: tuple[str, ...],
) -> list[tuple[str, str, dict[str, object]]]:
    connection_mode = normalize_connection_mode(panel.connection_mode_var.get())
    if connection_mode == "tunnel whole system":
        raise ValueError(
            "Delay test is not available while CONNECTION_MODE is tunnel whole system. "
            "Switch to a proxy mode before running temporary delay tests."
        )

    delay_jobs: list[tuple[str, str, dict[str, object]]] = []
    for profile_id in selected_profile_ids:
        profile = panel.xray_profiles.get(profile_id)
        if profile is None:
            continue
        runtime_config = build_updated_config(
            panel,
            active_profile_id=profile_id,
            require_active_profile=True,
        )
        delay_jobs.append((profile_id, panel._profile_label(profile), runtime_config))
    return delay_jobs


def parse_port_value(raw_value: str, field_name: str) -> int:
    try:
        port = int(raw_value.strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a valid TCP port") from exc
    if port < 1 or port > 65535:
        raise ValueError(f"{field_name} must be between 1 and 65535")
    return port


def handle_connection_mode_changed(panel: Any) -> None:
    if not panel._persist_proxy_mode_settings_to_disk(show_errors=True):
        return

    try:
        connection_mode = normalize_connection_mode(panel.connection_mode_var.get())
        local_proxy_port = parse_port_value(panel.local_proxy_port_var.get(), "LOCAL_PROXY_PORT")
        runtime_process = panel.process if panel._is_process_running() else None
        sync_connection_mode_change(
            connection_mode,
            local_proxy_port,
            runtime_is_running=runtime_process is not None,
            runtime_pid=None if runtime_process is None else runtime_process.pid,
            log_callback=panel._append_log,
        )
    except Exception as exc:
        messagebox.showerror("Failed To Apply Mode", str(exc), parent=panel)


def build_updated_config(
    panel: Any,
    *,
    active_profile_id: str | None = None,
    require_active_profile: bool = False,
) -> dict[str, object]:
    config = load_config()

    connect_ip = panel.connect_ip_var.get().strip()
    fake_sni = panel.fake_sni_var.get().strip()
    connection_mode = normalize_connection_mode(panel.connection_mode_var.get())
    local_proxy_port = parse_port_value(panel.local_proxy_port_var.get(), "LOCAL_PROXY_PORT")
    log_level = normalize_xray_log_level(panel.log_level_var.get())
    listen_port = get_config_port(config, "LISTEN_PORT", 40443)
    profiles = panel._get_profiles_in_display_order()
    resolved_active_profile_id = panel.active_profile_id if active_profile_id is None else active_profile_id

    if not connect_ip:
        raise ValueError("CONNECT_IP must not be empty")
    if not fake_sni:
        raise ValueError("FAKE_SNI must not be empty")
    if listen_port == local_proxy_port:
        raise ValueError("LISTEN_PORT must be different from LOCAL_PROXY_PORT")
    if require_active_profile:
        if not profiles:
            raise ValueError("Add at least one Xray profile before continuing.")
        if not resolved_active_profile_id or resolved_active_profile_id not in panel.xray_profiles:
            raise ValueError("Select an active Xray profile before continuing.")

    updated_config = replace_xray_profiles(
        config,
        profiles,
        active_profile_id=resolved_active_profile_id,
    )
    updated_config["CONNECT_IP"] = connect_ip
    updated_config["FAKE_SNI"] = fake_sni
    updated_config["CONNECTION_MODE"] = connection_mode
    updated_config["LOCAL_PROXY_PORT"] = local_proxy_port
    updated_config["XRAY_LOG_LEVEL"] = log_level
    return updated_config


def cleanup_runtime_config(panel: Any) -> None:
    relay_runtime.cleanup_runtime_config(panel.runtime_config_path)
    panel.runtime_config_path = None


def write_runtime_config(panel: Any, config: dict[str, object]):
    return relay_runtime.write_runtime_config(config)


def build_headless_command(panel: Any) -> list[str]:
    return relay_runtime.build_headless_command()


def start_relay(panel: Any) -> None:
    if panel._is_process_running():
        messagebox.showinfo("Relay Running", "Stop the current relay before starting a new one.", parent=panel)
        return

    try:
        runtime_config = build_updated_config(panel, require_active_profile=True)
    except Exception as exc:
        messagebox.showerror("Invalid Configuration", str(exc), parent=panel)
        return

    active_profile = get_active_xray_profile(runtime_config)
    if active_profile is None:
        messagebox.showerror(
            "Invalid Configuration",
            "Select an active Xray profile before starting the relay.",
            parent=panel,
        )
        return

    cleanup_runtime_config(panel)

    try:
        started_runtime = relay_runtime.start_relay_runtime(runtime_config)
    except Exception as exc:
        panel.process = None
        messagebox.showerror("Failed To Start Relay", str(exc), parent=panel)
        return

    panel.process = started_runtime.process
    panel.runtime_config_path = started_runtime.runtime_config_path
    if runtime_config["CONNECTION_MODE"] == "tunnel whole system":
        panel.status_var.set(f"Running Tunnel (PID {panel.process.pid})")
    else:
        panel.status_var.set(f"Running (PID {panel.process.pid})")
    panel._sync_button_state()
    panel._append_log("")
    panel._append_log(f"[start] {subprocess.list2cmdline(started_runtime.command)}")
    panel._append_log(f"[start] runtime config: {started_runtime.runtime_config_path}")
    panel._append_log(f"[start] active profile: {panel._profile_label(active_profile)}")
    panel._append_log(f"[start] connection mode: {runtime_config['CONNECTION_MODE']}")
    if runtime_config["CONNECTION_MODE"] == "tunnel whole system":
        panel._append_log("[start] tunnel mode will take ownership of routes and DNS while the relay is running")
    panel._append_log(f"[pid] {panel.process.pid}")

    threading.Thread(target=panel._read_process_output, args=(panel.process,), daemon=True).start()
    threading.Thread(target=panel._monitor_process, args=(panel.process,), daemon=True).start()


def test_delay(panel: Any) -> None:
    if panel._is_process_running():
        messagebox.showinfo(
            "Relay Running",
            "Stop the current relay before running a temporary delay test.",
            parent=panel,
        )
        return

    selected_profile_ids = panel._get_selected_profile_ids()
    if not selected_profile_ids:
        messagebox.showinfo(
            "Select Profiles",
            "Select one or more profiles to test.",
            parent=panel,
        )
        return

    try:
        delay_jobs = build_delay_test_jobs(panel, selected_profile_ids)
    except Exception as exc:
        messagebox.showerror("Invalid Configuration", str(exc), parent=panel)
        return

    if not delay_jobs:
        messagebox.showinfo(
            "Select Profiles",
            "Select one or more valid profiles to test.",
            parent=panel,
        )
        return

    panel.delay_test_in_progress = True
    prepare_profiles_for_delay_test(panel, selected_profile_ids)
    panel.status_var.set(f"Testing Delay (0/{len(delay_jobs)})...")
    panel._sync_button_state()
    panel._append_log(
        f"[delay] queued {len(delay_jobs)} selected profile(s) for proxied HTTPS GET to "
        "https://www.google.com/generate_204 through a temporary relay and Xray runtime"
    )
    threading.Thread(target=panel._run_delay_tests, args=(delay_jobs,), daemon=True).start()


def run_delay_tests(
    panel: Any,
    delay_jobs: list[tuple[str, str, dict[str, object]]],
) -> None:
    total_jobs = len(delay_jobs)
    try:
        headless_command = relay_runtime.build_headless_command()
        for index, (profile_id, profile_label, config) in enumerate(delay_jobs, start=1):
            panel.log_queue.put(("delay-started", profile_id, profile_label, index, total_jobs))
            try:
                result = measure_delay_with_temporary_runtime(
                    config,
                    headless_command,
                    log_callback=lambda message, label=profile_label: panel._queue_profile_delay_log(label, message),
                )
            except Exception as exc:
                try:
                    save_delay_result(profile_id, "", "Failed", "error")
                except Exception:
                    pass
                panel.log_queue.put(("delay-error", profile_id, profile_label, str(exc), index, total_jobs))
            else:
                delay_text = f"{result.latency_ms:.0f} ms"
                try:
                    save_delay_result(profile_id, delay_text, "OK", "success")
                except Exception:
                    pass
                panel.log_queue.put(("delay-result", profile_id, profile_label, result, index, total_jobs))
    finally:
        panel.log_queue.put(("delay-finished", total_jobs))


def stop_relay(panel: Any) -> None:
    if not panel._is_process_running() or panel.process is None:
        return
    pid = panel.process.pid
    panel.status_var.set(f"Stopping (PID {pid})")
    panel._sync_button_state()
    panel._append_log(f"[stop] taskkill /PID {pid} /T /F")
    threading.Thread(target=panel._kill_process_tree, args=(pid,), daemon=True).start()


def read_process_output(panel: Any, process: subprocess.Popen[str]) -> None:
    relay_runtime.read_process_output(process, lambda message: panel.log_queue.put(("log", message)))


def monitor_process(panel: Any, process: subprocess.Popen[str]) -> None:
    relay_runtime.monitor_process(
        process,
        lambda finished_process, return_code: panel.log_queue.put(("exit", finished_process, return_code)),
    )


def run_taskkill(panel: Any, pid: int) -> subprocess.CompletedProcess[str]:
    return relay_runtime.run_taskkill(pid)


def kill_process_tree(panel: Any, pid: int) -> None:
    relay_runtime.kill_process_tree(
        pid,
        fallback_process=panel.process,
        log_callback=lambda message: panel.log_queue.put(("log", message)),
    )
