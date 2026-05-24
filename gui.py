from __future__ import annotations

import base64
import ctypes
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable
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
APP_NAME = "RM SNI Spoofer"
APP_ROOT = Path(get_app_dir())
APP_ICON_ICO_PATH = APP_ROOT / "logo.ico"
APP_ICON_PNG_PATH = APP_ROOT / "logo.png"
APP_FONTS_DIR = APP_ROOT / "fonts"
APP_ICONS_DIR = APP_ROOT / "icons"
WINDOWS_PRIVATE_FONT_FLAG = 0x10

THEME = {
    "base_bg": "#0e0e0e",
    "shell": "#131313",
    "low": "#1c1b1b",
    "card": "#201f1f",
    "hover": "#2a2a2a",
    "strong": "#353534",
    "accent": "#ff6b00",
    "accent_text": "#ffb693",
    "text": "#e5e2e1",
    "muted": "#c8c6c5",
    "muted_alt": "#e2bfb0",
    "border": "#5a4136",
    "input_border": "#333333",
    "selection": "#3a2a21",
    "accent_soft": "#2b1d15",
    "success": "#16a34a",
    "warning": "#d97706",
    "error": "#dc2626",
    "log_bg": "#101010",
}

ICON_FALLBACK_TEXT = {
    "dashboard": "Dashboard",
    "refresh": "Check Updates",
    "volunteer": "Support Us",
    "help": "Help",
    "lan": "LAN",
    "public": "SNI",
    "usb": "Port",
    "bolt": "Start",
    "stop_circle": "Stop",
    "speed": "Test",
    "delete": "Clear",
}

ICON_GLYPHS = {
    "dashboard": "\uf246",
    "refresh": "\ue72c",
    "volunteer": "\ueb51",
    "help": "\ue897",
    "lan": "\ue968",
    "public": "\ue774",
    "usb": "\ue88e",
    "bolt": "\ue945",
    "stop_circle": "\uee95",
    "speed": "\uec4a",
    "delete": "\ue74d",
}

DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWCP_ROUND = 2


