"""Integration tests for sync flow (profile + git backend + chat status).

Excludes setup wizard tests. Uses isolated temp directories.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from cursor_saves import paths, profile
from cursor_saves.backends import GitBackend, load_config, save_config
from cursor_saves.importer import (
    format_sync_status,
    get_push_status_for_conversation,
    get_sync_status_for_snapshot,
    list_snapshot_projects,
    read_snapshot_meta,
)
from cursor_saves import db


class TempEnvMixin:
    """Patch cursaves paths to isolated temp directories."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cursaves-test-")
        self.root = Path(self._tmp)
        self.sync_dir = self.root / "cursaves"
        self.cursor_dot = self.root / "dot-cursor"
        self.cursor_user = self.root / "cursor-user"
        self.config_dir = self.root / "config"

        self.sync_dir.mkdir()
        self.cursor_dot.mkdir()
        self.cursor_user.mkdir()
        (self.cursor_user / "snippets").mkdir()

        self.patches = [
            mock.patch.object(paths, "get_sync_dir", return_value=self.sync_dir),
            mock.patch.object(paths, "get_snapshots_dir", lambda: self.sync_dir / "snapshots"),
            mock.patch.object(paths, "get_profile_staging_dir", lambda: self.sync_dir / "profile"),
            mock.patch.object(paths, "get_cursor_dot_dir", return_value=self.cursor_dot),
            mock.patch.object(paths, "get_cursor_user_dir", return_value=self.cursor_user),
            mock.patch("cursor_saves.profile.load_config", self._load_config),
            mock.patch("cursor_saves.backends._CONFIG_PATH", self.config_dir / "config.json"),
        ]
        for p in self.patches:
            p.start()

        self._config = {
            "backend": "git",
            "profile": {
                "enabled": True,
                "categories": dict(profile.DEFAULT_CATEGORIES),
            },
        }
        save_config(self._config)

    def _load_config(self):
        return dict(self._config)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self._tmp, ignore_errors=True)


class ProfileSyncTests(TempEnvMixin, unittest.TestCase):
    def test_export_apply_roundtrip_settings(self):
        settings = self.cursor_user / "settings.json"
        settings.write_text('{"editor.fontSize": 14}\n')

        self.assertTrue(profile.profile_has_local_changes())
        n = profile.export_profile()
        self.assertGreaterEqual(n, 1)
        self.assertFalse(profile.profile_has_local_changes())

        settings.write_text('{"editor.fontSize": 99}\n')
        self.assertTrue(profile.profile_has_local_changes())

        applied = profile.apply_profile()
        self.assertGreaterEqual(applied, 1)
        self.assertEqual(json.loads(settings.read_text())["editor.fontSize"], 14)

    def test_optional_keybindings_missing(self):
        rows = profile.profile_status()
        kb = [r for r in rows if r["path"] == "user/keybindings.json"][0]
        self.assertEqual(kb["state"], "missing")

        profile.export_profile()
        kb = [r for r in rows if r["path"] == "user/keybindings.json"]
        # still missing locally — export skips optional absent files
        self.assertFalse((self.sync_dir / "profile" / "user" / "keybindings.json").exists())

    def test_skills_tree_sync(self):
        skill_dir = self.cursor_dot / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My skill\n")

        profile.export_profile()
        staged = self.sync_dir / "profile" / "cursor" / "skills" / "my-skill" / "SKILL.md"
        self.assertTrue(staged.exists())

        shutil.rmtree(self.cursor_dot / "skills")
        profile.apply_profile()
        self.assertTrue((self.cursor_dot / "skills" / "my-skill" / "SKILL.md").exists())

    def test_skills_cursor_not_in_catalog(self):
        builtin = self.cursor_dot / "skills-cursor" / "canvas"
        builtin.mkdir(parents=True)
        (builtin / "SKILL.md").write_text("builtin")

        profile.export_profile()
        self.assertFalse((self.sync_dir / "profile" / "cursor" / "skills-cursor").exists())

    def test_mcp_disabled_by_default(self):
        mcp = self.cursor_dot / "mcps" / "server"
        mcp.mkdir(parents=True)
        (mcp / "config.json").write_text("{}")

        profile.export_profile()
        self.assertFalse((self.sync_dir / "profile" / "cursor" / "mcps").exists())

        self._config["profile"]["categories"]["mcp"] = True
        profile.export_profile()
        self.assertTrue((self.sync_dir / "profile" / "cursor" / "mcps" / "server" / "config.json").exists())

    def test_apply_creates_backup(self):
        settings = self.cursor_user / "settings.json"
        settings.write_text('{"local": true}\n')
        staged = self.sync_dir / "profile" / "user" / "settings.json"
        staged.parent.mkdir(parents=True)
        staged.write_text('{"remote": true}\n')

        profile.apply_profile()
        backups = list(self.cursor_user.glob("settings.json.bak_*"))
        self.assertGreaterEqual(len(backups), 1)
        self.assertEqual(json.loads(settings.read_text())["remote"], True)

    def test_profile_disabled_via_config(self):
        self._config["profile"]["enabled"] = False
        self.assertFalse(profile.is_profile_enabled())


