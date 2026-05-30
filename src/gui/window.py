from __future__ import annotations

import ctypes
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from src.core.config.app_config import (
    CONNECTION_MODES,
    DEFAULT_LOCAL_PROXY_BIND_HOST,
    XRAY_LOG_LEVELS,
    get_app_dir,
    get_connection_mode,
    get_local_proxy_bind_host,
    get_local_proxy_port,
    load_config,
    load_delay_results,
    normalize_connection_mode,
    save_config,
)
import src.gui.editor as editor_helpers
import src.gui.logs as log_helpers
import src.gui.profiles as profile_helpers
import src.gui.relay as relay_helpers
from src.gui.dialogs import (
    DONATION_ADDRESS,
    HowToRunDialog,
    ShareUrlDialog,
    SupportUsDialog,
)
from src.gui.theme import (
    APP_ICON_ICO_PATH,
    APP_ICON_PNG_PATH,
    APP_NAME,
    APP_VERSION,
    ICON_FALLBACK_TEXT,
    ICON_GLYPHS,
    THEME,
    WINDOWS_PRIVATE_FONT_FLAG,
    configure_styles,
    configure_window_frame,
    iter_private_font_paths as _iter_private_font_paths,
    style_menu,
)
from src.gui.widgets import RoundedPanel, SurfaceButton, ToggleSwitch
from src.services.delay_test import DelayTestResult


class ControlPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} v{APP_VERSION}")

        self.geometry("1280x840")
        self.minsize(1280, 720)
        self._window_icon: tk.PhotoImage | None = None
        self._private_font_paths: list[Path] = []
        self._font_families: dict[str, str] = {}
        self._relay_chip_frame: tk.Frame | None = None
        self._relay_chip_dot: tk.Label | None = None
        self._relay_chip_label: tk.Label | None = None
        self._status_detail_label: ttk.Label | None = None
        self._profile_scroll_y: ttk.Scrollbar | None = None
        self._profile_scroll_x: ttk.Scrollbar | None = None
        self._log_scroll_y: ttk.Scrollbar | None = None
        self._log_scroll_x: ttk.Scrollbar | None = None

        self.process: subprocess.Popen[str] | None = None
        self.delay_test_in_progress = False
        self.delay_test_stop_event = threading.Event()
        self.log_queue: queue.Queue[tuple] = queue.Queue()
        self.runtime_config_path: Path | None = None
        self.xray_profiles: dict[str, dict[str, object]] = {}
        self.active_profile_id = ""
        self._selected_profile_ids: tuple[str, ...] = ()
        self._profile_selection_syncing = False
        self.profile_delay_values: dict[str, str] = {}
        self.profile_delay_statuses: dict[str, str] = {}
        self.profile_delay_states: dict[str, str] = {}
        self._profile_sort_column: str | None = None
        self._profile_sort_reverse: bool = False

        self.connect_ip_var = tk.StringVar()
        self.fake_sni_var = tk.StringVar()
        self.connection_mode_var = tk.StringVar(value=CONNECTION_MODES[0])
        self.local_proxy_bind_host_var = tk.StringVar(value=DEFAULT_LOCAL_PROXY_BIND_HOST)
        self.local_proxy_port_var = tk.StringVar()
        self.lan_share_enabled_var = tk.BooleanVar(value=False)
        self.lan_share_header_var = tk.StringVar(value="LAN SHARING")
        self.lan_share_endpoint_var = tk.StringVar(value="LAN address unavailable")
        self.log_level_var = tk.StringVar(value="warning")
        self.profile_status_var = tk.StringVar(value="No active Xray profile selected.")
        self.status_var = tk.StringVar(value="Stopped")
        self.relay_chip_var = tk.StringVar(value="Stopped")
        self._context_menu_target: tk.Misc | None = None
        self.lan_share_switch: ToggleSwitch | None = None

        self.status_var.trace_add("write", self._sync_status_widgets)
        self._bootstrap_assets()
        self._configure_style()
        self._configure_icon()
        self._build_layout()
        self.after(0, self._configure_window_frame)
        self._install_context_menus()
        self.load_form_from_disk()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_log_queue)

    def _bootstrap_assets(self) -> None:
        self._register_private_fonts()
        self._font_families = {
            "body": self._resolve_font_family(
                ("Inter", "Inter Medium"),
                ("Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "headline": self._resolve_font_family(
                ("Inter SemiBold", "Inter Medium", "Inter"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "title": self._resolve_font_family(
                ("Inter SemiBold", "Inter Medium", "Inter"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "label": self._resolve_font_family(
                ("Geist Medium", "Geist SemiBold", "Geist"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "button": self._resolve_font_family(
                ("Inter Medium", "Inter SemiBold", "Inter"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "mono": self._resolve_font_family(
                ("Geist Mono", "Cascadia Mono", "Cascadia Code", "Consolas"),
                ("Courier New", "TkFixedFont"),
            ),
            "icon": self._resolve_font_family(
                ("Segoe Fluent Icons", "Segoe MDL2 Assets"),
                ("Segoe UI Symbol",),
            ),
        }

    def _register_private_fonts(self) -> None:
        if sys.platform != "win32":
            return

        try:
            add_font_resource = ctypes.windll.gdi32.AddFontResourceExW
        except Exception:
            return

        for font_path in _iter_private_font_paths():
            try:
                added_count = int(add_font_resource(str(font_path), WINDOWS_PRIVATE_FONT_FLAG, 0))
            except Exception:
                continue
            if added_count > 0:
                self._private_font_paths.append(font_path)

    def _available_font_families(self) -> tuple[str, ...]:
        families = tkfont.families(self)
        return tuple(str(family) for family in families)

    def _resolve_font_family(
        self,
        preferred_prefixes: tuple[str, ...],
        fallback_families: tuple[str, ...],
    ) -> str:
        available_families = self._available_font_families()
        lowered = {family.lower(): family for family in available_families}

        for prefix in preferred_prefixes:
            prefix_lower = prefix.lower()
            exact_match = lowered.get(prefix_lower)
            if exact_match is not None:
                return exact_match
            for family in available_families:
                if family.lower().startswith(prefix_lower):
                    return family

        for fallback in fallback_families:
            fallback_match = lowered.get(fallback.lower())
            if fallback_match is not None:
                return fallback_match
        return fallback_families[0]

    def _icon_glyph(self, icon_name: str) -> str:
        return ICON_GLYPHS.get(icon_name, "")

    def _build_icon_badge(self, parent: tk.Misc, icon_name: str) -> tk.Label:
        glyph = self._icon_glyph(icon_name)
        if glyph:
            return tk.Label(
                parent,
                text=glyph,
                bg=THEME["card"],
                fg=THEME["muted_alt"],
                font=(self._font_families["icon"], 12),
            )

        return tk.Label(
            parent,
            text=ICON_FALLBACK_TEXT.get(icon_name, icon_name).upper(),
            bg=THEME["card"],
            fg=THEME["accent_text"],
            font=(self._font_families["label"], 7, "bold"),
            padx=6,
            pady=2,
        )

    def _runtime_label(self) -> str:
        return "Bundled Build" if getattr(sys, "frozen", False) else "Source Build"

    def _check_for_updates(self) -> None:
        self._append_log("[updates] no update service is configured for this build")

    def _copy_donation_address(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(DONATION_ADDRESS)
        self._append_log("[support] donation address copied to clipboard")

    def _show_support_dialog(self) -> None:
        SupportUsDialog(self, "Support Us", copy_callback=self._copy_donation_address)

    def _sync_status_widgets(self, *_args: str) -> None:
        status_text = self.status_var.get().strip()
        status_lower = status_text.lower()
        chip_text = "RELAY IDLE"
        dot_color = THEME["muted_alt"]
        chip_bg = THEME["low"]
        chip_border = THEME["border"]

        if status_lower.startswith("running"):
            chip_text = "RELAY ACTIVE"
            dot_color = THEME["accent"]
            chip_bg = THEME["accent_soft"]
            chip_border = THEME["accent"]
        elif status_lower.startswith("testing"):
            chip_text = "TESTING"
            dot_color = THEME["warning"]
            chip_bg = THEME["accent_soft"]
            chip_border = THEME["accent"]
        elif status_lower.startswith("stopping"):
            chip_text = "STOPPING"
            dot_color = THEME["warning"]
            chip_bg = THEME["accent_soft"]
            chip_border = THEME["accent"]
        elif status_lower.startswith("delay"):
            chip_text = "DELAY TEST"
            dot_color = THEME["warning"]

        self.relay_chip_var.set(chip_text)
        if self._relay_chip_dot is not None:
            self._relay_chip_dot.configure(fg=dot_color, bg=chip_bg)
        if self._relay_chip_label is not None:
            self._relay_chip_label.configure(bg=chip_bg, fg=THEME["accent_text"] if chip_bg != THEME["low"] else THEME["muted_alt"])
        if self._relay_chip_frame is not None:
            self._relay_chip_frame.configure(bg=chip_bg, highlightbackground=chip_border)

    def _style_menu(self, menu: tk.Menu) -> None:
        style_menu(menu)

    def _configure_style(self) -> None:
        configure_styles(self, self._font_families)

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

    def _configure_window_frame(self) -> None:
        configure_window_frame(self)

    def _show_how_to_run_dialog(self) -> None:
        HowToRunDialog(self, "راهنمای اجرا")

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        shell = tk.Frame(self, bg=THEME["base_bg"])
        shell.grid(row=0, column=0, sticky="nsew")
        shell.columnconfigure(1, weight=1)
        shell.rowconfigure(0, weight=1)

        sidebar = tk.Frame(
            shell,
            bg=THEME["low"],
            width=248,
            highlightbackground=THEME["border"],
            highlightthickness=0,
            bd=0,
        )
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(2, weight=1)
        self._build_sidebar(sidebar)

        main_shell = tk.Frame(shell, bg=THEME["shell"])
        main_shell.grid(row=0, column=1, sticky="nsew")
        main_shell.columnconfigure(0, weight=1)
        main_shell.rowconfigure(1, weight=1)

        main = ttk.Frame(main_shell, style="Main.TFrame", padding=(24, 18, 24, 24))
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=2, minsize=190)
        main.rowconfigure(2, weight=5, minsize=300)
        main.rowconfigure(4, weight=3, minsize=220)

        self._build_settings_section(main)
        self._build_profiles_section(main)
        self._build_actions_section(main)
        self._build_logs_section(main)
        self._sync_status_widgets()
        self._sync_button_state()

    def _build_sidebar(self, parent: tk.Frame) -> None:
        brand = tk.Frame(parent, bg=THEME["low"], padx=20, pady=18)
        brand.grid(row=0, column=0, sticky="ew")
        brand.columnconfigure(0, weight=1)

        ttk.Label(brand, text=APP_NAME, style="SidebarTitle.TLabel").grid(row=0, column=0, sticky="w")

        nav = tk.Frame(parent, bg=THEME["low"], padx=10, pady=8)
        nav.grid(row=1, column=0, sticky="ew")
        nav.columnconfigure(0, weight=1)

        dashboard_button = SurfaceButton(
            nav,
            theme=THEME,
            fonts=self._font_families,
            text="Dashboard",
            icon_glyph=self._icon_glyph("dashboard"),
            variant="nav_active",
            command=lambda: None,
        )
        dashboard_button.grid(row=0, column=0, sticky="ew")

        footer = tk.Frame(parent, bg=THEME["low"], padx=14, pady=14)
        footer.grid(row=3, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)

        how_to_run_button = SurfaceButton(
            footer,
            theme=THEME,
            fonts=self._font_families,
            text="How to Run",
            icon_glyph=self._icon_glyph("help"),
            variant="sidebar_outline",
            command=self._show_how_to_run_dialog,
        )
        how_to_run_button.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        updates_button = SurfaceButton(
            footer,
            theme=THEME,
            fonts=self._font_families,
            text="Check Updates",
            icon_glyph=self._icon_glyph("refresh"),
            variant="sidebar_primary",
            command=self._check_for_updates,
        )
        updates_button.grid(row=1, column=0, sticky="ew")

        support_button = SurfaceButton(
            footer,
            theme=THEME,
            fonts=self._font_families,
            text="Support Us",
            icon_glyph=self._icon_glyph("volunteer"),
            variant="sidebar_outline",
            command=self._show_support_dialog,
        )
        support_button.grid(row=2, column=0, sticky="ew", pady=(10, 0))

    def _build_header(self, parent: ttk.Frame) -> None:
        header = tk.Frame(parent, bg=THEME["shell"], padx=24, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

    def _build_settings_section(self, parent: ttk.Frame) -> None:
        shell = RoundedPanel(
            parent,
            fill=THEME["card"],
            border=THEME["border"],
            radius=18,
            padding=(16, 16, 16, 16),
        )
        shell.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        section = shell.content
        for column in range(3):
            section.columnconfigure(column, weight=1)

        header = ttk.Frame(section, style="Section.TFrame")
        header.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Editable Settings", style="SectionTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )

        lan_share_wrap = ttk.Frame(header, style="Section.TFrame")
        lan_share_wrap.grid(row=0, column=1, sticky="e", padx=(0, 12))
        ttk.Label(
            lan_share_wrap,
            textvariable=self.lan_share_header_var,
            style="CardLabel.TLabel",
        ).grid(row=0, column=0, sticky="e", padx=(0, 8))
        self.lan_share_switch = ToggleSwitch(
            lan_share_wrap,
            theme=THEME,
            variable=self.lan_share_enabled_var,
            command=self._on_lan_share_toggled,
        )
        self.lan_share_switch.grid(row=0, column=1, sticky="e")

        connection_mode_wrap = ttk.Frame(header, style="Section.TFrame")
        connection_mode_wrap.grid(row=0, column=2, sticky="e", padx=(0, 12))
        ttk.Label(connection_mode_wrap, text="Connection Mode", style="CardLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="e",
            padx=(0, 8),
        )
        self.connection_mode_combo = ttk.Combobox(
            connection_mode_wrap,
            state="readonly",
            textvariable=self.connection_mode_var,
            values=CONNECTION_MODES,
            style="Card.TCombobox",
            width=22,
        )
        self.connection_mode_combo.grid(row=0, column=1, sticky="e")
        self.connection_mode_combo.bind("<<ComboboxSelected>>", self._on_connection_mode_changed, add="+")

        log_level_wrap = ttk.Frame(header, style="Section.TFrame")
        log_level_wrap.grid(row=0, column=3, sticky="e")
        ttk.Label(log_level_wrap, text="Log Level", style="CardLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="e",
            padx=(0, 8),
        )
        self.log_level_combo = ttk.Combobox(
            log_level_wrap,
            state="readonly",
            textvariable=self.log_level_var,
            values=XRAY_LOG_LEVELS,
            style="Card.TCombobox",
            width=12,
        )
        self.log_level_combo.grid(row=0, column=1, sticky="e")

        connect_ip_entry = self._build_settings_card(
            section,
            1,
            0,
            "CONNECT IP",
            self.connect_ip_var,
            "lan",
            total_columns=3,
        )
        connect_ip_entry.bind("<FocusOut>", self._on_connect_ip_changed, add="+")
        self._build_settings_card(section, 1, 1, "FAKE SNI", self.fake_sni_var, "public", total_columns=3)
        local_proxy_entry = self._build_settings_card(
            section,
            1,
            2,
            "MIXED PROXY PORT",
            self.local_proxy_port_var,
            "usb",
            total_columns=3,
        )
        local_proxy_entry.bind("<FocusOut>", self._on_proxy_mode_settings_changed, add="+")
        shell.refresh()

    def _build_settings_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label_text: str,
        variable: tk.StringVar,
        icon_name: str,
        *,
        total_columns: int = 4,
    ) -> ttk.Entry:
        card = RoundedPanel(
            parent,
            fill=THEME["card"],
            border=THEME["border"],
            radius=14,
            padding=(12, 10, 12, 10),
        )
        left_pad = 0 if column == 0 else 8
        right_pad = 0 if column == (total_columns - 1) else 8
        card.grid(row=row, column=column, sticky="ew", padx=(left_pad, right_pad), pady=4)
        card.content.columnconfigure(0, weight=1)

        top = tk.Frame(card.content, bg=THEME["card"])
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text=label_text, style="CardLabel.TLabel").grid(row=0, column=0, sticky="w")
        badge = self._build_icon_badge(top, icon_name)
        badge.grid(row=0, column=1, sticky="e")
        entry = ttk.Entry(card.content, textvariable=variable, style="Card.TEntry")
        entry.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        card.refresh()
        return entry

    def _build_profiles_section(self, parent: ttk.Frame) -> None:
        shell = RoundedPanel(
            parent,
            fill=THEME["card"],
            border=THEME["border"],
            radius=18,
            padding=(16, 16, 16, 16),
        )
        shell.grid(row=2, column=0, sticky="nsew", pady=(0, 16))
        section = shell.content
        section.columnconfigure(0, weight=1)
        section.rowconfigure(1, weight=1)

        header = ttk.Frame(section, style="Section.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(0, weight=1)

        title_wrap = tk.Frame(header, bg=THEME["card"])
        title_wrap.grid(row=0, column=0, sticky="w")
        tk.Label(
            title_wrap,
            text=self._icon_glyph("dashboard"),
            bg=THEME["card"],
            fg=THEME["accent_text"],
            font=(self._font_families["icon"], 12),
            padx=0,
        ).pack(side="left")
        ttk.Label(title_wrap, text="Xray Profiles", style="SectionTitle.TLabel").pack(side="left", padx=(8, 0))

        actions = tk.Frame(header, bg=THEME["card"])
        actions.grid(row=0, column=1, sticky="e")

        self.profile_add_button = SurfaceButton(
            actions,
            theme=THEME,
            fonts=self._font_families,
            text="Add Profile",
            variant="primary",
            command=self._add_profile,
        )
        self.profile_add_button.grid(row=0, column=0, padx=(0, 8))

        self.profile_edit_button = SurfaceButton(
            actions,
            theme=THEME,
            fonts=self._font_families,
            text="Edit",
            variant="secondary",
            command=self._edit_selected_profile,
        )
        self.profile_edit_button.grid(row=0, column=1, padx=(0, 8))

        self.profile_remove_button = SurfaceButton(
            actions,
            theme=THEME,
            fonts=self._font_families,
            text="Remove",
            variant="secondary",
            command=self._remove_selected_profiles,
        )
        self.profile_remove_button.grid(row=0, column=2, padx=(0, 8))

        self.profile_set_active_button = SurfaceButton(
            actions,
            theme=THEME,
            fonts=self._font_families,
            text="Set Active",
            variant="secondary",
            command=self._set_selected_profile_active,
        )
        self.profile_set_active_button.grid(row=0, column=3)

        table_shell = tk.Frame(
            section,
            bg=THEME["card"],
            highlightbackground=THEME["border"],
            highlightcolor=THEME["border"],
            highlightthickness=2,
            bd=0,
        )
        table_shell.grid(row=1, column=0, sticky="nsew")
        table_shell.columnconfigure(0, weight=1)
        table_shell.rowconfigure(0, weight=1)

        table_frame = ttk.Frame(table_shell, style="Section.TFrame")
        table_frame.grid(row=0, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

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
            table_frame,
            columns=profile_columns,
            show="headings",
            selectmode="extended",
            height=11,
            style="Profiles.Treeview",
        )
        self.profile_tree.heading("active", text="Active", command=lambda: self._sort_profiles("active"))
        self.profile_tree.heading("remark", text="Remark", command=lambda: self._sort_profiles("remark"))
        self.profile_tree.heading("protocol", text="Type", command=lambda: self._sort_profiles("protocol"))
        self.profile_tree.heading("address", text="Address", command=lambda: self._sort_profiles("address"))
        self.profile_tree.heading("port", text="Port", command=lambda: self._sort_profiles("port"))
        self.profile_tree.heading("transport", text="Transport", command=lambda: self._sort_profiles("transport"))
        self.profile_tree.heading("security", text="Security", command=lambda: self._sort_profiles("security"))
        self.profile_tree.heading("delay", text="Delay", command=lambda: self._sort_profiles("delay"))
        self.profile_tree.heading("status", text="Status", command=lambda: self._sort_profiles("status"))
        self.profile_tree.column("active", width=74, anchor="center", stretch=False)
        self.profile_tree.column("remark", width=180, stretch=True)
        self.profile_tree.column("protocol", width=84, anchor="center", stretch=False)
        self.profile_tree.column("address", width=220, stretch=True)
        self.profile_tree.column("port", width=70, anchor="center", stretch=False)
        self.profile_tree.column("transport", width=90, anchor="center", stretch=False)
        self.profile_tree.column("security", width=90, anchor="center", stretch=False)
        self.profile_tree.column("delay", width=90, anchor="center", stretch=False)
        self.profile_tree.column("status", width=110, anchor="center", stretch=False)
        self.profile_tree.grid(row=0, column=0, sticky="nsew")
        self.profile_tree.tag_configure(
            "active_profile",
            background=THEME["selection"],
            foreground=THEME["accent_text"],
        )
        self.profile_tree.tag_configure("queued_profile", foreground=THEME["muted"])
        self.profile_tree.tag_configure("testing_profile", foreground=THEME["warning"])
        self.profile_tree.tag_configure("success_profile", foreground=THEME["success"])
        self.profile_tree.tag_configure("error_profile", foreground=THEME["error"])
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_profile_selection_changed, add="+")
        self.profile_tree.bind("<Double-1>", self._on_profile_double_click, add="+")
        self.profile_tree.bind("<Configure>", lambda _event: self.after_idle(self._refresh_profile_scrollbars), add="+")

        self._profile_scroll_y = profile_scroll_y = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.profile_tree.yview,
            style="Shell.Vertical.TScrollbar",
        )
        profile_scroll_y.grid(row=0, column=1, sticky="ns")
        self.profile_tree.configure(
            yscrollcommand=lambda first, last, scrollbar=profile_scroll_y: self._update_scrollbar_visibility(
                scrollbar,
                first,
                last,
            ),
        )

        self._profile_scroll_x = profile_scroll_x = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.profile_tree.xview,
            style="Shell.Horizontal.TScrollbar",
        )
        profile_scroll_x.grid(row=1, column=0, sticky="ew")
        self.profile_tree.configure(
            xscrollcommand=lambda first, last, scrollbar=profile_scroll_x: self._update_scrollbar_visibility(
                scrollbar,
                first,
                last,
            ),
        )

        ttk.Label(section, textvariable=self.profile_status_var, style="StatusDetail.TLabel").grid(
            row=2,
            column=0,
            sticky="w",
            pady=(10, 0),
        )
        shell.refresh()

    def _build_actions_section(self, parent: ttk.Frame) -> None:
        section = ttk.Frame(parent, style="Main.TFrame", padding=(0, 0, 0, 0))
        section.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        section.columnconfigure(0, weight=1)
        section.columnconfigure(1, weight=0)

        divider = tk.Frame(section, bg=THEME["border"], height=1)
        divider.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))

        buttons = tk.Frame(section, bg=THEME["shell"])
        buttons.grid(row=1, column=0, sticky="w")

        self.start_button = SurfaceButton(
            buttons,
            theme=THEME,
            fonts=self._font_families,
            text="Start",
            icon_glyph=self._icon_glyph("bolt"),
            variant="primary",
            command=self.start_relay,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = SurfaceButton(
            buttons,
            theme=THEME,
            fonts=self._font_families,
            text="Stop",
            icon_glyph=self._icon_glyph("stop_circle"),
            variant="secondary",
            command=self.stop_relay,
        )
        self.stop_button.grid(row=0, column=1, padx=(0, 8))

        self.test_delay_button = SurfaceButton(
            buttons,
            theme=THEME,
            fonts=self._font_families,
            text="Test Delay",
            icon_glyph=self._icon_glyph("speed"),
            variant="secondary",
            command=self.test_delay,
        )
        self.test_delay_button.grid(row=0, column=2, padx=(0, 8))

        clear_logs_button = SurfaceButton(
            buttons,
            theme=THEME,
            fonts=self._font_families,
            text="Clear Logs",
            icon_glyph=self._icon_glyph("delete"),
            variant="secondary",
            command=self.clear_logs,
        )
        clear_logs_button.grid(row=0, column=3)

        status_wrap = tk.Frame(section, bg=THEME["shell"])
        status_wrap.grid(row=1, column=1, sticky="e")
        status_wrap.columnconfigure(0, weight=1)

        self._status_detail_label = ttk.Label(status_wrap, textvariable=self.status_var, style="StatusDetail.TLabel")
        self._status_detail_label.grid(row=0, column=0, sticky="w")

        self._relay_chip_frame = tk.Frame(
            status_wrap,
            bg=THEME["low"],
            highlightbackground=THEME["border"],
            highlightthickness=1,
            padx=7,
            pady=3,
        )
        self._relay_chip_frame.grid(row=0, column=1, sticky="w", padx=(12, 0))
        self._relay_chip_dot = tk.Label(
            self._relay_chip_frame,
            text="●",
            bg=THEME["low"],
            fg=THEME["muted"],
            font=(self._font_families["body"], 7, "bold"),
        )
        self._relay_chip_dot.pack(side="left")
        self._relay_chip_label = tk.Label(
            self._relay_chip_frame,
            textvariable=self.relay_chip_var,
            bg=THEME["low"],
            fg=THEME["text"],
            font=(self._font_families["label"], 7, "bold"),
            padx=4,
        )
        self._relay_chip_label.pack(side="left")

    def _build_logs_section(self, parent: ttk.Frame) -> None:
        shell = RoundedPanel(
            parent,
            fill=THEME["card"],
            border=THEME["border"],
            radius=18,
            padding=(16, 16, 16, 16),
        )
        shell.grid(row=4, column=0, sticky="nsew")
        section = shell.content
        section.columnconfigure(0, weight=1)
        section.rowconfigure(1, weight=1)

        header = tk.Frame(section, bg=THEME["low"], height=28)
        header.grid(row=0, column=0, columnspan=2, sticky="ew")
        header.grid_propagate(False)
        tk.Label(
            header,
            text="Relay Logs",
            bg=THEME["low"],
            fg=THEME["muted_alt"],
            font=(self._font_families["label"], 8, "bold"),
            anchor="w",
            padx=14,
        ).pack(side="left", fill="y")
        tk.Label(
            header,
            text="● ● ●",
            bg=THEME["low"],
            fg=THEME["strong"],
            font=(self._font_families["body"], 8),
            padx=12,
        ).pack(side="right", fill="y")

        self.log_text = tk.Text(
            section,
            wrap="none",
            state="disabled",
            font=(self._font_families["mono"], 10),
            background=THEME["log_bg"],
            foreground=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground=THEME["selection"],
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=12,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.tag_configure("delay_error", foreground=THEME["error"])
        self.log_text.tag_configure("delay_success", foreground=THEME["success"])
        self.log_text.tag_configure("log_start", foreground=THEME["accent_text"])
        self.log_text.tag_configure("log_stop", foreground=THEME["warning"])
        self.log_text.tag_configure("log_exit", foreground=THEME["error"])
        self.log_text.tag_configure("log_delay", foreground=THEME["warning"])
        self.log_text.tag_configure("log_meta", foreground=THEME["muted_alt"])
        self.log_text.bind("<Configure>", lambda _event: self.after_idle(self._refresh_log_scrollbars), add="+")

        self._log_scroll_y = log_scroll_y = ttk.Scrollbar(
            section,
            orient="vertical",
            command=self.log_text.yview,
            style="Shell.Vertical.TScrollbar",
        )
        log_scroll_y.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(
            yscrollcommand=lambda first, last, scrollbar=log_scroll_y: self._update_scrollbar_visibility(
                scrollbar,
                first,
                last,
            ),
        )

        self._log_scroll_x = log_scroll_x = ttk.Scrollbar(
            section,
            orient="horizontal",
            command=self.log_text.xview,
            style="Shell.Horizontal.TScrollbar",
        )
        log_scroll_x.grid(row=2, column=0, sticky="ew")
        self.log_text.configure(
            xscrollcommand=lambda first, last, scrollbar=log_scroll_x: self._update_scrollbar_visibility(
                scrollbar,
                first,
                last,
            ),
        )
        shell.refresh()

    def _install_context_menus(self) -> None:
        editor_helpers.install_context_menus(self)

    def _bind_context_menu_classes(self) -> None:
        editor_helpers.bind_context_menu_classes(self)

    def _show_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        return editor_helpers.show_context_menu(self, event)

    def _set_insert_cursor_from_event(self, widget: tk.Misc, event: tk.Event[tk.Misc]) -> None:
        editor_helpers.set_insert_cursor_from_event(widget, event)

    def _widget_is_editable(self, widget: tk.Misc) -> bool:
        return editor_helpers.widget_is_editable(widget)

    def _get_widget_text(self, widget: tk.Misc) -> str:
        return editor_helpers.get_widget_text(widget)

    def _get_selected_text(self, widget: tk.Misc) -> str:
        return editor_helpers.get_selected_text(widget)

    def _context_copy(self) -> None:
        editor_helpers.context_copy(self)

    def _context_cut(self) -> None:
        editor_helpers.context_cut(self)

    def _context_paste(self) -> None:
        editor_helpers.context_paste(self)

    def _context_delete(self) -> None:
        editor_helpers.context_delete(self)

    def _delete_selection(self, widget: tk.Misc) -> None:
        editor_helpers.delete_selection(widget)

    def _context_select_all(self) -> None:
        editor_helpers.context_select_all(self)

    def _copy_selected_profiles(self) -> None:
        profile_helpers.copy_selected_profiles(self)

    def _profile_row_values(self, profile: dict[str, object]) -> tuple[str, ...]:
        return profile_helpers.profile_row_values(self, profile)

    def _profile_row_tags(self, profile_id: str) -> tuple[str, ...]:
        return profile_helpers.profile_row_tags(self, profile_id)

    def _refresh_profile_row(self, profile_id: str) -> None:
        profile_helpers.refresh_profile_row(self, profile_id)

    def _set_profile_delay_state(
        self,
        profile_id: str,
        *,
        delay_text: str = "",
        status_text: str = "",
        status_state: str = "",
    ) -> None:
        profile_helpers.set_profile_delay_state(
            self,
            profile_id,
            delay_text=delay_text,
            status_text=status_text,
            status_state=status_state,
        )

    def _prune_profile_delay_state(self) -> None:
        profile_helpers.prune_profile_delay_state(self)

    def _sort_profiles(self, column: str) -> None:
        profile_helpers.sort_profiles(self, column)

    def _get_profiles_in_display_order(self) -> list[dict[str, object]]:
        return profile_helpers.get_profiles_in_display_order(self)

    def _profile_label(self, profile: dict[str, object]) -> str:
        return profile_helpers.profile_label(profile)

    def _load_profiles_from_config(
        self,
        config: dict[str, object],
        *,
        selected_profile_ids: tuple[str, ...] = (),
    ) -> None:
        profile_helpers.load_profiles_from_config(self, config, selected_profile_ids=selected_profile_ids)

    def _update_profile_selection_state(self) -> None:
        profile_helpers.update_profile_selection_state(self)

    def _on_profile_selection_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        profile_helpers.on_profile_selection_changed(self, _event)

    def _on_profile_double_click(self, event: tk.Event[tk.Misc]) -> str:
        return profile_helpers.on_profile_double_click(self, event)

    def _show_profile_context_menu(self, event: tk.Event[tk.Misc]) -> str:
        return profile_helpers.show_profile_context_menu(self, event)

    def _get_selected_profile_ids(self) -> tuple[str, ...]:
        return profile_helpers.get_selected_profile_ids(self)

    def _sync_profile_action_state(self) -> None:
        profile_helpers.sync_profile_action_state(self)

    def _prepare_profiles_for_delay_test(self, selected_profile_ids: tuple[str, ...]) -> None:
        relay_helpers.prepare_profiles_for_delay_test(self, selected_profile_ids)

    def _build_delay_test_jobs(
        self,
        selected_profile_ids: tuple[str, ...],
    ) -> list[tuple[str, str, dict[str, object]]]:
        return relay_helpers.build_delay_test_jobs(self, selected_profile_ids)

    def _queue_profile_delay_log(self, profile_label: str, message: str) -> None:
        log_helpers.queue_profile_delay_log(self, profile_label, message)

    def _prompt_for_profile(
        self,
        title: str,
        *,
        initial_profile: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        return profile_helpers.prompt_for_profile(self, title, initial_profile=initial_profile)

    def _persist_profile_state(
        self,
        profiles: list[dict[str, object]],
        *,
        active_profile_id: str = "",
        selected_profile_ids: tuple[str, ...] = (),
        log_message: str | None = None,
    ) -> None:
        self._persist_proxy_mode_settings_to_disk(show_errors=False)
        profile_helpers.persist_profile_state(
            self,
            profiles,
            active_profile_id=active_profile_id,
            selected_profile_ids=selected_profile_ids,
            log_message=log_message,
        )

    def _require_single_selected_profile(self, action_name: str) -> str | None:
        return profile_helpers.require_single_selected_profile(self, action_name)

    def _add_profile(self) -> None:
        profile_helpers.add_profile(self)

    def _edit_selected_profile(self) -> None:
        profile_helpers.edit_selected_profile(self)

    def _remove_selected_profiles(self) -> None:
        profile_helpers.remove_selected_profiles(self)

    def _set_selected_profile_active(self) -> None:
        profile_helpers.set_selected_profile_active(self)

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
            self.test_delay_button.set_text("Stop Tests")
            self.test_delay_button.set_command(self.stop_delay_tests)
            self.test_delay_button.state(["!disabled"])
        elif not has_delay_selection:
            self.test_delay_button.set_text("Test Delay")
            self.test_delay_button.set_command(self.test_delay)
            self.test_delay_button.state(["disabled"])
        else:
            self.test_delay_button.set_text("Test Delay")
            self.test_delay_button.set_command(self.test_delay)
            self.test_delay_button.state(["!disabled"])

        self._sync_profile_action_state()

    def _apply_lan_share_bind_host(self, bind_host: str) -> None:
        self.local_proxy_bind_host_var.set(bind_host)
        self.lan_share_enabled_var.set(relay_helpers.is_lan_share_enabled(bind_host))
        self._refresh_lan_share_details()

    def _refresh_lan_share_details(self) -> None:
        bind_host = self.local_proxy_bind_host_var.get().strip() or DEFAULT_LOCAL_PROXY_BIND_HOST
        is_enabled = relay_helpers.is_lan_share_enabled(bind_host)
        endpoint_host = relay_helpers.resolve_lan_share_display_host(
            bind_host,
            self.connect_ip_var.get(),
        )
        proxy_port = self.local_proxy_port_var.get().strip()

        if endpoint_host and proxy_port:
            endpoint_label = f"{endpoint_host}:{proxy_port}"
        elif endpoint_host:
            endpoint_label = endpoint_host
        elif proxy_port:
            endpoint_label = f"LAN address unavailable:{proxy_port}"
        else:
            endpoint_label = "LAN address unavailable"

        self.lan_share_endpoint_var.set(endpoint_label)
        self.lan_share_header_var.set(f"Lan Sharing ({endpoint_label})")

        if self.lan_share_switch is not None:
            if is_enabled:
                self.lan_share_switch.state(["!disabled"])
            else:
                self.lan_share_switch.state(["!disabled"])

    def _on_connect_ip_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._refresh_lan_share_details()

    def _on_lan_share_toggled(self) -> None:
        relay_helpers.handle_lan_share_toggled(self)

    def _is_process_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _update_scrollbar_visibility(
        self,
        scrollbar: ttk.Scrollbar | None,
        first: float | str,
        last: float | str,
    ) -> None:
        if scrollbar is None:
            return

        try:
            first_value = float(first)
            last_value = float(last)
        except (TypeError, ValueError, tk.TclError):
            return

        should_show = (last_value - first_value) < 0.999999
        is_managed = bool(scrollbar.grid_info())
        if should_show:
            if not is_managed:
                scrollbar.grid()
        elif is_managed:
            scrollbar.grid_remove()

        scrollbar.set(first_value, last_value)

    def _refresh_profile_scrollbars(self) -> None:
        profile_tree = getattr(self, "profile_tree", None)
        if profile_tree is None:
            return

        try:
            self._update_scrollbar_visibility(self._profile_scroll_y, *profile_tree.yview())
            self._update_scrollbar_visibility(self._profile_scroll_x, *profile_tree.xview())
        except tk.TclError:
            return

    def _refresh_log_scrollbars(self) -> None:
        log_helpers.refresh_log_scrollbars(self)

    def _append_log(self, message: str, tag: str | None = None) -> None:
        log_helpers.append_log(self, message, tag)

    def clear_logs(self) -> None:
        log_helpers.clear_logs(self)

    def load_form_from_disk(self, *, show_log: bool = False) -> None:
        try:
            config = load_config()
        except Exception as exc:
            messagebox.showerror("Failed To Load Config", str(exc), parent=self)
            return

        self.connect_ip_var.set(str(config.get("CONNECT_IP", "")))
        self.fake_sni_var.set(str(config.get("FAKE_SNI", "")))
        self.connection_mode_var.set(get_connection_mode(config))
        self.local_proxy_bind_host_var.set(get_local_proxy_bind_host(config))
        self.local_proxy_port_var.set(str(get_local_proxy_port(config)))
        self.log_level_var.set(str(config.get("XRAY_LOG_LEVEL", "warning")).strip().lower())
        self.lan_share_enabled_var.set(relay_helpers.is_lan_share_enabled(self.local_proxy_bind_host_var.get()))
        self._refresh_lan_share_details()

        # Load delay test results BEFORE loading profiles so they display correctly
        try:
            delay_results = load_delay_results()
            for profile_id, result in delay_results.items():
                self.profile_delay_values[profile_id] = result.get("delay_value", "")
                self.profile_delay_statuses[profile_id] = result.get("delay_status", "")
                self.profile_delay_states[profile_id] = result.get("delay_state", "")
        except Exception:
            pass

        self._load_profiles_from_config(config)
        self.after_idle(self._refresh_profile_scrollbars)
        if show_log:
            self._append_log("[loaded] config loaded from disk")

    def _persist_proxy_mode_settings_to_disk(self, *, show_errors: bool = False) -> bool:
        try:
            config = load_config()
            config["CONNECTION_MODE"] = normalize_connection_mode(self.connection_mode_var.get())
            config["LOCAL_PROXY_BIND_HOST"] = self.local_proxy_bind_host_var.get().strip() or DEFAULT_LOCAL_PROXY_BIND_HOST
            config["LOCAL_PROXY_PORT"] = self._parse_port_value(
                self.local_proxy_port_var.get(),
                "LOCAL_PROXY_PORT",
            )
            save_config(config)
        except Exception as exc:
            if show_errors:
                messagebox.showerror("Failed To Save Settings", str(exc), parent=self)
            return False
        return True

    def _on_proxy_mode_settings_changed(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        self._persist_proxy_mode_settings_to_disk(show_errors=False)
        self._refresh_lan_share_details()

    def _on_connection_mode_changed(
        self,
        _event: tk.Event[tk.Misc] | None = None,
    ) -> None:
        relay_helpers.handle_connection_mode_changed(self)

    def _parse_port_value(self, raw_value: str, field_name: str) -> int:
        return relay_helpers.parse_port_value(raw_value, field_name)

    def _build_updated_config(
        self,
        *,
        active_profile_id: str | None = None,
        require_active_profile: bool = False,
    ) -> dict[str, object]:
        return relay_helpers.build_updated_config(
            self,
            active_profile_id=active_profile_id,
            require_active_profile=require_active_profile,
        )

    def _cleanup_runtime_config(self) -> None:
        relay_helpers.cleanup_runtime_config(self)

    def _write_runtime_config(self, config: dict[str, object]) -> Path:
        return relay_helpers.write_runtime_config(self, config)

    def _build_headless_command(self) -> list[str]:
        return relay_helpers.build_headless_command(self)

    def start_relay(self) -> None:
        relay_helpers.start_relay(self)

    def test_delay(self) -> None:
        relay_helpers.test_delay(self, self.delay_test_stop_event)

    def stop_delay_tests(self) -> None:
        relay_helpers.stop_delay_tests(self)

    def _run_delay_tests(
        self,
        delay_jobs: list[tuple[str, str, dict[str, object]]],
    ) -> None:
        relay_helpers.run_delay_tests(self, delay_jobs)

    def stop_relay(self) -> None:
        relay_helpers.stop_relay(self)

    def _read_process_output(self, process: subprocess.Popen[str]) -> None:
        relay_helpers.read_process_output(self, process)

    def _monitor_process(self, process: subprocess.Popen[str]) -> None:
        relay_helpers.monitor_process(self, process)

    def _run_taskkill(self, pid: int) -> subprocess.CompletedProcess[str]:
        return relay_helpers.run_taskkill(self, pid)

    def _kill_process_tree(self, pid: int) -> None:
        relay_helpers.kill_process_tree(self, pid)

    def _handle_process_exit(self, process: subprocess.Popen[str], return_code: int) -> None:
        log_helpers.handle_process_exit(self, process, return_code)

    def _queue_worker_log(self, message: str) -> None:
        log_helpers.queue_worker_log(self, message)

    def _handle_delay_started(
        self,
        profile_id: str,
        profile_label: str,
        index: int,
        total: int,
    ) -> None:
        log_helpers.handle_delay_started(self, profile_id, profile_label, index, total)

    def _handle_delay_result(
        self,
        profile_id: str,
        profile_label: str,
        result: DelayTestResult,
        index: int,
        total: int,
    ) -> None:
        log_helpers.handle_delay_result(self, profile_id, profile_label, result, index, total)

    def _handle_delay_error(
        self,
        profile_id: str,
        profile_label: str,
        message: str,
    ) -> None:
        log_helpers.handle_delay_error(self, profile_id, profile_label, message)

    def _handle_delay_finished(self, total_jobs: int) -> None:
        log_helpers.handle_delay_finished(self, total_jobs)

    def _drain_log_queue(self) -> None:
        log_helpers.drain_log_queue(self)

    def _on_close(self) -> None:
        if self.delay_test_in_progress:
            should_close = messagebox.askyesno(
                "Delay Tests Running",
                "Delay tests are still running. Cancel them and close the control panel?",
                parent=self,
            )
            if not should_close:
                return
            self.delay_test_stop_event.set()

        if self._is_process_running() and self.process is not None:
            should_close = messagebox.askyesno(
                "Stop",
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
        self._persist_proxy_mode_settings_to_disk(show_errors=False)
        self._cleanup_runtime_config()
        self.destroy()


def launch_gui() -> None:
    app = ControlPanel()
    app.mainloop()
