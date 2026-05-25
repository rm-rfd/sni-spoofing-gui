from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import http.client
from pathlib import Path
import queue
import socket
import ssl
import subprocess
import tempfile
import threading
import time

from src.core.config.app_config import (
    get_active_xray_share_url,
    get_app_dir,
    get_config_port,
    get_local_proxy_port,
    get_config_string,
    save_config,
)
from src.core.xray.config import parse_xray_share_url


DELAY_TEST_TARGET_HTTP_HOST = "www.google.com"
DELAY_TEST_TARGET_HTTP_PATH = "/generate_204"
DELAY_TEST_TARGET_HOST = DELAY_TEST_TARGET_HTTP_HOST
DELAY_TEST_TARGET_PORT = 443


class DelayTestError(RuntimeError):
    pass


@dataclass(frozen=True)
class DelayTestResult:
    latency_ms: float
    relay_port: int
    proxy_port: int
    target_host: str = DELAY_TEST_TARGET_HOST
    target_port: int = DELAY_TEST_TARGET_PORT


LogCallback = Callable[[str], None]


def _emit_log(log_callback: LogCallback | None, message: str) -> None:
    if log_callback is not None:
        log_callback(message)


def _normalize_bind_host(bind_host: str) -> str:
    normalized = bind_host.strip() or "0.0.0.0"
    if normalized == "::":
        raise DelayTestError("Delay test currently supports only IPv4 LISTEN_HOST values")
    return normalized


