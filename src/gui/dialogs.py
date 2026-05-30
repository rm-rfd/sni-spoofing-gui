from __future__ import annotations

import tkinter as tk
from typing import Callable
from tkinter import messagebox, simpledialog, ttk

from src.core.config.app_config import build_xray_profile_record, build_xray_profile_records

from .theme import THEME, rtl_line

DONATION_NETWORK_LABEL = "USDT (BEP20):"
DONATION_ADDRESS = "0x6411d42175578CFafadfB6b536A4C97F0f6883Aa"

HOW_TO_RUN_TEXT = """
1. برنامه را با دسترسی Administrator باز کنید.
2. کانفیگ های Xray خود را از طریق دکمه Add در رابط کاربری اضافه کنید.
3. کانفیگ ها را از داخل رابط کاربری تست کنید. اگر یک کانفیگ ناموفق شد، ممکن است لازم باشد چند بار دیگر آن را تست کنید، چون گاهی false negative رخ می دهد و ممکن است کانفیگ در عمل سالم باشد.
4. کانفیگی را که کار می کند انتخاب کنید و روی Set Active بزنید.
5. برای اجرای relay با کانفیگ فعال، روی Start بزنید.

نکته ها:
- هنگام شروع relay، فقط پروفایل فعال استفاده می شود.
- تست Delay معیار مفیدی است، اما همیشه دقیق نیست.
"""

__all__ = [
    "DONATION_NETWORK_LABEL",
    "DONATION_ADDRESS",
    "HOW_TO_RUN_TEXT",
    "ShareUrlDialog",
    "HowToRunDialog",
    "SupportUsDialog",
]


class ShareUrlDialog(simpledialog.Dialog):
    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        initial_url: str = "",
        profile_id: str | None = None,
        allow_multiple: bool = False,
    ) -> None:
        self.initial_url = initial_url
        self.profile_id = profile_id
        self.allow_multiple = allow_multiple
        self.result: dict[str, object] | list[dict[str, object]] | None = None
        super().__init__(parent, title)

    def body(self, master: tk.Misc) -> tk.Widget:
        self.configure(bg=THEME["shell"])
        if isinstance(master, tk.Widget):
            master.configure(background=THEME["shell"])

        container = ttk.Frame(master, style="Section.TFrame", padding=(12, 12, 12, 12))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(1, weight=1)

        ttk.Label(
            container,
            text=(
                "Paste one or more direct vless:// or trojan:// share links. "
                "Each non-empty line becomes a separate profile."
                if self.allow_multiple
                else "Paste a direct vless:// or trojan:// share link."
            ),
            style="Body.TLabel",
            wraplength=620,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

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
            padx=8,
            pady=8,
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
        box = ttk.Frame(self, style="Shell.TFrame", padding=(12, 0, 12, 12))
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)

        buttons = ttk.Frame(box, style="Shell.TFrame")
        buttons.grid(row=0, column=1, sticky="e")

        save_button = ttk.Button(buttons, text="Save", style="Primary.TButton", command=self.ok)
        save_button.grid(row=0, column=0, padx=(0, 6))
        cancel_button = ttk.Button(buttons, text="Cancel", style="Secondary.TButton", command=self.cancel)
        cancel_button.grid(row=0, column=1)
        save_button.focus_set()

        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self) -> bool:
        share_url = self.url_text.get("1.0", "end").strip()
        try:
            if self.allow_multiple:
                self.result = build_xray_profile_records(share_url)
            else:
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

        container = ttk.Frame(master, style="Section.TFrame", padding=(12, 12, 12, 12))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="راهنمای اجرای برنامه",
            style="SectionTitle.TLabel",
            anchor="e",
            justify="right",
            font=("Segoe UI", 14, "bold"),
        ).grid(row=0, column=0, sticky="e", pady=(0, 6))

        instructions_frame = ttk.Frame(container, style="Card.TFrame", padding=(12, 12, 12, 12))
        instructions_frame.grid(row=1, column=0, sticky="ew")
        instructions_frame.columnconfigure(0, weight=1)

        tk.Label(
            instructions_frame,
            text="\n".join(rtl_line(line) for line in HOW_TO_RUN_TEXT.splitlines()),
            font=("Segoe UI", 12),
            justify="right",
            anchor="e",
            wraplength=620,
            bg=THEME["card"],
            fg=THEME["text"],
        ).grid(row=0, column=0, sticky="e")
        return None

    def buttonbox(self) -> None:
        box = ttk.Frame(self, style="Shell.TFrame", padding=(12, 0, 12, 12))
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

        container = ttk.Frame(master, style="Section.TFrame", padding=(12, 12, 12, 12))
        container.grid(row=0, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)

        ttk.Label(
            container,
            text="Support the Project",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

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
            padx=12,
            pady=12,
        ).grid(row=1, column=0, sticky="ew")

        address_wrap = ttk.Frame(container, style="Card.TFrame", padding=(12, 12, 12, 12))
        address_wrap.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        address_wrap.columnconfigure(0, weight=1)

        ttk.Label(address_wrap, text=DONATION_NETWORK_LABEL, style="CardLabel.TLabel").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 6),
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
        box = ttk.Frame(self, style="Shell.TFrame", padding=(12, 0, 12, 12))
        box.pack(fill="x")
        box.columnconfigure(0, weight=1)

        buttons = ttk.Frame(box, style="Shell.TFrame")
        buttons.grid(row=0, column=1, sticky="e")

        copy_button = ttk.Button(buttons, text="Copy Address", style="Primary.TButton", command=self._copy_address)
        copy_button.grid(row=0, column=0, padx=(0, 6))
        close_button = ttk.Button(buttons, text="Close", style="Secondary.TButton", command=self.cancel)
        close_button.grid(row=0, column=1)
        copy_button.focus_set()

        self.bind("<Return>", lambda _event: self._copy_address())
        self.bind("<Escape>", self.cancel)

    def _copy_address(self) -> None:
        self._copy_callback()
        messagebox.showinfo("Support Us", "The USDT (BEP20) address was copied to the clipboard.", parent=self)
