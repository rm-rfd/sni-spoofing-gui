from __future__ import annotations

import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from app_config import (
    XRAY_LOG_LEVELS,
    build_xray_profile_record,
    get_app_dir,
    get_active_xray_profile,
    get_config_port,
    get_xray_profiles,
    load_config,
    normalize_xray_log_level,
    replace_xray_profiles,
    save_config,
)
from utils.delay_test import DelayTestResult, measure_delay_with_temporary_runtime


DONATION_NETWORK_LABEL = "USDT (BEP20):"
DONATION_ADDRESS = "0x6411d42175578CFafadfB6b536A4C97F0f6883Aa"
APP_ICON_ICO_PATH = Path(get_app_dir()) / "logo.ico"
APP_ICON_PNG_PATH = Path(get_app_dir()) / "logo.png"


def _rtl_line(text: str) -> str:
    if not text:
        return ""
    return f"\u202B{text}\u202C"


HOW_TO_RUN_TEXT = """
1. برنامه را با دسترسی Administrator باز کنید.
2. کانفیگ های Xray خود را از طریق دکمه Add در رابط کاربری اضافه کنید.
3. کانفیگ ها را از داخل رابط کاربری تست کنید. اگر یک کانفیگ ناموفق شد، ممکن است لازم باشد چند بار دیگر آن را تست کنید، چون گاهی false negative رخ می دهد و ممکن است کانفیگ در عمل سالم باشد.
4. کانفیگی را که کار می کند انتخاب کنید و روی Set Active بزنید.
5. برای اجرای relay با کانفیگ فعال، روی Start Relay بزنید.

نکته ها:
- هنگام شروع relay، فقط پروفایل فعال استفاده می شود.
- تست Delay معیار مفیدی است، اما همیشه دقیق نیست.
"""


class ShareUrlDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        initial_url: str = "",
        profile_id: str | None = None,
    ) -> None:
        self.initial_url = initial_url
        self.profile_id = profile_id
        self.result: dict[str, object] | None = None
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        container = ttk.Frame(master, padding=8)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(
            container,
            text="Paste a direct vless:// or trojan:// share link.",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.url_text = tk.Text(
            container,
            width=92,
            height=6,
            wrap="word",
            font=("Consolas", 10),
            relief="solid",
            borderwidth=1,
        )
        self.url_text.grid(row=1, column=0, sticky="nsew")
        self.url_text.insert("1.0", self.initial_url)

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self.url_text.yview)
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.url_text.configure(yscrollcommand=scrollbar.set)
        return self.url_text

    def validate(self) -> bool:
        share_url = self.url_text.get("1.0", "end").strip()
        try:
            self.result = build_xray_profile_record(
                share_url,
                profile_id=self.profile_id,
            )
        except Exception as exc:
            messagebox.showerror("Invalid Share URL", str(exc), parent=self)
            return False
        return True


class HowToRunDialog(simpledialog.Dialog):
    def body(self, master: tk.Misc) -> tk.Widget:
        container = ttk.Frame(master, padding=8)
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="راهنمای اجرای برنامه",
            font=("Segoe UI Semibold", 11),
            anchor="e",
            justify="right",
        ).grid(row=0, column=0, sticky="e", pady=(0, 8))

        instructions_frame = ttk.Frame(container, padding=12, relief="solid", borderwidth=1)
        instructions_frame.grid(row=1, column=0, sticky="ew")
        instructions_frame.columnconfigure(0, weight=1)

        ttk.Label(
            instructions_frame,
            text="\n".join(_rtl_line(line) for line in HOW_TO_RUN_TEXT.splitlines()),
            font=("Segoe UI", 10),
            justify="right",
            anchor="e",
            wraplength=620,
        ).grid(row=0, column=0, sticky="e")
        return None

    def buttonbox(self) -> None:
        box = ttk.Frame(self)
        box.pack(anchor="e", padx=8, pady=(0, 8))

        close_button = ttk.Button(box, text="Close", command=self.cancel)
        close_button.pack()
        close_button.focus_set()
        self.bind("<Return>", self.cancel)
        self.bind("<Escape>", self.cancel)


class ControlPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("SNI-Spoofing Control Panel")
        self.geometry("980x720")
        self.minsize(860, 620)
        self._window_icon: tk.PhotoImage | None = None

        self.process: subprocess.Popen[str] | None = None
        self.delay_test_in_progress = False
        self.log_queue: queue.Queue[tuple] = queue.Queue()
        self.runtime_config_path: Path | None = None
        self.xray_profiles: dict[str, dict[str, object]] = {}
        self.active_profile_id = ""
        self.profile_delay_values: dict[str, str] = {}
        self.profile_delay_statuses: dict[str, str] = {}
        self.profile_delay_states: dict[str, str] = {}

        self.connect_ip_var = tk.StringVar()
        self.fake_sni_var = tk.StringVar()
        self.socks_port_var = tk.StringVar()
        self.http_port_var = tk.StringVar()
        self.log_level_var = tk.StringVar(value="warning")
        self.profile_status_var = tk.StringVar(value="No active Xray profile selected.")
        self.status_var = tk.StringVar(value="Stopped")
        self.donation_address_var = tk.StringVar(value=DONATION_ADDRESS)
        self._context_menu_target: tk.Misc | None = None

        self._configure_style()
        self._configure_icon()
        self._build_layout()
        self._install_context_menus()
        self.load_form_from_disk()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log_queue)

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")

    def _configure_icon(self) -> None:
        try:
            if APP_ICON_ICO_PATH.is_file():
                self.iconbitmap(default=str(APP_ICON_ICO_PATH))
                return
        except tk.TclError:
            pass

        if not APP_ICON_PNG_PATH.is_file():
            return
        try:
            self._window_icon = tk.PhotoImage(file=str(APP_ICON_PNG_PATH))
        except tk.TclError:
            return
        self.iconphoto(True, self._window_icon)

    def _show_how_to_run_dialog(self) -> None:
        HowToRunDialog(self, "راهنمای اجرا")

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
        ttk.Label(header, text="RM SNI Spoofer", font=("Segoe UI Semibold", 18)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(header, text="نحوه اجرا", command=self._show_how_to_run_dialog).grid(
            row=0, column=1, sticky="e"
        )
        ttk.Label(
            header,
            text="اگر از این برنامه خوشتان آمد، می‌توانید با حمایت مالی از آن پشتیبانی کنید:",
            foreground="#4b5563",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        donation_frame = ttk.Frame(header)
        donation_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        donation_frame.columnconfigure(1, weight=1)

        ttk.Label(donation_frame, text=DONATION_NETWORK_LABEL).grid(row=0, column=0, sticky="w", padx=(0, 8))
        donation_entry = ttk.Entry(
            donation_frame,
            textvariable=self.donation_address_var,
            state="readonly",
            font=("Consolas", 10),
        )
        donation_entry.grid(row=0, column=1, sticky="ew")

        settings_frame = ttk.LabelFrame(container, text="Editable Settings", padding=12)
        settings_frame.grid(row=1, column=0, sticky="ew", pady=(16, 12))
        settings_frame.columnconfigure(1, weight=1)
        settings_frame.columnconfigure(3, weight=1)
        settings_frame.rowconfigure(3, weight=1)

        ttk.Label(settings_frame, text="CONNECT IP").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=6)
        ttk.Entry(settings_frame, textvariable=self.connect_ip_var).grid(
            row=0, column=1, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="FAKE SNI").grid(row=0, column=2, sticky="w", padx=(16, 8), pady=6)
        ttk.Entry(settings_frame, textvariable=self.fake_sni_var).grid(
            row=0, column=3, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="SOCKS PORT").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=6
        )
        ttk.Entry(settings_frame, textvariable=self.socks_port_var).grid(
            row=1, column=1, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="HTTP PORT").grid(
            row=1, column=2, sticky="w", padx=(16, 8), pady=6
        )
        ttk.Entry(settings_frame, textvariable=self.http_port_var).grid(
            row=1, column=3, sticky="ew", pady=6
        )

        ttk.Label(settings_frame, text="LOG LEVEL").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=6
        )
        self.log_level_combo = ttk.Combobox(
            settings_frame,
            state="readonly",
            textvariable=self.log_level_var,
            values=XRAY_LOG_LEVELS,
        )
        self.log_level_combo.grid(row=2, column=1, sticky="ew", pady=6)

        ttk.Label(settings_frame, text="XRAY Profiles").grid(row=3, column=0, sticky="nw", padx=(0, 8), pady=(10, 6))
        profiles_frame = ttk.Frame(settings_frame)
        profiles_frame.grid(row=3, column=1, columnspan=3, sticky="nsew", pady=(10, 6))
        profiles_frame.columnconfigure(0, weight=1)
        profiles_frame.rowconfigure(1, weight=1)

        profile_actions = ttk.Frame(profiles_frame)
        profile_actions.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.profile_add_button = ttk.Button(profile_actions, text="Add", command=self._add_profile)
        self.profile_add_button.grid(row=0, column=0, padx=(0, 8))

        self.profile_edit_button = ttk.Button(profile_actions, text="Edit", command=self._edit_selected_profile)
        self.profile_edit_button.grid(row=0, column=1, padx=(0, 8))

        self.profile_remove_button = ttk.Button(profile_actions, text="Remove", command=self._remove_selected_profiles)
        self.profile_remove_button.grid(row=0, column=2, padx=(0, 8))

        self.profile_set_active_button = ttk.Button(
            profile_actions,
            text="Set Active",
            command=self._set_selected_profile_active,
        )
        self.profile_set_active_button.grid(row=0, column=3)

        profile_table_frame = ttk.Frame(profiles_frame)
        profile_table_frame.grid(row=1, column=0, sticky="nsew")
        profile_table_frame.columnconfigure(0, weight=1)
        profile_table_frame.rowconfigure(0, weight=1)

        profile_columns = (
            "active",
            "remark",
            "protocol",
            "address",
            "port",
            "transport",
            "security",
            "delay",
            "status",
        )
        self.profile_tree = ttk.Treeview(
            profile_table_frame,
            columns=profile_columns,
            show="headings",
            selectmode="extended",
            height=7,
        )
        self.profile_tree.heading("active", text="Active")
        self.profile_tree.heading("remark", text="Remark")
        self.profile_tree.heading("protocol", text="Type")
        self.profile_tree.heading("address", text="Address")
        self.profile_tree.heading("port", text="Port")
        self.profile_tree.heading("transport", text="Transport")
        self.profile_tree.heading("security", text="Security")
        self.profile_tree.heading("delay", text="Delay")
        self.profile_tree.heading("status", text="Status")
        self.profile_tree.column("active", width=70, anchor="center", stretch=False)
        self.profile_tree.column("remark", width=180, stretch=True)
        self.profile_tree.column("protocol", width=80, anchor="center", stretch=False)
        self.profile_tree.column("address", width=200, stretch=True)
        self.profile_tree.column("port", width=70, anchor="center", stretch=False)
        self.profile_tree.column("transport", width=90, anchor="center", stretch=False)
        self.profile_tree.column("security", width=90, anchor="center", stretch=False)
        self.profile_tree.column("delay", width=90, anchor="center", stretch=False)
        self.profile_tree.column("status", width=110, anchor="center", stretch=False)
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        self.profile_tree.tag_configure("active_profile", background="#e0f2fe")
        self.profile_tree.tag_configure("queued_profile", foreground="#6b7280")
        self.profile_tree.tag_configure("testing_profile", foreground="#b45309")
        self.profile_tree.tag_configure("success_profile", foreground="#15803d")
        self.profile_tree.tag_configure("error_profile", foreground="#b91c1c")
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_profile_selection_changed, add="+")
        self.profile_tree.bind("<Double-1>", self._on_profile_double_click, add="+")

        profile_scroll_y = ttk.Scrollbar(
            profile_table_frame,
            orient="vertical",
            command=self.profile_tree.yview,
        )
        profile_scroll_y.grid(row=0, column=1, sticky="ns")
        self.profile_tree.configure(yscrollcommand=profile_scroll_y.set)

        profile_scroll_x = ttk.Scrollbar(
            profile_table_frame,
            orient="horizontal",
            command=self.profile_tree.xview,
        )
        profile_scroll_x.grid(row=1, column=0, sticky="ew")
        self.profile_tree.configure(xscrollcommand=profile_scroll_x.set)

        ttk.Label(
            profiles_frame,
            textvariable=self.profile_status_var,
            foreground="#4b5563",
        ).grid(row=2, column=0, sticky="w", pady=(6, 0))

        actions = ttk.Frame(container)
        actions.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        actions.columnconfigure(4, weight=1)

        self.start_button = ttk.Button(actions, text="Start Relay", command=self.start_relay)
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = ttk.Button(actions, text="Stop Relay", command=self.stop_relay)
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        self.test_delay_button = ttk.Button(actions, text="Test Delay", command=self.test_delay)
        self.test_delay_button.grid(row=0, column=2, padx=(0, 8))

        ttk.Button(actions, text="Clear Logs", command=self.clear_logs).grid(row=0, column=3)

        ttk.Label(actions, textvariable=self.status_var, foreground="#1d4ed8").grid(
            row=0, column=4, sticky="e"
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
        self.log_text.tag_configure("delay_error", foreground="#b91c1c")
        self.log_text.tag_configure("delay_success", foreground="#15803d")

        log_scroll_y = ttk.Scrollbar(logs_frame, orient="vertical", command=self.log_text.yview)
        log_scroll_y.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll_y.set)

        log_scroll_x = ttk.Scrollbar(logs_frame, orient="horizontal", command=self.log_text.xview)
        log_scroll_x.grid(row=1, column=0, sticky="ew")
        self.log_text.configure(xscrollcommand=log_scroll_x.set)

        self._sync_button_state()

    def _install_context_menus(self) -> None:
        self._editable_context_menu = tk.Menu(self, tearoff=False)
        self._editable_context_menu.add_command(label="Cut", command=self._context_cut)
        self._editable_context_menu.add_command(label="Copy", command=self._context_copy)
        self._editable_context_menu.add_command(label="Paste", command=self._context_paste)
        self._editable_context_menu.add_command(label="Delete", command=self._context_delete)
        self._editable_context_menu.add_separator()
        self._editable_context_menu.add_command(label="Select All", command=self._context_select_all)

        self._readonly_context_menu = tk.Menu(self, tearoff=False)
        self._readonly_context_menu.add_command(label="Copy", command=self._context_copy)
        self._readonly_context_menu.add_separator()
        self._readonly_context_menu.add_command(label="Select All", command=self._context_select_all)

        self._profile_context_menu = tk.Menu(self, tearoff=False)
        self._profile_context_menu.add_command(label="Copy", command=self._copy_selected_profiles)
        self._profile_context_menu.add_command(label="Remove", command=self._remove_selected_profiles)
        self._profile_context_menu.add_command(label="Edit", command=self._edit_selected_profile)
        self._profile_context_menu.add_command(label="Set As Active", command=self._set_selected_profile_active)
        self._profile_context_menu.add_command(label="Test Delay", command=self.test_delay)

        self._bind_context_menu_classes()
        self.profile_tree.bind("<Button-3>", self._show_profile_context_menu, add="+")

    def _bind_context_menu_classes(self) -> None:
        for widget_class in ("Entry", "TEntry", "TCombobox", "Text"):
            self.bind_class(widget_class, "<Button-3>", self._show_context_menu, add="+")

    def _show_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        widget = event.widget
        if not isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
            return ""

        self._context_menu_target = widget
        widget.focus_set()
        self._set_insert_cursor_from_event(widget, event)

        has_selection = bool(self._get_selected_text(widget))
        has_content = bool(self._get_widget_text(widget))
        editable = self._widget_is_editable(widget)
        menu = self._editable_context_menu if editable else self._readonly_context_menu

        if editable:
            self._editable_context_menu.entryconfigure(0, state="normal" if has_selection else "disabled")
            self._editable_context_menu.entryconfigure(1, state="normal" if has_content else "disabled")
            self._editable_context_menu.entryconfigure(2, state="normal")
            self._editable_context_menu.entryconfigure(3, state="normal" if has_selection else "disabled")
            self._editable_context_menu.entryconfigure(5, state="normal" if has_content else "disabled")
        else:
            self._readonly_context_menu.entryconfigure(0, state="normal" if has_content else "disabled")
            self._readonly_context_menu.entryconfigure(2, state="normal" if has_content else "disabled")

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _set_insert_cursor_from_event(self, widget: tk.Misc, event: tk.Event[tk.Misc]) -> None:
        if isinstance(widget, tk.Text):
            if not self._get_selected_text(widget):
                widget.mark_set("insert", f"@{event.x},{event.y}")
            return

        if not self._get_selected_text(widget):
            widget.icursor(widget.index(f"@{event.x}"))

    def _widget_is_editable(self, widget: tk.Misc) -> bool:
        state = str(widget.cget("state"))
        return state not in {"disabled", "readonly"}

    def _get_widget_text(self, widget: tk.Misc) -> str:
        if isinstance(widget, tk.Text):
            return widget.get("1.0", "end-1c")
        return str(widget.get())

    def _get_selected_text(self, widget: tk.Misc) -> str:
        if isinstance(widget, tk.Text):
            if not widget.tag_ranges(tk.SEL):
                return ""
            return widget.get("sel.first", "sel.last")

        if not widget.selection_present():
            return ""
        return str(widget.selection_get())

    def _context_copy(self) -> None:
        widget = self._context_menu_target
        if widget is None:
            return

        text = self._get_selected_text(widget) or self._get_widget_text(widget)
        if not text:
            return

        self.clipboard_clear()
        self.clipboard_append(text)

    def _context_cut(self) -> None:
        widget = self._context_menu_target
        if widget is None or not self._widget_is_editable(widget):
            return

        text = self._get_selected_text(widget)
        if not text:
            return

        self.clipboard_clear()
        self.clipboard_append(text)
        self._delete_selection(widget)

    def _context_paste(self) -> None:
        widget = self._context_menu_target
        if widget is None or not self._widget_is_editable(widget):
            return

        try:
            text = self.clipboard_get()
        except tk.TclError:
            return

        self._delete_selection(widget)
        if isinstance(widget, tk.Text):
            widget.insert("insert", text)
        else:
            widget.insert("insert", text)

    def _context_delete(self) -> None:
        widget = self._context_menu_target
        if widget is None or not self._widget_is_editable(widget):
            return

        self._delete_selection(widget)

    def _delete_selection(self, widget: tk.Misc) -> None:
        if isinstance(widget, tk.Text):
            if widget.tag_ranges(tk.SEL):
                widget.delete("sel.first", "sel.last")
            return

        if widget.selection_present():
            widget.delete("sel.first", "sel.last")

    def _context_select_all(self) -> None:
        widget = self._context_menu_target
        if widget is None:
            return

        if isinstance(widget, tk.Text):
            widget.tag_add(tk.SEL, "1.0", "end-1c")
            widget.mark_set("insert", "end-1c")
            widget.see("insert")
            return

        widget.select_range(0, "end")
        widget.icursor("end")

    def _copy_selected_profiles(self) -> None:
        profile_urls: list[str] = []
        for profile_id in self._get_selected_profile_ids():
            profile = self.xray_profiles.get(profile_id)
            if profile is None:
                continue

            share_url = str(profile.get("url", "")).strip()
            if share_url:
                profile_urls.append(share_url)

        if not profile_urls:
            return

        self.clipboard_clear()
        self.clipboard_append("\n".join(profile_urls))

    def _profile_row_values(self, profile: dict[str, object]) -> tuple[str, ...]:
        profile_id = str(profile["id"])
        return (
            "Yes" if profile_id == self.active_profile_id else "",
            str(profile.get("tag", "")) or "(untitled)",
            str(profile.get("protocol", "")).upper(),
            str(profile.get("address", "")),
            str(profile.get("port", "")),
            str(profile.get("transport", "")),
            str(profile.get("security", "")),
            self.profile_delay_values.get(profile_id, ""),
            self.profile_delay_statuses.get(profile_id, ""),
        )

    def _profile_row_tags(self, profile_id: str) -> tuple[str, ...]:
        tags: list[str] = []
        if profile_id == self.active_profile_id:
            tags.append("active_profile")

        status_state = self.profile_delay_states.get(profile_id, "")
        if status_state:
            tags.append(f"{status_state}_profile")
        return tuple(tags)

    def _refresh_profile_row(self, profile_id: str) -> None:
        profile = self.xray_profiles.get(profile_id)
        if profile is None or not self.profile_tree.exists(profile_id):
            return

        self.profile_tree.item(
            profile_id,
            values=self._profile_row_values(profile),
            tags=self._profile_row_tags(profile_id),
        )

    def _set_profile_delay_state(
        self,
        profile_id: str,
        *,
        delay_text: str = "",
        status_text: str = "",
        status_state: str = "",
    ) -> None:
        if delay_text:
            self.profile_delay_values[profile_id] = delay_text
        else:
            self.profile_delay_values.pop(profile_id, None)

        if status_text:
            self.profile_delay_statuses[profile_id] = status_text
        else:
            self.profile_delay_statuses.pop(profile_id, None)

        if status_state:
            self.profile_delay_states[profile_id] = status_state
        else:
            self.profile_delay_states.pop(profile_id, None)

        self._refresh_profile_row(profile_id)

    def _prune_profile_delay_state(self) -> None:
        valid_profile_ids = set(self.xray_profiles)
        for mapping in (
            self.profile_delay_values,
            self.profile_delay_statuses,
            self.profile_delay_states,
        ):
            stale_profile_ids = [profile_id for profile_id in mapping if profile_id not in valid_profile_ids]
            for profile_id in stale_profile_ids:
                mapping.pop(profile_id, None)

    def _get_profiles_in_display_order(self) -> list[dict[str, object]]:
        profiles: list[dict[str, object]] = []
        for profile_id in self.profile_tree.get_children(""):
            profile = self.xray_profiles.get(str(profile_id))
            if profile is not None:
                profiles.append(dict(profile))
        return profiles

    def _profile_label(self, profile: dict[str, object]) -> str:
        tag = str(profile.get("tag", "")).strip()
        if tag:
            return tag
        protocol = str(profile.get("protocol", "")).upper()
        address = str(profile.get("address", "")).strip()
        return f"{protocol} {address}".strip()

    def _load_profiles_from_config(
        self,
        config: dict[str, object],
        *,
        selected_profile_ids: tuple[str, ...] = (),
    ) -> None:
        profiles = get_xray_profiles(config)
        active_profile = get_active_xray_profile(config)
        self.xray_profiles = {str(profile["id"]): dict(profile) for profile in profiles}
        self.active_profile_id = "" if active_profile is None else str(active_profile["id"])
        self._prune_profile_delay_state()

        self.profile_tree.delete(*self.profile_tree.get_children(""))
        for profile in profiles:
            profile_id = str(profile["id"])
            self.profile_tree.insert(
                "",
                "end",
                iid=profile_id,
                values=self._profile_row_values(profile),
                tags=self._profile_row_tags(profile_id),
            )

        resolved_selection = tuple(
            profile_id for profile_id in selected_profile_ids if profile_id in self.xray_profiles
        )
        if not resolved_selection and self.active_profile_id in self.xray_profiles:
            resolved_selection = (self.active_profile_id,)

        if resolved_selection:
            self.profile_tree.selection_set(resolved_selection)
            self.profile_tree.focus(resolved_selection[0])
            self.profile_tree.see(resolved_selection[0])
        else:
            self.profile_tree.selection_remove(self.profile_tree.selection())

        self._update_profile_selection_state()

    def _update_profile_selection_state(self) -> None:
        selection = self.profile_tree.selection()

        active_profile = self.xray_profiles.get(self.active_profile_id)
        if active_profile is None:
            status_text = "No active Xray profile selected."
        else:
            status_text = (
                f"Active profile: {self._profile_label(active_profile)} "
                f"({str(active_profile.get('protocol', '')).upper()} "
                f"{active_profile.get('address', '')}:{active_profile.get('port', '')})"
            )

        if len(selection) > 1:
            status_text = f"{status_text} | Selected: {len(selection)}"
        self.profile_status_var.set(status_text)
        self._sync_button_state()

    def _on_profile_selection_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._update_profile_selection_state()

    def _on_profile_double_click(self, event: tk.Event[tk.Misc]) -> str:
        profile_id = self.profile_tree.identify_row(event.y)
        if not profile_id:
            return ""
        self.profile_tree.selection_set((profile_id,))
        self._edit_selected_profile()
        return "break"

    def _show_profile_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        profile_id = str(self.profile_tree.identify_row(event.y))
        selected_profile_ids = self._get_selected_profile_ids()

        if profile_id:
            if profile_id not in selected_profile_ids:
                self.profile_tree.selection_set((profile_id,))
                selected_profile_ids = (profile_id,)
            self.profile_tree.focus(profile_id)
            self.profile_tree.see(profile_id)
            self._update_profile_selection_state()
        elif not selected_profile_ids:
            return ""

        is_locked = self._is_process_running() or self.delay_test_in_progress
        single_profile_selected = len(selected_profile_ids) == 1
        can_set_active = (
            not is_locked
            and single_profile_selected
            and selected_profile_ids[0] != self.active_profile_id
        )

        self._profile_context_menu.entryconfigure(0, state="normal")
        self._profile_context_menu.entryconfigure(1, state="disabled" if is_locked else "normal")
        self._profile_context_menu.entryconfigure(
            2,
            state="normal" if not is_locked and single_profile_selected else "disabled",
        )
        self._profile_context_menu.entryconfigure(3, state="normal" if can_set_active else "disabled")
        self._profile_context_menu.entryconfigure(4, state="disabled" if is_locked else "normal")

        try:
            self._profile_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._profile_context_menu.grab_release()
        return "break"

    def _get_selected_profile_ids(self) -> tuple[str, ...]:
        return tuple(
            str(profile_id)
            for profile_id in self.profile_tree.selection()
            if str(profile_id) in self.xray_profiles
        )

    def _sync_profile_action_state(self) -> None:
        is_locked = self._is_process_running() or self.delay_test_in_progress
        selected_profile_ids = self._get_selected_profile_ids()
        single_profile_selected = len(selected_profile_ids) == 1

        if is_locked:
            self.profile_add_button.state(["disabled"])
            self.profile_edit_button.state(["disabled"])
            self.profile_remove_button.state(["disabled"])
            self.profile_set_active_button.state(["disabled"])
            return

        self.profile_add_button.state(["!disabled"])
        if single_profile_selected:
            self.profile_edit_button.state(["!disabled"])
        else:
            self.profile_edit_button.state(["disabled"])

        if selected_profile_ids:
            self.profile_remove_button.state(["!disabled"])
        else:
            self.profile_remove_button.state(["disabled"])

        if single_profile_selected and selected_profile_ids[0] != self.active_profile_id:
            self.profile_set_active_button.state(["!disabled"])
        else:
            self.profile_set_active_button.state(["disabled"])

    def _prepare_profiles_for_delay_test(self, selected_profile_ids: tuple[str, ...]) -> None:
        for profile_id in selected_profile_ids:
            self._set_profile_delay_state(
                profile_id,
                delay_text="",
                status_text="Queued",
                status_state="queued",
            )

    def _build_delay_test_jobs(
        self,
        selected_profile_ids: tuple[str, ...],
    ) -> list[tuple[str, str, dict[str, object]]]:
        delay_jobs: list[tuple[str, str, dict[str, object]]] = []
        for profile_id in selected_profile_ids:
            profile = self.xray_profiles.get(profile_id)
            if profile is None:
                continue
            runtime_config = self._build_updated_config(
                active_profile_id=profile_id,
                require_active_profile=True,
            )
            delay_jobs.append((profile_id, self._profile_label(profile), runtime_config))
        return delay_jobs

    def _queue_profile_delay_log(self, profile_label: str, message: str) -> None:
        normalized_message = message.strip()
        if normalized_message.startswith("[delay]"):
            normalized_message = normalized_message[len("[delay]"):].strip()
        if normalized_message:
            self.log_queue.put(("log", f"[delay][{profile_label}] {normalized_message}"))
        else:
            self.log_queue.put(("log", f"[delay][{profile_label}]"))

    def _prompt_for_profile(
        self,
        title: str,
        *,
        initial_profile: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        dialog = ShareUrlDialog(
            self,
            title,
            initial_url="" if initial_profile is None else str(initial_profile.get("url", "")),
            profile_id=None if initial_profile is None else str(initial_profile["id"]),
        )
        return dialog.result

    def _persist_profile_state(
        self,
        profiles: list[dict[str, object]],
        *,
        active_profile_id: str = "",
        selected_profile_ids: tuple[str, ...] = (),
        log_message: str | None = None,
    ) -> None:
        config = load_config()
        updated_config = replace_xray_profiles(
            config,
            profiles,
            active_profile_id=active_profile_id,
        )
        save_config(updated_config)
        self._load_profiles_from_config(
            updated_config,
            selected_profile_ids=selected_profile_ids,
        )
        if log_message:
            self._append_log(log_message)

    def _require_single_selected_profile(self, action_name: str) -> str | None:
        selected_profile_ids = self._get_selected_profile_ids()
        if not selected_profile_ids:
            messagebox.showinfo(
                "Select A Profile",
                f"Select one profile to {action_name}.",
                parent=self,
            )
            return None
        if len(selected_profile_ids) != 1:
            messagebox.showinfo(
                "Select One Profile",
                f"Select exactly one profile to {action_name}.",
                parent=self,
            )
            return None
        return selected_profile_ids[0]

    def _add_profile(self) -> None:
        new_profile = self._prompt_for_profile("Add Xray Profile")
        if new_profile is None:
            return

        profiles = self._get_profiles_in_display_order()
        profiles.append(new_profile)
        active_profile_id = self.active_profile_id or str(new_profile["id"])

        try:
            self._persist_profile_state(
                profiles,
                active_profile_id=active_profile_id,
                selected_profile_ids=(str(new_profile["id"]),),
                log_message=f"[profiles] added {self._profile_label(new_profile)}",
            )
        except Exception as exc:
            messagebox.showerror("Failed To Save Profiles", str(exc), parent=self)

    def _edit_selected_profile(self) -> None:
        profile_id = self._require_single_selected_profile("edit")
        if profile_id is None:
            return

        profile = self.xray_profiles.get(profile_id)
        if profile is None:
            return

        updated_profile = self._prompt_for_profile(
            "Edit Xray Profile",
            initial_profile=profile,
        )
        if updated_profile is None:
            return

        profiles: list[dict[str, object]] = []
        for existing_profile in self._get_profiles_in_display_order():
            if str(existing_profile["id"]) == profile_id:
                profiles.append(updated_profile)
            else:
                profiles.append(existing_profile)

        try:
            self._persist_profile_state(
                profiles,
                active_profile_id=self.active_profile_id,
                selected_profile_ids=(profile_id,),
                log_message=f"[profiles] updated {self._profile_label(updated_profile)}",
            )
            self._set_profile_delay_state(profile_id)
        except Exception as exc:
            messagebox.showerror("Failed To Save Profiles", str(exc), parent=self)

    def _remove_selected_profiles(self) -> None:
        selected_profile_ids = self._get_selected_profile_ids()
        if not selected_profile_ids:
            messagebox.showinfo(
                "Select Profiles",
                "Select one or more profiles to remove.",
                parent=self,
            )
            return

        should_remove = messagebox.askyesno(
            "Remove Profiles",
            f"Remove {len(selected_profile_ids)} selected profile(s)?",
            parent=self,
        )
        if not should_remove:
            return

        profiles = [
            profile
            for profile in self._get_profiles_in_display_order()
            if str(profile["id"]) not in selected_profile_ids
        ]
        remaining_profile_ids = [str(profile["id"]) for profile in profiles]
        active_profile_id = self.active_profile_id
        if active_profile_id not in remaining_profile_ids:
            active_profile_id = "" if not remaining_profile_ids else remaining_profile_ids[0]

        selected_after_save = () if not active_profile_id else (active_profile_id,)
        try:
            self._persist_profile_state(
                profiles,
                active_profile_id=active_profile_id,
                selected_profile_ids=selected_after_save,
                log_message=f"[profiles] removed {len(selected_profile_ids)} profile(s)",
            )
        except Exception as exc:
            messagebox.showerror("Failed To Save Profiles", str(exc), parent=self)

    def _set_selected_profile_active(self) -> None:
        profile_id = self._require_single_selected_profile("set active")
        if profile_id is None:
            return

        profile = self.xray_profiles.get(profile_id)
        if profile is None:
            return

        try:
            self._persist_profile_state(
                self._get_profiles_in_display_order(),
                active_profile_id=profile_id,
                selected_profile_ids=(profile_id,),
                log_message=f"[profiles] active profile set to {self._profile_label(profile)}",
            )
        except Exception as exc:
            messagebox.showerror("Failed To Save Profiles", str(exc), parent=self)

    def _sync_button_state(self) -> None:
        is_running = self._is_process_running()
        is_busy = self.delay_test_in_progress
        has_active_profile = bool(self.active_profile_id and self.active_profile_id in self.xray_profiles)
        has_delay_selection = bool(self._get_selected_profile_ids())

        if is_running or is_busy or not has_active_profile:
            self.start_button.state(["disabled"])
        else:
            self.start_button.state(["!disabled"])

        if is_running:
            self.stop_button.state(["!disabled"])
        else:
            self.stop_button.state(["disabled"])

        if is_busy:
            self.test_delay_button.state(["disabled"])
        elif is_running or not has_delay_selection:
            self.test_delay_button.state(["disabled"])
        else:
            self.test_delay_button.state(["!disabled"])

        self._sync_profile_action_state()

    def _is_process_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _append_log(self, message: str, tag: str | None = None) -> None:
        self.log_text.configure(state="normal")
        if tag is None:
            self.log_text.insert("end", f"{message}\n")
        else:
            self.log_text.insert("end", f"{message}\n", tag)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_logs(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def load_form_from_disk(self, *, show_log: bool = False) -> None:
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
        self._load_profiles_from_config(config)
        if show_log:
            self._append_log("[loaded] config loaded from disk")

    def _parse_port_value(self, raw_value: str, field_name: str) -> int:
        try:
            port = int(raw_value.strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a valid TCP port") from exc
        if port < 1 or port > 65535:
            raise ValueError(f"{field_name} must be between 1 and 65535")
        return port

    def _build_updated_config(
        self,
        *,
        active_profile_id: str | None = None,
        require_active_profile: bool = False,
    ) -> dict[str, object]:
        config = load_config()

        connect_ip = self.connect_ip_var.get().strip()
        fake_sni = self.fake_sni_var.get().strip()
        socks_port = self._parse_port_value(self.socks_port_var.get(), "XRAY_SOCKS_PORT")
        http_port = self._parse_port_value(self.http_port_var.get(), "XRAY_HTTP_PORT")
        log_level = normalize_xray_log_level(self.log_level_var.get())
        listen_port = get_config_port(config, "LISTEN_PORT", 40443)
        profiles = self._get_profiles_in_display_order()
        resolved_active_profile_id = self.active_profile_id if active_profile_id is None else active_profile_id

        if not connect_ip:
            raise ValueError("CONNECT_IP must not be empty")
        if not fake_sni:
            raise ValueError("FAKE_SNI must not be empty")
        if socks_port == http_port:
            raise ValueError("XRAY_SOCKS_PORT and XRAY_HTTP_PORT must be different")
        if listen_port in {socks_port, http_port}:
            raise ValueError("LISTEN_PORT must be different from XRAY_SOCKS_PORT and XRAY_HTTP_PORT")
        if require_active_profile:
            if not profiles:
                raise ValueError("Add at least one Xray profile before continuing.")
            if not resolved_active_profile_id or resolved_active_profile_id not in self.xray_profiles:
                raise ValueError("Select an active Xray profile before continuing.")

        updated_config = replace_xray_profiles(
            config,
            profiles,
            active_profile_id=resolved_active_profile_id,
        )
        updated_config["CONNECT_IP"] = connect_ip
        updated_config["FAKE_SNI"] = fake_sni
        updated_config["XRAY_SOCKS_PORT"] = socks_port
        updated_config["XRAY_HTTP_PORT"] = http_port
        updated_config["XRAY_LOG_LEVEL"] = log_level
        return updated_config

    def _cleanup_runtime_config(self) -> None:
        if self.runtime_config_path is None:
            return

        self.runtime_config_path.unlink(missing_ok=True)
        self.runtime_config_path = None

    def _write_runtime_config(self, config: dict[str, object]) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".json", prefix="rm-sni-spoofer-", delete=False) as temp_file:
            runtime_config_path = Path(temp_file.name)
        save_config(config, str(runtime_config_path))
        return runtime_config_path

    def _build_headless_command(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--headless"]
        return [sys.executable, "-u", str(Path(get_app_dir()) / "main.py"), "--headless"]

    def start_relay(self) -> None:
        if self._is_process_running():
            messagebox.showinfo("Relay Running", "Stop the current relay before starting a new one.", parent=self)
            return

        try:
            runtime_config = self._build_updated_config(require_active_profile=True)
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc), parent=self)
            return

        active_profile = get_active_xray_profile(runtime_config)
        if active_profile is None:
            messagebox.showerror(
                "Invalid Configuration",
                "Select an active Xray profile before starting the relay.",
                parent=self,
            )
            return

        self._cleanup_runtime_config()
        runtime_config_path = self._write_runtime_config(runtime_config)

        command = self._build_headless_command()
        command.extend(["--config", str(runtime_config_path)])
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
            runtime_config_path.unlink(missing_ok=True)
            self.process = None
            messagebox.showerror("Failed To Start Relay", str(exc), parent=self)
            return

        self.runtime_config_path = runtime_config_path
        self.status_var.set(f"Running (PID {self.process.pid})")
        self._sync_button_state()
        self._append_log("")
        self._append_log(f"[start] {subprocess.list2cmdline(command)}")
        self._append_log(f"[start] runtime config: {runtime_config_path}")
        self._append_log(f"[start] active profile: {self._profile_label(active_profile)}")
        self._append_log(f"[pid] {self.process.pid}")

        threading.Thread(target=self._read_process_output, args=(self.process,), daemon=True).start()
        threading.Thread(target=self._monitor_process, args=(self.process,), daemon=True).start()

    def test_delay(self) -> None:
        if self._is_process_running():
            messagebox.showinfo(
                "Relay Running",
                "Stop the current relay before running a temporary delay test.",
                parent=self,
            )
            return

        selected_profile_ids = self._get_selected_profile_ids()
        if not selected_profile_ids:
            messagebox.showinfo(
                "Select Profiles",
                "Select one or more profiles to test.",
                parent=self,
            )
            return

        try:
            delay_jobs = self._build_delay_test_jobs(selected_profile_ids)
        except Exception as exc:
            messagebox.showerror("Invalid Configuration", str(exc), parent=self)
            return

        if not delay_jobs:
            messagebox.showinfo(
                "Select Profiles",
                "Select one or more valid profiles to test.",
                parent=self,
            )
            return

        self.delay_test_in_progress = True
        self._prepare_profiles_for_delay_test(selected_profile_ids)
        self.status_var.set(f"Testing Delay (0/{len(delay_jobs)})...")
        self._sync_button_state()
        self._append_log(
            f"[delay] queued {len(delay_jobs)} selected profile(s) for proxied HTTPS GET to "
            "https://www.google.com/generate_204 through a temporary relay and Xray runtime"
        )
        threading.Thread(target=self._run_delay_tests, args=(delay_jobs,), daemon=True).start()

    def _run_delay_tests(
        self,
        delay_jobs: list[tuple[str, str, dict[str, object]]],
    ) -> None:
        total_jobs = len(delay_jobs)
        try:
            for index, (profile_id, profile_label, config) in enumerate(delay_jobs, start=1):
                self.log_queue.put(("delay-started", profile_id, profile_label, index, total_jobs))
                try:
                    result = measure_delay_with_temporary_runtime(
                        config,
                        self._build_headless_command(),
                        log_callback=lambda message, label=profile_label: self._queue_profile_delay_log(label, message),
                    )
                except Exception as exc:
                    self.log_queue.put(("delay-error", profile_id, profile_label, str(exc), index, total_jobs))
                else:
                    self.log_queue.put(("delay-result", profile_id, profile_label, result, index, total_jobs))
        finally:
            self.log_queue.put(("delay-finished", total_jobs))

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
            self._cleanup_runtime_config()
            self.status_var.set(f"Stopped (exit {return_code})")
            self._sync_button_state()
        self._append_log(f"[exit] relay exited with code {return_code}")

    def _queue_worker_log(self, message: str) -> None:
        self.log_queue.put(("log", message))

    def _handle_delay_started(
        self,
        profile_id: str,
        profile_label: str,
        index: int,
        total: int,
    ) -> None:
        self._set_profile_delay_state(
            profile_id,
            delay_text="",
            status_text="Testing",
            status_state="testing",
        )
        self.status_var.set(f"Testing Delay ({index}/{total}): {profile_label}")

    def _handle_delay_result(
        self,
        profile_id: str,
        profile_label: str,
        result: DelayTestResult,
        index: int,
        total: int,
    ) -> None:
        delay_text = f"{result.latency_ms:.0f} ms"
        self._set_profile_delay_state(
            profile_id,
            delay_text=delay_text,
            status_text="OK",
            status_state="success",
        )
        self._append_log(
            f"[delay] {profile_label}: {result.target_host}:{result.target_port} reachable in {result.latency_ms:.0f} ms "
            f"via relay={result.relay_port}, socks={result.socks_port}, http={result.http_port}",
            "delay_success",
        )
        if index == total:
            self.status_var.set(f"Delay: {delay_text}")

    def _handle_delay_error(
        self,
        profile_id: str,
        profile_label: str,
        message: str,
    ) -> None:
        self._set_profile_delay_state(
            profile_id,
            delay_text="",
            status_text="Failed",
            status_state="error",
        )
        self._append_log(f"[delay] {profile_label}: failed: {message}", "delay_error")

    def _handle_delay_finished(self, total_jobs: int) -> None:
        self.delay_test_in_progress = False
        if self._is_process_running() and self.process is not None:
            self.status_var.set(f"Running (PID {self.process.pid})")
        elif total_jobs > 0:
            self.status_var.set(f"Delay Tests Complete ({total_jobs})")
        else:
            self.status_var.set("Stopped")
        self._sync_button_state()

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
            elif kind == "delay-started":
                _, profile_id, profile_label, index, total = item
                self._handle_delay_started(str(profile_id), str(profile_label), int(index), int(total))
            elif kind == "delay-result":
                _, profile_id, profile_label, result, index, total = item
                self._handle_delay_result(
                    str(profile_id),
                    str(profile_label),
                    result,
                    int(index),
                    int(total),
                )
            elif kind == "delay-error":
                _, profile_id, profile_label, message, _index, _total = item
                self._handle_delay_error(str(profile_id), str(profile_label), str(message))
            elif kind == "delay-finished":
                _, total_jobs = item
                self._handle_delay_finished(int(total_jobs))

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
        self._cleanup_runtime_config()
        self.destroy()


def launch_gui() -> None:
    app = ControlPanel()
    app.mainloop()