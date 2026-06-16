"""Chat lifecycle: remove, pin, exclude, and retention pruning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import paths
from .backends import get_backend, load_config, save_config
from .importer import (
    list_snapshot_files,
    list_snapshot_projects,
    purge_chats,
    read_snapshot_meta,
)

DEFAULT_SYNC_CONFIG = {
    "retention_days": 90,
    "retention_purge_local": False,
    "pinned_composers": [],
    "excluded_composers": [],
}


def get_sync_config() -> dict:
    """Return merged sync lifecycle configuration."""
    config = load_config()
    sync = dict(config.get("sync", {}))
    merged = {**DEFAULT_SYNC_CONFIG, **sync}
    for key in ("pinned_composers", "excluded_composers"):
        if not merged.get(key):
            merged[key] = []
    return merged


def save_sync_config(updates: dict) -> dict:
    """Merge updates into config sync section and persist."""
    config = load_config()
    sync = get_sync_config()
    sync.update(updates)
    config["sync"] = sync
    save_config(config)
    return sync


def is_excluded(composer_id: str) -> bool:
    return composer_id in get_sync_config().get("excluded_composers", [])


def is_pinned(composer_id: str) -> bool:
    return composer_id in get_sync_config().get("pinned_composers", [])


def pin_composer(composer_id: str) -> None:
    sync = get_sync_config()
    pinned = list(sync["pinned_composers"])
    if composer_id not in pinned:
        pinned.append(composer_id)
    save_sync_config({"pinned_composers": pinned})


def unpin_composer(composer_id: str) -> None:
    sync = get_sync_config()
    pinned = [c for c in sync["pinned_composers"] if c != composer_id]
    save_sync_config({"pinned_composers": pinned})


def exclude_composer(composer_id: str) -> None:
    sync = get_sync_config()
    excluded = list(sync["excluded_composers"])
    if composer_id not in excluded:
        excluded.append(composer_id)
    save_sync_config({"excluded_composers": excluded})


def unexclude_composer(composer_id: str) -> None:
    sync = get_sync_config()
    excluded = [c for c in sync["excluded_composers"] if c != composer_id]
    save_sync_config({"excluded_composers": excluded})


def _snapshot_id_from_path(path: Path) -> str:
    name = path.name
    if name.endswith(".json.gz"):
        return name[:-8]
    if name.endswith(".json"):
        return name[:-5]
    return path.stem


def delete_snapshot_file(snapshot_path: Path) -> bool:
    """Delete a snapshot file (or shards) and metadata sidecar."""
    if not snapshot_path.parent.exists():
        return False
    sid = _snapshot_id_from_path(snapshot_path)
    deleted = False
    if snapshot_path.exists():
        snapshot_path.unlink()
        deleted = True
    for shard in snapshot_path.parent.glob(f"{sid}.json.gz.*"):
        if not shard.name.endswith(".meta.json"):
            shard.unlink()
            deleted = True
    meta = snapshot_path.parent / f"{sid}.meta.json"
    if meta.exists():
        meta.unlink()
        deleted = True
    return deleted


def find_snapshot_path(composer_id: str) -> Optional[tuple[Path, str]]:
    """Return (snapshot_path, project_id) for a composer, or None."""
    snapshots_dir = paths.get_snapshots_dir()
    for project in list_snapshot_projects(snapshots_dir):
        meta_path = project["path"] / f"{composer_id}.meta.json"
        if meta_path.exists():
            gz = project["path"] / f"{composer_id}.json.gz"
            plain = project["path"] / f"{composer_id}.json"
            snapshot_path = gz if gz.exists() or not plain.exists() else plain
            return snapshot_path, project["name"]
        for sf in list_snapshot_files(project["path"]):
            meta = read_snapshot_meta(sf)
            if meta.get("composerId") == composer_id:
                return sf, project["name"]
    return None


@dataclass
class RemoveResult:
    removed_snapshots: int = 0
    purged_local: int = 0
    excluded: int = 0


def remove_chats(
    composer_ids: list[str],
    *,
    purge_local: bool = True,
    push_remote: bool = True,
    force: bool = False,
) -> RemoveResult:
    """Remove chats from sync repo and optionally from Cursor; mark as excluded."""
    result = RemoveResult()
    if not composer_ids:
        return result

    backend = get_backend()
    snapshots_dir = paths.get_snapshots_dir()
    if push_remote and backend.has_remote():
        backend.pull(snapshots_dir)

    for cid in composer_ids:
        found = find_snapshot_path(cid)
        if found:
            snapshot_path, _ = found
            if delete_snapshot_file(snapshot_path):
                result.removed_snapshots += 1
        exclude_composer(cid)
        result.excluded += 1

    if purge_local:
        deleted, _ = purge_chats(composer_ids, force=force)
        result.purged_local = deleted

    if push_remote and result.removed_snapshots > 0 and backend.has_remote():
        backend.push(snapshots_dir)

    return result


def _snapshot_age_days(exported_at: Optional[str]) -> Optional[float]:
    if not exported_at:
        return None
    try:
        dt = datetime.fromisoformat(exported_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    except (ValueError, TypeError):
        return None


@dataclass
class RetentionResult:
    pruned: int = 0
    skipped_pinned: int = 0
    skipped_excluded: int = 0


def apply_retention(*, dry_run: bool = False) -> RetentionResult:
    """Delete snapshot files older than retention_days (unless pinned/excluded)."""
    sync = get_sync_config()
    days = sync.get("retention_days", 90)
    if not days or days <= 0:
        return RetentionResult()

    result = RetentionResult()
    snapshots_dir = paths.get_snapshots_dir()
    for project in list_snapshot_projects(snapshots_dir):
        for sf in list_snapshot_files(project["path"]):
            meta = read_snapshot_meta(sf)
            cid = meta.get("composerId") or _snapshot_id_from_path(sf)
            if not cid:
                continue
            if is_pinned(cid):
                result.skipped_pinned += 1
                continue
            if is_excluded(cid):
                result.skipped_excluded += 1
                continue
            age = _snapshot_age_days(meta.get("exportedAt"))
            if age is None or age <= days:
                continue
            if dry_run:
                result.pruned += 1
            elif delete_snapshot_file(sf):
                result.pruned += 1

    return result
