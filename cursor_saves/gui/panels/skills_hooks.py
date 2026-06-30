"""Skills & Hooks management tab."""

from __future__ import annotations

import customtkinter as ctk

from ... import skills_hooks
from ..runner import CommandRunner
from ..widgets import confirm_action


def build_skills_hooks(parent, runner: CommandRunner, require_sync_ready) -> None:
    frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    ctk.CTkLabel(
        frame,
        text=(
            "Deleting a skill or hook locally does not remove it from the sync repo. "
            "Use Delete here (or cursaves skills/hooks delete) to remove from the repo."
        ),
        wraplength=700,
        justify="left",
    ).pack(anchor="w", padx=4, pady=(4, 8))

    skills_header = ctk.CTkFrame(frame, fg_color="transparent")
    skills_header.pack(fill="x", pady=(8, 4))
    ctk.CTkLabel(skills_header, text="Skills", font=ctk.CTkFont(weight="bold")).pack(
        side="left", padx=4,
    )
    skills_list_frame = ctk.CTkFrame(frame, fg_color="transparent")
    skills_list_frame.pack(fill="x", pady=4)

    hooks_header = ctk.CTkFrame(frame, fg_color="transparent")
    hooks_header.pack(fill="x", pady=(16, 4))
    ctk.CTkLabel(hooks_header, text="Hooks", font=ctk.CTkFont(weight="bold")).pack(
        side="left", padx=4,
    )
    hooks_list_frame = ctk.CTkFrame(frame, fg_color="transparent")
    hooks_list_frame.pack(fill="x", pady=4)

    def run(args):
        if not require_sync_ready():
            return
        runner.run(CommandRunner.cursaves_argv(*args))

    def delete_skill(name: str):
        if confirm_action("Delete skill", f"Remove skill '{name}' from local and sync repo?"):
            run(["skills", "delete", name, "-y"])

    def delete_hook(name: str):
        if confirm_action("Delete hook", f"Remove hook '{name}' from local and sync repo?"):
            run(["hooks", "delete", name, "-y"])

    def clear_frame(container: ctk.CTkFrame) -> None:
        for child in container.winfo_children():
            child.destroy()

    def render_skills():
        clear_frame(skills_list_frame)
        rows = skills_hooks.list_skills()
        if not rows:
            ctk.CTkLabel(skills_list_frame, text="No skills found.").pack(anchor="w", padx=4)
            return
        for row in rows:
            item = ctk.CTkFrame(skills_list_frame, fg_color="transparent")
            item.pack(fill="x", pady=2)
            ctk.CTkLabel(
                item, text=f"{row['name']}  ({row['state']})", anchor="w", width=400,
            ).pack(side="left", padx=4)
            ctk.CTkButton(
                item,
                text="Delete",
                width=80,
                command=lambda n=row["name"]: delete_skill(n),
            ).pack(side="right", padx=4)

    def render_hooks():
        clear_frame(hooks_list_frame)
        rows = skills_hooks.list_hooks()
        if not rows:
            ctk.CTkLabel(hooks_list_frame, text="No hooks found.").pack(anchor="w", padx=4)
            return
        for row in rows:
            item = ctk.CTkFrame(hooks_list_frame, fg_color="transparent")
            item.pack(fill="x", pady=2)
            label = f"{row['name']}  [{row['kind']}]  ({row['state']})"
            ctk.CTkLabel(item, text=label, anchor="w", width=500).pack(side="left", padx=4)
            ctk.CTkButton(
                item,
                text="Delete",
                width=80,
                command=lambda n=row["name"]: delete_hook(n),
            ).pack(side="right", padx=4)

    def refresh_lists():
        render_skills()
        render_hooks()

    ctk.CTkButton(skills_header, text="Refresh", command=refresh_lists, width=80).pack(
        side="right", padx=4,
    )

    refresh_lists()
    parent._skills_hooks_refresh = refresh_lists  # type: ignore[attr-defined]
