"""Read-only app state for the GUI dashboard and status bar."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from .. import paths, profile
from ..backends import get_backend, load_config
from ..hook_install import _is_cursaves_hook, _load_hooks_json
from ..importer import is_cursor_running, list_snapshot_projects
from ..watch import get_watch_log_path, is_watch_running


def is_configured() -> bool:
    return paths.is_sync_repo_initialized()


def get_remote_url() -> Optional[str]:
    if not is_configured():
        return None
    try:
        backend = get_backend()
        if not backend.has_remote():
            return None
        sync_dir = paths.get_sync_dir()
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(sync_dir),
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def hook_is_installed() -> bool:
    try:
        data = _load_hooks_json()
        for entry in data.get("hooks", {}).get("sessionStart", []):
            if _is_cursaves_hook(entry):
                return True
    except Exception:
        pass
    return False


def get_dashboard_stats() -> dict:
    workspaces = paths.list_workspaces_with_conversations()
    projects = list_snapshot_projects() if is_configured() else []
    pending_profile = 0
    if is_configured():
        try:
            rows = profile.profile_status()
            pending_profile = sum(
                1 for r in rows if r["state"] in ("local_only", "differ")
            )
        except Exception:
            pass
    return {
        "workspaces": len(workspaces),
        "snapshot_projects": len(projects),
        "pending_profile": pending_profile,
    }


def get_status_bar_text() -> str:
    parts = [
        f"Machine: {paths.get_machine_id()}",
        f"Sync repo: {'yes' if is_configured() else 'no'}",
    ]
    remote = get_remote_url()
    if remote:
        if len(remote) > 40:
            remote = remote[:37] + "..."
        parts.append(f"Remote: {remote}")
    parts.append(f"Cursor: {'running' if is_cursor_running() else 'closed'}")
    parts.append(f"Watch: {'on' if is_watch_running() else 'off'}")
    if hook_is_installed():
        parts.append("Hook: installed")
    return "  |  ".join(parts)


def open_path(path: Path) -> None:
    import os
    import sys

    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def get_sync_dir() -> Path:
    return paths.get_sync_dir()


def get_watch_log() -> Path:
    return get_watch_log_path()
