"""Setup / first-run tab."""

from __future__ import annotations

import webbrowser

import customtkinter as ctk

from ... import github_auth
from .. import state
from ..runner import CommandRunner
from ..shortcut import create_desktop_shortcut
from ..widgets import confirm_action


class _DeviceCodeDialog(ctk.CTkToplevel):
    """Show GitHub OAuth device code for browser authorization."""

    def __init__(self, parent, code: str):
        super().__init__(parent)
        self.title("GitHub login code")
        self.geometry("460x260")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self._poll_job: str | None = None
        self._close_job: str | None = None

        ctk.CTkLabel(
            self,
            text="Enter this code on the GitHub page in your browser:",
            wraplength=420,
            justify="left",
        ).pack(padx=16, pady=(16, 8))

        ctk.CTkLabel(
            self,
            text=code,
            font=ctk.CTkFont(size=32, weight="bold"),
        ).pack(padx=16, pady=8)

        self._status_label = ctk.CTkLabel(
            self,
            text="This window will close automatically when login completes.",
            text_color="gray",
            wraplength=420,
            justify="left",
        )
        self._status_label.pack(padx=16, pady=(4, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=16, pady=8)

        ctk.CTkButton(
            btn_row,
            text="Copy code",
            command=lambda: self._copy_code(code),
            width=100,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row,
            text="Open GitHub",
            command=self._open_github,
            width=110,
        ).pack(side="left", padx=4)

        self._poll_auth()

    def _poll_auth(self) -> None:
        if not self.winfo_exists():
            return
        if github_auth.is_authenticated():
            self._status_label.configure(
                text="Logged in! This window will close…",
                text_color=("green", "#4ade80"),
            )
            self._close_job = self.after(1500, self._close)
            return
        self._poll_job = self.after(1000, self._poll_auth)

    def _close(self) -> None:
        self._cancel_jobs()
        if self.winfo_exists():
            self.destroy()

    def _cancel_jobs(self) -> None:
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        if self._close_job:
            try:
                self.after_cancel(self._close_job)
            except Exception:
                pass
            self._close_job = None

    def destroy(self) -> None:
        self._cancel_jobs()
        super().destroy()

    def _copy_code(self, code: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(code)
        self.update()

    def _open_github(self) -> None:
        webbrowser.open(github_auth.device_login_url())


class _GhInstallDialog(ctk.CTkToplevel):
    """Offer to install GitHub CLI when missing."""

    def __init__(self, parent, on_done):
        super().__init__(parent)
        self.title("Install GitHub CLI")
        self.geometry("500x200")
        self.resizable(False, False)
        self._on_done = on_done
        self.transient(parent)
        self.grab_set()

        cmd = github_auth.gh_auto_install_description()
        steps = github_auth.gh_install_steps()
        intro = (
            "GitHub CLI (gh) is required for Login with GitHub.\n\n"
            "It is not installed. Install automatically now?\n\n"
        )
        if steps:
            intro += "Cursaves will:\n" + cmd
        else:
            intro += cmd
        ctk.CTkLabel(
            self,
            text=intro,
            wraplength=460,
            justify="left",
        ).pack(padx=16, pady=(16, 12))

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=16, pady=8)

        ctk.CTkButton(
            btn_row,
            text="Install gh",
            command=self._install,
            width=120,
        ).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Cancel", command=self._cancel, width=80).pack(
            side="left", padx=4,
        )

    def _install(self):
        self._on_done(True)
        self.destroy()

    def _cancel(self):
        self._on_done(False)
        self.destroy()


