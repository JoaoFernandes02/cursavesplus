"""Info tab."""

from __future__ import annotations

import customtkinter as ctk

from ..runner import CommandRunner
from ..widgets import WorkspaceSelector


def build_info(parent, runner: CommandRunner) -> WorkspaceSelector:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    ws = WorkspaceSelector(frame)

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=4)

    def run(args):
        runner.run(CommandRunner.cursaves_argv(*args))

    def run_ws(base):
        w = ws.get_workspace_arg()
        args = list(base)
        if w:
            args.extend(["-w", w])
        run(args)

    buttons = [
        ("Workspaces", lambda: run(["workspaces"])),
        ("Snapshots", lambda: run(["snapshots"])),
        ("List chats", lambda: run_ws(["list"])),
        ("Status", lambda: run_ws(["status"])),
        ("Reload Cursor", lambda: run(["reload"])),
    ]
    for label, cmd in buttons:
        ctk.CTkButton(btn_frame, text=label, command=cmd, width=130).pack(
            side="left", padx=4, pady=4,
        )

    return ws
