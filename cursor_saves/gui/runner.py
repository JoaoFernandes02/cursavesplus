"""Run cursaves CLI commands in a background thread."""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from typing import Callable, Optional


class CommandRunner:
    """Execute CLI commands without blocking the GUI thread."""

    def __init__(
        self,
        on_line: Callable[[str], None],
        on_start: Callable[[str], None],
        on_done: Callable[[int], None],
    ):
        self._on_line = on_line
        self._on_start = on_start
        self._on_done = on_done
        self._process: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @staticmethod
    def cursaves_argv(*args: str) -> list[str]:
        exe = shutil.which("cursaves")
        if exe:
            return [exe, *args]
        return [sys.executable, "-m", "cursor_saves.cli", *args]

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def run(self, argv: list[str]) -> None:
        if self.is_running:
            self._on_line("Another command is already running.\n")
            return

        cmd_display = " ".join(argv)
        self._on_start(cmd_display)
        self._thread = threading.Thread(target=self._run_subprocess, args=(argv,), daemon=True)
        self._thread.start()

    def run_callable(self, fn: Callable, *args, **kwargs) -> None:
        if self.is_running:
            self._on_line("Another command is already running.\n")
            return

        self._on_start(getattr(fn, "__name__", "callable"))
        self._thread = threading.Thread(
            target=self._run_callable,
            args=(fn, args, kwargs),
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        with self._lock:
            proc = self._process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def _run_subprocess(self, argv: list[str]) -> None:
        code = 1
        try:
            with self._lock:
                self._process = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                proc = self._process
            if proc.stdout:
                for line in proc.stdout:
                    self._on_line(line)
            code = proc.wait()
        except Exception as exc:
            self._on_line(f"Error: {exc}\n")
        finally:
            with self._lock:
                self._process = None
            self._on_done(code)

    def _run_callable(self, fn: Callable, args: tuple, kwargs: dict) -> None:
        code = 0
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer), redirect_stderr(buffer):
                fn(*args, **kwargs)
            output = buffer.getvalue()
            if output:
                self._on_line(output if output.endswith("\n") else output + "\n")
        except SystemExit as exc:
            code = int(exc.code) if isinstance(exc.code, int) else 1
            self._on_line(f"Exited with code {code}\n")
        except Exception as exc:
            code = 1
            self._on_line(f"Error: {exc}\n")
        finally:
            self._on_done(code)