class _RepoDialog(ctk.CTkToplevel):
    """Ask whether the user already has a sync repo."""

    def __init__(self, parent, on_done):
        super().__init__(parent)
        self.title("Sync repository")
        self.geometry("480x220")
        self.resizable(False, False)
        self._on_done = on_done
        self.transient(parent)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text="Do you already have a private GitHub repo for cursaves sync?",
            wraplength=440,
        ).pack(padx=16, pady=(16, 8))

        self._url_entry = ctk.CTkEntry(
            self,
            placeholder_text="https://github.com/you/cursaves-data.git (if yes)",
            width=420,
        )
        self._url_entry.pack(padx=16, pady=8)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(padx=16, pady=12)

        ctk.CTkButton(
            btn_row,
            text="Yes — use existing",
            command=self._yes,
            width=140,
        ).pack(side="left", padx=4)
        ctk.CTkButton(
            btn_row,
            text="No — create for me",
            command=self._no,
            width=140,
        ).pack(side="left", padx=4)
        ctk.CTkButton(btn_row, text="Cancel", command=self.destroy, width=80).pack(
            side="left", padx=4,
        )

    def _yes(self):
        url = self._url_entry.get().strip()
        self._on_done(True, url or None)
        self.destroy()

    def _no(self):
        self._on_done(False, None)
        self.destroy()


