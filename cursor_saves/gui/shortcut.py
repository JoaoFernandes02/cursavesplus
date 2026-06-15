"""Desktop shortcut helpers."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def _find_cursaves_exe() -> str | None:
    exe = shutil.which("cursaves")
    if exe:
        return exe
    local = Path.home() / ".local" / "bin"
    for name in ("cursaves.exe", "cursaves"):
        candidate = local / name
        if candidate.exists():
            return str(candidate)
    return None


def create_desktop_shortcut(name: str = "Cursaves") -> tuple[bool, str]:
    """Create a Desktop shortcut that launches cursaves (opens GUI)."""
    cursaves_exe = _find_cursaves_exe()
    if not cursaves_exe:
        return False, "cursaves executable not found on PATH"

    if sys.platform == "win32":
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
        shortcut_path = desktop / f"{name}.lnk"
        ps = f"""
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
$Shortcut.TargetPath = '{cursaves_exe}'
$Shortcut.WorkingDirectory = '{Path(cursaves_exe).parent}'
$Shortcut.Description = 'Cursaves - sync Cursor chats'
$Shortcut.Save()
"""
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return False, result.stderr.strip() or "Failed to create shortcut"
        return True, str(shortcut_path)

    if sys.platform == "darwin":
        desktop = Path.home() / "Desktop"
        app_link = desktop / f"{name}.command"
        app_link.write_text(
            f"#!/bin/bash\nexec '{cursaves_exe}'\n",
            encoding="utf-8",
        )
        app_link.chmod(0o755)
        return True, str(app_link)

    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    link = desktop / f"{name}.desktop"
    link.write_text(
        f"""[Desktop Entry]
Type=Application
Name={name}
Exec={cursaves_exe}
Terminal=false
""",
        encoding="utf-8",
    )
    link.chmod(0o755)
    return True, str(link)
