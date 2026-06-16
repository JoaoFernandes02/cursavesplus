"""Tests for chat lifecycle and never_pushed auto-push."""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cursor_saves import db, paths, profile
from cursor_saves.backends import GitBackend, save_config
from cursor_saves.chat_lifecycle import (
    apply_retention,
    exclude_composer,
    get_sync_config,
    is_excluded,
    is_pinned,
    pin_composer,
    remove_chats,
    save_sync_config,
)
from cursor_saves.cli import _find_conversations_to_push, _pull_behind
from cursor_saves.importer import get_push_status_for_conversation


class TempEnvMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cursaves-lifecycle-")
        self.root = Path(self._tmp)
        self.sync_dir = self.root / "cursaves"
        self.cursor_dot = self.root / "dot-cursor"
        self.cursor_user = self.root / "cursor-user"
        self.config_dir = self.root / "config"
        self.project_path = self.root / "myproject"
        self.ws_dir = self.root / "ws-hash"

        for d in (self.sync_dir, self.cursor_dot, self.cursor_user, self.project_path, self.ws_dir):
            d.mkdir(parents=True)

        self.patches = [
            mock.patch.object(paths, "get_sync_dir", return_value=self.sync_dir),
            mock.patch.object(paths, "get_snapshots_dir", lambda: self.sync_dir / "snapshots"),
            mock.patch.object(paths, "get_profile_staging_dir", lambda: self.sync_dir / "profile"),
            mock.patch.object(paths, "get_cursor_dot_dir", return_value=self.cursor_dot),
            mock.patch.object(paths, "get_cursor_user_dir", return_value=self.cursor_user),
            mock.patch("cursor_saves.profile.load_config", self._load_config),
            mock.patch("cursor_saves.backends.load_config", self._load_config),
            mock.patch("cursor_saves.backends.save_config", self._save_config),
            mock.patch("cursor_saves.chat_lifecycle.load_config", self._load_config),
            mock.patch("cursor_saves.chat_lifecycle.save_config", self._save_config),
            mock.patch("cursor_saves.backends._CONFIG_PATH", self.config_dir / "config.json"),
        ]
        for p in self.patches:
            p.start()

        self._config = {
            "backend": "git",
            "profile": {"enabled": True, "categories": dict(profile.DEFAULT_CATEGORIES)},
            "sync": {
                "retention_days": 90,
                "retention_purge_local": False,
                "pinned_composers": [],
                "excluded_composers": [],
            },
        }
        save_config(self._config)

    def _load_config(self):
        return dict(self._config)

    def _save_config(self, config):
        self._config = dict(config)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        (self.config_dir / "config.json").write_text(json.dumps(self._config, indent=2))

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_global_db(self, composer_id: str, msg_count: int = 1, name: str = "Test chat") -> Path:
        db_path = self.root / "global.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        data = json.dumps({
            "name": name,
            "fullConversationHeadersOnly": [{"id": f"m{i}"} for i in range(msg_count)],
        })
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"composerData:{composer_id}", data.encode()),
        )
        conn.commit()
        conn.close()
        return db_path

    def _make_workspace_db(self, composer_id: str) -> Path:
        db_path = self.ws_dir / "state.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        headers = json.dumps([{"composerId": composer_id, "name": "Test"}])
        conn.execute(
            "INSERT INTO ItemTable (key, value) VALUES (?, ?)",
            ("composer.composerHeaders", headers.encode()),
        )
        conn.commit()
        conn.close()
        return db_path


class NeverPushedPushTests(TempEnvMixin, unittest.TestCase):
    def test_find_conversations_includes_never_pushed(self):
        cid = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        global_db = self._make_global_db(cid, msg_count=3)
        self._make_workspace_db(cid)
        project_id = "github.com-user-repo"

        with (
            mock.patch.object(paths, "get_global_db_path", return_value=global_db),
            mock.patch.object(
                paths,
                "list_workspaces_with_conversations",
                return_value=[{
                    "path": str(self.project_path),
                    "workspace_dir": self.ws_dir,
                    "host": "",
                }],
            ),
            mock.patch.object(paths, "get_project_identifier", return_value=project_id),
            mock.patch.object(paths, "get_workspace_composer_ids", return_value=[cid]),
        ):
            items = _find_conversations_to_push()
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["composerId"], cid)
            self.assertEqual(items[0]["push_status"], "never_pushed")

    def test_excluded_conversation_not_pushed(self):
        cid = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        exclude_composer(cid)
        global_db = self._make_global_db(cid)
        self._make_workspace_db(cid)

        with (
            mock.patch.object(paths, "get_global_db_path", return_value=global_db),
            mock.patch.object(
                paths,
                "list_workspaces_with_conversations",
                return_value=[{
                    "path": str(self.project_path),
                    "workspace_dir": self.ws_dir,
                    "host": "",
                }],
            ),
            mock.patch.object(paths, "get_project_identifier", return_value="proj"),
            mock.patch.object(paths, "get_workspace_composer_ids", return_value=[cid]),
        ):
            self.assertEqual(_find_conversations_to_push(), [])