class GitBackendSyncTests(TempEnvMixin, unittest.TestCase):
    def _init_git_with_remote(self) -> Path:
        bare = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
        backend = GitBackend(self.sync_dir)
        backend.init_repo(remote=str(bare))
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.sync_dir, check=True, capture_output=True)
        return bare

    def test_init_creates_snapshots_and_profile(self):
        backend = GitBackend(self.sync_dir)
        backend.init_repo()
        self.assertTrue((self.sync_dir / "snapshots").is_dir())
        self.assertTrue((self.sync_dir / "profile").is_dir())
        self.assertTrue((self.sync_dir / ".git").exists())

    def test_push_includes_profile_and_snapshots(self):
        bare = self._init_git_with_remote()
        (self.sync_dir / "profile" / "user").mkdir(parents=True)
        (self.sync_dir / "profile" / "user" / "settings.json").write_text("{}")
        (self.sync_dir / "snapshots" / "proj").mkdir(parents=True)
        (self.sync_dir / "snapshots" / "proj" / "abc.meta.json").write_text('{"composerId":"abc"}')

        backend = GitBackend(self.sync_dir)
        snapshots_dir = paths.get_snapshots_dir()
        self.assertTrue(backend.push(snapshots_dir))

        clone = self.root / "clone"
        subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
        self.assertTrue((clone / "profile" / "user" / "settings.json").exists())
        self.assertTrue((clone / "snapshots" / "proj" / "abc.meta.json").exists())

    def test_push_profile_only(self):
        bare = self._init_git_with_remote()
        (self.sync_dir / "profile" / "user").mkdir(parents=True)
        (self.sync_dir / "profile" / "user" / "settings.json").write_text('{"a":1}')

        backend = GitBackend(self.sync_dir)
        self.assertTrue(backend.push_profile(paths.get_snapshots_dir()))

        clone = self.root / "clone-profile"
        subprocess.run(["git", "clone", str(bare), str(clone)], check=True, capture_output=True)
        self.assertTrue((clone / "profile" / "user" / "settings.json").exists())

    def test_pull_hard_reset_restores_remote_profile(self):
        bare = self._init_git_with_remote()
        (self.sync_dir / "profile" / "user").mkdir(parents=True)
        (self.sync_dir / "profile" / "user" / "settings.json").write_text('{"remote":true}')
        backend = GitBackend(self.sync_dir)
        backend.push_profile(paths.get_snapshots_dir())

        (self.sync_dir / "profile" / "user" / "settings.json").write_text('{"local_dirty":true}')
        self.assertIn("local_dirty", (self.sync_dir / "profile" / "user" / "settings.json").read_text())

        backend.pull(paths.get_snapshots_dir())
        self.assertIn("remote", (self.sync_dir / "profile" / "user" / "settings.json").read_text())

    def test_idempotent_push_no_changes(self):
        bare = self._init_git_with_remote()
        backend = GitBackend(self.sync_dir)
        snapshots = paths.get_snapshots_dir()
        self.assertTrue(backend.push(snapshots))
        self.assertTrue(backend.push(snapshots))

    def test_two_machine_profile_flow(self):
        bare = self._init_git_with_remote()

        # Machine A: local edit -> export -> push
        settings_a = self.cursor_user / "settings.json"
        settings_a.write_text('{"team": "shared"}\n')
        profile.export_profile()
        GitBackend(self.sync_dir).push_profile(paths.get_snapshots_dir())

        # Machine B: separate sync dir, init, pull, apply
        machine_b = self.root / "machine-b"
        machine_b.mkdir()
        cursor_b = self.root / "cursor-b"
        cursor_b.mkdir()
        with mock.patch.object(paths, "get_sync_dir", return_value=machine_b):
            with mock.patch.object(paths, "get_snapshots_dir", lambda: machine_b / "snapshots"):
                with mock.patch.object(paths, "get_profile_staging_dir", lambda: machine_b / "profile"):
                    with mock.patch.object(paths, "get_cursor_user_dir", return_value=cursor_b):
                        GitBackend(machine_b).init_repo(remote=str(bare))
                        GitBackend(machine_b).pull(paths.get_snapshots_dir())
                        applied = profile.apply_profile(profile_dir=machine_b / "profile")
                        self.assertGreaterEqual(applied, 1)
                        self.assertIn("shared", (cursor_b / "settings.json").read_text())


