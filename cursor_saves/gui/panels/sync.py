"""Sync tab."""

from __future__ import annotations

import customtkinter as ctk

from ...chat_lifecycle import is_chat_sync_enabled
from ..runner import CommandRunner
from ..widgets import WorkspaceSelector, warn_cursor_running


def build_sync(parent, runner: CommandRunner, require_sync_ready: callable) -> WorkspaceSelector:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    if not is_chat_sync_enabled():
        ctk.CTkLabel(
            frame,
            text="Chat sync is disabled (sync.chat_enabled=false). Profile sync still runs via Sync.",
            wraplength=600,
            justify="left",
            text_color=("#b45309", "#fbbf24"),
        ).pack(anchor="w", padx=4, pady=(0, 8))

    ws = WorkspaceSelector(frame, label="Workspace (for scoped actions)")

    export_id = ctk.CTkEntry(frame, placeholder_text="Composer ID for export", width=400)
    export_id.pack(anchor="w", padx=4, pady=8)

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=4)

    def run(args):
        if not require_sync_ready():
            return
        runner.run(CommandRunner.cursaves_argv(*args))

    def run_with_ws(base_args):
        w = ws.get_workspace_arg()
        if w:
            run([*base_args, "-w", w])

    def import_all():
        if warn_cursor_running("import") is False:
            return
        w = ws.get_workspace_arg()
        args = ["import", "--all"]
        if w:
            args.extend(["-w", w])
        run(args)

    def pull():
        if warn_cursor_running("pull") is False:
            return
        w = ws.get_workspace_arg()
        args = ["pull"]
        if w:
            args.extend(["-w", w])
        run(args)

    buttons = [
        ("Sync", lambda: run(["sync"])),
        ("Push ahead", lambda: run(["push", "--ahead"])),
        ("Push all", lambda: run_with_ws(["push", "--all"])),
        ("Pull", pull),
        ("Import all", import_all),
        ("Checkpoint", lambda: run_with_ws(["checkpoint"])),
    ]
    for i, (label, cmd) in enumerate(buttons):
        row = i // 3
        col = i % 3
        if col == 0 and i > 0:
            btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
            btn_frame.pack(fill="x", pady=2)
        ctk.CTkButton(btn_frame, text=label, command=cmd, width=130).pack(
            side="left", padx=4, pady=4,
        )

    exp_frame = ctk.CTkFrame(frame, fg_color="transparent")
    exp_frame.pack(fill="x", pady=8)
    ctk.CTkButton(
        exp_frame,
        text="Export by ID",
        command=lambda: run(["export", export_id.get().strip()]) if export_id.get().strip() else None,
        width=130,
    ).pack(side="left", padx=4)

    parent._workspace_selector = ws  # type: ignore[attr-defined]
    return ws