class SurfaceButton:
    def __init__(
        self,
        master: tk.Misc,
        *,
        theme: dict[str, str],
        fonts: dict[str, str],
        text: str,
        command: Callable[[], None] | None = None,
        icon_glyph: str = "",
        variant: str = "secondary",
        icon_only: bool = False,
    ) -> None:
        self._theme = theme
        self._fonts = fonts
        self._text = text
        self._command = command
        self._icon_glyph = icon_glyph
        self._variant = variant
        self._icon_only = icon_only
        self._disabled = False
        self._hovered = False

        self._parent_bg = str(master.cget("bg")) if "bg" in master.keys() else theme["shell"]
        self._canvas = tk.Canvas(
            master,
            bd=0,
            highlightthickness=0,
            relief="flat",
            takefocus=1,
            background=self._parent_bg,
            cursor="hand2",
        )
        for sequence in ("<Enter>", "<Leave>", "<Button-1>", "<Return>", "<space>", "<Configure>"):
            handler = {
                "<Enter>": self._on_enter,
                "<Leave>": self._on_leave,
                "<Button-1>": self._invoke,
                "<Return>": self._invoke,
                "<space>": self._invoke,
                "<Configure>": self._redraw,
            }[sequence]
            self._canvas.bind(sequence, handler, add="+")

        self._apply_style()

    def _style_tokens(self) -> dict[str, object]:
        base_styles: dict[str, dict[str, object]] = {
            "primary": {
                "bg": self._theme["accent"],
                "fg": self._theme["base_bg"],
                "border": self._theme["accent"],
                "hover_bg": "#ff8129",
                "hover_fg": self._theme["base_bg"],
                "hover_border": "#ff8129",
                "disabled_bg": self._theme["strong"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["strong"],
                "padx": 14,
                "pady": 6,
                "gap": 8,
                "font_size": 10,
                "icon_size": 12,
                "radius": 11,
                "min_height": 36,
                "min_width": 120,
                "content_anchor": "center",
                "draw_surface": True,
            },
            "secondary": {
                "bg": self._theme["shell"],
                "fg": self._theme["text"],
                "border": self._theme["border"],
                "hover_bg": self._theme["accent_soft"],
                "hover_fg": self._theme["text"],
                "hover_border": self._theme["accent"],
                "disabled_bg": self._theme["shell"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["input_border"],
                "padx": 14,
                "pady": 6,
                "gap": 8,
                "font_size": 10,
                "icon_size": 12,
                "radius": 11,
                "min_height": 36,
                "min_width": 120,
                "content_anchor": "center",
                "draw_surface": True,
            },
            "sidebar_primary": {
                "bg": self._theme["accent"],
                "fg": self._theme["base_bg"],
                "border": self._theme["accent"],
                "hover_bg": "#ff8129",
                "hover_fg": self._theme["base_bg"],
                "hover_border": "#ff8129",
                "disabled_bg": self._theme["strong"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["strong"],
                "padx": 16,
                "pady": 10,
                "gap": 8,
                "font_size": 10,
                "icon_size": 12,
                "radius": 11,
                "min_height": 42,
                "min_width": 0,
                "content_anchor": "center",
                "draw_surface": True,
            },
            "sidebar_outline": {
                "bg": self._theme["low"],
                "fg": self._theme["accent_text"],
                "border": self._theme["accent"],
                "hover_bg": self._theme["accent_soft"],
                "hover_fg": self._theme["accent_text"],
                "hover_border": self._theme["accent"],
                "disabled_bg": self._theme["low"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["input_border"],
                "padx": 16,
                "pady": 10,
                "gap": 8,
                "font_size": 10,
                "icon_size": 12,
                "radius": 11,
                "min_height": 42,
                "min_width": 0,
                "content_anchor": "center",
                "draw_surface": True,
            },
            "nav_active": {
                "bg": self._theme["accent_soft"],
                "fg": self._theme["accent_text"],
                "border": self._theme["accent"],
                "hover_bg": "#362419",
                "hover_fg": self._theme["accent_text"],
                "hover_border": self._theme["accent"],
                "disabled_bg": self._theme["accent_soft"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["accent"],
                "padx": 16,
                "pady": 10,
                "gap": 8,
                "font_size": 10,
                "icon_size": 12,
                "radius": 11,
                "min_height": 42,
                "min_width": 0,
                "content_anchor": "left",
                "draw_surface": True,
            },
            "header_icon": {
                "bg": self._theme["shell"],
                "fg": self._theme["muted_alt"],
                "border": self._theme["shell"],
                "hover_bg": self._theme["shell"],
                "hover_fg": self._theme["accent_text"],
                "hover_border": self._theme["shell"],
                "disabled_bg": self._theme["shell"],
                "disabled_fg": self._theme["muted"],
                "disabled_border": self._theme["shell"],
                "padx": 4,
                "pady": 4,
                "gap": 0,
                "font_size": 10,
                "icon_size": 18,
                "radius": 0,
                "min_height": 24,
                "min_width": 24,
                "content_anchor": "center",
                "draw_surface": False,
            },
        }
        return base_styles[self._variant]

    def _measure(self, style: dict[str, object]) -> tuple[int, int, int, int, int]:
        icon_width = 0
        text_width = 0
        line_height = 0

        icon_font = tkfont.Font(family=self._fonts["icon"], size=int(style["icon_size"]))
        if self._icon_glyph:
            icon_width = icon_font.measure(self._icon_glyph)
            line_height = max(line_height, icon_font.metrics("linespace"))

        show_text = not self._icon_only or not self._icon_glyph
        text_font = tkfont.Font(family=self._fonts["button"], size=int(style["font_size"]), weight="bold")
        if show_text:
            text_width = text_font.measure(self._text)
            line_height = max(line_height, text_font.metrics("linespace"))

        content_width = icon_width + text_width
        if icon_width and text_width:
            content_width += int(style["gap"])

        width = max(int(style["min_width"]), content_width + (int(style["padx"]) * 2))
        height = max(int(style["min_height"]), line_height + (int(style["pady"]) * 2))
        return width, height, icon_width, text_width, line_height

    def _rounded_points(self, x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
        return [
            x1 + radius,
            y1,
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        style = self._style_tokens()
        width_hint, height_hint, icon_width, text_width, _line_height = self._measure(style)
        current_width = max(width_hint, self._canvas.winfo_width())
        current_height = max(height_hint, self._canvas.winfo_height())

        self._canvas.configure(
            width=width_hint,
            height=height_hint,
            bg=self._parent_bg,
            cursor="arrow" if self._disabled else "hand2",
        )
        self._canvas.delete("surface")
        self._canvas.delete("content")

        if bool(style["draw_surface"]):
            radius = float(style["radius"])
            self._canvas.create_polygon(
                self._rounded_points(1, 1, current_width - 1, current_height - 1, radius),
                smooth=True,
                splinesteps=36,
                fill=self._background,
                outline=self._border,
                width=1,
                tags="surface",
            )

        content_width = icon_width + text_width
        if icon_width and text_width:
            content_width += int(style["gap"])

        if style["content_anchor"] == "left":
            x = float(style["padx"])
        else:
            x = max(float(style["padx"]), (current_width - content_width) / 2)

        y = current_height / 2
        if self._icon_glyph:
            self._canvas.create_text(
                x,
                y,
                text=self._icon_glyph,
                fill=self._foreground,
                font=(self._fonts["icon"], int(style["icon_size"])),
                anchor="w",
                tags="content",
            )
            x += icon_width
            if text_width:
                x += int(style["gap"])

        if not self._icon_only or not self._icon_glyph:
            self._canvas.create_text(
                x,
                y,
                text=self._text,
                fill=self._foreground,
                font=(self._fonts["button"], int(style["font_size"]), "bold"),
                anchor="w",
                tags="content",
            )

    def _apply_style(self) -> None:
        style = self._style_tokens()
        if self._disabled:
            self._background = str(style["disabled_bg"])
            self._foreground = str(style["disabled_fg"])
            self._border = str(style["disabled_border"])
        elif self._hovered:
            self._background = str(style["hover_bg"])
            self._foreground = str(style["hover_fg"])
            self._border = str(style["hover_border"])
        else:
            self._background = str(style["bg"])
            self._foreground = str(style["fg"])
            self._border = str(style["border"])

        self._redraw()

    def _on_enter(self, _event: tk.Event[tk.Misc]) -> None:
        if self._disabled:
            return
        self._hovered = True
        self._apply_style()

    def _on_leave(self, _event: tk.Event[tk.Misc]) -> None:
        if self._disabled:
            return
        self._hovered = False
        self._apply_style()

    def _invoke(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self._disabled or self._command is None:
            return "break"
        self._command()
        return "break"

    def state(self, state_specs: list[str]) -> None:
        for state_spec in state_specs:
            if state_spec == "disabled":
                self._disabled = True
            elif state_spec == "!disabled":
                self._disabled = False
        self._hovered = False
        self._apply_style()

    def grid(self, *args: object, **kwargs: object) -> None:
        self._canvas.grid(*args, **kwargs)

    def pack(self, *args: object, **kwargs: object) -> None:
        self._canvas.pack(*args, **kwargs)

    def place(self, *args: object, **kwargs: object) -> None:
        self._canvas.place(*args, **kwargs)


class RoundedPanel:
    def __init__(
        self,
        master: tk.Misc,
        *,
        fill: str,
        border: str,
        radius: int = 18,
        padding: tuple[int, int, int, int] = (16, 16, 16, 16),
        border_width: int = 1,
    ) -> None:
        self._fill = fill
        self._border = border
        self._radius = radius
        self._padding = padding
        self._border_width = border_width

        try:
            self._parent_bg = str(master.cget("bg"))
        except Exception:
            self._parent_bg = THEME["shell"]

        self._canvas = tk.Canvas(
            master,
            bd=0,
            highlightthickness=0,
            relief="flat",
            background=self._parent_bg,
        )
        self._content = tk.Frame(self._canvas, bg=self._fill, bd=0, highlightthickness=0)
        self._window_id = self._canvas.create_window(0, 0, anchor="nw", window=self._content)
        self._canvas.bind("<Configure>", self._redraw, add="+")
        self._content.bind("<Configure>", self._redraw, add="+")
        self._redraw()

    @property
    def content(self) -> tk.Frame:
        return self._content

    def _rounded_points(self, x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
        return [
            x1 + radius,
            y1,
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]

    def _redraw(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        width = max(2, self._canvas.winfo_width())
        pad_left, pad_top, pad_right, pad_bottom = self._padding
        content_height = max(1, self._content.winfo_reqheight())
        desired_height = max(2, content_height + pad_top + pad_bottom)
        if self._canvas.winfo_height() != desired_height:
            self._canvas.configure(height=desired_height)
        height = max(2, self._canvas.winfo_height())
        content_width = max(1, width - pad_left - pad_right)
        content_height = max(1, height - pad_top - pad_bottom)

        self._canvas.delete("surface")
        self._canvas.create_polygon(
            self._rounded_points(1, 1, width - 1, height - 1, float(self._radius)),
            smooth=True,
            splinesteps=36,
            fill=self._fill,
            outline=self._border,
            width=self._border_width,
            tags="surface",
        )
        self._canvas.coords(self._window_id, pad_left, pad_top)
        self._canvas.itemconfigure(self._window_id, width=content_width, height=content_height)

    def refresh(self) -> None:
        self._canvas.update_idletasks()
        self._redraw()

    def grid(self, *args: object, **kwargs: object) -> None:
        self._canvas.grid(*args, **kwargs)

    def pack(self, *args: object, **kwargs: object) -> None:
        self._canvas.pack(*args, **kwargs)

    def place(self, *args: object, **kwargs: object) -> None:
        self._canvas.place(*args, **kwargs)


def _iter_private_font_paths() -> list[Path]:
    font_paths: list[Path] = []
    for font_dir in (
        APP_FONTS_DIR / "Inter" / "static",
        APP_FONTS_DIR / "Geist" / "static",
    ):
        if not font_dir.is_dir():
            continue
        font_paths.extend(sorted(font_dir.glob("*.ttf")))
    return font_paths


def _status_prefix_tag(message: str) -> str | None:
    match = re.match(r"^(\[[^\]]+\])", message)
    if match is None:
        return None

    prefix = match.group(1).lower()
    return {
        "[start]": "log_start",
        "[stop]": "log_stop",
        "[exit]": "log_exit",
        "[delay]": "log_delay",
        "[pid]": "log_meta",
        "[profiles]": "log_meta",
        "[loaded]": "log_meta",
        "[support]": "log_meta",
        "[updates]": "log_meta",
    }.get(prefix)


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
        self.configure(bg=THEME["shell"])
        if isinstance(master, tk.Widget):
            master.configure(background=THEME["shell"])

        container = ttk.Frame(master, style="Section.TFrame", padding=(16, 16, 16, 16))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(
            container,
            text="Paste a direct vless:// or trojan:// share link.",
            style="Body.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        self.url_text = tk.Text(
            container,
            width=92,
            height=6,
            wrap="word",
            font=("Consolas", 10),
            relief="flat",
            borderwidth=0,
            background=THEME["log_bg"],
            foreground=THEME["text"],
            insertbackground=THEME["text"],
            selectbackground=THEME["selection"],
            padx=12,
            pady=12,
        )
        self.url_text.grid(row=1, column=0, sticky="nsew")
        self.url_text.insert("1.0", self.initial_url)

        scrollbar = ttk.Scrollbar(
            container,
            orient="vertical",
            command=self.url_text.yview,
            style="Shell.Vertical.TScrollbar",
        )
        scrollbar.grid(row=1, column=1, sticky="ns")
        self.url_text.configure(yscrollcommand=scrollbar.set)
        return self.url_text

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Shell.TFrame", padding=(16, 0, 16, 16))
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)

        buttons = ttk.Frame(box, style="Shell.TFrame")
        buttons.grid(row=0, column=1, sticky="e")

        save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=self.ok)
        save_button.grid(row=0, column=0, padx=(0, 8))
        cancel_button = ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=self.cancel)
        cancel_button.grid(row=0, column=1)
        save_button.focus_set()

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

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
        self.configure(bg=THEME["shell"])
        if isinstance(master, tk.Widget):
            master.configure(background=THEME["shell"])

        container = ttk.Frame(master, style="Section.TFrame", padding=(16, 16, 16, 16))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="راهنمای اجرای برنامه",
            style="SectionTitle.TLabel",
            anchor="e",
            justify="right",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="e", pady=(0, 8))

        instructions_frame = ttk.Frame(container, style="Card.TFrame", padding=(16, 16, 16, 16))
        instructions_frame.grid(row=1, column=0, sticky="ew")
        instructions_frame.columnconfigure(0, weight=1)

        tk.Label(
            instructions_frame,
            text="\n".join(_rtl_line(line) for line in HOW_TO_RUN_TEXT.splitlines()),
            font=("Segoe UI", 12),
            justify="right",
            anchor="e",
            wraplength=620,
            bg=THEME["card"],
            fg=THEME["text"],
        ).grid(row=0, column=0, sticky="e")
        return None

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Shell.TFrame", padding=(16, 0, 16, 16))
        box.pack(fill="x")

        close_button = ttk.Button(box, text="Close", style="Secondary.TButton", command=self.cancel)
        close_button.pack(anchor="e")
        close_button.focus_set()
        self.bind("<Return>", self.cancel)
        self.bind("<Escape>", self.cancel)


class SupportUsDialog(simpledialog.Dialog):
    def __init__(self, parent: tk.Misc, title: str, *, copy_callback: Callable[[], None]) -> None:
        self._copy_callback = copy_callback
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        self.configure(bg=THEME["shell"])
        if isinstance(master, tk.Widget):
            master.configure(background=THEME["shell"])

        container = ttk.Frame(master, style="Section.TFrame", padding=(16, 16, 16, 16))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="Support the Project",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 10))

        message = (
            "If RM SNI Spoofer helps you, you can support continued maintenance "
            "by sending USDT on BEP20 to the address below."
        )
        tk.Label(
            container,
            text=message,
            bg=THEME["card"],
            fg=THEME["text"],
            font=("Segoe UI", 10),
            justify="left",
            wraplength=520,
            padx=16,
            pady=16,
        ).grid(row=1, column=0, sticky="ew")

        address_wrap = ttk.Frame(container, style="Card.TFrame", padding=(16, 16, 16, 16))
        address_wrap.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        address_wrap.columnconfigure(0, weight=1)

        ttk.Label(address_wrap, text=DONATION_NETWORK_LABEL, style="CardLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 8),
        )
        self._address_var = tk.StringVar(value=DONATION_ADDRESS)
        address_entry = ttk.Entry(
            address_wrap,
            textvariable=self._address_var,
            state="readonly",
            style="Card.TEntry",
        )
        address_entry.grid(row=1, column=0, sticky="ew")
        return address_entry

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Shell.TFrame", padding=(16, 0, 16, 16))
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)

        buttons = ttk.Frame(box, style="Shell.TFrame")
        buttons.grid(row=0, column=1, sticky="e")

        copy_button = ttk.Button(buttons, text="Copy Address", style="Primary.TButton", command=self._copy_address)
        copy_button.grid(row=0, column=0, padx=(0, 8))
        close_button = ttk.Button(buttons, text="Close", style="Secondary.TButton", command=self.cancel)
        close_button.grid(row=0, column=1)
        copy_button.focus_set()

        self.bind("<Return>", lambda _event: self._copy_address())
        self.bind("<Escape>", self.cancel)

    def _copy_address(self) -> None:
        self._copy_callback()
        messagebox.showinfo("Support Us", "The USDT (BEP20) address was copied to the clipboard.", parent=self)


class ControlPanel(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1240x840")
        self.minsize(1080, 720)
        self._window_icon: tk.PhotoImage | None = None
        self._icon_cache: dict[str, tk.PhotoImage | None] = {}
        self._private_font_paths: list[Path] = []
        self._font_families: dict[str, str] = {}
        self._relay_chip_frame: tk.Frame | None = None
        self._relay_chip_dot: tk.Label | None = None
        self._relay_chip_label: tk.Label | None = None
        self._status_detail_label: ttk.Label | None = None

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
        self.relay_chip_var = tk.StringVar(value="Stopped")
        self._context_menu_target: tk.Misc | None = None

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
                ("Inter 18pt", "Inter 24pt", "Inter"),
                ("Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "headline": self._resolve_font_family(
                ("Inter 24pt SemiBold", "Inter 24pt Medium", "Inter 24pt", "Inter 18pt SemiBold"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "title": self._resolve_font_family(
                ("Inter 28pt SemiBold", "Inter 28pt Medium", "Inter 28pt", "Inter 24pt SemiBold"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "label": self._resolve_font_family(
                ("Geist Medium", "Geist SemiBold", "Geist"),
                ("Segoe UI Semibold", "Segoe UI", "Arial", "TkDefaultFont"),
            ),
            "button": self._resolve_font_family(
                ("Inter 18pt Medium", "Inter 18pt SemiBold", "Inter 18pt", "Inter"),
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

    def _load_icon_image(self, icon_name: str, *, size: int = 16) -> tk.PhotoImage | None:
        cache_key = f"{icon_name}:{size}"
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        icon_path = APP_ICONS_DIR / f"{icon_name}.svg"
        image: tk.PhotoImage | None = None
        if icon_path.is_file():
            try:
                image = tk.PhotoImage(file=str(icon_path))
            except tk.TclError:
                try:
                    import cairosvg  # type: ignore
                except Exception:
                    image = None
                else:
                    try:
                        png_bytes = cairosvg.svg2png(
                            url=str(icon_path),
                            output_width=size,
                            output_height=size,
                        )
                        image = tk.PhotoImage(data=base64.b64encode(png_bytes).decode("ascii"))
                    except Exception:
                        image = None

        self._icon_cache[cache_key] = image
        return image

    def _icon_glyph(self, icon_name: str) -> str:
        return ICON_GLYPHS.get(icon_name, "")

    def _decorate_button(self, button: ttk.Button, text: str, icon_name: str | None = None) -> None:
        button.configure(text=text)
        if icon_name is None:
            return

        image = self._load_icon_image(icon_name)
        if image is None:
            return

        button.configure(image=image, compound="left")
        button.image = image

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

        image = self._load_icon_image(icon_name)
        if image is not None:
            badge = tk.Label(parent, image=image, bg=THEME["card"])
            badge.image = image
            return badge

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
        menu.configure(
            background=THEME["low"],
            foreground=THEME["text"],
            activebackground=THEME["accent_soft"],
            activeforeground=THEME["text"],
            disabledforeground=THEME["muted"],
            relief="flat",
            borderwidth=1,
        )

    def _configure_button_style(
        self,
        style: ttk.Style,
        style_name: str,
        *,
        background: str,
        foreground: str,
        bordercolor: str,
        active_background: str,
        disabled_background: str,
    ) -> None:
        style.configure(
            style_name,
            background=background,
            foreground=foreground,
            bordercolor=bordercolor,
            lightcolor=bordercolor,
            darkcolor=bordercolor,
            padding=(14, 9),
            relief="flat",
            focusthickness=0,
            font=(self._font_families["body"], 10, "bold"),
        )
        style.map(
            style_name,
            background=[
                ("disabled", disabled_background),
                ("pressed", active_background),
                ("active", active_background),
            ],
            foreground=[("disabled", THEME["muted"])],
            bordercolor=[("active", THEME["accent"]), ("focus", THEME["accent"])],
        )

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        elif "vista" in style.theme_names():
            style.theme_use("vista")

        self.configure(bg=THEME["base_bg"])

        style.configure(
            ".",
            background=THEME["shell"],
            foreground=THEME["text"],
            font=(self._font_families["body"], 10),
        )
        style.configure("TFrame", background=THEME["shell"])
        style.configure("Shell.TFrame", background=THEME["shell"])
        style.configure("Sidebar.TFrame", background=THEME["low"])
        style.configure("Main.TFrame", background=THEME["shell"])
        style.configure("Section.TFrame", background=THEME["card"])
        style.configure("Card.TFrame", background=THEME["card"])
        style.configure("CardInner.TFrame", background=THEME["low"])

        style.configure(
            "AppTitle.TLabel",
            background=THEME["shell"],
            foreground=THEME["accent_text"],
            font=(self._font_families["title"], 20, "bold"),
        )
        style.configure(
            "SidebarTitle.TLabel",
            background=THEME["low"],
            foreground=THEME["accent_text"],
            font=(self._font_families["body"], 17, "bold"),
        )
        style.configure(
            "SectionTitle.TLabel",
            background=THEME["card"],
            foreground=THEME["text"],
            font=(self._font_families["headline"], 14, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background=THEME["card"],
            foreground=THEME["text"],
            font=(self._font_families["body"], 10),
        )
        style.configure(
            "Muted.TLabel",
            background=THEME["card"],
            foreground=THEME["muted"],
            font=(self._font_families["body"], 9),
        )
        style.configure(
            "SidebarMeta.TLabel",
            background=THEME["low"],
            foreground=THEME["muted_alt"],
            font=(self._font_families["label"], 8),
        )
        style.configure(
            "CardLabel.TLabel",
            background=THEME["card"],
            foreground=THEME["muted_alt"],
            font=(self._font_families["label"], 8, "bold"),
        )
        style.configure(
            "StatusDetail.TLabel",
            background=THEME["card"],
            foreground=THEME["muted"],
            font=(self._font_families["body"], 9),
        )

        self._configure_button_style(
            style,
            "Primary.TButton",
            background=THEME["accent"],
            foreground=THEME["base_bg"],
            bordercolor=THEME["accent"],
            active_background="#ff7d24",
            disabled_background=THEME["strong"],
        )
        self._configure_button_style(
            style,
            "Secondary.TButton",
            background=THEME["card"],
            foreground=THEME["text"],
            bordercolor=THEME["border"],
            active_background=THEME["hover"],
            disabled_background=THEME["strong"],
        )
        self._configure_button_style(
            style,
            "SidebarAction.TButton",
            background=THEME["low"],
            foreground=THEME["text"],
            bordercolor=THEME["border"],
            active_background=THEME["hover"],
            disabled_background=THEME["strong"],
        )
        self._configure_button_style(
            style,
            "NavActive.TButton",
            background=THEME["accent_soft"],
            foreground=THEME["accent_text"],
            bordercolor=THEME["accent"],
            active_background="#38251b",
            disabled_background=THEME["accent_soft"],
        )

        style.configure(
            "Card.TEntry",
            foreground=THEME["text"],
            fieldbackground=THEME["low"],
            background=THEME["low"],
            bordercolor=THEME["input_border"],
            lightcolor=THEME["input_border"],
            darkcolor=THEME["input_border"],
            insertcolor=THEME["text"],
            padding=(10, 7),
            relief="flat",
            font=(self._font_families["mono"], 11),
        )
        style.map(
            "Card.TEntry",
            bordercolor=[("focus", THEME["accent"]), ("disabled", THEME["input_border"])],
            lightcolor=[("focus", THEME["accent"])],
            darkcolor=[("focus", THEME["accent"])],
            fieldbackground=[("readonly", THEME["low"]), ("disabled", THEME["low"])],
        )
        style.configure(
            "Card.TCombobox",
            foreground=THEME["text"],
            fieldbackground=THEME["low"],
            background=THEME["low"],
            bordercolor=THEME["input_border"],
            lightcolor=THEME["input_border"],
            darkcolor=THEME["input_border"],
            arrowcolor=THEME["accent_text"],
            padding=(10, 7),
            relief="flat",
            font=(self._font_families["mono"], 10),
        )
        style.map(
            "Card.TCombobox",
            bordercolor=[("focus", THEME["accent"]), ("readonly", THEME["input_border"])],
            lightcolor=[("focus", THEME["accent"])],
            darkcolor=[("focus", THEME["accent"])],
            fieldbackground=[("readonly", THEME["low"]), ("disabled", THEME["low"])],
            selectbackground=[("readonly", THEME["low"])],
            selectforeground=[("readonly", THEME["text"])],
        )

        style.configure(
            "Profiles.Treeview",
            background=THEME["card"],
            fieldbackground=THEME["card"],
            foreground=THEME["text"],
            bordercolor=THEME["input_border"],
            lightcolor=THEME["input_border"],
            darkcolor=THEME["input_border"],
            rowheight=38,
            relief="flat",
            font=(self._font_families["body"], 10),
        )
        style.map(
            "Profiles.Treeview",
            background=[("selected", THEME["selection"])],
            foreground=[("selected", THEME["text"])],
        )
        style.configure(
            "Profiles.Treeview.Heading",
            background=THEME["card"],
            foreground=THEME["muted_alt"],
            relief="flat",
            padding=(8, 6),
            font=(self._font_families["label"], 8, "bold"),
        )
        style.map(
            "Profiles.Treeview.Heading",
            background=[("active", THEME["card"])],
            foreground=[("active", THEME["text"])],
        )

        style.configure(
            "Shell.Vertical.TScrollbar",
            background=THEME["card"],
            troughcolor=THEME["base_bg"],
            bordercolor=THEME["base_bg"],
            arrowcolor=THEME["muted"],
            relief="flat",
            arrowsize=8,
            width=8,
        )
        style.configure(
            "Shell.Horizontal.TScrollbar",
            background=THEME["card"],
            troughcolor=THEME["base_bg"],
            bordercolor=THEME["base_bg"],
            arrowcolor=THEME["muted"],
            relief="flat",
            arrowsize=8,
            width=8,
        )

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
        if sys.platform != "win32":
            return

        try:
            corner_preference = ctypes.c_int(DWMWCP_ROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                self.winfo_id(),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(corner_preference),
                ctypes.sizeof(corner_preference),
            )
        except Exception:
            return

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


        tk.Label(
            brand,
            text=self._runtime_label(),
            bg=THEME["low"],
            fg=THEME["muted_alt"],
            font=(self._font_families["label"], 8),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

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

        # help_button = tk.Label(
        #     footer,
        #     text=self._icon_glyph("help"),
        #     bg=THEME["low"],
        #     fg=THEME["muted"],
        #     font=(self._font_families["icon"], 18),
        #     cursor="hand2",
        #     padx=2,
        # )
        # help_button.grid(row=0, column=0, sticky="w", pady=(0, 8))
        # help_button.bind("<Button-1>", lambda _event: self._show_how_to_run_dialog(), add="+")
        # help_button.bind("<Enter>", lambda _event: help_button.configure(fg=THEME["accent_text"]), add="+")
        # help_button.bind("<Leave>", lambda _event: help_button.configure(fg=THEME["muted"]), add="+")

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
        for column in range(4):
            section.columnconfigure(column, weight=1)

        header = ttk.Frame(section, style="Section.TFrame")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text="Editable Settings", style="SectionTitle.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
        )

        log_level_wrap = ttk.Frame(header, style="Section.TFrame")
        log_level_wrap.grid(row=0, column=1, sticky="e")
        ttk.Label(log_level_wrap, text="XRAY LOG LEVEL", style="CardLabel.TLabel").grid(
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

        self._build_settings_card(section, 1, 0, "CONNECT IP", self.connect_ip_var, "lan")
        self._build_settings_card(section, 1, 1, "FAKE SNI", self.fake_sni_var, "public")
        self._build_settings_card(section, 1, 2, "SOCKS PORT", self.socks_port_var, "usb")
        self._build_settings_card(section, 1, 3, "HTTP PORT", self.http_port_var, "usb")
        shell.refresh()

    def _build_settings_card(
        self,
        parent: ttk.Frame,
        row: int,
        column: int,
        label_text: str,
        variable: tk.StringVar,
        icon_name: str,
    ) -> None:
        card = RoundedPanel(
            parent,
            fill=THEME["card"],
            border=THEME["border"],
            radius=14,
            padding=(12, 10, 12, 10),
        )
        left_pad = 0 if column == 0 else 8
        right_pad = 0 if column == 3 else 8
        card.grid(row=row, column=column, sticky="ew", padx=(left_pad, right_pad), pady=4)
        card.content.columnconfigure(0, weight=1)

        top = tk.Frame(card.content, bg=THEME["card"])
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(0, weight=1)

        ttk.Label(top, text=label_text, style="CardLabel.TLabel").grid(row=0, column=0, sticky="w")
        badge = self._build_icon_badge(top, icon_name)
        badge.grid(row=0, column=1, sticky="e")
        ttk.Entry(card.content, textvariable=variable, style="Card.TEntry").grid(row=1, column=0, sticky="ew", pady=(10, 0))
        card.refresh()

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

        table_frame = ttk.Frame(section, style="Section.TFrame")
        table_frame.grid(row=1, column=0, sticky="nsew")
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
        self.profile_tree.heading("active", text="Active")
        self.profile_tree.heading("remark", text="Remark")
        self.profile_tree.heading("protocol", text="Type")
        self.profile_tree.heading("address", text="Address")
        self.profile_tree.heading("port", text="Port")
        self.profile_tree.heading("transport", text="Transport")
        self.profile_tree.heading("security", text="Security")
        self.profile_tree.heading("delay", text="Delay")
        self.profile_tree.heading("status", text="Status")
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

        profile_scroll_y = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.profile_tree.yview,
            style="Shell.Vertical.TScrollbar",
        )
        profile_scroll_y.grid(row=0, column=1, sticky="ns")
        self.profile_tree.configure(yscrollcommand=profile_scroll_y.set)

        profile_scroll_x = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.profile_tree.xview,
            style="Shell.Horizontal.TScrollbar",
        )
        profile_scroll_x.grid(row=1, column=0, sticky="ew")
        self.profile_tree.configure(xscrollcommand=profile_scroll_x.set)

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
            text="Start Relay",
            icon_glyph=self._icon_glyph("bolt"),
            variant="primary",
            command=self.start_relay,
        )
        self.start_button.grid(row=0, column=0, padx=(0, 8))

        self.stop_button = SurfaceButton(
            buttons,
            theme=THEME,
            fonts=self._font_families,
            text="Stop Relay",
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

        log_scroll_y = ttk.Scrollbar(
            section,
            orient="vertical",
            command=self.log_text.yview,
            style="Shell.Vertical.TScrollbar",
        )
        log_scroll_y.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll_y.set)

        log_scroll_x = ttk.Scrollbar(
            section,
            orient="horizontal",
            command=self.log_text.xview,
            style="Shell.Horizontal.TScrollbar",
        )
        log_scroll_x.grid(row=2, column=0, sticky="ew")
        self.log_text.configure(xscrollcommand=log_scroll_x.set)
        shell.refresh()

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

        self._style_menu(self._editable_context_menu)
        self._style_menu(self._readonly_context_menu)
        self._style_menu(self._profile_context_menu)

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
            "●" if profile_id == self.active_profile_id else "",
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
        if tag is not None:
            self.log_text.insert("end", f"{message}\n", tag)
        elif not message:
            self.log_text.insert("end", "\n")
        else:
            prefix_tag = _status_prefix_tag(message)
            if prefix_tag is None:
                self.log_text.insert("end", f"{message}\n")
            else:
                match = re.match(r"^(\[[^\]]+\])(.*)$", message)
                if match is None:
                    self.log_text.insert("end", f"{message}\n")
                else:
                    self.log_text.insert("end", match.group(1), prefix_tag)
                    self.log_text.insert("end", f"{match.group(2)}\n")
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