class SyncStatusTests(unittest.TestCase):
    def _make_db_with_composer(self, composer_id: str, msg_count: int) -> Path:
        tmp = tempfile.mkdtemp(prefix="cursaves-db-")
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        db_path = Path(tmp) / "state.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        data = json.dumps({"fullConversationHeadersOnly": [{"id": f"m{i}"} for i in range(msg_count)]})
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"composerData:{composer_id}", data.encode()),
        )
        conn.commit()
        conn.close()
        return db_path

    def test_sync_status_matrix(self):
        cid = "11111111-1111-1111-1111-111111111111"
        db_path = self._make_db_with_composer(cid, 5)
        with db.CursorDB(db_path) as cdb:
            self.assertEqual(get_sync_status_for_snapshot(cid, 5, _cdb=cdb), "up_to_date")
            self.assertEqual(get_sync_status_for_snapshot(cid, 3, _cdb=cdb), "local_ahead")
            self.assertEqual(get_sync_status_for_snapshot(cid, 7, _cdb=cdb), "behind")
            self.assertEqual(get_sync_status_for_snapshot("missing-id", 1, _cdb=cdb), "not_local")

    def test_format_sync_status_labels(self):
        self.assertEqual(format_sync_status("local_ahead"), "ahead")
        self.assertEqual(format_sync_status("behind"), "behind")


class PushStatusTests(TempEnvMixin, unittest.TestCase):
    def test_never_pushed_without_snapshot(self):
        cid = "22222222-2222-2222-2222-222222222222"
        db_path = Path(tempfile.mkdtemp()) / "state.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        data = json.dumps({"fullConversationHeadersOnly": [{"id": "m1"}]})
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"composerData:{cid}", data.encode()),
        )
        conn.commit()
        conn.close()

        with mock.patch.object(paths, "get_global_db_path", return_value=db_path):
            self.assertEqual(get_push_status_for_conversation(cid, "no-such-project"), "never_pushed")

    def test_up_to_date_with_meta(self):
        cid = "33333333-3333-3333-3333-333333333333"
        project = "github.com-team-repo"
        proj_dir = paths.get_snapshots_dir() / project
        proj_dir.mkdir(parents=True)
        (proj_dir / f"{cid}.meta.json").write_text(json.dumps({"composerId": cid, "messageCount": 2}))

        db_path = Path(tempfile.mkdtemp()) / "state.vscdb"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE cursorDiskKV (key TEXT PRIMARY KEY, value BLOB)")
        data = json.dumps({"fullConversationHeadersOnly": [{"id": "m1"}, {"id": "m2"}]})
        conn.execute(
            "INSERT INTO cursorDiskKV (key, value) VALUES (?, ?)",
            (f"composerData:{cid}", data.encode()),
        )
        conn.commit()
        conn.close()

        with db.CursorDB(db_path) as cdb:
            self.assertEqual(get_push_status_for_conversation(cid, project, _cdb=cdb), "up_to_date")


