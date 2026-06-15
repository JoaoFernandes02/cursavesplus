"""Main cursaves GUI application."""

from __future__ import annotations

import customtkinter as ctk

from . import state
from .panels import autosync, dashboard, info, profile, setup, sync, tools
from .runner import CommandRunner
from .widgets import OutputLog


class CursavesApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("cursaves")
        self.geometry("920x680")
        self.minsize(800, 600)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._configured = state.is_configured()
        self._build_ui()
        self._refresh_status_bar()
        self.after(30_000, self._periodic_refresh)

    def _build_ui(self) -> None:
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        tabs = ["Dashboard", "Sync", "Auto-sync", "Profile", "Info", "Tools", "Setup"]
        for name in tabs:
            self.tabview.add(name)

        output_frame = ctk.CTkFrame(self)
        output_frame.pack(fill="both", expand=True, padx=8, pady=4)

        ctk.CTkLabel(output_frame, text="Output", anchor="w").pack(fill="x", padx=8, pady=(4, 0))
        self.output_box = ctk.CTkTextbox(output_frame, height=180, state="disabled")
        self.output_box.pack(fill="both", expand=True, padx=8, pady=4)

        btn_row = ctk.CTkFrame(output_frame, fg_color="transparent")
        btn_row.pack(fill="x", padx=8, pady=(0, 8))
        self.log = OutputLog(self.output_box)

        self.runner = CommandRunner(
            on_line=self.log.append,
            on_start=self._on_command_start,
            on_done=self._on_command_done,
        )

        ctk.CTkButton(btn_row, text="Clear output", command=self.log.clear, width=100).pack(
            side="left", padx=4,
        )
        ctk.CTkButton(btn_row, text="Stop", command=self.runner.stop, width=80).pack(
            side="left", padx=4,
        )

        self.status_bar = ctk.CTkLabel(self, text="", anchor="w", font=ctk.CTkFont(size=11))
        self.status_bar.pack(fill="x", padx=12, pady=(0, 8))

        def is_enabled():
            return self._configured

        def go_setup():
            self.tabview.set("Setup")

        def on_configured():
            self._configured = state.is_configured()
            self._refresh_all()

        dashboard.build_dashboard(
            self.tabview.tab("Dashboard"),
            self.runner,
            on_go_setup=go_setup,
            refresh_status=self._refresh_status_bar,
        )
        sync.build_sync(self.tabview.tab("Sync"), self.runner, is_enabled)
        autosync.build_autosync(self.tabview.tab("Auto-sync"), self.runner)
        profile.build_profile(self.tabview.tab("Profile"), self.runner, is_enabled)
        info.build_info(self.tabview.tab("Info"), self.runner)
        tools.build_tools(
            self.tabview.tab("Tools"),
            self.runner,
            self.log.append,
            is_enabled,
        )
        setup.build_setup(self.tabview.tab("Setup"), self.runner, on_configured)

    def _on_command_start(self, cmd: str) -> None:
        self.log.append(f"\n$ {cmd}\n")

    def _on_command_done(self, code: int) -> None:
        if code != 0:
            self.log.append(f"\n[exit code {code}]\n")
        self._configured = state.is_configured()
        self._refresh_all()

    def _refresh_status_bar(self) -> None:
        self.status_bar.configure(text=state.get_status_bar_text())

    def _refresh_all(self) -> None:
        self._refresh_status_bar()
        dash = self.tabview.tab("Dashboard")
        if hasattr(dash, "_dashboard_refresh"):
            dash._dashboard_refresh()
        auto = self.tabview.tab("Auto-sync")
        if hasattr(auto, "_autosync_refresh"):
            auto._autosync_refresh()
        setup_tab = self.tabview.tab("Setup")
        if hasattr(setup_tab, "_setup_refresh"):
            setup_tab._setup_refresh()

    def _periodic_refresh(self) -> None:
        self._refresh_status_bar()
        auto = self.tabview.tab("Auto-sync")
        if hasattr(auto, "_autosync_refresh"):
            auto._autosync_refresh()
        self.after(30_000, self._periodic_refresh)


def main() -> None:
    try:
        app = CursavesApp()
        app.mainloop()
    except Exception as exc:
        import sys
        print(f"Failed to start GUI: {exc}", file=sys.stderr)
        print("Install GUI dependencies: uv tool install --force .", file=sys.stderr)
        raise
