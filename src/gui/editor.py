from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import style_menu

__all__ = [
    "install_context_menus",
    "bind_context_menu_classes",
    "show_context_menu",
    "set_insert_cursor_from_event",
    "widget_is_editable",
    "get_widget_text",
    "get_selected_text",
    "context_copy",
    "context_cut",
    "context_paste",
    "context_delete",
    "delete_selection",
    "context_select_all",
]


def install_context_menus(panel: tk.Misc) -> None:
    panel._editable_context_menu = tk.Menu(panel, tearoff=False)
    panel._editable_context_menu.add_command(label="Cut", command=panel._context_cut)
    panel._editable_context_menu.add_command(label="Copy", command=panel._context_copy)
    panel._editable_context_menu.add_command(label="Paste", command=panel._context_paste)
    panel._editable_context_menu.add_command(label="Delete", command=panel._context_delete)
    panel._editable_context_menu.add_separator()
    panel._editable_context_menu.add_command(label="Select All", command=panel._context_select_all)

    panel._readonly_context_menu = tk.Menu(panel, tearoff=False)
    panel._readonly_context_menu.add_command(label="Copy", command=panel._context_copy)
    panel._readonly_context_menu.add_separator()
    panel._readonly_context_menu.add_command(label="Select All", command=panel._context_select_all)

    panel._profile_context_menu = tk.Menu(panel, tearoff=False)
    panel._profile_context_menu.add_command(label="Copy", command=panel._copy_selected_profiles)
    panel._profile_context_menu.add_command(label="Paste", command=panel._paste_profiles_from_clipboard)
    panel._profile_context_menu.add_command(label="Remove", command=panel._remove_selected_profiles)
    panel._profile_context_menu.add_command(label="Edit", command=panel._edit_selected_profile)
    panel._profile_context_menu.add_command(label="Set As Active", command=panel._set_selected_profile_active)
    panel._profile_context_menu.add_command(label="Test Delay", command=panel.test_delay)

    style_menu(panel._editable_context_menu)
    style_menu(panel._readonly_context_menu)
    style_menu(panel._profile_context_menu)

    bind_context_menu_classes(panel)
    panel.profile_tree.bind("<Button-3>", panel._show_profile_context_menu, add="+")


def bind_context_menu_classes(panel: tk.Misc) -> None:
    for widget_class in ("Entry", "TEntry", "TCombobox", "Text"):
        panel.bind_class(widget_class, "<Button-3>", panel._show_context_menu, add="+")


def show_context_menu(panel: tk.Misc, event: tk.Event[tk.Misc]) -> str:
    widget = event.widget
    if not isinstance(widget, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text)):
        return ""

    panel._context_menu_target = widget
    widget.focus_set()
    set_insert_cursor_from_event(widget, event)

    has_selection = bool(get_selected_text(widget))
    has_content = bool(get_widget_text(widget))
    editable = widget_is_editable(widget)
    menu = panel._editable_context_menu if editable else panel._readonly_context_menu

    if editable:
        panel._editable_context_menu.entryconfigure(0, state="normal" if has_selection else "disabled")
        panel._editable_context_menu.entryconfigure(1, state="normal" if has_content else "disabled")
        panel._editable_context_menu.entryconfigure(2, state="normal")
        panel._editable_context_menu.entryconfigure(3, state="normal" if has_selection else "disabled")
        panel._editable_context_menu.entryconfigure(5, state="normal" if has_content else "disabled")
    else:
        panel._readonly_context_menu.entryconfigure(0, state="normal" if has_content else "disabled")
        panel._readonly_context_menu.entryconfigure(2, state="normal" if has_content else "disabled")

    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()
    return "break"


def set_insert_cursor_from_event(widget: tk.Misc, event: tk.Event[tk.Misc]) -> None:
    if isinstance(widget, tk.Text):
        if not get_selected_text(widget):
            widget.mark_set("insert", f"@{event.x},{event.y}")
        return

    if not get_selected_text(widget):
        widget.icursor(widget.index(f"@{event.x}"))


def widget_is_editable(widget: tk.Misc) -> bool:
    state = str(widget.cget("state"))
    return state not in {"disabled", "readonly"}


def get_widget_text(widget: tk.Misc) -> str:
    if isinstance(widget, tk.Text):
        return widget.get("1.0", "end-1c")
    return str(widget.get())


def get_selected_text(widget: tk.Misc) -> str:
    if isinstance(widget, tk.Text):
        if not widget.tag_ranges(tk.SEL):
            return ""
        return widget.get("sel.first", "sel.last")

    if not widget.selection_present():
        return ""
    return str(widget.selection_get())


def context_copy(panel: tk.Misc) -> None:
    widget = panel._context_menu_target
    if widget is None:
        return

    text = get_selected_text(widget) or get_widget_text(widget)
    if not text:
        return

    panel.clipboard_clear()
    panel.clipboard_append(text)


def context_cut(panel: tk.Misc) -> None:
    widget = panel._context_menu_target
    if widget is None or not widget_is_editable(widget):
        return

    text = get_selected_text(widget)
    if not text:
        return

    panel.clipboard_clear()
    panel.clipboard_append(text)
    delete_selection(widget)


def context_paste(panel: tk.Misc) -> None:
    widget = panel._context_menu_target
    if widget is None or not widget_is_editable(widget):
        return

    try:
        text = panel.clipboard_get()
    except tk.TclError:
        return

    delete_selection(widget)
    widget.insert("insert", text)


def context_delete(panel: tk.Misc) -> None:
    widget = panel._context_menu_target
    if widget is None or not widget_is_editable(widget):
        return

    delete_selection(widget)


def delete_selection(widget: tk.Misc) -> None:
    if isinstance(widget, tk.Text):
        if widget.tag_ranges(tk.SEL):
            widget.delete("sel.first", "sel.last")
        return

    if widget.selection_present():
        widget.delete("sel.first", "sel.last")


def context_select_all(panel: tk.Misc) -> None:
    widget = panel._context_menu_target
    if widget is None:
        return

    if isinstance(widget, tk.Text):
        widget.tag_add(tk.SEL, "1.0", "end-1c")
        widget.mark_set("insert", "end-1c")
        widget.see("insert")
        return

    widget.select_range(0, "end")
    widget.icursor("end")
