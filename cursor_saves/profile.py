"""Export/apply global Cursor profile settings for cross-machine sync."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from . import paths
from .backends import load_config

DEFAULT_CATEGORIES = {
    "settings": True,
    "keybindings": True,
    "snippets": True,
    "skills": True,
    "commands": True,
    "agents": True,
    "hooks": True,
    "rules": True,
    "cli": True,
    "mcp": False,
}

BACKUP_KEEP = 2


@dataclass(frozen=True)
class ProfileEntry:
    """Maps a local Cursor path to a path under ~/.cursaves/profile/."""

    category: str
    profile_rel: str
    root: str  # "cursor" or "user"
    local_name: str
    optional: bool = False
    is_dir: bool = False


PROFILE_CATALOG: tuple[ProfileEntry, ...] = (
    ProfileEntry("settings", "user/settings.json", "user", "settings.json"),
    ProfileEntry("keybindings", "user/keybindings.json", "user", "keybindings.json", optional=True),
    ProfileEntry("snippets", "user/snippets", "user", "snippets", is_dir=True),
    ProfileEntry("skills", "cursor/skills", "cursor", "skills", is_dir=True),
    ProfileEntry("commands", "cursor/commands", "cursor", "commands", is_dir=True),
    ProfileEntry("agents", "cursor/agents", "cursor", "agents", is_dir=True),
    ProfileEntry("hooks", "cursor/hooks.json", "cursor", "hooks.json", optional=True),
    ProfileEntry("hooks", "cursor/hooks", "cursor", "hooks", optional=True, is_dir=True),
    ProfileEntry("rules", "cursor/rules", "cursor", "rules", optional=True, is_dir=True),
    ProfileEntry("cli", "cursor/cli-config.json", "cursor", "cli-config.json", optional=True),
    ProfileEntry("cli", "cursor/statusline.sh", "cursor", "statusline.sh", optional=True),
    ProfileEntry("mcp", "cursor/mcps", "cursor", "mcps", optional=True, is_dir=True),
)


def get_profile_config() -> dict:
    """Return merged profile sync configuration."""
    config = load_config()
    profile_cfg = dict(config.get("profile", {}))
    if "enabled" not in profile_cfg:
        profile_cfg["enabled"] = True
    categories = {**DEFAULT_CATEGORIES, **profile_cfg.get("categories", {})}
    profile_cfg["categories"] = categories
    return profile_cfg


def is_profile_enabled() -> bool:
    """Return True if profile sync is enabled."""
    return get_profile_config().get("enabled", True)


def get_profile_dir() -> Path:
    """Return ~/.cursaves/profile/, creating it if needed."""
    return paths.get_profile_staging_dir()


def _local_root(entry: ProfileEntry) -> Path:
    if entry.root == "cursor":
        return paths.get_cursor_dot_dir()
    return paths.get_cursor_user_dir()


def _local_path(entry: ProfileEntry) -> Path:
    return _local_root(entry) / entry.local_name


def _staging_path(profile_dir: Path, entry: ProfileEntry) -> Path:
    return profile_dir / entry.profile_rel


def _enabled_entries() -> list[ProfileEntry]:
    categories = get_profile_config()["categories"]
    return [e for e in PROFILE_CATALOG if categories.get(e.category, False)]


def _file_hash(path: Path) -> Optional[str]:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _tree_hash(root: Path) -> Optional[str]:
    if not root.exists():
        return None
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _path_fingerprint(path: Path, is_dir: bool) -> Optional[str]:
    if is_dir:
        return _tree_hash(path)
    return _file_hash(path)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _merge_tree(src: Path, dst: Path) -> None:
    """Copy new/changed files from src into dst without removing extra dst files."""
    dst.mkdir(parents=True, exist_ok=True)
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or path.read_bytes() != target.read_bytes():
            shutil.copy2(path, target)


def _load_hooks_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": 1, "hooks": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "hooks": {}}


def _save_hooks_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _hook_command_key(entry: dict[str, Any]) -> str:
    return str(entry.get("command", ""))


def _merge_hooks_json_export(local: Path, staging: Path) -> None:
    """Merge local hooks.json into staging without removing staging-only entries."""
    local_data = _load_hooks_json(local)
    staging_data = _load_hooks_json(staging) if staging.is_file() else {"version": 1, "hooks": {}}
    merged: dict[str, Any] = {
        "version": local_data.get("version", staging_data.get("version", 1)),
        "hooks": dict(staging_data.get("hooks", {})),
    }
    for event, local_hooks in local_data.get("hooks", {}).items():
        staged_hooks = list(merged["hooks"].get(event, []))
        by_command = {_hook_command_key(h): h for h in staged_hooks}
        for hook in local_hooks:
            by_command[_hook_command_key(hook)] = hook
        merged["hooks"][event] = list(by_command.values())
    _save_hooks_json(staging, merged)


def _tree_has_local_additions_or_modifications(local: Path, staged: Path) -> bool:
    """True if local has files new or changed vs staged (ignores local deletions)."""
    if not local.exists():
        return False
    if not staged.exists():
        return any(p.is_file() for p in local.rglob("*"))
    for path in local.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(local)
        target = staged / rel
        if not target.is_file() or path.read_bytes() != target.read_bytes():
            return True
    return False


def _hooks_json_has_local_additions_or_modifications(local: Path, staged: Path) -> bool:
    if not local.is_file():
        return False
    if not staged.is_file():
        return True
    local_data = _load_hooks_json(local)
    staging_data = _load_hooks_json(staged)
    local_commands: set[str] = set()
    for hooks in local_data.get("hooks", {}).values():
        for hook in hooks:
            local_commands.add(_hook_command_key(hook))
    staging_by_command: dict[str, dict[str, Any]] = {}
    for hooks in staging_data.get("hooks", {}).values():
        for hook in hooks:
            staging_by_command[_hook_command_key(hook)] = hook
    for event, hooks in local_data.get("hooks", {}).items():
        for hook in hooks:
            key = _hook_command_key(hook)
            if key not in staging_by_command or hook != staging_by_command[key]:
                return True
    return False


def _tree_has_local_deletions(local: Path, staged: Path) -> bool:
    """True if staged has files missing from local."""
    if not staged.exists():
        return False
    if not local.exists():
        return any(p.is_file() for p in staged.rglob("*"))
    for path in staged.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(staged)
        if not (local / rel).is_file():
            return True
    return False


def _hooks_json_has_local_deletions(local: Path, staged: Path) -> bool:
    if not staged.is_file():
        return False
    if not local.is_file():
        return True
    local_commands: set[str] = set()
    for hooks in _load_hooks_json(local).get("hooks", {}).values():
        for hook in hooks:
            local_commands.add(_hook_command_key(hook))
    for hooks in _load_hooks_json(staged).get("hooks", {}).values():
        for hook in hooks:
            if _hook_command_key(hook) not in local_commands:
                return True
    return False


def _uses_merge_export(entry: ProfileEntry) -> bool:
    return entry.category in ("skills", "hooks")


def _entry_state(entry: ProfileEntry, local: Path, staged: Path) -> str:
    if entry.is_dir:
        local_exists = local.is_dir()
        staged_exists = staged.is_dir()
    else:
        local_exists = local.is_file()
        staged_exists = staged.is_file()

    if not local_exists and not staged_exists:
        return "missing"
    if not local_exists:
        return "remote_only"
    if not staged_exists:
        return "local_only"

    if _uses_merge_export(entry):
        if entry.local_name == "hooks.json":
            has_add = _hooks_json_has_local_additions_or_modifications(local, staged)
            has_del = _hooks_json_has_local_deletions(local, staged)
        else:
            has_add = _tree_has_local_additions_or_modifications(local, staged)
            has_del = _tree_has_local_deletions(local, staged)
        if has_add:
            return "differ"
        if has_del:
            return "local_behind"
        return "synced"

    local_fp = _path_fingerprint(local, entry.is_dir)
    staged_fp = _path_fingerprint(staged, entry.is_dir)
    if local_fp == staged_fp:
        return "synced"
    return "differ"


def _backup_path(target: Path) -> None:
    if not target.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = target.with_name(f"{target.name}.bak_{timestamp}")
    if target.is_dir():
        shutil.copytree(target, backup)
    else:
        shutil.copy2(target, backup)
    _prune_backups(target)


def _prune_backups(target: Path) -> None:
    pattern = f"{target.name}.bak_*"
    backups = sorted(
        target.parent.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[BACKUP_KEEP:]:
        if stale.is_dir():
            shutil.rmtree(stale, ignore_errors=True)
        else:
            stale.unlink(missing_ok=True)


def export_profile(profile_dir: Optional[Path] = None) -> int:
    """Copy enabled local Cursor profile files into the staging directory.

    Returns the number of entries exported.
    """
    profile_dir = profile_dir or get_profile_dir()
    exported = 0

    for entry in _enabled_entries():
        src = _local_path(entry)
        dst = _staging_path(profile_dir, entry)

        if entry.is_dir:
            if not src.is_dir():
                if entry.optional:
                    continue
                continue
            if _uses_merge_export(entry):
                _merge_tree(src, dst)
            else:
                _copy_tree(src, dst)
            exported += 1
        else:
            if not src.is_file():
                if entry.optional:
                    continue
                continue
            if entry.category == "hooks" and entry.local_name == "hooks.json":
                _merge_hooks_json_export(src, dst)
            else:
                _copy_file(src, dst)
            exported += 1

    return exported


def apply_profile(profile_dir: Optional[Path] = None, backup: bool = True) -> int:
    """Copy staged profile files back to local Cursor paths.

    Returns the number of entries applied.
    """
    profile_dir = profile_dir or get_profile_dir()
    applied = 0

    for entry in _enabled_entries():
        src = _staging_path(profile_dir, entry)
        dst = _local_path(entry)

        if entry.is_dir:
            if not src.is_dir():
                continue
            if backup and dst.exists():
                _backup_path(dst)
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(src, dst)
            applied += 1
        else:
            if not src.is_file():
                continue
            if backup and dst.exists():
                _backup_path(dst)
            _copy_file(src, dst)
            applied += 1

    return applied


def profile_status(profile_dir: Optional[Path] = None) -> list[dict]:
    """Compare local Cursor paths with the staged profile mirror."""
    profile_dir = profile_dir or get_profile_dir()
    rows: list[dict] = []

    for entry in _enabled_entries():
        local = _local_path(entry)
        staged = _staging_path(profile_dir, entry)
        state = _entry_state(entry, local, staged)

        rows.append(
            {
                "category": entry.category,
                "path": entry.profile_rel,
                "local": str(local),
                "state": state,
            }
        )

    return rows


def profile_has_local_changes(profile_dir: Optional[Path] = None) -> bool:
    """Return True if local Cursor files have pushable changes vs staged profile."""
    return any(row["state"] in ("local_only", "differ") for row in profile_status(profile_dir))


def format_profile_status(rows: list[dict]) -> str:
    """Format profile status rows for CLI output."""
    lines = [f"{'Category':<12} {'State':<12} {'Path'}"]
    lines.append("-" * 60)
    for row in rows:
        if row["state"] == "missing":
            continue
        lines.append(f"{row['category']:<12} {row['state']:<12} {row['path']}")
    return "\n".join(lines)
