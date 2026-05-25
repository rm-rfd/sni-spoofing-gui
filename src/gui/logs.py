from __future__ import annotations

import queue
import re
from typing import Any

from .theme import status_prefix_tag

__all__ = [
    "queue_profile_delay_log",
    "refresh_log_scrollbars",
    "append_log",
    "clear_logs",
    "handle_process_exit",
    "queue_worker_log",
    "handle_delay_started",
    "handle_delay_result",
    "handle_delay_error",
    "handle_delay_finished",
    "drain_log_queue",
]


def queue_profile_delay_log(panel: Any, profile_label: str, message: str) -> None:
    normalized_message = message.strip()
    if normalized_message.startswith("[delay]"):
        normalized_message = normalized_message[len("[delay]"):].strip()
    if normalized_message:
        panel.log_queue.put(("log", f"[delay][{profile_label}] {normalized_message}"))
    else:
        panel.log_queue.put(("log", f"[delay][{profile_label}]"))


def refresh_log_scrollbars(panel: Any) -> None:
    log_text = getattr(panel, "log_text", None)
    if log_text is None:
        return

    try:
        panel._update_scrollbar_visibility(panel._log_scroll_y, *log_text.yview())
        panel._update_scrollbar_visibility(panel._log_scroll_x, *log_text.xview())
    except Exception:
        return


def append_log(panel: Any, message: str, tag: str | None = None) -> None:
    panel.log_text.configure(state="normal")
    if tag is not None:
        panel.log_text.insert("end", f"{message}\n", tag)
    elif not message:
        panel.log_text.insert("end", "\n")
    else:
        prefix_tag = status_prefix_tag(message)
        if prefix_tag is None:
            panel.log_text.insert("end", f"{message}\n")
        else:
            match = re.match(r"^(\[[^\]]+\])(.*)$", message)
            if match is None:
                panel.log_text.insert("end", f"{message}\n")
            else:
                panel.log_text.insert("end", match.group(1), prefix_tag)
                panel.log_text.insert("end", f"{match.group(2)}\n")
    panel.log_text.see("end")
    panel.log_text.configure(state="disabled")
    panel.after_idle(panel._refresh_log_scrollbars)


def clear_logs(panel: Any) -> None:
    panel.log_text.configure(state="normal")
    panel.log_text.delete("1.0", "end")
    panel.log_text.configure(state="disabled")
    panel.after_idle(panel._refresh_log_scrollbars)


def handle_process_exit(panel: Any, process: Any, return_code: int) -> None:
    if panel.process is process:
        panel.process = None
        panel._cleanup_runtime_config()
        panel.status_var.set(f"Stopped (exit {return_code})")
        panel._sync_button_state()
    append_log(panel, f"[exit] relay exited with code {return_code}")


def queue_worker_log(panel: Any, message: str) -> None:
    panel.log_queue.put(("log", message))


def handle_delay_started(
    panel: Any,
    profile_id: str,
    profile_label: str,
    index: int,
    total: int,
) -> None:
    panel._set_profile_delay_state(
        profile_id,
        delay_text="",
        status_text="Testing",
        status_state="testing",
    )
    panel.status_var.set(f"Testing Delay ({index}/{total}): {profile_label}")


def handle_delay_result(
    panel: Any,
    profile_id: str,
    profile_label: str,
    result: Any,
    index: int,
    total: int,
) -> None:
    delay_text = f"{result.latency_ms:.0f} ms"
    panel._set_profile_delay_state(
        profile_id,
        delay_text=delay_text,
        status_text="OK",
        status_state="success",
    )
    append_log(
        panel,
        f"[delay] {profile_label}: {result.target_host}:{result.target_port} reachable in {result.latency_ms:.0f} ms "
        f"via relay={result.relay_port}, mixed={result.proxy_port}",
        "delay_success",
    )
    if index == total:
        panel.status_var.set(f"Delay: {delay_text}")


def handle_delay_error(
    panel: Any,
    profile_id: str,
    profile_label: str,
    message: str,
) -> None:
    panel._set_profile_delay_state(
        profile_id,
        delay_text="",
        status_text="Failed",
        status_state="error",
    )
    append_log(panel, f"[delay] {profile_label}: failed: {message}", "delay_error")


def handle_delay_finished(panel: Any, total_jobs: int) -> None:
    panel.delay_test_in_progress = False
    if panel._is_process_running() and panel.process is not None:
        panel.status_var.set(f"Running (PID {panel.process.pid})")
    elif total_jobs > 0:
        panel.status_var.set(f"Delay Tests Complete ({total_jobs})")
    else:
        panel.status_var.set("Stopped")
    panel._sync_button_state()


def drain_log_queue(panel: Any) -> None:
    while True:
        try:
            item = panel.log_queue.get_nowait()
        except queue.Empty:
            break

        kind = item[0]
        if kind == "log":
            append_log(panel, str(item[1]))
        elif kind == "exit":
            _, process, return_code = item
            handle_process_exit(panel, process, int(return_code))
        elif kind == "delay-started":
            _, profile_id, profile_label, index, total = item
            handle_delay_started(panel, str(profile_id), str(profile_label), int(index), int(total))
        elif kind == "delay-result":
            _, profile_id, profile_label, result, index, total = item
            handle_delay_result(
                panel,
                str(profile_id),
                str(profile_label),
                result,
                int(index),
                int(total),
            )
        elif kind == "delay-error":
            _, profile_id, profile_label, message, _index, _total = item
            handle_delay_error(panel, str(profile_id), str(profile_label), str(message))
        elif kind == "delay-finished":
            _, total_jobs = item
            handle_delay_finished(panel, int(total_jobs))

    if panel.winfo_exists():
        panel.after(100, panel._drain_log_queue)
