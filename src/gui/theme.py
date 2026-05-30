from __future__ import annotations

import ctypes
import re
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from src.core.config.app_config import get_app_dir, get_asset_path


APP_NAME = "RM SNI Spoofer"
APP_VERSION = "0.0.7"
APP_ROOT = Path(get_app_dir())
APP_ICON_ICO_PATH = get_asset_path("logo.ico")
APP_ICON_PNG_PATH = get_asset_path("logo.png")
APP_FONTS_DIR = get_asset_path("fonts")
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
    "profile_selection": "#2a2c2e",
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

__all__ = [
    "APP_NAME",
    "APP_VERSION",
    "APP_ROOT",
    "APP_ICON_ICO_PATH",
    "APP_ICON_PNG_PATH",
    "APP_FONTS_DIR",
    "WINDOWS_PRIVATE_FONT_FLAG",
    "THEME",
    "ICON_FALLBACK_TEXT",
    "ICON_GLYPHS",
    "iter_private_font_paths",
    "status_prefix_tag",
    "rtl_line",
    "style_menu",
    "configure_styles",
    "configure_window_frame",
]


def iter_private_font_paths() -> list[Path]:
    font_paths: list[Path] = []
    for font_path in (
        APP_FONTS_DIR / "Inter" / "Inter-VariableFont_opsz,wght.ttf",
        APP_FONTS_DIR / "Geist" / "Geist-VariableFont_wght.ttf",
    ):
        if not font_path.is_file():
            continue
        font_paths.append(font_path)
    return font_paths


def status_prefix_tag(message: str) -> str | None:
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


def rtl_line(text: str) -> str:
    if not text:
        return ""
    return f"\u202B{text}\u202C"


def style_menu(menu: tk.Menu) -> None:
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
    style: ttk.Style,
    font_families: dict[str, str],
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
        font=(font_families["body"], 10, "bold"),
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


def configure_styles(window: tk.Misc, font_families: dict[str, str]) -> None:
    style = ttk.Style(window)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    elif "vista" in style.theme_names():
        style.theme_use("vista")

    window.configure(bg=THEME["base_bg"])

    style.configure(
        ".",
        background=THEME["shell"],
        foreground=THEME["text"],
        font=(font_families["body"], 10),
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
        font=(font_families["title"], 20, "bold"),
    )
    style.configure(
        "SidebarTitle.TLabel",
        background=THEME["low"],
        foreground=THEME["accent_text"],
        font=(font_families["body"], 17, "bold"),
    )
    style.configure(
        "SectionTitle.TLabel",
        background=THEME["card"],
        foreground=THEME["text"],
        font=(font_families["headline"], 14, "bold"),
    )
    style.configure(
        "Body.TLabel",
        background=THEME["card"],
        foreground=THEME["text"],
        font=(font_families["body"], 10),
    )
    style.configure(
        "Muted.TLabel",
        background=THEME["card"],
        foreground=THEME["muted"],
        font=(font_families["body"], 9),
    )
    style.configure(
        "SidebarMeta.TLabel",
        background=THEME["low"],
        foreground=THEME["muted_alt"],
        font=(font_families["label"], 8),
    )
    style.configure(
        "CardLabel.TLabel",
        background=THEME["card"],
        foreground=THEME["muted_alt"],
        font=(font_families["label"], 8, "bold"),
    )
    style.configure(
        "StatusDetail.TLabel",
        background=THEME["card"],
        foreground=THEME["muted"],
        font=(font_families["body"], 9),
    )
    style.configure(
        "LanShareValue.TLabel",
        background=THEME["low"],
        foreground=THEME["accent_text"],
        font=(font_families["mono"], 11, "bold"),
    )

    _configure_button_style(
        style,
        font_families,
        "Primary.TButton",
        background=THEME["accent"],
        foreground=THEME["base_bg"],
        bordercolor=THEME["accent"],
        active_background="#ff7d24",
        disabled_background=THEME["strong"],
    )
    _configure_button_style(
        style,
        font_families,
        "Secondary.TButton",
        background=THEME["card"],
        foreground=THEME["text"],
        bordercolor=THEME["border"],
        active_background=THEME["hover"],
        disabled_background=THEME["strong"],
    )
    _configure_button_style(
        style,
        font_families,
        "SidebarAction.TButton",
        background=THEME["low"],
        foreground=THEME["text"],
        bordercolor=THEME["border"],
        active_background=THEME["hover"],
        disabled_background=THEME["strong"],
    )
    _configure_button_style(
        style,
        font_families,
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
        font=(font_families["mono"], 11),
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
        font=(font_families["mono"], 10),
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
        borderwidth=0,
        padding=0,
        bordercolor=THEME["card"],
        lightcolor=THEME["card"],
        darkcolor=THEME["card"],
        rowheight=38,
        relief="flat",
        font=(font_families["body"], 10),
    )
    style.layout(
        "Profiles.Treeview",
        [
            (
                "Treeview.field",
                {
                    "sticky": "nswe",
                    "children": [("Treeview.treearea", {"sticky": "nswe"})],
                },
            )
        ],
    )
    style.map(
        "Profiles.Treeview",
        background=[("selected", THEME["profile_selection"])],
        foreground=[("selected", THEME["text"])],
    )
    style.configure(
        "Profiles.Treeview.Heading",
        background=THEME["card"],
        foreground=THEME["muted_alt"],
        borderwidth=0,
        relief="flat",
        padding=(8, 6),
        font=(font_families["label"], 8, "bold"),
    )
    style.layout(
        "Profiles.Treeview.Heading",
        [
            (
                "Treeheading.cell",
                {
                    "sticky": "nswe",
                    "children": [
                        (
                            "Treeheading.padding",
                            {
                                "sticky": "nswe",
                                "children": [
                                    ("Treeheading.image", {"side": "right", "sticky": ""}),
                                    ("Treeheading.text", {"sticky": "we"}),
                                ],
                            },
                        )
                    ],
                },
            )
        ],
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


def configure_window_frame(window: tk.Tk) -> None:
    if sys.platform != "win32":
        return

    try:
        corner_preference = ctypes.c_int(DWMWCP_ROUND)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            window.winfo_id(),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_preference),
            ctypes.sizeof(corner_preference),
        )
    except Exception:
        return
