from __future__ import annotations

import tkinter as tk
from typing import Any
from tkinter import messagebox

from src.core.config.app_config import (
    get_active_xray_profile,
    get_xray_profiles,
    load_config,
    replace_xray_profiles,
    save_config,
)

from .dialogs import ShareUrlDialog

__all__ = [
    "copy_selected_profiles",
    "profile_row_values",
    "profile_row_tags",
    "refresh_profile_row",
    "sort_profiles",
    "set_profile_delay_state",
    "prune_profile_delay_state",
    "get_profiles_in_display_order",
    "profile_label",
    "load_profiles_from_config",
    "update_profile_selection_state",
    "on_profile_selection_changed",
    "on_profile_double_click",
    "show_profile_context_menu",
    "get_selected_profile_ids",
    "sync_profile_action_state",
    "prompt_for_profile",
    "persist_profile_state",
    "require_single_selected_profile",
    "add_profile",
    "edit_selected_profile",
    "remove_selected_profiles",
    "set_selected_profile_active",
]


SORTABLE_COLUMNS: dict[str, int] = {
    "active": 0,
    "remark": 1,
    "protocol": 2,
    "address": 3,
    "port": 4,
    "transport": 5,
    "security": 6,
    "delay": 7,
    "status": 8,
}


def copy_selected_profiles(panel: Any) -> None:
    profile_urls: list[str] = []
    for profile_id in get_selected_profile_ids(panel):
        profile = panel.xray_profiles.get(profile_id)
        if profile is None:
            continue

        share_url = str(profile.get("url", "")).strip()
        if share_url:
            profile_urls.append(share_url)

    if not profile_urls:
        return

    panel.clipboard_clear()
    panel.clipboard_append("\n".join(profile_urls))


def profile_row_values(panel: Any, profile: dict[str, object]) -> tuple[str, ...]:
    profile_id = str(profile["id"])
    return (
        "●" if profile_id == panel.active_profile_id else "",
        str(profile.get("tag", "")) or "(untitled)",
        str(profile.get("protocol", "")).upper(),
        str(profile.get("address", "")),
        str(profile.get("port", "")),
        str(profile.get("transport", "")),
        str(profile.get("security", "")),
        panel.profile_delay_values.get(profile_id, ""),
        panel.profile_delay_statuses.get(profile_id, ""),
    )


def profile_row_tags(panel: Any, profile_id: str) -> tuple[str, ...]:
    tags: list[str] = []
    if profile_id == panel.active_profile_id:
        tags.append("active_profile")

    status_state = panel.profile_delay_states.get(profile_id, "")
    if status_state:
        tags.append(f"{status_state}_profile")
    return tuple(tags)


def sync_profile_selection_state(panel: Any, selection: tuple[str, ...] | None = None) -> tuple[str, ...]:
    if getattr(panel, "_profile_selection_syncing", False):
        return getattr(panel, "_selected_profile_ids", ())

    panel._profile_selection_syncing = True
    try:
        if selection is None:
            selection = tuple(str(profile_id) for profile_id in panel.profile_tree.selection())

        logical_selection = tuple(
            profile_id for profile_id in selection if profile_id in panel.xray_profiles
        )
        panel._selected_profile_ids = logical_selection

        active_profile_id = panel.active_profile_id
        if active_profile_id and active_profile_id in selection:
            panel.profile_tree.selection_remove(active_profile_id)
        return logical_selection
    finally:
        panel._profile_selection_syncing = False


