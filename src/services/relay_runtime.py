from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from src.core.config.app_config import get_app_dir, save_config
from src.core.runtime.runtime_controller import request_running_xray_reload

LogCallback = Callable[[str], None]
ExitCallback = Callable[[subprocess.Popen[str], int], None]


@dataclass(frozen=True)
class StartedRelayRuntime:
    process: subprocess.Popen[str]
    runtime_config_path: Path
    command: list[str]


def cleanup_runtime_config(runtime_config_path: Path | None) -> None:
    if runtime_config_path is None:
        return
    runtime_config_path.unlink(missing_ok=True)


def write_runtime_config(config: dict[str, object]) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".json", prefix="rm-sni-spoofer-", delete=False) as temp_file:
        runtime_config_path = Path(temp_file.name)
    save_config(config, str(runtime_config_path))
    return runtime_config_path


def update_running_runtime_config(
    runtime_config_path: Path,
    config: dict[str, object],
    *,
    runtime_pid: int,
    timeout: float = 10.0,
) -> dict[str, object]:
    save_config(config, str(runtime_config_path))
    return request_running_xray_reload(runtime_pid, timeout=timeout)


def build_headless_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--headless"]
    return [sys.executable, "-u", "-m", "src", "--headless"]


def start_relay_runtime(config: dict[str, object]) -> StartedRelayRuntime:
    runtime_config_path = write_runtime_config(config)
    command = build_headless_command()
    command.extend(["--config", str(runtime_config_path)])
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.Popen(
            command,
            cwd=get_app_dir(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=creationflags,
        )
    except Exception:
        cleanup_runtime_config(runtime_config_path)
        raise

    return StartedRelayRuntime(
        process=process,
        runtime_config_path=runtime_config_path,
        command=command,
    )


def read_process_output(process: subprocess.Popen[str], log_callback: LogCallback) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        log_callback(line.rstrip("\r\n"))
    process.stdout.close()


def monitor_process(process: subprocess.Popen[str], exit_callback: ExitCallback) -> None:
    exit_callback(process, process.wait())


def run_taskkill(pid: int) -> subprocess.CompletedProcess[str]:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )


def kill_process_tree(
    pid: int,
    *,
    fallback_process: subprocess.Popen[str] | None = None,
    log_callback: LogCallback | None = None,
) -> None:
    try:
        result = run_taskkill(pid)
    except FileNotFoundError:
        if fallback_process is not None:
            fallback_process.kill()
        if log_callback is not None:
            log_callback("[stop] taskkill was not available, falling back to process.kill()")
        return

    if log_callback is None:
        return
    if result.stdout.strip():
        log_callback(result.stdout.strip())
    if result.stderr.strip():
        log_callback(result.stderr.strip())