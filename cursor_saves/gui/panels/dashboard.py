"""Dashboard tab."""

from __future__ import annotations

import customtkinter as ctk

from ...chat_lifecycle import is_chat_sync_enabled
from ..runner import CommandRunner
from .. import state


def build_dashboard(parent, runner: CommandRunner, on_go_setup, refresh_status, require_sync_ready) -> None:
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
        if state.is_sync_ready():
            if is_chat_sync_enabled():
                banner_text = (
                    "cursaves is ready to sync. Use Sync now or rely on auto-sync hook."
                )
            else:
                banner_text = (
                    "cursaves is ready — profile/skills/hooks sync is active. "
                    "Chat sync is disabled (sync.chat_enabled=false)."
                )
            banner_label.configure(
                text=banner_text,
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
        elif state.is_github_logged_in():
            gh = state.get_github_auth()
            login = gh.get("login") or "GitHub"
            banner_label.configure(
                text=f"Logged in as @{login} — go to Setup to choose a sync repository.",
                text_color=("#b45309", "#fbbf24"),
            )
            stats_label.configure(text="Complete Setup → Login with GitHub → choose sync repo.")
        else:
            banner_label.configure(
                text="Not configured — go to Setup → Login with GitHub.",
                text_color=("#b45309", "#fbbf24"),
            )
            stats_label.configure(text="Complete Setup → Login with GitHub, then choose sync repo.")

    def refresh_dashboard():
        refresh_dashboard_ui()
        refresh_status()

    def run_cmd(args):
        if not require_sync_ready():
            return
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