def set_profile_selection(panel: Any, selection: tuple[str, ...]) -> tuple[str, ...]:
    if getattr(panel, "_profile_selection_syncing", False):
        return getattr(panel, "_selected_profile_ids", ())

    panel._profile_selection_syncing = True
    try:
        logical_selection = tuple(
            profile_id for profile_id in selection if profile_id in panel.xray_profiles
        )
        panel._selected_profile_ids = logical_selection

        tree_selection = tuple(
            profile_id for profile_id in logical_selection if profile_id != panel.active_profile_id
        )
        current_selection = tuple(str(profile_id) for profile_id in panel.profile_tree.selection())

        if tree_selection:
            panel.profile_tree.selection_set(tree_selection)
        elif current_selection:
            panel.profile_tree.selection_remove(current_selection)

        active_profile_id = panel.active_profile_id
        if active_profile_id and active_profile_id in current_selection:
            panel.profile_tree.selection_remove(active_profile_id)
        return logical_selection
    finally:
        panel._profile_selection_syncing = False


def refresh_profile_row(panel: Any, profile_id: str) -> None:
    profile = panel.xray_profiles.get(profile_id)
    if profile is None or not panel.profile_tree.exists(profile_id):
        return

    panel.profile_tree.item(
        profile_id,
        values=profile_row_values(panel, profile),
        tags=profile_row_tags(panel, profile_id),
    )


def _sort_key(panel: Any, profile_id: str, column_index: int):
    """Return a sort-safe key for a profile by column index."""
    profile = panel.xray_profiles.get(profile_id)
    if profile is None:
        return ""

    if column_index == 0:
        # Active column: sort active above inactive
        return ("0" if profile_id == panel.active_profile_id else "1")
    if column_index == 4:
        # Port column: numeric sort
        try:
            return (int(profile.get("port", 0)),)
        except (TypeError, ValueError):
            return (99999,)
    if column_index == 7:
        # Delay column: sort by numeric value (extract ms)
        raw = panel.profile_delay_values.get(profile_id, "")
        if raw.endswith(" ms"):
            try:
                return (float(raw[:-3].strip()),)
            except (TypeError, ValueError):
                return (float("inf"),)
        return (float("inf"),)
    if column_index == 8:
        # Status column: sort consistently
        return panel.profile_delay_statuses.get(profile_id, "")

    values = profile_row_values(panel, profile)
    if column_index < len(values):
        return str(values[column_index]).lower()
    return ""


def sort_profiles(panel: Any, column: str) -> None:
    """Sort the profile tree by *column*. Toggle direction on repeated clicks."""
    column_index = SORTABLE_COLUMNS.get(column)
    if column_index is None:
        return

    reverse = False
    if getattr(panel, "_profile_sort_column", None) == column:
        reverse = not panel._profile_sort_reverse
    panel._profile_sort_column = column
    panel._profile_sort_reverse = reverse

    children = panel.profile_tree.get_children("")
    if not children:
        return

    items = [
        (profile_id, _sort_key(panel, profile_id, column_index))
        for profile_id in children
    ]
    items.sort(key=lambda pair: pair[1], reverse=reverse)

    for index, (profile_id, _) in enumerate(items):
        panel.profile_tree.move(profile_id, "", index)

    # Update heading indicators
    marker = " ▲" if not reverse else " ▼"
    column_labels = {
        "active": "Active",
        "remark": "Remark",
        "protocol": "Type",
        "address": "Address",
        "port": "Port",
        "transport": "Transport",
        "security": "Security",
        "delay": "Delay",
        "status": "Status",
    }
    for col in column_labels:
        label = column_labels[col]
        if col == column:
            label += marker
        panel.profile_tree.heading(col, text=label)


def set_profile_delay_state(
    panel: Any,
    profile_id: str,
    *,
    delay_text: str = "",
    status_text: str = "",
    status_state: str = "",
) -> None:
    if delay_text:
        panel.profile_delay_values[profile_id] = delay_text
    else:
        panel.profile_delay_values.pop(profile_id, None)

    if status_text:
        panel.profile_delay_statuses[profile_id] = status_text
    else:
        panel.profile_delay_statuses.pop(profile_id, None)

    if status_state:
        panel.profile_delay_states[profile_id] = status_state
    else:
        panel.profile_delay_states.pop(profile_id, None)

    refresh_profile_row(panel, profile_id)


