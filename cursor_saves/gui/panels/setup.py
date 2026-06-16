"""Setup / first-run tab."""

from __future__ import annotations

import customtkinter as ctk

from .. import state
from ..runner import CommandRunner
from ..shortcut import create_desktop_shortcut


def build_setup(parent, runner: CommandRunner, on_configured) -> None:
    frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    status_label = ctk.CTkLabel(frame, text="", justify="left")
    status_label.pack(anchor="w", padx=4, pady=8)

    ctk.CTkLabel(frame, text="Initialize sync repo", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(8, 4),
    )

    remote_entry = ctk.CTkEntry(frame, placeholder_text="Git remote URL (optional)", width=450)
    remote_entry.pack(anchor="w", padx=4, pady=4)

    backend_var = ctk.StringVar(value="git")
    ctk.CTkOptionMenu(frame, values=["git", "s3"], variable=backend_var, width=120).pack(
        anchor="w", padx=4, pady=4,
    )

    bucket_entry = ctk.CTkEntry(frame, placeholder_text="S3 bucket (if backend=s3)", width=450)
    bucket_entry.pack(anchor="w", padx=4, pady=4)

    def run_init():
        args = ["init", "--backend", backend_var.get()]
        remote = remote_entry.get().strip()
        if remote:
            args.extend(["--remote", remote])
        bucket = bucket_entry.get().strip()
        if bucket:
            args.extend(["--bucket", bucket])
        runner.run(CommandRunner.cursaves_argv(*args))

    ctk.CTkButton(frame, text="Init", command=run_init, width=120).pack(anchor="w", padx=4, pady=8)

    ctk.CTkLabel(frame, text="Run full setup", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )

    setup_remote = ctk.CTkEntry(frame, placeholder_text="Git remote URL", width=450)
    setup_remote.pack(anchor="w", padx=4, pady=4)

    profile_var = ctk.BooleanVar(value=True)
    initial_sync_var = ctk.BooleanVar(value=True)
    auto_watch_var = ctk.BooleanVar(value=True)
    ctk.CTkCheckBox(frame, text="Profile sync", variable=profile_var).pack(anchor="w", padx=4)
    ctk.CTkCheckBox(frame, text="Initial sync", variable=initial_sync_var).pack(anchor="w", padx=4)
    ctk.CTkCheckBox(frame, text="Install auto-sync hook", variable=auto_watch_var).pack(anchor="w", padx=4)

    def run_setup():
        remote = setup_remote.get().strip()
        args = ["setup", "--yes"]
        if remote:
            args.extend(["--remote", remote])
        if not initial_sync_var.get():
            args.append("--no-sync")
        if not auto_watch_var.get():
            args.append("--no-watch")
        runner.run(CommandRunner.cursaves_argv(*args))

    ctk.CTkButton(frame, text="Run setup", command=run_setup, width=120).pack(anchor="w", padx=4, pady=8)

    ctk.CTkLabel(frame, text="Git commit identity", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )

    git_name_entry = ctk.CTkEntry(frame, placeholder_text="Git user.name", width=450)
    git_name_entry.pack(anchor="w", padx=4, pady=4)
    git_email_entry = ctk.CTkEntry(frame, placeholder_text="Git user.email", width=450)
    git_email_entry.pack(anchor="w", padx=4, pady=4)
    git_sign_var = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(
        frame,
        text="Sign commits with GPG",
        variable=git_sign_var,
    ).pack(anchor="w", padx=4, pady=4)

    def run_save_git_identity():
        name = git_name_entry.get().strip()
        email = git_email_entry.get().strip()
        if not name or not email:
            status_label.configure(text="Git identity: name and email are required.")
            return
        args = ["config", "git", "--name", name, "--email", email]
        if git_sign_var.get():
            args.append("--sign")
        else:
            args.append("--no-sign")
        runner.run(CommandRunner.cursaves_argv(*args))

    ctk.CTkButton(
        frame,
        text="Save Git identity",
        command=run_save_git_identity,
        width=160,
    ).pack(anchor="w", padx=4, pady=8)

    ctk.CTkLabel(frame, text="Shortcuts", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )

    def make_shortcut():
        ok, msg = create_desktop_shortcut()
        status_label.configure(text=f"Shortcut: {msg}" if ok else f"Failed: {msg}")

    ctk.CTkButton(frame, text="Create desktop shortcut", command=make_shortcut, width=180).pack(
        anchor="w", padx=4, pady=4,
    )
    ctk.CTkButton(
        frame,
        text="Open ~/.cursaves/",
        command=lambda: state.open_path(state.get_sync_dir()),
        width=180,
    ).pack(anchor="w", padx=4, pady=4)

    def refresh_status():
        configured = state.is_configured()
        remote = state.get_remote_url() or "(none)"
        git_id = state.get_git_identity()
        git_name = git_id.get("name") or "(not set)"
        git_email = git_id.get("email") or "(not set)"
        gpg = "yes" if git_id.get("sign_commits") else "no"
        status_label.configure(
            text=(
                f"Sync repo initialized: {'yes' if configured else 'no'}\n"
                f"Remote: {remote}\n"
                f"Git identity: {git_name} <{git_email}> (GPG: {gpg})\n"
                f"Data directory: {state.get_sync_dir()}"
            ),
        )
        if git_id.get("name"):
            git_name_entry.delete(0, "end")
            git_name_entry.insert(0, git_id["name"])
        if git_id.get("email"):
            git_email_entry.delete(0, "end")
            git_email_entry.insert(0, git_id["email"])
        git_sign_var.set(bool(git_id.get("sign_commits")))

    refresh_status()
    parent._setup_refresh = refresh_status  # type: ignore[attr-defined]
