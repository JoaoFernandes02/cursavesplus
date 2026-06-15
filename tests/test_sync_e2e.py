"""End-to-end sync orchestration tests via subprocess-style flow."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cursor_saves import paths, profile
from cursor_saves.backends import GitBackend


class SyncOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cursaves-e2e-")
        self.root = Path(self._tmp)
        self.sync_a = self.root / "machine-a"
        self.sync_b = self.root / "machine-b"
        self.cursor_a = self.root / "cursor-a"
        self.cursor_b = self.root / "cursor-b"
        self.bare = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.bare)], check=True, capture_output=True)

        for d in (self.sync_a, self.sync_b, self.cursor_a, self.cursor_b):
            d.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _machine(self, sync_dir, cursor_user, cursor_dot=None):
        cursor_dot = cursor_dot or cursor_user.parent / f"dot-{cursor_user.name}"
        cursor_dot.mkdir(exist_ok=True)
        return mock.patch.multiple(
            paths,
            get_sync_dir=lambda sd=sync_dir: sd,
            get_snapshots_dir=lambda sd=sync_dir: sd / "snapshots",
            get_profile_staging_dir=lambda sd=sync_dir: sd / "profile",
            get_cursor_user_dir=lambda cu=cursor_user: cu,
            get_cursor_dot_dir=lambda cd=cursor_dot: cd,
        )

    def test_full_profile_sync_cycle_machine_a_to_b(self):
        """Simulates: A edits -> export/push -> B pull -> apply."""
        from cursor_saves.cli import _profile_apply_after_pull, _profile_export_push
        from cursor_saves.backends import get_backend

        GitBackend(self.sync_a).init_repo(remote=str(self.bare))
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.sync_a, check=True, capture_output=True)

        (self.cursor_a / "settings.json").write_text('{"machine": "A"}\n')
        (self.cursor_a / "snippets").mkdir(exist_ok=True)

        with self._machine(self.sync_a, self.cursor_a):
            backend = GitBackend(self.sync_a)
            with mock.patch("cursor_saves.cli.get_backend", return_value=backend):
                self.assertTrue(_profile_export_push(backend, paths.get_snapshots_dir()))

        GitBackend(self.sync_b).init_repo(remote=str(self.bare))
        with self._machine(self.sync_b, self.cursor_b):
            backend_b = GitBackend(self.sync_b)
            backend_b.pull(paths.get_snapshots_dir())
            applied = _profile_apply_after_pull()
            self.assertGreaterEqual(applied, 1)
            self.assertIn('"A"', (self.cursor_b / "settings.json").read_text())

    def test_sync_with_empty_remote_repo(self):
        """B initializes from empty remote — apply should not crash."""
        GitBackend(self.sync_a).init_repo(remote=str(self.bare))
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.sync_a, check=True, capture_output=True)

        GitBackend(self.sync_b).init_repo(remote=str(self.bare))
        with self._machine(self.sync_b, self.cursor_b):
            backend_b = GitBackend(self.sync_b)
            self.assertTrue(backend_b.pull(paths.get_snapshots_dir()))
            applied = profile.apply_profile(profile_dir=self.sync_b / "profile")
            self.assertEqual(applied, 0)

    def test_local_ahead_profile_not_lost_before_push(self):
        """Export-before-pull: local profile changes should be pushable."""
        GitBackend(self.sync_a).init_repo(remote=str(self.bare))
        (self.sync_a / "profile" / "user").mkdir(parents=True)
        (self.sync_a / "profile" / "user" / "settings.json").write_text('{"old": true}')
        subprocess.run(["git", "add", "."], cwd=self.sync_a, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=self.sync_a, check=True, capture_output=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.sync_a, check=True, capture_output=True)

        (self.cursor_a / "settings.json").write_text('{"new_local": true}\n')
        with self._machine(self.sync_a, self.cursor_a):
            self.assertTrue(profile.profile_has_local_changes())
            profile.export_profile()
            backend = GitBackend(self.sync_a)
            self.assertTrue(backend.push_profile(paths.get_snapshots_dir()))

        clone = self.root / "verify"
        subprocess.run(["git", "clone", str(self.bare), str(clone)], check=True, capture_output=True)
        self.assertIn("new_local", (clone / "profile" / "user" / "settings.json").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