def prune_profile_delay_state(panel: Any) -> None:
    valid_profile_ids = set(panel.xray_profiles)
    for mapping in (
        panel.profile_delay_values,
        panel.profile_delay_statuses,
        panel.profile_delay_states,
    ):
        stale_profile_ids = [profile_id for profile_id in mapping if profile_id not in valid_profile_ids]
        for profile_id in stale_profile_ids:
            mapping.pop(profile_id, None)


def get_profiles_in_display_order(panel: Any) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    for profile_id in panel.profile_tree.get_children(""):
        profile = panel.xray_profiles.get(str(profile_id))
        if profile is not None:
            profiles.append(dict(profile))
    return profiles


def profile_label(profile: dict[str, object]) -> str:
    tag = str(profile.get("tag", "")).strip()
    if tag:
        return tag
    protocol = str(profile.get("protocol", "")).upper()
    address = str(profile.get("address", "")).strip()
    return f"{protocol} {address}".strip()


def load_profiles_from_config(
    panel: Any,
    config: dict[str, object],
    *,
    selected_profile_ids: tuple[str, ...] = (),
) -> None:
    profiles = get_xray_profiles(config)
    active_profile = get_active_xray_profile(config)
    panel.xray_profiles = {str(profile["id"]): dict(profile) for profile in profiles}
    panel.active_profile_id = "" if active_profile is None else str(active_profile["id"])
    prune_profile_delay_state(panel)

    panel.profile_tree.delete(*panel.profile_tree.get_children(""))
    for profile in profiles:
        profile_id = str(profile["id"])
        panel.profile_tree.insert(
            "",
            "end",
            iid=profile_id,
            values=profile_row_values(panel, profile),
            tags=profile_row_tags(panel, profile_id),
        )

    resolved_selection = tuple(
        profile_id for profile_id in selected_profile_ids if profile_id in panel.xray_profiles
    )
    if not resolved_selection and panel.active_profile_id in panel.xray_profiles:
        resolved_selection = (panel.active_profile_id,)

    set_profile_selection(panel, resolved_selection)
    focus_target = next(
        (
            profile_id
            for profile_id in resolved_selection
            if profile_id != panel.active_profile_id
        ),
        resolved_selection[0] if resolved_selection else "",
    )
    if focus_target:
        panel.profile_tree.focus(focus_target)
        panel.profile_tree.see(focus_target)

    # Re-apply the current sort column if one was active
    sort_column = getattr(panel, "_profile_sort_column", None)
    if sort_column is not None and sort_column in SORTABLE_COLUMNS:
        sort_profiles(panel, sort_column)

    update_profile_selection_state(panel)


def update_profile_selection_state(panel: Any) -> None:
    selection = get_selected_profile_ids(panel)

    active_profile = panel.xray_profiles.get(panel.active_profile_id)
    if active_profile is None:
        status_text = "No active Xray profile selected."
    else:
        status_text = (
            f"Active profile: {profile_label(active_profile)} "
            f"({str(active_profile.get('protocol', '')).upper()} "
            f"{active_profile.get('address', '')}:{active_profile.get('port', '')})"
        )

    if len(selection) > 1:
        status_text = f"{status_text} | Selected: {len(selection)}"
    panel.profile_status_var.set(status_text)
    panel._sync_button_state()


def on_profile_selection_changed(panel: Any, _event: tk.Event[tk.Misc] | None = None) -> None:
    if getattr(panel, "_profile_selection_syncing", False):
        return

    sync_profile_selection_state(panel)
    update_profile_selection_state(panel)


def on_profile_double_click(panel: Any, event: tk.Event[tk.Misc]) -> str:
    profile_id = panel.profile_tree.identify_row(event.y)
    if not profile_id:
        return ""
    set_profile_selection(panel, (profile_id,))
    panel._edit_selected_profile()
    return "break"


