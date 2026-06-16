"""Tests for GUI readiness helpers."""

from __future__ import annotations

import unittest
from unittest import mock

from cursor_saves.gui import state


class GuiStateReadinessTests(unittest.TestCase):
    @mock.patch("cursor_saves.gui.state.get_remote_url", return_value="https://github.com/u/r.git")
    @mock.patch("cursor_saves.gui.state.is_configured", return_value=True)
    @mock.patch("cursor_saves.gui.state.is_github_logged_in", return_value=True)
    def test_is_sync_ready_true(self, _login, _cfg, _remote):
        self.assertTrue(state.is_sync_ready())
        self.assertIsNone(state.get_setup_block_reason())

    @mock.patch("cursor_saves.github_auth.find_gh", return_value=None)
    def test_block_reason_no_gh(self, _find):
        self.assertIn("gh", state.get_setup_block_reason().lower())

    @mock.patch("cursor_saves.github_auth.find_gh", return_value="gh")
    @mock.patch("cursor_saves.gui.state.is_github_logged_in", return_value=False)
    def test_block_reason_not_logged_in(self, _login, _find):
        self.assertIn("logged in", state.get_setup_block_reason().lower())

    @mock.patch("cursor_saves.github_auth.find_gh", return_value="gh")
    @mock.patch("cursor_saves.gui.state.is_github_logged_in", return_value=True)
    @mock.patch("cursor_saves.gui.state.is_configured", return_value=False)
    def test_block_reason_no_repo(self, _cfg, _login, _find):
        self.assertIn("initialized", state.get_setup_block_reason().lower())

    @mock.patch("cursor_saves.github_auth.find_gh", return_value="gh")
    @mock.patch("cursor_saves.gui.state.get_github_auth", return_value={"login": "alice"})
    @mock.patch("cursor_saves.gui.state.get_remote_url", return_value=None)
    @mock.patch("cursor_saves.gui.state.is_configured", return_value=True)
    @mock.patch("cursor_saves.gui.state.is_github_logged_in", return_value=True)
    def test_block_reason_no_remote(self, _login, _cfg, _remote, _gh, _find):
        reason = state.get_setup_block_reason()
        self.assertIn("alice", reason)
        self.assertIn("remote", reason.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
