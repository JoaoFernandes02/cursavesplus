"""GitHub authentication and sync repo setup via GitHub CLI (gh).

One GitHub login configures:
- git push/pull credentials (gh auth setup-git + HTTPS)
- commit author identity (name/email from GitHub profile)
- sync remote URL on the logged-in account
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .backends import load_config, save_config, save_git_config
from . import paths


DEFAULT_REPO_NAME = "cursaves-data"
GITHUB_HOST = "github.com"


@dataclass
class GitHubProfile:
    login: str
    name: str
    email: str


def _windows_gh_paths() -> list[Path]:
    paths: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        paths.append(Path(local) / "Programs" / "GitHub CLI" / "gh.exe")
    paths.append(Path(r"C:\Program Files\GitHub CLI\gh.exe"))
    return paths


def _windows_winget_paths() -> list[Path]:
    paths: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        paths.append(Path(local) / "Microsoft" / "WindowsApps" / "winget.exe")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    paths.append(Path(program_files) / "WindowsApps" / "winget.exe")
    return paths


def _windows_powershell() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if candidate.is_file():
        return str(candidate)
    return "powershell"


def find_winget() -> Optional[str]:
    found = shutil.which("winget")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in _windows_winget_paths():
            if candidate.is_file():
                return str(candidate)
    return None


def find_gh() -> Optional[str]:
    found = shutil.which("gh")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in _windows_gh_paths():
            if candidate.is_file():
                return str(candidate)
    return None


def gh_install_hint() -> str:
    if sys.platform == "win32":
        return "winget install GitHub.cli"
    if sys.platform == "darwin":
        return "brew install gh"
    return "See https://github.com/cli/cli#installation"


def can_auto_install_gh() -> bool:
    """Return True if cursaves can install gh (and winget on Windows) automatically."""
    if sys.platform == "win32":
        return True
    if sys.platform == "darwin":
        return shutil.which("brew") is not None
    return False


def gh_install_steps() -> list[str]:
    """Steps cursaves will run when offering automatic gh install."""
    steps: list[str] = []
    if sys.platform == "win32":
        if not find_winget():
            steps.append("Install Windows Package Manager (winget)")
        if not find_gh():
            steps.append("Install GitHub CLI (gh) via winget")
    elif sys.platform == "darwin":
        if not find_gh():
            steps.append("Install GitHub CLI (gh) via Homebrew")
    return steps


def gh_auto_install_description() -> str:
    steps = gh_install_steps()
    if steps:
        return "\n".join(f"  • {step}" for step in steps)
    if sys.platform == "win32":
        return "winget install GitHub.cli"
    if sys.platform == "darwin":
        return "brew install gh"
    return gh_install_hint()


def install_winget() -> tuple[bool, str]:
    """Install Windows Package Manager (winget). Returns (success, message)."""
    if find_winget():
        return True, "winget is already installed."

    if sys.platform != "win32":
        return False, "winget is only available on Windows."

    print("Installing Windows Package Manager (winget)...")
    ps_script = """
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    Add-AppxPackage -Path 'https://aka.ms/getwinget'
} catch {
    Add-AppxPackage -Path 'https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx'
    Add-AppxPackage -Path 'https://github.com/microsoft/microsoft-ui-xaml/releases/download/v2.8.6/Microsoft.UI.Xaml.2.8.x64.appx'
    Add-AppxPackage -Path 'https://aka.ms/getwinget'
}
"""
    result = subprocess.run(
        [_windows_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return False, f"winget install failed: {err}"

    for _ in range(6):
        winget = find_winget()
        if winget:
            return True, "winget installed successfully."
        time.sleep(2)

    return False, "winget install finished but was not found. Restart cursaves and try again."


def install_gh() -> tuple[bool, str]:
    """Install GitHub CLI. Returns (success, message)."""
    if find_gh():
        return True, "GitHub CLI is already installed."

    print("Installing GitHub CLI (gh)...")
    print(f"  Command: {gh_auto_install_description()}")

    if sys.platform == "win32":
        winget = find_winget()
        if not winget:
            ok, msg = install_winget()
            if not ok:
                return False, msg
            winget = find_winget()
            if not winget:
                return False, "winget install finished but was not found. Restart cursaves and try again."
        result = subprocess.run(
            [
                winget, "install", "--id", "GitHub.cli", "-e",
                "--accept-source-agreements", "--accept-package-agreements",
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()
            return False, f"Install failed: {err}"
        if find_gh():
            return True, "GitHub CLI installed successfully."
        return False, "Install finished but gh was not found. Restart cursaves and try again."

    if sys.platform == "darwin":
        if not shutil.which("brew"):
            return False, "Homebrew not found. Install manually: brew install gh"
        result = subprocess.run(
            ["brew", "install", "gh"],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()
            return False, f"brew install failed: {err}"
        if find_gh():
            return True, "GitHub CLI installed successfully."
        return False, "Install finished but gh was not found. Restart the terminal and try again."

    return False, f"Automatic install not supported on this OS. {gh_install_hint()}"


def ensure_gh_or_install(*, offer_install: bool = False) -> str:
    """Return path to gh, optionally attempting install when missing."""
    gh = find_gh()
    if gh:
        return gh
    if offer_install and can_auto_install_gh():
        ok, msg = install_gh()
        print(msg)
        gh = find_gh()
        if gh:
            return gh
    ensure_gh()
    return ""


def ensure_gh() -> str:
    """Return path to gh or exit with install instructions."""
    gh = find_gh()
    if gh:
        return gh
    print("Error: GitHub CLI (gh) is required for Login with GitHub.", file=sys.stderr)
    if can_auto_install_gh():
        print(f"Install with: {gh_auto_install_description()}", file=sys.stderr)
        print("Or run: cursaves auth github (interactive install prompt in setup/GUI)", file=sys.stderr)
    else:
        print(f"Install with: {gh_install_hint()}", file=sys.stderr)
    sys.exit(1)


def _run_gh(
    args: list[str],
    *,
    timeout: Optional[int] = None,
    check: bool = False,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    gh = find_gh() or "gh"
    cmd = [gh, *args]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        input=input_text,
    )
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        print(f"gh {' '.join(args)} failed: {err}", file=sys.stderr)
        sys.exit(1)
    return result


def is_authenticated() -> bool:
    if not find_gh():
        return False
    result = _run_gh(["auth", "status", "-h", GITHUB_HOST])
    return result.returncode == 0


def get_auth_status_login() -> Optional[str]:
    """Parse @login from gh auth status output."""
    if not find_gh():
        return None
    result = _run_gh(["auth", "status", "-h", GITHUB_HOST])
    if result.returncode != 0:
        return None
    text = result.stdout + result.stderr
    patterns = [
        r"Logged in to github\.com account (\S+)",
        r"Logged in to github\.com as (\S+)",
        r"account\s+(\S+)\s+\(",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(1).lstrip("@")
    return None


def _gh_login_device_url() -> str:
    return f"https://{GITHUB_HOST}/login/device"


def device_login_url() -> str:
    return _gh_login_device_url()


def parse_device_code(text: str) -> Optional[str]:
    """Extract GitHub OAuth device code (XXXX-XXXX) from gh output."""
    patterns = [
        r"one-time code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})",
        r"device code:\s*([A-Z0-9]{4}-[A-Z0-9]{4})",
        r"([A-Z0-9]{4}-[A-Z0-9]{4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            return m.group(1).upper()
    return None


def _maybe_open_github_login_browser(line: str, *, opened: set[str]) -> None:
    """Open device-login URL when gh prints OAuth instructions (non-TTY mode)."""
    for url in re.findall(r"https://[^\s\]]+", line):
        if GITHUB_HOST in url and url not in opened:
            webbrowser.open(url)
            opened.add(url)
            return
    if re.search(r"one-time code", line, re.I) and _gh_login_device_url() not in opened:
        webbrowser.open(_gh_login_device_url())
        opened.add(_gh_login_device_url())


def login_web(
    *,
    on_status: Optional[Callable[[str], None]] = None,
    on_device_code: Optional[Callable[[str], None]] = None,
) -> None:
    """Browser login; opens the device flow when gh is not attached to a TTY."""
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)
        else:
            print(msg)

    ensure_gh()
    if is_authenticated():
        login = get_auth_status_login()
        if login:
            status(f"Already logged in to GitHub as @{login}")
            return

    gh = find_gh() or "gh"
    cmd = [
        gh,
        "auth",
        "login",
        "--web",
        "--git-protocol",
        "https",
        "-h",
        GITHUB_HOST,
        "--skip-ssh-key",
    ]

    status("Opening browser for GitHub login...")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    opened_urls: set[str] = set()
    output_lines: list[str] = []
    device_code_sent = False

    def read_output() -> None:
        nonlocal device_code_sent
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            output_lines.append(line)
            status(line)
            if not device_code_sent:
                code = parse_device_code(line)
                if code and on_device_code:
                    on_device_code(code)
                    device_code_sent = True
            _maybe_open_github_login_browser(line, opened=opened_urls)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    try:
        return_code = proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)
        status("GitHub login timed out.")
        sys.exit(1)
    finally:
        reader.join(timeout=5)

    if return_code != 0:
        err = "\n".join(output_lines) or "unknown error"
        status(f"GitHub login failed: {err}")
        sys.exit(1)

    if not is_authenticated():
        status("GitHub login did not complete. Try again.")
        sys.exit(1)

    login = get_auth_status_login()
    if login:
        status(f"Logged in as @{login}")


def setup_git_credentials() -> None:
    ensure_gh()
    result = _run_gh(["auth", "setup-git", "-h", GITHUB_HOST])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        print(f"Warning: gh auth setup-git failed: {err}", file=sys.stderr)


def logout() -> None:
    ensure_gh()
    login = get_auth_status_login()
    args = ["auth", "logout", "-h", GITHUB_HOST]
    if login:
        args.extend(["--user", login])
    _run_gh(args)
    config = load_config()
    config.pop("github", None)
    save_config(config)
    print("Logged out from GitHub.")


def _gh_api_json(endpoint: str) -> dict:
    result = _run_gh(["api", endpoint], timeout=60)
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        print(f"GitHub API failed ({endpoint}): {err}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print(f"Invalid JSON from GitHub API: {endpoint}", file=sys.stderr)
        sys.exit(1)


def fetch_profile() -> GitHubProfile:
    """Fetch name, login, and primary verified email from GitHub."""
    ensure_gh()
    if not is_authenticated():
        print("Error: not logged in to GitHub. Run: cursaves auth github", file=sys.stderr)
        sys.exit(1)

    user = _gh_api_json("user")
    login = user.get("login") or ""
    name = user.get("name") or login

    emails = _gh_api_json("user/emails")
    email = ""
    if isinstance(emails, list):
        primary = [e for e in emails if e.get("primary") and e.get("verified")]
        if primary:
            email = primary[0].get("email", "")
        else:
            verified = [e for e in emails if e.get("verified")]
            if verified:
                email = verified[0].get("email", "")
    if not email:
        email = f"{login}@users.noreply.github.com"

    return GitHubProfile(login=login, name=name, email=email)


def default_repo_name() -> str:
    return DEFAULT_REPO_NAME


def https_remote(login: str, repo: str = DEFAULT_REPO_NAME) -> str:
    return f"https://github.com/{login}/{repo}.git"


def normalize_to_https(url: str) -> str:
    """Convert SSH GitHub remotes to HTTPS."""
    url = url.strip()
    m = re.match(r"^git@github\.com:([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return https_remote(m.group(1), m.group(2).removesuffix(".git"))
    m = re.match(r"^ssh://git@github\.com/([^/]+)/(.+?)(?:\.git)?$", url)
    if m:
        return https_remote(m.group(1), m.group(2).removesuffix(".git"))
    if url.endswith(".git") or url.startswith("https://"):
        return url
    return url


def parse_github_repo(url: str) -> Optional[tuple[str, str]]:
    """Return (owner, repo) from a GitHub HTTPS or SSH URL."""
    url = url.strip().removesuffix(".git")
    m = re.match(r"^git@github\.com:([^/]+)/(.+)$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^https://github\.com/([^/]+)/(.+)$", url)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"^ssh://git@github\.com/([^/]+)/(.+)$", url)
    if m:
        return m.group(1), m.group(2)
    return None


def remote_exists(url: str) -> bool:
    https_url = normalize_to_https(url)
    parsed = parse_github_repo(https_url)
    if parsed and find_gh():
        owner, repo = parsed
        result = _run_gh(["repo", "view", f"{owner}/{repo}", "--json", "name"])
        if result.returncode == 0:
            return True
    result = subprocess.run(
        ["git", "ls-remote", "--heads", https_url],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def verify_account_can_access(url: str, login: str) -> bool:
    https_url = normalize_to_https(url)
    parsed = parse_github_repo(https_url)
    if not parsed:
        print(f"  Not a GitHub repository URL: {url}", file=sys.stderr)
        return False
    owner, repo = parsed
    if not find_gh():
        return remote_exists(https_url)
    result = _run_gh(["repo", "view", f"{owner}/{repo}", "--json", "name"])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        print(f"  Cannot access {owner}/{repo} as @{login}: {err}", file=sys.stderr)
        return False
    if owner != login:
        print(
            f"  Note: repo owner is @{owner} (logged in as @{login}). "
            "Ensure you have push access.",
        )
    return True


def create_sync_repo(login: str, repo: str = DEFAULT_REPO_NAME) -> str:
    ensure_gh()
    full = f"{login}/{repo}"
    if remote_exists(https_remote(login, repo)):
        print(f"  Repository already exists: {full}")
        return https_remote(login, repo)
    print(f"  Creating private repository {full}...")
    result = _run_gh(
        ["repo", "create", full, "--private", "--confirm"],
        timeout=120,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        print(f"  Failed to create repository: {err}", file=sys.stderr)
        sys.exit(1)
    remote = https_remote(login, repo)
    print(f"  Created {remote}")
    return remote


def save_auth_config(profile: GitHubProfile, remote_url: Optional[str] = None) -> dict:
    """Persist GitHub session + mirror git identity from same account."""
    config = load_config()
    github_cfg = {
        "login": profile.login,
        "name": profile.name,
        "email": profile.email,
        "repo": default_repo_name(),
    }
    if remote_url:
        remote_url = normalize_to_https(remote_url)
        github_cfg["remote_url"] = remote_url
        parsed = parse_github_repo(remote_url)
        if parsed:
            github_cfg["repo"] = parsed[1]
    config["github"] = github_cfg
    save_config(config)

    save_git_config(
        name=profile.name,
        email=profile.email,
        sign_commits=False,
    )
    return config.get("github", {})


def get_github_config() -> dict:
    return load_config().get("github", {})


def configure_sync_remote(remote_url: str) -> None:
    """Init or update ~/.cursaves/ origin to HTTPS remote."""
    from .backends import GitBackend

    remote_url = normalize_to_https(remote_url)
    sync_dir = paths.get_sync_dir()
    backend = GitBackend(sync_dir)
    if backend.is_initialized():
        backend.update_remote(remote_url)
        print(f"  Updated sync remote: {remote_url}")
    else:
        backend.init_repo(remote=remote_url)
        print(f"  Initialized sync repo with remote: {remote_url}")


def _prompt_yes_no(message: str, default: bool = True) -> bool:
    from .interactive import confirm
    return confirm(message, default=default)


def _prompt_text(message: str, default: str = "") -> Optional[str]:
    from InquirerPy import inquirer
    try:
        value = inquirer.text(message=message, default=default).execute()
    except (KeyboardInterrupt, EOFError):
        return None
    return value.strip() if value else None


def resolve_remote(
    profile: GitHubProfile,
    *,
    interactive: bool = True,
    existing_url: Optional[str] = None,
    create_repo: bool = False,
    yes: bool = False,
) -> str:
    """Resolve sync remote URL: existing, user-provided, or auto-created."""
    if existing_url:
        url = normalize_to_https(existing_url)
        if not verify_account_can_access(url, profile.login):
            sys.exit(1)
        return url

    if create_repo or yes:
        return create_sync_repo(profile.login, default_repo_name())

    if not interactive:
        cfg = get_github_config()
        if cfg.get("remote_url"):
            return cfg["remote_url"]
        return create_sync_repo(profile.login, default_repo_name())

    if _prompt_yes_no("Do you already have a private GitHub repo for cursaves sync?"):
        url = _prompt_text(
            "GitHub remote URL (HTTPS):",
            default=https_remote(profile.login, default_repo_name()),
        )
        if not url:
            sys.exit(1)
        url = normalize_to_https(url)
        if not verify_account_can_access(url, profile.login):
            sys.exit(1)
        return url

    return create_sync_repo(profile.login, default_repo_name())


def run_auth_flow(
    *,
    login_only: bool = False,
    remote_url: Optional[str] = None,
    create_repo: bool = False,
    yes: bool = False,
    interactive: bool = True,
    on_status: Optional[Callable[[str], None]] = None,
    on_device_code: Optional[Callable[[str], None]] = None,
) -> dict:
    """Full GitHub login flow: auth, profile, optional remote setup."""
    def status(msg: str) -> None:
        if on_status:
            on_status(msg)
        else:
            print(msg)

    ensure_gh()
    if not is_authenticated():
        status("Logging in to GitHub (browser)...")
        login_web(on_status=on_status, on_device_code=on_device_code)
    else:
        login = get_auth_status_login()
        status(f"Already logged in as @{login or 'GitHub'}")

    status("Configuring git credentials for GitHub HTTPS...")
    setup_git_credentials()

    profile = fetch_profile()
    status(f"GitHub account: {profile.name} <{profile.email}> (@{profile.login})")

    github_cfg = save_auth_config(profile)
    status("Saved commit identity for sync repo (GPG signing disabled).")

    if login_only:
        return github_cfg

    if remote_url or create_repo or yes or interactive:
        resolved = resolve_remote(
            profile,
            interactive=interactive and not yes and not remote_url and not create_repo,
            existing_url=remote_url,
            create_repo=create_repo,
            yes=yes,
        )
        github_cfg = save_auth_config(profile, resolved)
        configure_sync_remote(resolved)
        status(f"Sync remote: {resolved}")

    return github_cfg


def run_gui_login(
    *,
    on_status: Optional[Callable[[str], None]] = None,
    on_device_code: Optional[Callable[[str], None]] = None,
) -> dict:
    """GitHub browser login for GUI (no repo dialog yet)."""
    return run_auth_flow(
        login_only=True,
        interactive=False,
        on_status=on_status,
        on_device_code=on_device_code,
    )


def run_gui_repo_setup(
    *,
    has_existing_repo: Optional[bool] = None,
    remote_url: Optional[str] = None,
    on_status: Optional[Callable[[str], None]] = None,
) -> dict:
    """Configure sync remote after GUI repo dialog."""
    create_repo = has_existing_repo is False
    existing = remote_url if has_existing_repo else None
    return run_auth_flow(
        remote_url=existing,
        create_repo=create_repo,
        interactive=False,
        on_status=on_status,
    )


def run_gui_flow(
    *,
    has_existing_repo: Optional[bool] = None,
    remote_url: Optional[str] = None,
) -> dict:
    """GitHub auth for GUI with optional repo dialog inputs (login + repo in one call)."""
    create_repo = has_existing_repo is False
    existing = remote_url if has_existing_repo else None
    return run_auth_flow(
        remote_url=existing,
        create_repo=create_repo,
        interactive=False,
    )


def print_auth_status() -> None:
    cfg = get_github_config()
    if is_authenticated():
        login = get_auth_status_login() or cfg.get("login", "?")
        print(f"GitHub: logged in as @{login}")
    else:
        print("GitHub: not logged in")
    if cfg:
        print(f"  Name:  {cfg.get('name') or '(not set)'}")
        print(f"  Email: {cfg.get('email') or '(not set)'}")
        print(f"  Remote: {cfg.get('remote_url') or '(not set)'}")
    else:
        print("  No cursaves GitHub config saved.")
