"""Reusable GUI widgets."""

from __future__ import annotations

import tkinter.messagebox as messagebox
from typing import Callable, Optional

import customtkinter as ctk

from .. import export, paths


class OutputLog:
    """Thread-safe output log backed by a CTkTextbox."""

    def __init__(self, textbox: ctk.CTkTextbox):
        self._textbox = textbox

    def append(self, text: str) -> None:
        def _do():
            self._textbox.configure(state="normal")
            self._textbox.insert("end", text)
            self._textbox.see("end")
            self._textbox.configure(state="disabled")

        self._textbox.after(0, _do)

    def clear(self) -> None:
        self._textbox.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._textbox.configure(state="disabled")


class WorkspaceSelector:
    """Dropdown of Cursor workspaces (by index for -w)."""

    def __init__(self, parent, label: str = "Workspace"):
        self._workspaces: list[dict] = []
        ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=4, pady=(4, 0))
        self.combo = ctk.CTkComboBox(parent, values=["(refresh to load)"], width=400)
        self.combo.pack(anchor="w", padx=4, pady=4)
        self.refresh()

    def refresh(self) -> None:
        self._workspaces = paths.list_workspaces_with_conversations()
        if not self._workspaces:
            self.combo.configure(values=["(no workspaces)"])
            self.combo.set("(no workspaces)")
            return
        labels = []
        for i, ws in enumerate(self._workspaces, 1):
            path = ws["path"]
            name = path if len(path) <= 45 else "..." + path[-42:]
            host = ws.get("host") or ""
            host_part = f" [{host}]" if host else ""
            labels.append(f"{i}: {name}{host_part}")
        self.combo.configure(values=labels)
        self.combo.set(labels[0])

    def get_workspace_arg(self) -> Optional[str]:
        if not self._workspaces:
            return None
        selection = self.combo.get()
        try:
            index = int(selection.split(":", 1)[0].strip()) - 1
            if 0 <= index < len(self._workspaces):
                return str(index + 1)
        except (ValueError, IndexError):
            pass
        return "1"

    def get_workspace(self) -> Optional[dict]:
        if not self._workspaces:
            return None
        selection = self.combo.get()
        try:
            index = int(selection.split(":", 1)[0].strip()) - 1
            if 0 <= index < len(self._workspaces):
                return self._workspaces[index]
        except (ValueError, IndexError):
            pass
        return self._workspaces[0] if self._workspaces else None


class ChatCheckList(ctk.CTkScrollableFrame):
    """Checkboxes for selecting conversations."""

    def __init__(self, parent, height: int = 160):
        super().__init__(parent, height=height, label_text="Chats")
        self._vars: list[tuple[ctk.BooleanVar, str]] = []

    def load(self, project_path: str, workspace_dir) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._vars.clear()
        convos = export.list_conversations(project_path, workspace_dir=workspace_dir)
        if not convos:
            ctk.CTkLabel(self, text="No conversations").pack(anchor="w")
            return
        for c in convos:
            var = ctk.BooleanVar(value=True)
            name = c["name"]
            if len(name) > 50:
                name = name[:47] + "..."
            cb = ctk.CTkCheckBox(self, text=f"{name} ({c['id'][:8]}...)", variable=var)
            cb.pack(anchor="w", padx=4, pady=2)
            self._vars.append((var, c["id"]))

    def selected_ids(self) -> list[str]:
        return [cid for var, cid in self._vars if var.get()]


def confirm_action(title: str, message: str) -> bool:
    return messagebox.askyesno(title, message)


def warn_cursor_running(action: str, allow_force: bool = True) -> Optional[bool]:
    """Return True to continue, False to cancel, None if cancelled without force."""
    from ..importer import is_cursor_running

    if not is_cursor_running():
        return True
    msg = (
        f"Cursor is running. For safest results, close Cursor before {action}.\n\n"
        "Continue anyway?"
    )
    if allow_force:
        return confirm_action("Cursor is open", msg)
    messagebox.showwarning("Cursor is open", msg + "\n\nCancelled.")
    return False


def make_button_row(parent, buttons: list[tuple[str, Callable]], enabled: bool = True) -> ctk.CTkFrame:
    """Create a row of buttons. Each item is (label, callback)."""
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", padx=8, pady=4)
    for label, callback in buttons:
        btn = ctk.CTkButton(
            frame,
            text=label,
            command=callback,
            width=140,
            state="normal" if enabled else "disabled",
        )
        btn.pack(side="left", padx=4, pady=4)
    return frame
