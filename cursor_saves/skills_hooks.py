"""List and delete Cursor skills and hooks in the sync repo."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

from . import paths, profile
from .backends import get_backend
from .hook_install import HOOK_SCRIPT_STEM

PROTECTED_HOOK_SCRIPTS = {f"{HOOK_SCRIPT_STEM}.sh", f"{HOOK_SCRIPT_STEM}.ps1"}


def _skills_local_dir() -> Path:
    return paths.get_cursor_dot_dir() / "skills"


def _skills_staging_dir() -> Path:
    return profile.get_profile_dir() / "cursor" / "skills"


def _hooks_local_dir() -> Path:
    return paths.get_cursor_dot_dir() / "hooks"


def _hooks_staging_dir() -> Path:
    return profile.get_profile_dir() / "cursor" / "hooks"


def _hooks_json_local() -> Path:
    return paths.get_cursor_dot_dir() / "hooks.json"


def _hooks_json_staging() -> Path:
    return profile.get_profile_dir() / "cursor" / "hooks.json"


def _skill_state(name: str) -> str:
    local = _skills_local_dir() / name
    staged = _skills_staging_dir() / name
    local_exists = local.is_dir()
    staged_exists = staged.is_dir()
    if local_exists and staged_exists:
        if profile._tree_has_local_additions_or_modifications(local, staged):
            return "differ"
        if profile._tree_has_local_deletions(local, staged):
            return "local_behind"
        return "synced"
    if staged_exists:
        return "local_behind" if not local_exists else "synced"
    if local_exists:
        return "pending"
    return "missing"


def list_skills() -> list[dict[str, str]]:
    """List skills from staging (repo) plus local-only pending items."""
    local_root = _skills_local_dir()
    staged_root = _skills_staging_dir()
    names: set[str] = set()
    if staged_root.is_dir():
        names.update(p.name for p in staged_root.iterdir() if p.is_dir())
    if local_root.is_dir():
        names.update(p.name for p in local_root.iterdir() if p.is_dir())
    rows = []
    for name in sorted(names):
        rows.append({"name": name, "state": _skill_state(name)})
    return rows


def _is_protected_hook_script(name: str) -> bool:
    return name in PROTECTED_HOOK_SCRIPTS or HOOK_SCRIPT_STEM in name


def _hook_script_state(name: str) -> str:
    local = _hooks_local_dir() / name
    staged = _hooks_staging_dir() / name
    if local.is_file() and staged.is_file():
        if local.read_bytes() != staged.read_bytes():
            return "differ"
        return "synced"
    if staged.is_file():
        return "local_behind"
    if local.is_file():
        return "pending"
    return "missing"


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


def _hook_json_state(command: str) -> str:
    local = _hooks_json_local()
    staged = _hooks_json_staging()
    local_data = _load_hooks_json(local)
    staged_data = _load_hooks_json(staged)
    local_hook = None
    staged_hook = None
    for hooks in local_data.get("hooks", {}).values():
        for hook in hooks:
            if hook.get("command") == command:
                local_hook = hook
    for hooks in staged_data.get("hooks", {}).values():
        for hook in hooks:
            if hook.get("command") == command:
                staged_hook = hook
    if local_hook is not None and staged_hook is not None:
        return "synced" if local_hook == staged_hook else "differ"
    if staged_hook is not None:
        return "local_behind"
    if local_hook is not None:
        return "pending"
    return "missing"


def list_hooks() -> list[dict[str, str]]:
    """List hook scripts and hooks.json entries (excluding cursaves auto-sync)."""
    rows: list[dict[str, str]] = []
    seen_scripts: set[str] = set()
    local_hooks = _hooks_local_dir()
    staged_hooks = _hooks_staging_dir()
    script_names: set[str] = set()
    if staged_hooks.is_dir():
        script_names.update(p.name for p in staged_hooks.iterdir() if p.is_file())
    if local_hooks.is_dir():
        script_names.update(p.name for p in local_hooks.iterdir() if p.is_file())
    for name in sorted(script_names):
        if _is_protected_hook_script(name):
            continue
        seen_scripts.add(name)
        rows.append({
            "name": name,
            "kind": "script",
            "state": _hook_script_state(name),
        })

    commands: set[str] = set()
    for path in (_hooks_json_staging(), _hooks_json_local()):
        data = _load_hooks_json(path)
        for hooks in data.get("hooks", {}).values():
            for hook in hooks:
                cmd = str(hook.get("command", ""))
                if not cmd or HOOK_SCRIPT_STEM in cmd:
                    continue
                script_name = Path(cmd).name
                if script_name in seen_scripts:
                    continue
                commands.add(cmd)
    for command in sorted(commands):
        rows.append({
            "name": command,
            "kind": "hooks.json",
            "state": _hook_json_state(command),
        })
    return rows


def _push_profile_changes() -> bool:
    backend = get_backend()
    snapshots_dir = paths.get_snapshots_dir()
    profile.export_profile()
    if backend.has_remote():
        return backend.push_profile(snapshots_dir)
    return True


def delete_skill(name: str) -> bool:
    """Remove a skill from local, staging, and remote repo."""
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return False
    local = _skills_local_dir() / name
    staged = _skills_staging_dir() / name
    deleted = False
    if local.is_dir():
        shutil.rmtree(local)
        deleted = True
    if staged.is_dir():
        shutil.rmtree(staged)
        deleted = True
    if not deleted:
        return False
    return _push_profile_changes()


def _remove_hook_from_json(path: Path, identifier: str) -> bool:
    if not path.is_file():
        return False
    data = _load_hooks_json(path)
    changed = False
    for event, hooks in list(data.get("hooks", {}).items()):
        filtered = [h for h in hooks if h.get("command") != identifier]
        if len(filtered) != len(hooks):
            changed = True
            if filtered:
                data["hooks"][event] = filtered
            else:
                del data["hooks"][event]
    if changed:
        if data.get("hooks"):
            _save_hooks_json(path, data)
        else:
            path.unlink(missing_ok=True)
    return changed


def delete_hook(name: str) -> bool:
    """Remove a hook script or hooks.json entry from local, staging, and remote."""
    if not name or _is_protected_hook_script(Path(name).name):
        return False

    deleted = False
    local_script = _hooks_local_dir() / name
    staged_script = _hooks_staging_dir() / name
    if local_script.is_file():
        local_script.unlink()
        deleted = True
    if staged_script.is_file():
        staged_script.unlink()
        deleted = True

    identifier = name if name.startswith("./") else f"./hooks/{name}"
    if _remove_hook_from_json(_hooks_json_local(), identifier):
        deleted = True
    if _remove_hook_from_json(_hooks_json_local(), name):
        deleted = True
    if _remove_hook_from_json(_hooks_json_staging(), identifier):
        deleted = True
    if _remove_hook_from_json(_hooks_json_staging(), name):
        deleted = True

    if not deleted:
        return False
    return _push_profile_changes()


def format_skills_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "No skills found."
    lines = [f"{'Name':<24} {'State'}"]
    lines.append("-" * 40)
    for row in rows:
        lines.append(f"{row['name']:<24} {row['state']}")
    return "\n".join(lines)


def format_hooks_list(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "No hooks found."
    lines = [f"{'Name':<32} {'Kind':<12} {'State'}"]
    lines.append("-" * 56)
    for row in rows:
        lines.append(f"{row['name']:<32} {row['kind']:<12} {row['state']}")
    return "\n".join(lines)
