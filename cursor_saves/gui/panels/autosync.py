"""Auto-sync tab."""

from __future__ import annotations

import customtkinter as ctk

from .. import state
from ..runner import CommandRunner


def build_autosync(parent, runner: CommandRunner) -> None:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    status_label = ctk.CTkLabel(frame, text="", justify="left")
    status_label.pack(anchor="w", padx=4, pady=8)

    def run(args):
        runner.run(CommandRunner.cursaves_argv(*args))

    def open_hooks():
        from ... import paths
        p = paths.get_cursor_dot_dir() / "hooks.json"
        if p.exists():
            state.open_path(p)

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=4)

    ctk.CTkButton(
        btn_frame, text="Install hook", command=lambda: run(["watch", "--install-hook"]), width=140,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame, text="Uninstall hook", command=lambda: run(["watch", "--uninstall-hook"]), width=140,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame, text="Start watch now", command=lambda: run(["watch", "--all", "--detach"]), width=140,
    ).pack(side="left", padx=4)

    btn_frame2 = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame2.pack(fill="x", pady=4)
    ctk.CTkButton(
        btn_frame2,
        text="Open hooks.json",
        command=open_hooks,
        width=140,
    ).pack(side="left", padx=4)

    def refresh():
        from ...watch import is_watch_running
        hook = "installed" if state.hook_is_installed() else "not installed"
        watch = "running" if is_watch_running() else "stopped"
        status_label.configure(
            text=f"Session hook: {hook}\nWatch daemon: {watch}\n\n"
            "Install hook to auto-sync when you open a Cursor session.",
        )

    refresh()
    parent._autosync_refresh = refresh  # type: ignore[attr-defined]