def show_profile_context_menu(panel: Any, event: tk.Event[tk.Misc]) -> str:
    profile_id = str(panel.profile_tree.identify_row(event.y))
    selected_profile_ids = get_selected_profile_ids(panel)

    if profile_id:
        if profile_id not in selected_profile_ids:
            set_profile_selection(panel, (profile_id,))
            selected_profile_ids = (profile_id,)
        panel.profile_tree.focus(profile_id)
        panel.profile_tree.see(profile_id)
        update_profile_selection_state(panel)
    elif not selected_profile_ids:
        return ""

    is_locked = panel._is_process_running() or panel.delay_test_in_progress
    single_profile_selected = len(selected_profile_ids) == 1
    can_set_active = (
        not is_locked
        and single_profile_selected
        and selected_profile_ids[0] != panel.active_profile_id
    )

    panel._profile_context_menu.entryconfigure(0, state="normal")
    panel._profile_context_menu.entryconfigure(1, state="disabled" if is_locked else "normal")
    panel._profile_context_menu.entryconfigure(
        2,
        state="normal" if not is_locked and single_profile_selected else "disabled",
    )
    panel._profile_context_menu.entryconfigure(3, state="normal" if can_set_active else "disabled")
    panel._profile_context_menu.entryconfigure(4, state="disabled" if is_locked else "normal")

    try:
        panel._profile_context_menu.tk_popup(event.x_root, event.y_root)
    finally:
        panel._profile_context_menu.grab_release()
    return "break"


def get_selected_profile_ids(panel: Any) -> tuple[str, ...]:
    selected_profile_ids = getattr(panel, "_selected_profile_ids", ())
    if selected_profile_ids:
        return tuple(
            profile_id
            for profile_id in selected_profile_ids
            if profile_id in panel.xray_profiles
        )

    return tuple(
        str(profile_id)
        for profile_id in panel.profile_tree.selection()
        if str(profile_id) in panel.xray_profiles
    )


def sync_profile_action_state(panel: Any) -> None:
    is_locked = panel._is_process_running() or panel.delay_test_in_progress
    selected_profile_ids = get_selected_profile_ids(panel)
    single_profile_selected = len(selected_profile_ids) == 1

    if is_locked:
        panel.profile_add_button.state(["disabled"])
        panel.profile_edit_button.state(["disabled"])
        panel.profile_remove_button.state(["disabled"])
        panel.profile_set_active_button.state(["disabled"])
        return

    panel.profile_add_button.state(["!disabled"])
    if single_profile_selected:
        panel.profile_edit_button.state(["!disabled"])
    else:
        panel.profile_edit_button.state(["disabled"])

    if selected_profile_ids:
        panel.profile_remove_button.state(["!disabled"])
    else:
        panel.profile_remove_button.state(["disabled"])

    if single_profile_selected and selected_profile_ids[0] != panel.active_profile_id:
        panel.profile_set_active_button.state(["!disabled"])
    else:
        panel.profile_set_active_button.state(["disabled"])


def prompt_for_profile(
    panel: Any,
    title: str,
    *,
    initial_profile: dict[str, object] | None = None,
) -> dict[str, object] | None:
    dialog = ShareUrlDialog(
        panel,
        title,
        initial_url="" if initial_profile is None else str(initial_profile.get("url", "")),
        profile_id=None if initial_profile is None else str(initial_profile["id"]),
    )
    return dialog.result


