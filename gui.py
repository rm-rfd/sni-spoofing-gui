from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from app_config import (
    XRAY_LOG_LEVELS,
    get_app_dir,
    get_config_path,
    get_config_port,
    load_config,
    normalize_xray_log_level,
    save_config,
)


class ControlPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SNI-Spoofing Control Panel")
        self.geometry("980x720")
        self.minsize(860, 620)

        self.process: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[tuple] = queue.Queue()

        self.connect_ip_var = tk.StringVar()
        self.fake_sni_var = tk.StringVar()
        self.socks_port_var = tk.StringVar()
        self.http_port_var = tk.StringVar()
        self.log_level_var = tk.StringVar(value="warning")
        self.status_var = tk.StringVar(value="Stopped")

        self._configure_style()
        self._build_layout()
        self.load_form_from_disk()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        container = ttk.Frame(self, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(3, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="SNI-Spoofing", font=("Segoe UI Semibold", 18)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text=f"Config file: {get_config_path()}",
            foreground="#4b5563",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        settings_frame = ttk.LabelFrame(container, text="Editable Settings", padding=12)
        settings_frame.grid(row=1, column=0, sticky="ew", pady=(16, 12))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)

        ttk.Label(settings_frame, text="CONNECT_IP").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(settings_frame, textvariable=self.connect_ip_var).grid(
            row=0, column=1, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="FAKE_SNI").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=6)
        ttk.Entry(settings_frame, textvariable=self.fake_sni_var).grid(
            row=0, column=3, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="XRAY_SOCKS_PORT").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(settings_frame, textvariable=self.socks_port_var).grid(
            row=1, column=1, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="XRAY_HTTP_PORT").grid(
            row=1, column=2, sticky="w", padx=(16, 8), pady=6
        )
        ttk.Entry(settings_frame, textvariable=self.http_port_var).grid(
            row=1, column=3, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="XRAY_LOG_LEVEL").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.log_level_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            textvariable=self.log_level_var,
            values=XRAY_LOG_LEVELS,
        )
        self.log_level_combo.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(settings_frame, text="XRAY_URL (vless://, trojan://, ...)").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=(10, 6))
        xray_url_frame = ttk.Frame(settings_frame)
        xray_url_frame.grid(row=3, column=1, columnspan=3, sticky="nsew", pady=(10, 6))
        xray_url_frame.columnconfigure(0, weight=1)
        xray_url_frame.rowconfigure(0, weight=1)
        self.xray_url_text = tk.Text(
            xray_url_frame,
            height=5,
            wrap="word",
            font=("Consolas", 10),
            relief="solid",
            borderwidth=1,
        )
        self.xray_url_text.grid(row=0, column=0, sticky="nsew")
        xray_url_scrollbar = ttk.Scrollbar(xray_url_frame, orient="vertical", command=self.xray_url_text.yview)
        xray_url_scrollbar.grid(row=0, column=1, sticky="ns")
        self.xray_url_text.configure(yscrollcommand=xray_url_scrollbar.set)

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        actions.columnconfigure(5, weight=1)

        self.start_button = ttk.Button(actions, text="Start Relay", command=self.start_relay)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(actions, text="Stop Relay", command=self.stop_relay)
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        self.reload_button = ttk.Button(actions, text="Reload From Disk", command=self.load_form_from_disk)
        self.reload_button.grid(row=0, column=2, padx=(0, 8))

        self.save_button = ttk.Button(actions, text="Save Config", command=self.save_form_to_disk)
        self.save_button.grid(row=0, column=3, padx=(0, 8))

        ttk.Button(actions, text="Clear Logs", command=self.clear_logs).grid(row=0, column=4)

        ttk.Label(actions, textvariable=self.status_var, foreground="#1d4ed8").grid(
            row=0, column=5, sticky="e"
        )

        logs_frame = ttk.LabelFrame(container, text="Relay Logs", padding=12)
        logs_frame.grid(row=3, column=0, sticky="nsew")
        logs_frame.columnconfigure(0, weight=1)
        logs_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(
            logs_frame,
            wrap="none",
            state="disabled",
            font=("Consolas", 10),
            background="#f8fafc",
            relief="solid",
            borderwidth=1,
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")

        log_scroll_y = ttk.Scrollbar(logs_frame, orient="vertical", command=self.log_text.yview)
        log_scroll_y.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll_y.set)

        log_scroll_x = ttk.Scrollbar(logs_frame, orient="horizontal", command=self.log_text.xview)
        log_scroll_x.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(xscrollcommand=log_scroll_x.set)

        self._sync_button_state()

    def _sync_button_state(self) -> None:
        is_running = self._is_process_running()
        if is_running:
            self.start_button.state(["disabled"])
            self.stop_button.state(["!disabled"])
        else:
            self.start_button.state(["!disabled"])
            self.stop_button.state(["disabled"])

    def _is_process_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def load_form_from_disk(self) -> None:
        try:
            config = load_config()
        except Exception as exc:
            messagebox.showerror("Failed To Load Config", str(exc), parent=self)
            return

        self.connect_ip_var.set(str(config.get("CONNECT_IP", "")))
        self.fake_sni_var.set(str(config.get("FAKE_SNI", "")))
        self.socks_port_var.set(str(config.get("XRAY_SOCKS_PORT", "")))
        self.http_port_var.set(str(config.get("XRAY_HTTP_PORT", "")))
        self.log_level_var.set(str(config.get("XRAY_LOG_LEVEL", "warning")).strip().lower())
        self.xray_url_text.delete("1.0", "end")
        xray_url = str(config.get("XRAY_URL", "")).strip()
        if not xray_url:
            xray_url = str(config.get("VLESS_URL", ""))
        self.xray_url_text.insert("1.0", xray_url)
        self._append_log(f"[loaded] {get_config_path()}")

    def _parse_port_value(self, raw_value: str, field_name: str) -> int:
        try:
            port = int(raw_value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid TCP port") from exc
        if port < 1 or port > 65535:
            raise ValueError(f"{field_name} must be between 1 and 65535")
        return port

    def _build_updated_config(self) -> dict[str, object]:
        config = load_config()

        connect_ip = self.connect_ip_var.get().strip()
        fake_sni = self.fake_sni_var.get().strip()
        xray_url = self.xray_url_text.get("1.0", "end").strip()
        socks_port = self._parse_port_value(self.socks_port_var.get(), "XRAY_SOCKS_PORT")
        http_port = self._parse_port_value(self.http_port_var.get(), "XRAY_HTTP_PORT")
        log_level = normalize_xray_log_level(self.log_level_var.get())
        listen_port = get_config_port(config, "LISTEN_PORT", 40443)

        if not connect_ip:
            raise ValueError("CONNECT_IP must not be empty")
        if not fake_sni:
            raise ValueError("FAKE_SNI must not be empty")
        if socks_port == http_port:
            raise ValueError("XRAY_SOCKS_PORT and XRAY_HTTP_PORT must be different")
        if listen_port in {socks_port, http_port}:
            raise ValueError("LISTEN_PORT must be different from XRAY_SOCKS_PORT and XRAY_HTTP_PORT")

        updated_config = dict(config)
        updated_config["CONNECT_IP"] = connect_ip
        updated_config["FAKE_SNI"] = fake_sni
        updated_config["XRAY_URL"] = xray_url
        updated_config.pop("VLESS_URL", None)
        updated_config["XRAY_SOCKS_PORT"] = socks_port
        updated_config["XRAY_HTTP_PORT"] = http_port
        updated_config["XRAY_LOG_LEVEL"] = log_level
        return updated_config

    def save_form_to_disk(self, *, show_message: bool = True) -> bool:
        try:
            updated_config = self._build_updated_config()
            save_config(updated_config)
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc), parent=self)
            return False

        self._append_log(f"[saved] {get_config_path()}")
        if show_message:
            messagebox.showinfo("Config Saved", "The selected fields were written to config.json.", parent=self)
        return True

    def _build_headless_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--headless"]
        return [sys.executable, "-u", str(Path(get_app_dir()) / "main.py"), "--headless"]

    def start_relay(self) -> None:
        if self._is_process_running():
            messagebox.showinfo("Relay Running", "Stop the current relay before starting a new one.", parent=self)
            return
        if not self.save_form_to_disk(show_message=False):
            return

        command = self._build_headless_command()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.process = subprocess.Popen(
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
        except Exception as exc:
            self.process = None
            messagebox.showerror("Failed To Start Relay", str(exc), parent=self)
            return

        self.status_var.set(f"Running (PID {self.process.pid})")
        self._sync_button_state()
        self._append_log("")
        self._append_log(f"[start] {subprocess.list2cmdline(command)}")
        self._append_log(f"[pid] {self.process.pid}")

        threading.Thread(target=self._read_process_output, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._monitor_process, args=(self.process,), daemon=True).start()

    def stop_relay(self) -> None:
        if not self._is_process_running() or self.process is None:
            return
        pid = self.process.pid
        self.status_var.set(f"Stopping (PID {pid})")
        self._sync_button_state()
        self._append_log(f"[stop] taskkill /PID {pid} /T /F")
        threading.Thread(target=self._kill_process_tree, args=(pid,), daemon=True).start()

    def _read_process_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            self.log_queue.put(("log", line.rstrip("\r\n")))
        process.stdout.close()

    def _monitor_process(self, process: subprocess.Popen[str]) -> None:
        return_code = process.wait()
        self.log_queue.put(("exit", process, return_code))

    def _run_taskkill(self, pid: int) -> subprocess.CompletedProcess[str]:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )

    def _kill_process_tree(self, pid: int) -> None:
        try:
            result = self._run_taskkill(pid)
        except FileNotFoundError:
            if self.process is not None:
                self.process.kill()
            self.log_queue.put(("log", "[stop] taskkill was not available, falling back to process.kill()"))
            return

        if result.stdout.strip():
            self.log_queue.put(("log", result.stdout.strip()))
        if result.stderr.strip():
            self.log_queue.put(("log", result.stderr.strip()))

    def _handle_process_exit(self, process: subprocess.Popen[str], return_code: int) -> None:
        if self.process is process:
            self.process = None
            self.status_var.set(f"Stopped (exit {return_code})")
            self._sync_button_state()
        self._append_log(f"[exit] relay exited with code {return_code}")

    def _drain_log_queue(self) -> None:
        while True:
            try:
                item = self.log_queue.get_nowait()
            except queue.Empty:
                break

            kind = item[0]
            if kind == "log":
                self._append_log(str(item[1]))
            elif kind == "exit":
                _, process, return_code = item
                self._handle_process_exit(process, int(return_code))

        if self.winfo_exists():
            self.after(100, self._drain_log_queue)

    def _on_close(self) -> None:
        if self._is_process_running() and self.process is not None:
            should_close = messagebox.askyesno(
                "Stop Relay",
                "The relay is still running. Stop it and close the control panel?",
                parent=self,
            )
            if not should_close:
                return
            try:
                self._run_taskkill(self.process.pid)
            except Exception:
                pass
            self.process = None
        self.destroy()


def launch_gui() -> None:
    app = ControlPanel()
    app.mainloop()