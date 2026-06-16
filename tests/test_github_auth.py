"""Tests for GitHub auth helpers."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cursor_saves import github_auth
from cursor_saves.backends import load_config, save_config


class GitHubAuthHelpersTests(unittest.TestCase):
    def test_https_remote(self):
        self.assertEqual(
            github_auth.https_remote("alice", "cursaves-data"),
            "https://github.com/alice/cursaves-data.git",
        )

    def test_normalize_ssh_to_https(self):
        self.assertEqual(
            github_auth.normalize_to_https("git@github.com:bob/cursaves-data.git"),
            "https://github.com/bob/cursaves-data.git",
        )
        self.assertEqual(
            github_auth.normalize_to_https("https://github.com/bob/repo.git"),
            "https://github.com/bob/repo.git",
        )

    def test_parse_github_repo(self):
        self.assertEqual(
            github_auth.parse_github_repo("git@github.com:user/repo.git"),
            ("user", "repo"),
        )
        self.assertEqual(
            github_auth.parse_github_repo("https://github.com/user/repo"),
            ("user", "repo"),
        )

    def test_default_repo_name(self):
        self.assertEqual(github_auth.default_repo_name(), "cursaves-data")


class SaveAuthConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cursaves-gh-test-")
        self.config_path = Path(self._tmp) / "config.json"
        self.patcher = mock.patch(
            "cursor_saves.backends._CONFIG_PATH",
            self.config_path,
        )
        self.patcher.start()
        self.sync_patcher = mock.patch(
            "cursor_saves.paths.get_sync_dir",
            return_value=Path(self._tmp) / "cursaves",
        )
        self.sync_patcher.start()

    def tearDown(self):
        self.sync_patcher.stop()
        self.patcher.stop()

    def test_save_auth_config_writes_github_and_git(self):
        profile = github_auth.GitHubProfile(
            login="testuser",
            name="Test User",
            email="test@example.com",
        )
        github_auth.save_auth_config(
            profile,
            "https://github.com/testuser/cursaves-data.git",
        )
        config = load_config()
        self.assertEqual(config["github"]["login"], "testuser")
        self.assertEqual(config["github"]["email"], "test@example.com")
        self.assertEqual(config["git"]["name"], "Test User")
        self.assertEqual(config["git"]["email"], "test@example.com")
        self.assertFalse(config["git"]["sign_commits"])


class FetchProfileTests(unittest.TestCase):
    @mock.patch("cursor_saves.github_auth.ensure_gh", return_value="gh")
    @mock.patch("cursor_saves.github_auth.is_authenticated", return_value=True)
    @mock.patch("cursor_saves.github_auth._gh_api_json")
    def test_fetch_profile_primary_email(self, mock_api, _mock_auth, _mock_gh):
        mock_api.side_effect = [
            {"login": "alice", "name": "Alice"},
            [
                {"email": "a@users.noreply.github.com", "primary": False, "verified": True},
                {"email": "alice@example.com", "primary": True, "verified": True},
            ],
        ]
        profile = github_auth.fetch_profile()
        self.assertEqual(profile.login, "alice")
        self.assertEqual(profile.name, "Alice")
        self.assertEqual(profile.email, "alice@example.com")


class ResolveRemoteTests(unittest.TestCase):
    @mock.patch("cursor_saves.github_auth.create_sync_repo")
    @mock.patch("cursor_saves.github_auth.verify_account_can_access", return_value=True)
    def test_resolve_existing_url(self, _mock_verify, mock_create):
        profile = github_auth.GitHubProfile("u", "U", "u@e.com")
        url = github_auth.resolve_remote(
            profile,
            interactive=False,
            existing_url="https://github.com/u/my-repo.git",
        )
        self.assertEqual(url, "https://github.com/u/my-repo.git")
        mock_create.assert_not_called()

    @mock.patch("cursor_saves.github_auth.create_sync_repo")
    def test_resolve_create_repo(self, mock_create):
        mock_create.return_value = "https://github.com/u/cursaves-data.git"
        profile = github_auth.GitHubProfile("u", "U", "u@e.com")
        url = github_auth.resolve_remote(
            profile,
            interactive=False,
            create_repo=True,
        )
        self.assertEqual(url, "https://github.com/u/cursaves-data.git")
        mock_create.assert_called_once_with("u", "cursaves-data")


class LoginWebTests(unittest.TestCase):
    def test_parse_device_code(self):
        self.assertEqual(
            github_auth.parse_device_code("! First copy your one-time code: ABCD-1234"),
            "ABCD-1234",
        )
        self.assertIsNone(github_auth.parse_device_code("no code here"))

    @mock.patch("cursor_saves.github_auth.webbrowser.open")
    @mock.patch("cursor_saves.github_auth.is_authenticated", side_effect=[False, True])
    @mock.patch("cursor_saves.github_auth.get_auth_status_login", return_value="alice")
    @mock.patch("cursor_saves.github_auth.find_gh", return_value="gh")
    @mock.patch("cursor_saves.github_auth.subprocess.Popen")
    def test_login_web_opens_device_url(self, mock_popen, _mock_gh, _mock_login, _mock_auth, mock_open):
        proc = mock.MagicMock()
        proc.stdout = iter(["! First copy your one-time code: ABCD-1234"])
        proc.wait.return_value = 0
        mock_popen.return_value = proc

        github_auth.login_web()

        mock_open.assert_called()
        opened_url = mock_open.call_args[0][0]
        self.assertIn("github.com/login/device", opened_url)

    @mock.patch("cursor_saves.github_auth.webbrowser.open")
    @mock.patch("cursor_saves.github_auth.is_authenticated", side_effect=[False, True])
    @mock.patch("cursor_saves.github_auth.get_auth_status_login", return_value="alice")
    @mock.patch("cursor_saves.github_auth.find_gh", return_value="gh")
    @mock.patch("cursor_saves.github_auth.subprocess.Popen")
    def test_login_web_calls_on_device_code(self, mock_popen, _mock_gh, _mock_login, _mock_auth, _mock_open):
        proc = mock.MagicMock()
        proc.stdout = iter(["! First copy your one-time code: WXYZ-9876"])
        proc.wait.return_value = 0
        mock_popen.return_value = proc
        callback = mock.MagicMock()

        github_auth.login_web(on_device_code=callback)

        callback.assert_called_once_with("WXYZ-9876")

    def test_get_auth_status_login_parses_as_format(self):
        result = subprocess.CompletedProcess(
            [],
            0,
            "",
            "github.com\n  ✓ Logged in to github.com as alice (oauth_token)\n",
        )
        with mock.patch("cursor_saves.github_auth.find_gh", return_value="gh"):
            with mock.patch("cursor_saves.github_auth._run_gh", return_value=result):
                self.assertEqual(github_auth.get_auth_status_login(), "alice")


class InstallGhTests(unittest.TestCase):
    @mock.patch("cursor_saves.github_auth.find_winget", return_value="winget")
    @mock.patch("cursor_saves.github_auth.subprocess.run")
    def test_install_gh_winget_success(self, mock_run, _mock_winget):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")

        with mock.patch("cursor_saves.github_auth.sys.platform", "win32"):
            with mock.patch(
                "cursor_saves.github_auth.find_gh",
                side_effect=[None, None, r"C:\Program Files\GitHub CLI\gh.exe"],
            ):
                ok, msg = github_auth.install_gh()
        self.assertTrue(ok)
        mock_run.assert_called_once()

    @mock.patch("cursor_saves.github_auth.install_winget", return_value=(True, "winget ok"))
    @mock.patch("cursor_saves.github_auth.find_winget", side_effect=[None, None, "winget"])
    @mock.patch("cursor_saves.github_auth.subprocess.run")
    def test_install_gh_installs_winget_first(self, mock_run, _mock_find_winget, mock_install_winget):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")

        with mock.patch("cursor_saves.github_auth.sys.platform", "win32"):
            with mock.patch(
                "cursor_saves.github_auth.find_gh",
                side_effect=[None, None, r"C:\Program Files\GitHub CLI\gh.exe"],
            ):
                ok, msg = github_auth.install_gh()
        self.assertTrue(ok)
        mock_install_winget.assert_called_once()

    @mock.patch("cursor_saves.github_auth.find_winget", return_value=None)
    @mock.patch("cursor_saves.github_auth.subprocess.run")
    def test_install_winget_powershell(self, mock_run, _mock_find):
        mock_run.return_value = subprocess.CompletedProcess([], 0, "", "")

        with mock.patch("cursor_saves.github_auth.sys.platform", "win32"):
            with mock.patch("cursor_saves.github_auth.find_winget", side_effect=[None, None, "winget"]):
                with mock.patch("cursor_saves.github_auth.time.sleep"):
                    ok, msg = github_auth.install_winget()
        self.assertTrue(ok)
        self.assertIn("powershell", mock_run.call_args[0][0][0].lower())

    def test_can_auto_install_true_on_windows(self):
        with mock.patch("cursor_saves.github_auth.sys.platform", "win32"):
            self.assertTrue(github_auth.can_auto_install_gh())

    def test_gh_install_steps_includes_winget_when_missing(self):
        with mock.patch("cursor_saves.github_auth.sys.platform", "win32"):
            with mock.patch("cursor_saves.github_auth.find_winget", return_value=None):
                with mock.patch("cursor_saves.github_auth.find_gh", return_value=None):
                    steps = github_auth.gh_install_steps()
        self.assertIn("winget", steps[0].lower())
        self.assertIn("gh", steps[1].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
