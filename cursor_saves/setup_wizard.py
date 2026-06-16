"""Interactive first-time setup wizard."""

from __future__ import annotations

import shutil
import subprocess
import sys
import platform
import os
from argparse import Namespace
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from InquirerPy import inquirer

from . import paths, profile
from . import github_auth
from .backends import (
    GitBackend,
    S3Backend,
    load_config,
    read_global_git_identity,
    save_config,
    save_git_config,
)
from .interactive import confirm, select_one


@dataclass
class SetupOptions:
    backend: str = "git"
    remote: Optional[str] = None
    bucket: Optional[str] = None
    region: Optional[str] = None
    profile_enabled: bool = True
    sync_mcp: bool = False
    initial_sync: bool = True
    auto_watch: bool = True
    init_action: str = "init"  # init | update_remote | skip
    git_name: Optional[str] = None
    git_email: Optional[str] = None
    git_sign_commits: bool = False
    github_login: Optional[str] = None
    use_manual_git: bool = False


def _cursor_user_dir_path() -> Optional[Path]:
    """Return expected Cursor User dir without exiting if missing."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User"
    if system == "Linux":
        return Path.home() / ".config" / "Cursor" / "User"
    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        return Path(appdata) / "Cursor" / "User"
    return None


def check_prerequisites() -> list[str]:
    """Verify required tools exist. Returns non-fatal warnings."""
    warnings: list[str] = []

    if sys.version_info < (3, 10):
        print(
            f"Error: Python 3.10+ required (found {sys.version_info.major}.{sys.version_info.minor}).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not shutil.which("git"):
        print(
            "Error: git is not installed or not on PATH.\n"
            "Install git before running setup:\n"
            "  https://git-scm.com/downloads",
            file=sys.stderr,
        )
        sys.exit(1)

    cursor_dir = _cursor_user_dir_path()
    if cursor_dir is None or not cursor_dir.exists():
        warnings.append(
            "Cursor data directory not found. Open Cursor at least once before syncing chats."
        )

    return warnings


def verify_remote(url: str) -> bool:
    """Check that the git remote URL is reachable."""
    print(f"  Verifying access to {url}...", end="", flush=True)
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", url],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            print(" ok")
            return True
        err = (result.stderr or result.stdout or "unknown error").strip()
        print(" failed")
        print(f"  Error: {err}", file=sys.stderr)
        print(
            "  Check your SSH key or HTTPS credentials and repo access.",
            file=sys.stderr,
        )
        return False
    except subprocess.TimeoutExpired:
        print(" timed out")
        print("  Error: git ls-remote timed out.", file=sys.stderr)
        return False


def _prompt_text(message: str, default: str = "") -> Optional[str]:
    try:
        value = inquirer.text(
            message=message,
            default=default,
            validate=lambda v: bool(v.strip()) or "Required",
        ).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    return value.strip() if value else None


def _prompt_backend() -> Optional[str]:
    choice = select_one(
        [
            {"name": "Git (private repo — recommended)", "value": "git"},
            {"name": "S3 bucket", "value": "s3"},
        ],
        message="Sync backend:",
        name_key="name",
        value_key="value",
    )
    return choice if isinstance(choice, str) else None


def _prompt_existing_action() -> Optional[str]:
    choice = select_one(
        [
            {"name": "Update remote URL", "value": "update_remote"},
            {"name": "Keep existing configuration (skip init)", "value": "skip"},
            {"name": "Cancel setup", "value": "cancel"},
        ],
        message="~/.cursaves/ already initialized:",
        name_key="name",
        value_key="value",
    )
    return choice if isinstance(choice, str) else None


def _prompt_github_auth(options: SetupOptions, args) -> bool:
    """Login with GitHub for unified push auth + commit identity + remote."""
    if getattr(args, "remote", None):
        options.remote = github_auth.normalize_to_https(args.remote)

    use_defaults = getattr(args, "yes", False)

    if use_defaults:
        if github_auth.find_gh() and github_auth.is_authenticated():
            print("\n── GitHub ──")
            cfg = github_auth.run_auth_flow(
                remote_url=options.remote,
                create_repo=not options.remote,
                yes=True,
                interactive=False,
            )
            options.remote = cfg.get("remote_url") or options.remote
            options.git_name = cfg.get("name")
            options.git_email = cfg.get("email")
            options.github_login = cfg.get("login")
            options.git_sign_commits = False
            return True
        global_id = read_global_git_identity()
        options.git_name = global_id.get("name")
        options.git_email = global_id.get("email")
        options.git_sign_commits = False
        if not options.git_name or not options.git_email:
            print(
                "Warning: not logged in to GitHub and no global git identity. "
                "Run: cursaves auth github",
                file=sys.stderr,
            )
        return True

    if not confirm("Login with GitHub? (recommended — sets up push, commits, and remote)", default=True):
        return _prompt_git_identity_manual(options, args)

    print("\n── GitHub login ──")
    if not github_auth.find_gh():
        if github_auth.can_auto_install_gh() and confirm(
            f"GitHub CLI (gh) not found. Install now?\n  {github_auth.gh_auto_install_description()}",
            default=True,
        ):
            ok, msg = github_auth.install_gh()
            print(f"  {msg}")
            if not ok or not github_auth.find_gh():
                if confirm("Continue with manual git configuration instead?", default=False):
                    return _prompt_git_identity_manual(options, args)
                sys.exit(1)
        else:
            print(f"GitHub CLI (gh) not found. Install with: {github_auth.gh_install_hint()}")
            if confirm("Continue with manual git configuration instead?", default=False):
                return _prompt_git_identity_manual(options, args)
            sys.exit(1)

    cfg = github_auth.run_auth_flow(
        remote_url=options.remote,
        interactive=not options.remote,
    )
    options.remote = cfg.get("remote_url") or options.remote
    options.git_name = cfg.get("name")
    options.git_email = cfg.get("email")
    options.github_login = cfg.get("login")
    options.git_sign_commits = False
    return True


def _prompt_git_identity_manual(options: SetupOptions, args) -> bool:
    """Legacy manual git identity (no GitHub login)."""
    options.use_manual_git = True
    if getattr(args, "git_name", None):
        options.git_name = args.git_name
    if getattr(args, "git_email", None):
        options.git_email = args.git_email
    if getattr(args, "git_sign", None) is not None:
        options.git_sign_commits = bool(args.git_sign)

    if options.git_name and options.git_email:
        return True

    global_id = read_global_git_identity()
    global_label = ""
    if global_id.get("name") or global_id.get("email"):
        global_label = (
            f"{global_id.get('name') or '(no name)'} "
            f"<{global_id.get('email') or 'no email'}>"
        )
        if confirm(
            f"Use your global git identity for sync commits?\n  {global_label}",
            default=True,
        ):
            options.git_name = global_id.get("name")
            options.git_email = global_id.get("email")
            options.git_sign_commits = False
            print("  GPG signing disabled for sync repo commits.")
            print("  Warning: manual mode — ensure git credentials match this identity.")
            return True

    options.git_name = _prompt_text(
        "Git user.name for sync commits:",
        default=global_id.get("name") or "",
    )
    if options.git_name is None:
        return False
    options.git_email = _prompt_text(
        "Git user.email for sync commits:",
        default=global_id.get("email") or "",
    )
    if options.git_email is None:
        return False
    options.git_sign_commits = False
    print("  GPG signing disabled for sync repo commits.")
    return True


def _prompt_git_identity(options: SetupOptions, args) -> bool:
    """Collect git commit identity for the sync repo. Returns False if cancelled."""
    return _prompt_github_auth(options, args)


def prompt_setup_options(args) -> Optional[SetupOptions]:
    """Collect setup options interactively or from CLI flags."""
    use_defaults = getattr(args, "yes", False)
    options = SetupOptions()

    if getattr(args, "backend", None):
        options.backend = args.backend
    elif not use_defaults:
        backend = _prompt_backend()
        if backend is None:
            return None
        options.backend = backend
    else:
        options.backend = "git"

    if options.backend == "git":
        if getattr(args, "remote", None):
            options.remote = github_auth.normalize_to_https(args.remote)
    else:
        if getattr(args, "bucket", None):
            options.bucket = args.bucket
        elif use_defaults:
            print("Error: --bucket is required for S3 backend.", file=sys.stderr)
            sys.exit(1)
        else:
            options.bucket = _prompt_text("S3 bucket name:")
            if not options.bucket:
                return None
        if getattr(args, "region", None):
            options.region = args.region
        elif not use_defaults:
            region = _prompt_text("AWS region (optional, press Enter to skip):", default="")
            options.region = region or None

    if options.backend == "git":
        if not _prompt_git_identity(options, args):
            return None

    if paths.is_sync_repo_initialized():
        if use_defaults:
            options.init_action = "skip"
        else:
            action = _prompt_existing_action()
            if action is None or action == "cancel":
                print("Setup cancelled.")
                return None
            options.init_action = action
            if action == "update_remote" and options.backend == "git" and options.remote:
                pass  # remote already collected
    else:
        options.init_action = "init"

    if use_defaults:
        options.profile_enabled = True
        options.sync_mcp = False
        options.initial_sync = not getattr(args, "no_sync", False)
        options.auto_watch = not getattr(args, "no_watch", False)
    else:
        options.profile_enabled = confirm("Enable profile sync (settings, skills, hooks)?", default=True)
        options.sync_mcp = confirm(
            "Sync MCP configs? (may contain secrets — not recommended)",
            default=False,
        )
        if not getattr(args, "no_sync", False):
            options.initial_sync = confirm("Run initial sync now (profile + chats)?", default=True)
        else:
            options.initial_sync = False
        if not getattr(args, "no_watch", False):
            if sys.platform == "win32":
                options.auto_watch = confirm(
                    "Install auto-sync when Cursor opens (sessionStart hook)?",
                    default=True,
                )
            else:
                options.auto_watch = confirm(
                    "Install auto-sync when Cursor opens (sessionStart hook)?",
                    default=True,
                )
        else:
            options.auto_watch = False

    return options


def _save_profile_config(options: SetupOptions) -> None:
    config = load_config()
    categories = dict(profile.DEFAULT_CATEGORIES)
    categories["mcp"] = options.sync_mcp
    config["profile"] = {
        "enabled": options.profile_enabled,
        "categories": categories,
    }
    save_config(config)


def _save_git_config(options: SetupOptions) -> None:
    if options.backend != "git":
        return
    if not options.git_name and not options.git_email:
        return
    save_git_config(
        name=options.git_name,
        email=options.git_email,
        sign_commits=options.git_sign_commits,
    )


def _run_init(options: SetupOptions) -> None:
    sync_dir = paths.get_sync_dir()

    if options.init_action == "skip":
        print("\n── Init ──")
        print("  Using existing ~/.cursaves/ configuration")
        _save_profile_config(options)
        _save_git_config(options)
        return

    if options.init_action == "update_remote":
        print("\n── Init ──")
        if options.backend != "git" or not options.remote:
            print("  Remote update only supported for git backend.", file=sys.stderr)
            sys.exit(1)
        git_backend = GitBackend(sync_dir)
        git_backend.update_remote(options.remote)
        print(f"  Updated remote: {options.remote}")
        _save_profile_config(options)
        _save_git_config(options)
        return

    print("\n── Init ──")
    _save_git_config(options)
    if options.backend == "s3":
        from .cli import cmd_init

        cmd_init(
            Namespace(
                backend="s3",
                remote=None,
                bucket=options.bucket,
                prefix=None,
                region=options.region,
            )
        )
    else:
        git_backend = GitBackend(sync_dir)
        if git_backend.is_initialized():
            if options.remote:
                git_backend.update_remote(options.remote)
                print(f"  Updated remote: {options.remote}")
        else:
            git_backend.init_repo(remote=options.remote)
            print(f"  Created {sync_dir}")
            if options.remote:
                print(f"  Added remote: {options.remote}")
        _save_profile_config(options)


def _run_initial_sync(options: SetupOptions) -> None:
    from .cli import cmd_sync

    print("\n── Initial sync ──")
    cmd_sync(
        Namespace(
            no_profile=not options.profile_enabled,
        )
    )


def _install_auto_watch(options: SetupOptions) -> None:
    if not options.auto_watch:
        return

    print("\n── Auto-sync ──")
    from .hook_install import install_watch_hook

    install_watch_hook(interval=120)


def print_summary(options: SetupOptions) -> None:
    print("\n" + "=" * 60)
    print("Setup complete")
    print("=" * 60)
    print("\nDaily usage:")
    print("  cursaves sync              # sync chats + profile")
    print("  cursaves profile status    # check profile sync state")
    print("\nAfter importing chats or profile changes, restart Cursor fully.")
    if options.backend == "git" and options.remote:
        print(f"\nYour sync repo: {options.remote}")
    elif options.backend == "git":
        print("\nNo remote configured — local-only mode. Add later with:")
        print("  cursaves init --remote git@github.com:you/your-cursaves-data.git")
    if options.backend == "git":
        if options.github_login:
            print(f"\nGitHub: @{options.github_login}")
            print(f"  Push/pull + commit identity: {options.git_name} <{options.git_email}>")
        elif options.git_name and options.git_email:
            print(f"\nGit commit identity: {options.git_name} <{options.git_email}>")
            print("  GPG signing: disabled for sync repo")
        else:
            print(
                "\nWarning: no git identity configured. Run: cursaves auth github"
            )
    print(f"Local data: {paths.get_sync_dir()}")


def run_setup(args) -> None:
    """Run the full interactive setup wizard."""
    print("cursaves setup")
    print("=" * 60)

    warnings = check_prerequisites()
    for warning in warnings:
        print(f"Warning: {warning}")

    options = prompt_setup_options(args)
    if options is None:
        sys.exit(1)

    if options.backend == "git" and options.remote:
        if options.init_action == "init" and not verify_remote(options.remote):
            sys.exit(1)
        if options.init_action == "update_remote" and not verify_remote(options.remote):
            sys.exit(1)
    elif options.backend == "git" and not options.remote and options.init_action == "init":
        if options.use_manual_git:
            print("\nSkipping remote verification (local-only setup).")

    _run_init(options)

    if options.initial_sync:
        if not paths.is_sync_repo_initialized():
            print("Error: Sync repo not initialized.", file=sys.stderr)
            sys.exit(1)
        _run_initial_sync(options)

    _install_auto_watch(options)
    print_summary(options)