def _allocate_free_tcp_port(bind_host: str, excluded_ports: set[int], attempts: int = 64) -> int:
    last_error: OSError | None = None
    for _ in range(attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
                probe_socket.bind((bind_host, 0))
                port = int(probe_socket.getsockname()[1])
        except OSError as exc:
            last_error = exc
            break
        if port in excluded_ports:
            continue
        excluded_ports.add(port)
        return port

    if last_error is not None:
        raise DelayTestError(
            f"Could not allocate a temporary TCP port on {bind_host}: {last_error}"
        ) from last_error
    raise DelayTestError("Could not allocate a non-conflicting temporary TCP port")


def _write_temp_config(config: dict[str, object]) -> str:
    with tempfile.NamedTemporaryFile(suffix=".json", prefix="sni-spoofing-delay-", delete=False) as temp_file:
        temp_config_path = temp_file.name
    save_config(config, temp_config_path)
    return temp_config_path


def _drain_output_queue(output_queue: queue.Queue[str]) -> list[str]:
    lines: list[str] = []
    while True:
        try:
            lines.append(output_queue.get_nowait())
        except queue.Empty:
            return lines


def _tail_output(lines: list[str], max_lines: int = 8) -> str:
    if not lines:
        return ""
    return "\n".join(lines[-max_lines:])


def _pump_process_output(
    process: subprocess.Popen[str],
    output_queue: queue.Queue[str],
    log_callback: LogCallback | None,
) -> None:
    if process.stdout is None:
        return
    for line in process.stdout:
        stripped_line = line.rstrip("\r\n")
        output_queue.put(stripped_line)
        _emit_log(log_callback, stripped_line)
    process.stdout.close()


def _wait_for_proxy_ready(
    process: subprocess.Popen[str],
    output_queue: queue.Queue[str],
    proxy_host: str,
    proxy_port: int,
    timeout_seconds: float,
) -> None:
    ready_token = f"Mixed proxy: {proxy_host}:{proxy_port}"
    observed_lines: list[str] = []
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if process.poll() is not None:
            observed_lines.extend(_drain_output_queue(output_queue))
            details = _tail_output(observed_lines)
            if details:
                raise DelayTestError(
                    f"Temporary relay exited with code {process.returncode} before the delay test was ready.\n{details}"
                )
            raise DelayTestError(
                f"Temporary relay exited with code {process.returncode} before the delay test was ready."
            )

        try:
            line = output_queue.get(timeout=0.2)
        except queue.Empty:
            continue

        observed_lines.append(line)
        if ready_token in line:
            return

    observed_lines.extend(_drain_output_queue(output_queue))
    details = _tail_output(observed_lines)
    if details:
        raise DelayTestError(
            f"Timed out while waiting for the temporary mixed proxy to start.\n{details}"
        )
    raise DelayTestError("Timed out while waiting for the temporary mixed proxy to start.")


def _measure_https_request_delay(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    request_host: str,
    request_path: str,
    timeout_seconds: float,
) -> float:
    connection = http.client.HTTPSConnection(
        proxy_host,
        proxy_port,
        timeout=timeout_seconds,
        context=ssl.create_default_context(),
    )
    connection.set_tunnel(
        target_host,
        target_port,
        headers={"Host": f"{target_host}:{target_port}"},
    )
    start_time = time.perf_counter()

    try:
        connection.request(
            "GET",
            request_path,
            headers={
                "Host": request_host,
                "Connection": "close",
                "User-Agent": "SNI-Spoofing-Delay-Test/1.0",
            },
        )
        response = connection.getresponse()
        response.read()
        return (time.perf_counter() - start_time) * 1000.0
    except Exception as exc:
        raise DelayTestError(
            f"Delay test could not fetch https://{request_host}{request_path} through the temporary mixed proxy: {exc}"
        ) from exc
    finally:
        connection.close()


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            timeout=10,
        )
    except FileNotFoundError:
        process.terminate()
    except Exception:
        process.kill()

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def measure_delay_with_temporary_runtime(
    config: dict[str, object],
    headless_command: Iterable[str],
    *,
    startup_timeout: float = 20.0,
    connect_timeout: float = 15.0,
    target_host: str = DELAY_TEST_TARGET_HOST,
    target_port: int = DELAY_TEST_TARGET_PORT,
    log_callback: LogCallback | None = None,
) -> DelayTestResult:
    share_url = get_active_xray_share_url(config)
    if not share_url:
        raise DelayTestError("An active Xray profile must be configured before running the delay test")
    parse_xray_share_url(share_url)

    listen_host = _normalize_bind_host(get_config_string(config, "LISTEN_HOST", "0.0.0.0"))
    excluded_ports = {
        get_config_port(config, "LISTEN_PORT", 40443),
        get_config_port(config, "CONNECT_PORT", 443),
        get_local_proxy_port(config),
        get_config_port(config, "XRAY_SOCKS_PORT", 10808),
        get_config_port(config, "XRAY_HTTP_PORT", 10809),
    }
    relay_port = _allocate_free_tcp_port(listen_host, excluded_ports)
    proxy_port = _allocate_free_tcp_port("127.0.0.1", excluded_ports)

    temp_config = dict(config)
    temp_config["LISTEN_PORT"] = relay_port
    temp_config["LOCAL_PROXY_PORT"] = proxy_port

    temp_config_path = _write_temp_config(temp_config)
    process: subprocess.Popen[str] | None = None

    _emit_log(log_callback, f"[delay] Launching temporary relay on {listen_host}:{relay_port}")
    _emit_log(log_callback, f"[delay] Temporary Xray mixed proxy: 127.0.0.1:{proxy_port}")

    try:
        command = [str(part) for part in headless_command]
        command.extend(["--config", temp_config_path])
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
            creationflags=creationflags,
        )
        output_queue: queue.Queue[str] = queue.Queue()
        threading.Thread(
            target=_pump_process_output,
            args=(process, output_queue, log_callback),
            daemon=True,
        ).start()

        _wait_for_proxy_ready(process, output_queue, "127.0.0.1", proxy_port, startup_timeout)
        latency_ms = _measure_https_request_delay(
            "127.0.0.1",
            proxy_port,
            target_host,
            target_port,
            DELAY_TEST_TARGET_HTTP_HOST,
            DELAY_TEST_TARGET_HTTP_PATH,
            connect_timeout,
        )
        return DelayTestResult(
            latency_ms=latency_ms,
            relay_port=relay_port,
            proxy_port=proxy_port,
            target_host=target_host,
            target_port=target_port,
        )
    finally:
        if process is not None:
            _terminate_process_tree(process)
        Path(temp_config_path).unlink(missing_ok=True)


__all__ = [
    "DelayTestError",
    "DelayTestResult",
    "measure_delay_with_temporary_runtime",
]