class CliSyncFlowTests(TempEnvMixin, unittest.TestCase):
    def test_profile_sync_enabled_flag(self):
        from cursor_saves.cli import _profile_sync_enabled

        self.assertTrue(_profile_sync_enabled(Namespace(no_profile=False)))
        self.assertFalse(_profile_sync_enabled(Namespace(no_profile=True)))

    def test_sync_state_persistence(self):
        from cursor_saves.cli import _load_sync_state, _save_sync_state, _get_sync_state_path

        with mock.patch("cursor_saves.cli._get_sync_state_path") as mock_path:
            state_file = self.config_dir / "sync_state.json"
            mock_path.return_value = state_file
            _save_sync_state({"handled_diverged": {"abc": 10}})
            loaded = _load_sync_state()
            self.assertEqual(loaded["handled_diverged"]["abc"], 10)

    def test_cmd_sync_no_profile_skips_profile_steps(self):
        from cursor_saves.cli import _configure_stdio, cmd_sync

        _configure_stdio()
        bare = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)
        GitBackend(self.sync_dir).init_repo(remote=str(bare))
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.sync_dir, check=True, capture_output=True)

        with mock.patch("cursor_saves.cli._profile_export_push") as mock_export:
            with mock.patch("cursor_saves.cli._profile_apply_after_pull") as mock_apply:
                with mock.patch("cursor_saves.cli._pull_behind", return_value=0):
                    with mock.patch("cursor_saves.cli._push_ahead", return_value=0):
                        with mock.patch("cursor_saves.cli.get_backend") as mock_backend:
                            backend = GitBackend(self.sync_dir)
                            mock_backend.return_value = backend
                            cmd_sync(Namespace(no_profile=True))
                            mock_export.assert_not_called()
                            mock_apply.assert_not_called()


class SnapshotListingTests(TempEnvMixin, unittest.TestCase):
    def test_list_snapshot_projects_empty(self):
        paths.get_snapshots_dir().mkdir(parents=True, exist_ok=True)
        self.assertEqual(list_snapshot_projects(), [])

    def test_list_snapshot_projects_with_meta(self):
        proj = paths.get_snapshots_dir() / "github.com-a-b"
        proj.mkdir(parents=True)
        cid = "44444444-4444-4444-4444-444444444444"
        snapshot = proj / f"{cid}.json.gz"
        snapshot.write_bytes(b"\x1f\x8b")  # placeholder snapshot file
        (proj / f"{cid}.meta.json").write_text(
            json.dumps({"composerId": cid, "messageCount": 1, "sourceProjectPath": "/tmp/p"})
        )
        projects = list_snapshot_projects()
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["name"], "github.com-a-b")
        self.assertEqual(projects[0]["count"], 1)


class PullBehindEdgeCaseTests(TempEnvMixin, unittest.TestCase):
    def test_handled_diverged_skips_reimport(self):
        from cursor_saves.cli import _load_sync_state, _pull_behind, _save_sync_state, _get_sync_state_path

        cid = "55555555-5555-5555-5555-555555555555"
        proj = paths.get_snapshots_dir() / "github.com-x-y"
        proj.mkdir(parents=True)
        snapshot = proj / f"{cid}.json.gz"
        snapshot.write_bytes(b"\x1f\x8b")
        (proj / f"{cid}.meta.json").write_text(
            json.dumps({
                "composerId": cid,
                "messageCount": 5,
                "sourceProjectPath": str(self.root / "fake-project"),
            })
        )

        state_file = self.config_dir / "sync_state.json"
        with mock.patch("cursor_saves.cli._get_sync_state_path", return_value=state_file):
            _save_sync_state({"handled_diverged": {cid: 5}})
            with mock.patch("cursor_saves.cli.import_snapshot") as mock_import:
                imported = _pull_behind(self.sync_dir)
                mock_import.assert_not_called()
                self.assertEqual(imported, 0)


class ProfileCliEdgeCaseTests(TempEnvMixin, unittest.TestCase):
    def test_profile_push_without_remote(self):
        from cursor_saves.cli import cmd_profile_push

        GitBackend(self.sync_dir).init_repo()
        (self.cursor_user / "settings.json").write_text('{"x": 1}')
        cmd_profile_push(Namespace())
        self.assertTrue((self.sync_dir / "profile" / "user" / "settings.json").exists())

    def test_profile_pull_applies_staged(self):
        from cursor_saves.cli import cmd_profile_pull

        GitBackend(self.sync_dir).init_repo()
        staged = self.sync_dir / "profile" / "user" / "settings.json"
        staged.parent.mkdir(parents=True)
        staged.write_text('{"from": "remote"}\n')

        with mock.patch("cursor_saves.cli.get_backend") as mock_backend:
            backend = GitBackend(self.sync_dir)
            mock_backend.return_value = backend
            cmd_profile_pull(Namespace())
        self.assertIn("remote", (self.cursor_user / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