def build_setup(parent, runner: CommandRunner, on_configured) -> None:
    frame = ctk.CTkScrollableFrame(parent, fg_color="transparent")
    frame.pack(fill="both", expand=True, padx=8, pady=8)

    status_label = ctk.CTkLabel(frame, text="", justify="left")
    status_label.pack(anchor="w", padx=4, pady=8)

    github_status = ctk.CTkLabel(frame, text="", justify="left")
    github_status.pack(anchor="w", padx=4, pady=4)

    ctk.CTkLabel(frame, text="GitHub", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(8, 4),
    )
    ctk.CTkLabel(
        frame,
        text="One login sets up push/pull, commit identity, and sync remote.",
        text_color="gray",
        wraplength=500,
        justify="left",
    ).pack(anchor="w", padx=4, pady=(0, 4))

    def _gui_status(msg: str) -> None:
        parent.after(0, lambda m=msg: status_label.configure(text=m))

    _device_code_dialog: _DeviceCodeDialog | None = None

    def _show_device_code(code: str) -> None:
        nonlocal _device_code_dialog
        if _device_code_dialog and _device_code_dialog.winfo_exists():
            return
        _device_code_dialog = _DeviceCodeDialog(parent.winfo_toplevel(), code)

    def _on_device_code(code: str) -> None:
        parent.after(0, lambda c=code: _show_device_code(c))

    def _finish_github_login(has_repo: bool | None, url: str | None):
        if has_repo and not url:
            status_label.configure(text="Enter your GitHub remote URL, then try again.")
            return

        def task():
            github_auth.run_gui_repo_setup(
                has_existing_repo=has_repo,
                remote_url=url,
                on_status=_gui_status,
            )

        def _after_repo_setup(exit_code: int):
            parent.after(0, refresh_status)
            if exit_code == 0:
                parent.after(0, on_configured)

        runner.run_callable(task, capture_output=False, on_done=_after_repo_setup)

    def _open_repo_dialog():
        _RepoDialog(parent.winfo_toplevel(), _finish_github_login)

    def _after_github_login(code: int):
        nonlocal _device_code_dialog
        if _device_code_dialog and _device_code_dialog.winfo_exists():
            parent.after(0, _device_code_dialog.destroy)
            _device_code_dialog = None
        parent.after(0, refresh_status)
        if code == 0 and github_auth.is_authenticated():
            parent.after(0, _open_repo_dialog)
        elif code != 0:
            parent.after(
                0,
                lambda: status_label.configure(
                    text="GitHub login failed. See Output panel for details.",
                ),
            )

    def _run_github_login():
        status_label.configure(text="Opening browser for GitHub login...")

        def task():
            github_auth.run_gui_login(
                on_status=_gui_status,
                on_device_code=_on_device_code,
            )

        runner.run_callable(
            task,
            capture_output=False,
            on_done=_after_github_login,
        )

    def _install_gh_task():
        status_label.configure(text="Installing dependencies (this may take a few minutes)...")
        ok, msg = github_auth.install_gh()
        print(msg)
        if ok and github_auth.find_gh():
            parent.after(0, _run_github_login)
        else:
            parent.after(
                0,
                lambda: status_label.configure(
                    text=msg or "Install failed. Try restarting cursaves.",
                ),
            )
        parent.after(0, refresh_status)

    def _on_gh_install_choice(install: bool):
        if install:
            runner.run_callable(_install_gh_task)
        else:
            status_label.configure(
                text=f"Login cancelled. Install gh: {github_auth.gh_install_hint()}",
            )

    def start_github_login():
        if not github_auth.find_gh():
            if github_auth.can_auto_install_gh():
                _GhInstallDialog(parent.winfo_toplevel(), _on_gh_install_choice)
            else:
                status_label.configure(
                    text=f"Install GitHub CLI first: {github_auth.gh_install_hint()}",
                )
            return
        _run_github_login()

    ctk.CTkButton(
        frame,
        text="Login with GitHub",
        command=start_github_login,
        width=180,
    ).pack(anchor="w", padx=4, pady=8)

    def logout_github():
        if not github_auth.is_authenticated():
            status_label.configure(text="Not logged in to GitHub.")
            refresh_status()
            return
        if not confirm_action(
            "Logout from GitHub",
            "Log out from GitHub?\n\n"
            "Push/pull will stop working until you log in again on this machine.",
        ):
            return
        github_auth.logout()
        status_label.configure(text="Logged out from GitHub.")
        refresh_status()

    ctk.CTkButton(
        frame,
        text="Logout from GitHub",
        command=logout_github,
        width=180,
        fg_color="gray30",
        hover_color="gray25",
    ).pack(anchor="w", padx=4, pady=(0, 8))

    ctk.CTkLabel(frame, text="Run full setup", font=ctk.CTkFont(weight="bold")).pack(
        anchor="w", padx=4, pady=(12, 4),
    )

    setup_remote = ctk.CTkEntry(frame, placeholder_text="Git remote URL (optional override)", width=450)
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

    advanced_var = ctk.BooleanVar(value=False)
    advanced_toggle = ctk.CTkCheckBox(
        frame,
        text="Advanced: manual git identity (legacy)",
        variable=advanced_var,
        command=lambda: advanced_frame.pack() if advanced_var.get() else advanced_frame.pack_forget(),
    )
    advanced_toggle.pack(anchor="w", padx=4, pady=(12, 4))

    advanced_frame = ctk.CTkFrame(frame, fg_color="transparent")
    ctk.CTkLabel(
        advanced_frame,
        text="Manual mode may desync push auth from commit author. Prefer Login with GitHub.",
        text_color="gray",
        wraplength=500,
        justify="left",
    ).pack(anchor="w", padx=4, pady=4)

    git_name_entry = ctk.CTkEntry(advanced_frame, placeholder_text="Git user.name", width=450)
    git_name_entry.pack(anchor="w", padx=4, pady=4)
    git_email_entry = ctk.CTkEntry(advanced_frame, placeholder_text="Git user.email", width=450)
    git_email_entry.pack(anchor="w", padx=4, pady=4)
    git_sign_var = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(
        advanced_frame,
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
        advanced_frame,
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
        gh = state.get_github_auth()
        git_id = state.get_git_identity()
        git_name = git_id.get("name") or "(not set)"
        git_email = git_id.get("email") or "(not set)"
        gpg = "yes" if git_id.get("sign_commits") else "no"

        if gh.get("authenticated"):
            login = gh.get("login")
            if login:
                github_status.configure(text=f"GitHub: logged in as @{login}")
            else:
                github_status.configure(text="GitHub: logged in")
        else:
            github_status.configure(text="GitHub: not logged in — click Login with GitHub")

        status_label.configure(
            text=(
                f"Sync repo initialized: {'yes' if configured else 'no'}\n"
                f"Remote: {remote}\n"
                f"Commit identity: {git_name} <{git_email}> (GPG: {gpg})\n"
                f"Data directory: {state.get_sync_dir()}"
            ),
        )
        cfg_remote = gh.get("remote_url") or ""
        if cfg_remote and not setup_remote.get():
            setup_remote.delete(0, "end")
            setup_remote.insert(0, cfg_remote)
        if git_id.get("name"):
            git_name_entry.delete(0, "end")
            git_name_entry.insert(0, git_id["name"])
        if git_id.get("email"):
            git_email_entry.delete(0, "end")
            git_email_entry.insert(0, git_id["email"])
        git_sign_var.set(bool(git_id.get("sign_commits")))

    refresh_status()
    parent._setup_refresh = refresh_status  # type: ignore[attr-defined]
