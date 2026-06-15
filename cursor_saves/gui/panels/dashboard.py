"""Dashboard tab."""

from __future__ import annotations

import customtkinter as ctk

from ..runner import CommandRunner
from .. import state


def build_dashboard(parent, runner: CommandRunner, on_go_setup, refresh_status) -> None:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    banner_frame = ctk.CTkFrame(frame)
    banner_frame.pack(fill="x", pady=(0, 8))
    banner_label = ctk.CTkLabel(
        banner_frame,
        text="",
        font=ctk.CTkFont(size=14, weight="bold"),
        wraplength=700,
        justify="left",
    )
    banner_label.pack(anchor="w", padx=12, pady=12)

    stats_frame = ctk.CTkFrame(frame)
    stats_frame.pack(fill="x", pady=8)
    stats_label = ctk.CTkLabel(stats_frame, text="", justify="left")
    stats_label.pack(anchor="w", padx=12, pady=12)

    def refresh_dashboard_ui():
        configured = state.is_configured()
        if configured:
            banner_label.configure(
                text="cursaves is configured. Use Sync now or rely on auto-sync hook.",
                text_color=("gray10", "gray90"),
            )
            stats = state.get_dashboard_stats()
            stats_label.configure(
                text=(
                    f"Workspaces with chats: {stats['workspaces']}\n"
                    f"Snapshot projects: {stats['snapshot_projects']}\n"
                    f"Profile items pending sync: {stats['pending_profile']}"
                ),
            )
        else:
            banner_label.configure(
                text="Not configured — go to the Setup tab to initialize cursaves.",
                text_color=("#b45309", "#fbbf24"),
            )
            stats_label.configure(text="Complete Setup → Init, then Run setup.")

    def refresh_dashboard():
        refresh_dashboard_ui()
        refresh_status()

    def run_cmd(args):
        runner.run(CommandRunner.cursaves_argv(*args))

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=8)

    ctk.CTkButton(
        btn_frame, text="Sync now", command=lambda: run_cmd(["sync"]), width=120,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame, text="Status", command=lambda: run_cmd(["status"]), width=120,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame, text="Refresh info", command=refresh_dashboard, width=120,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame, text="Go to Setup", command=on_go_setup, width=120,
    ).pack(side="left", padx=4)
    ctk.CTkButton(
        btn_frame,
        text="Open watch log",
        command=lambda: state.open_path(state.get_watch_log()),
        width=120,
    ).pack(side="left", padx=4)

    refresh_dashboard_ui()
    parent._dashboard_refresh = refresh_dashboard  # type: ignore[attr-defined]
