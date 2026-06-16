"""Sync backends for cursaves snapshot storage.

Each backend handles the transport layer: syncing snapshot files between
the local ``~/.cursaves/`` directory (``snapshots/`` and ``profile/``) and a
remote store (git repo, S3 bucket, Azure container, etc.).

The local staging directories are always the source of truth for reads —
backends just keep them in sync with a remote.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


_CONFIG_PATH = Path.home() / ".config" / "cursaves" / "config.json"

_SYNC_SUBDIRS = ("snapshots", "profile")

_GITIGNORE_CONTENT = """.DS_Store
profile/cursor/mcps/**/credentials*
profile/**/*.env
profile/**/secrets*
"""


def _sync_subdir_paths(snapshots_dir: Path) -> dict[str, Path]:
    """Return local paths for each sync subdirectory under ~/.cursaves/."""
    sync_dir = snapshots_dir.parent
    return {
        "snapshots": snapshots_dir,
        "profile": sync_dir / "profile",
    }


# ── Abstract base ────────────────────────────────────────────────────────


class SyncBackend(ABC):
    """Interface every sync backend must implement."""

    @abstractmethod
    def pull(self, snapshots_dir: Path) -> bool:
        """Download remote snapshots into *snapshots_dir*.

        Must be idempotent — running twice without changes is a no-op.
        Returns True on success, False on failure.
        """

    @abstractmethod
    def push(self, snapshots_dir: Path) -> bool:
        """Upload local snapshots from *snapshots_dir* to the remote.

        Returns True on success, False on failure.
        """

    def push_profile(self, snapshots_dir: Path) -> bool:
        """Upload only profile/ changes. Override in backends that support it."""
        return True

    @abstractmethod
    def has_remote(self) -> bool:
        """Return True if a remote target is configured."""

    @abstractmethod
    def is_initialized(self) -> bool:
        """Return True if the backend has been set up (init already run)."""


# ── Git backend ──────────────────────────────────────────────────────────


class GitBackend(SyncBackend):
    """Original backend: a local git repo at *sync_dir* with an optional remote."""

    def __init__(self, sync_dir: Path):
        self.sync_dir = sync_dir

    # -- SyncBackend interface ------------------------------------------

    def pull(self, snapshots_dir: Path) -> bool:
        if not self.has_remote():
            return True
        return self._reset_to_origin()

    def push(self, snapshots_dir: Path) -> bool:
        return self._git_push(snapshots_dir, subdirs=_SYNC_SUBDIRS)

    def push_profile(self, snapshots_dir: Path) -> bool:
        """Commit and push only profile/ changes (used before pull)."""
        return self._git_push(snapshots_dir, subdirs=("profile",), message_suffix="profile")

    def _git_push(
        self,
        snapshots_dir: Path,
        subdirs: tuple[str, ...],
        message_suffix: str = "profile + snapshots",
    ) -> bool:
        apply_git_identity(self.sync_dir)

        add_args = [f"{name}/" for name in subdirs]
        subprocess.run(
            ["git", "add", *add_args],
            cwd=str(self.sync_dir), capture_output=True,
        )
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(self.sync_dir), capture_output=True,
        )
        if result.returncode == 0:
            return True  # nothing to commit

        from . import paths
        hostname = paths.get_machine_id()
        msg = f"[{hostname}] sync {message_suffix}"
        commit_result = subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(self.sync_dir), capture_output=True, text=True,
        )
        if commit_result.returncode != 0:
            err = (commit_result.stderr or commit_result.stdout or "unknown error").strip()
            print(f"  Commit failed: {err}", file=sys.stderr)
            return False

        if self.has_remote():
            try:
                push_result = subprocess.run(
                    ["git", "push", "-u", "origin", "main"],
                    cwd=str(self.sync_dir),
                    capture_output=True, text=True, timeout=120,
                )
                if push_result.returncode != 0:
                    print(f"  Push failed: {push_result.stderr.strip()}", file=sys.stderr)
                    return False
            except subprocess.TimeoutExpired:
                print("  Push timed out", file=sys.stderr)
                return False
        return True

    def has_remote(self) -> bool:
        try:
            result = subprocess.run(
                ["git", "remote"],
                capture_output=True, text=True,
                cwd=str(self.sync_dir),
            )
            return result.returncode == 0 and result.stdout.strip() != ""
        except FileNotFoundError:
            return False

    def is_initialized(self) -> bool:
        return (self.sync_dir / ".git").exists()

    # -- Git-specific helpers -------------------------------------------

    def _reset_to_origin(self) -> bool:
        """Fetch + hard-reset to origin/main.  Remote is ground truth."""
        if not self.sync_dir.exists():
            return False

        for abort_cmd in (
            ["git", "rebase", "--abort"],
            ["git", "merge", "--abort"],
            ["git", "cherry-pick", "--abort"],
        ):
            subprocess.run(abort_cmd, cwd=str(self.sync_dir), capture_output=True)

        if not self.has_remote():
            subprocess.run(
                ["git", "checkout", "-f", "-B", "main"],
                cwd=str(self.sync_dir), capture_output=True,
            )
            return True

        try:
            fetch = subprocess.run(
                ["git", "fetch", "--depth", "1", "origin"],
                cwd=str(self.sync_dir),
                capture_output=True, text=True, timeout=180,
            )
            if fetch.returncode != 0:
                return False

            subprocess.run(
                ["git", "checkout", "-f", "-B", "main", "origin/main"],
                cwd=str(self.sync_dir), capture_output=True,
            )
            subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=str(self.sync_dir), capture_output=True,
            )
            subprocess.run(
                ["git", "branch", "--set-upstream-to=origin/main", "main"],
                cwd=str(self.sync_dir), capture_output=True,
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                cwd=str(self.sync_dir), capture_output=True,
            )
            return True
        except subprocess.TimeoutExpired:
            return False

    def init_repo(self, remote: Optional[str] = None):
        """Create the git repo and optionally add a remote."""
        self.sync_dir.mkdir(parents=True, exist_ok=True)
        (self.sync_dir / "snapshots").mkdir(exist_ok=True)
        (self.sync_dir / "profile").mkdir(exist_ok=True)

        subprocess.run(
            ["git", "init", "-b", "main"],
            cwd=str(self.sync_dir), capture_output=True,
        )

        apply_git_identity(self.sync_dir)

        gitignore = self.sync_dir / ".gitignore"
        gitignore.write_text(_GITIGNORE_CONTENT)

        subprocess.run(
            ["git", "add", "."],
            cwd=str(self.sync_dir), capture_output=True,
        )
        commit_result = subprocess.run(
            ["git", "commit", "-m", "Initialize cursaves sync repo"],
            cwd=str(self.sync_dir), capture_output=True, text=True,
        )
        if commit_result.returncode != 0:
            err = (commit_result.stderr or commit_result.stdout or "unknown error").strip()
            print(f"  Initial commit failed: {err}", file=sys.stderr)

        if remote:
            subprocess.run(
                ["git", "remote", "add", "origin", remote],
                cwd=str(self.sync_dir), capture_output=True,
            )

    def update_remote(self, remote: str):
        """Add or update the origin remote."""
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(self.sync_dir),
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            subprocess.run(
                ["git", "remote", "set-url", "origin", remote],
                cwd=str(self.sync_dir), capture_output=True,
            )
        else:
            subprocess.run(
                ["git", "remote", "add", "origin", remote],
                cwd=str(self.sync_dir), capture_output=True,
            )


# ── S3 backend ───────────────────────────────────────────────────────────


class S3Backend(SyncBackend):
    """Sync snapshots to/from an S3 bucket.

    Requires ``boto3`` — install with ``pip install cursaves[s3]``.

    Configuration (in ~/.config/cursaves/config.json)::

        {
            "backend": "s3",
            "s3": {
                "bucket": "my-cursor-saves",
                "prefix": "snapshots/",
                "region": "us-east-1"      // optional
            }
        }

    Authentication uses the standard AWS credential chain:
    env vars, ~/.aws/credentials, IAM roles, etc.
    """

    def __init__(self, bucket: str, prefix: str = "snapshots/", region: Optional[str] = None):
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/"
        self.region = region
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import boto3
            except ImportError:
                print(
                    "Error: boto3 is required for S3 backend.\n"
                    "Install it with: pip install cursaves[s3]  or  pip install boto3",
                    file=sys.stderr,
                )
                sys.exit(1)
            kwargs = {}
            if self.region:
                kwargs["region_name"] = self.region
            self._client = boto3.client("s3", **kwargs)
        return self._client

    # -- SyncBackend interface ------------------------------------------

    def pull(self, snapshots_dir: Path) -> bool:
        """Download remote snapshot and profile files that are newer or missing locally."""
        subdirs = _sync_subdir_paths(snapshots_dir)
        ok = True
        for name, local_dir in subdirs.items():
            local_dir.mkdir(parents=True, exist_ok=True)
            prefix = f"{name}/"
            if not self._s3_pull_dir(local_dir, prefix):
                ok = False
        return ok

    def push(self, snapshots_dir: Path) -> bool:
        """Upload local snapshot and profile files that are newer or missing remotely."""
        subdirs = _sync_subdir_paths(snapshots_dir)
        ok = True
        for name, local_dir in subdirs.items():
            if not local_dir.exists():
                continue
            prefix = f"{name}/"
            if not self._s3_push_dir(local_dir, prefix):
                ok = False
        return ok

    def push_profile(self, snapshots_dir: Path) -> bool:
        profile_dir = snapshots_dir.parent / "profile"
        if not profile_dir.exists():
            return True
        return self._s3_push_dir(profile_dir, "profile/")

    def _s3_pull_dir(self, local_dir: Path, prefix: str) -> bool:
        client = self._get_client()
        try:
            paginator = client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)

            downloaded = 0
            for page in pages:
                for obj in page.get("Contents", []):
                    remote_key = obj["Key"]
                    rel_path = remote_key[len(prefix):]
                    if not rel_path:
                        continue

                    local_path = local_dir / rel_path
                    remote_mtime = obj["LastModified"].timestamp()

                    if local_path.exists():
                        local_mtime = local_path.stat().st_mtime
                        local_size = local_path.stat().st_size
                        if local_size == obj["Size"] and local_mtime >= remote_mtime:
                            continue

                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    client.download_file(self.bucket, remote_key, str(local_path))
                    os.utime(str(local_path), (remote_mtime, remote_mtime))
                    downloaded += 1

            if downloaded:
                print(f"  Downloaded {downloaded} file(s) from s3://{self.bucket}/{prefix}")
            return True

        except Exception as e:
            print(f"S3 pull failed ({prefix}): {e}", file=sys.stderr)
            return False

    def _s3_push_dir(self, local_dir: Path, prefix: str) -> bool:
        client = self._get_client()
        try:
            remote_index: dict[str, tuple[float, int]] = {}
            paginator = client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket, Prefix=prefix)
            for page in pages:
                for obj in page.get("Contents", []):
                    rel = obj["Key"][len(prefix):]
                    if rel:
                        remote_index[rel] = (obj["LastModified"].timestamp(), obj["Size"])

            uploaded = 0
            for local_path in local_dir.rglob("*"):
                if not local_path.is_file():
                    continue
                rel = str(local_path.relative_to(local_dir))
                remote_key = prefix + rel

                local_mtime = local_path.stat().st_mtime
                local_size = local_path.stat().st_size

                if rel in remote_index:
                    remote_mtime, remote_size = remote_index[rel]
                    if local_size == remote_size and local_mtime <= remote_mtime:
                        continue

                client.upload_file(str(local_path), self.bucket, remote_key)
                uploaded += 1

            if uploaded:
                print(f"  Uploaded {uploaded} file(s) to s3://{self.bucket}/{prefix}")
            return True

        except Exception as e:
            print(f"S3 push failed ({prefix}): {e}", file=sys.stderr)
            return False

    def has_remote(self) -> bool:
        return True  # S3 is always remote

    def is_initialized(self) -> bool:
        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
            return True
        except Exception:
            return False


# ── Configuration ────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load cursaves config from ~/.config/cursaves/config.json."""
    if _CONFIG_PATH.exists():
        try:
            return json.loads(_CONFIG_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(config: dict):
    """Persist cursaves config."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def get_git_config() -> dict:
    """Return git identity settings for sync commits (with safe defaults)."""
    git_cfg = load_config().get("git", {})
    return {
        "name": git_cfg.get("name") or None,
        "email": git_cfg.get("email") or None,
        "sign_commits": bool(git_cfg.get("sign_commits", False)),
    }


def read_global_git_identity() -> dict:
    """Read user.name and user.email from global git config."""
    identity: dict[str, Optional[str]] = {"name": None, "email": None}
    for key, field in (("user.name", "name"), ("user.email", "email")):
        try:
            result = subprocess.run(
                ["git", "config", "--global", key],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                value = result.stdout.strip()
                if value:
                    identity[field] = value
        except FileNotFoundError:
            break
    return identity


def _git_config_local(sync_dir: Path, key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--local", key, value],
        cwd=str(sync_dir),
        capture_output=True,
    )


def apply_git_identity(sync_dir: Path) -> None:
    """Apply configured git identity to the sync repo (local config only)."""
    if not (sync_dir / ".git").exists():
        return

    git_cfg = get_git_config()
    name = git_cfg.get("name")
    email = git_cfg.get("email")
    if name:
        _git_config_local(sync_dir, "user.name", name)
    if email:
        _git_config_local(sync_dir, "user.email", email)

    sign_commits = git_cfg.get("sign_commits", False)
    _git_config_local(sync_dir, "commit.gpgsign", "true" if sign_commits else "false")


def save_git_config(
    name: Optional[str] = None,
    email: Optional[str] = None,
    sign_commits: bool = False,
) -> dict:
    """Persist git identity to config.json and apply to the sync repo."""
    from . import paths

    config = load_config()
    git_cfg = config.setdefault("git", {})
    if name is not None:
        git_cfg["name"] = name
    if email is not None:
        git_cfg["email"] = email
    git_cfg["sign_commits"] = sign_commits
    save_config(config)

    sync_dir = paths.get_sync_dir()
    if sync_dir.exists():
        apply_git_identity(sync_dir)

    return get_git_config()


def get_backend() -> SyncBackend:
    """Instantiate the configured sync backend.

    Falls back to GitBackend if nothing is configured (backward-compatible).
    """
    from . import paths

    config = load_config()
    backend_type = config.get("backend", "git")

    if backend_type == "s3":
        s3_cfg = config.get("s3", {})
        bucket = s3_cfg.get("bucket")
        if not bucket:
            print("Error: S3 backend configured but no bucket specified.", file=sys.stderr)
            print("Run: cursaves init --backend s3 --bucket <name>", file=sys.stderr)
            sys.exit(1)
        return S3Backend(
            bucket=bucket,
            prefix=s3_cfg.get("prefix", "snapshots/"),
            region=s3_cfg.get("region"),
        )

    # Default: git
    return GitBackend(paths.get_sync_dir())
