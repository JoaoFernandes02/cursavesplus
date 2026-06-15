"""Profile tab."""

from __future__ import annotations

import customtkinter as ctk

from ..runner import CommandRunner


def build_profile(parent, runner: CommandRunner, is_enabled: callable) -> None:
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    ctk.CTkLabel(
        frame,
        text="Sync global Cursor profile (settings, skills, hooks, commands).",
        wraplength=600,
        justify="left",
    ).pack(anchor="w", padx=4, pady=8)

    btn_frame = ctk.CTkFrame(frame, fg_color="transparent")
    btn_frame.pack(fill="x", pady=4)

    def run(args):
        if not is_enabled():
            return
        runner.run(CommandRunner.cursaves_argv(*args))

    for label, args in [
        ("Profile push", ["profile", "push"]),
        ("Profile pull", ["profile", "pull"]),
        ("Profile status", ["profile", "status"]),
    ]:
        ctk.CTkButton(btn_frame, text=label, command=lambda a=args: run(a), width=140).pack(
            side="left", padx=4, pady=4,
        )