class RetentionTests(TempEnvMixin, unittest.TestCase):
    def test_retention_prunes_old_snapshots(self):
        cid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        project = "github.com-a-b"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        (proj_dir / f"{cid}.json.gz").write_bytes(b"\x1f\x8b")
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({
            "composerId": cid,
            "messageCount": 1,
            "exportedAt": old_date,
        }))

        result = apply_retention()
        self.assertEqual(result.pruned, 1)
        self.assertFalse((proj_dir / f"{cid}.meta.json").exists())

    def test_pinned_skips_retention(self):
        cid = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        pin_composer(cid)
        project = "github.com-a-b"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        (proj_dir / f"{cid}.json.gz").write_bytes(b"\x1f\x8b")
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({
            "composerId": cid,
            "messageCount": 1,
            "exportedAt": old_date,
        }))

        result = apply_retention()
        self.assertEqual(result.pruned, 0)
        self.assertEqual(result.skipped_pinned, 1)
        self.assertTrue((proj_dir / f"{cid}.meta.json").exists())

    def test_retention_off_when_zero_days(self):
        save_sync_config({"retention_days": 0})
        cid = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        project = "github.com-a-b"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        old_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
        (proj_dir / f"{cid}.json.gz").write_bytes(b"\x1f\x8b")
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({
            "composerId": cid,
            "messageCount": 1,
            "exportedAt": old_date,
        }))
        self.assertEqual(apply_retention().pruned, 0)


class RemoveTests(TempEnvMixin, unittest.TestCase):
    def test_remove_deletes_snapshot_and_excludes(self):
        cid = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        project = "github.com-x-y"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        (proj_dir / f"{cid}.json.gz").write_bytes(b"\x1f\x8b")
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({"composerId": cid, "messageCount": 1}))

        with mock.patch("cursor_saves.chat_lifecycle.purge_chats", return_value=(1, 5)):
            with mock.patch("cursor_saves.chat_lifecycle.get_backend") as mock_backend:
                backend = mock.Mock()
                backend.has_remote.return_value = False
                mock_backend.return_value = backend
                result = remove_chats([cid], purge_local=True, push_remote=False)

        self.assertEqual(result.removed_snapshots, 1)
        self.assertEqual(result.excluded, 1)
        self.assertTrue(is_excluded(cid))
        self.assertFalse((proj_dir / f"{cid}.meta.json").exists())


class PullBehindExcludeTests(TempEnvMixin, unittest.TestCase):
    def test_excluded_snapshot_not_imported(self):
        cid = "11111111-2222-3333-4444-555555555555"
        exclude_composer(cid)
        project = "github.com-x-y"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        (proj_dir / f"{cid}.json.gz").write_bytes(b"\x1f\x8b")
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({
            "composerId": cid,
            "messageCount": 5,
            "sourceProjectPath": str(self.project_path),
        }))

        with mock.patch("cursor_saves.cli.import_snapshot") as mock_import:
            imported = _pull_behind(self.sync_dir)
            mock_import.assert_not_called()
            self.assertEqual(imported, 0)


class ProfileRulesTests(TempEnvMixin, unittest.TestCase):
    def test_rules_export_apply_roundtrip(self):
        rules_dir = self.cursor_dot / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "my-rule.mdc").write_text("# Rule\n")

        n = profile.export_profile()
        self.assertGreaterEqual(n, 1)
        staged = self.sync_dir / "profile" / "cursor" / "rules" / "my-rule.mdc"
        self.assertTrue(staged.exists())

        shutil.rmtree(rules_dir)
        profile.apply_profile()
        self.assertTrue((self.cursor_dot / "rules" / "my-rule.mdc").exists())


class TwoMachinePullTests(TempEnvMixin, unittest.TestCase):
    def test_never_pushed_status_for_new_project(self):
        cid = "99999999-9999-9999-9999-999999999999"
        db_path = self._make_global_db(cid, msg_count=2)
        project = "github.com-new-project"

        with db.CursorDB(db_path) as cdb:
            status = get_push_status_for_conversation(cid, project, _cdb=cdb)
            self.assertEqual(status, "never_pushed")


class SyncConfigTests(TempEnvMixin, unittest.TestCase):
    def test_pin_roundtrip(self):
        cid = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee"
        pin_composer(cid)
        self.assertTrue(is_pinned(cid))
        sync = get_sync_config()
        self.assertIn(cid, sync["pinned_composers"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