def persist_profile_state(
    panel: Any,
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
    panel._load_profiles_from_config(
        updated_config,
        selected_profile_ids=selected_profile_ids,
    )
    if log_message:
        panel._append_log(log_message)


def require_single_selected_profile(panel: Any, action_name: str) -> str | None:
    selected_profile_ids = get_selected_profile_ids(panel)
    if not selected_profile_ids:
        messagebox.showinfo(
            "Select A Profile",
            f"Select one profile to {action_name}.",
            parent=panel,
        )
        return None
    if len(selected_profile_ids) != 1:
        messagebox.showinfo(
            "Select One Profile",
            f"Select exactly one profile to {action_name}.",
            parent=panel,
        )
        return None
    return selected_profile_ids[0]


def add_profile(panel: Any) -> None:
    new_profile = prompt_for_profile(panel, "Add Xray Profile")
    if new_profile is None:
        return

    profiles = get_profiles_in_display_order(panel)
    profiles.append(new_profile)
    active_profile_id = panel.active_profile_id or str(new_profile["id"])

    try:
        persist_profile_state(
            panel,
            profiles,
            active_profile_id=active_profile_id,
            selected_profile_ids=(str(new_profile["id"]),),
            log_message=f"[profiles] added {profile_label(new_profile)}",
        )
    except Exception as exc:
        messagebox.showerror("Failed To Save Profiles", str(exc), parent=panel)


def edit_selected_profile(panel: Any) -> None:
    profile_id = require_single_selected_profile(panel, "edit")
    if profile_id is None:
        return

    profile = panel.xray_profiles.get(profile_id)
    if profile is None:
        return

    updated_profile = prompt_for_profile(
        panel,
        "Edit Xray Profile",
        initial_profile=profile,
    )
    if updated_profile is None:
        return

    profiles: list[dict[str, object]] = []
    for existing_profile in get_profiles_in_display_order(panel):
        if str(existing_profile["id"]) == profile_id:
            profiles.append(updated_profile)
        else:
            profiles.append(existing_profile)

    try:
        persist_profile_state(
            panel,
            profiles,
            active_profile_id=panel.active_profile_id,
            selected_profile_ids=(profile_id,),
            log_message=f"[profiles] updated {profile_label(updated_profile)}",
        )
        set_profile_delay_state(panel, profile_id)
    except Exception as exc:
        messagebox.showerror("Failed To Save Profiles", str(exc), parent=panel)


def remove_selected_profiles(panel: Any) -> None:
    selected_profile_ids = get_selected_profile_ids(panel)
    if not selected_profile_ids:
        messagebox.showinfo(
            "Select Profiles",
            "Select one or more profiles to remove.",
            parent=panel,
        )
        return

    should_remove = messagebox.askyesno(
        "Remove Profiles",
        f"Remove {len(selected_profile_ids)} selected profile(s)?",
        parent=panel,
    )
    if not should_remove:
        return

    profiles = [
        profile
        for profile in get_profiles_in_display_order(panel)
        if str(profile["id"]) not in selected_profile_ids
    ]
    remaining_profile_ids = [str(profile["id"]) for profile in profiles]
    active_profile_id = panel.active_profile_id
    if active_profile_id not in remaining_profile_ids:
        active_profile_id = "" if not remaining_profile_ids else remaining_profile_ids[0]

    selected_after_save = () if not active_profile_id else (active_profile_id,)
    try:
        persist_profile_state(
            panel,
            profiles,
            active_profile_id=active_profile_id,
            selected_profile_ids=selected_after_save,
            log_message=f"[profiles] removed {len(selected_profile_ids)} profile(s)",
        )
    except Exception as exc:
        messagebox.showerror("Failed To Save Profiles", str(exc), parent=panel)


def set_selected_profile_active(panel: Any) -> None:
    profile_id = require_single_selected_profile(panel, "set active")
    if profile_id is None:
        return

    profile = panel.xray_profiles.get(profile_id)
    if profile is None:
        return

    try:
        persist_profile_state(
            panel,
            get_profiles_in_display_order(panel),
            active_profile_id=profile_id,
            selected_profile_ids=(profile_id,),
            log_message=f"[profiles] active profile set to {profile_label(profile)}",
        )
    except Exception as exc:
        messagebox.showerror("Failed To Save Profiles", str(exc), parent=panel)
