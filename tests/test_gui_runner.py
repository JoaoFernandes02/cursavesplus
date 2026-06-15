"""Tests for GUI CommandRunner."""

from __future__ import annotations

import sys
import threading
import time
import unittest


class TestCommandRunner(unittest.TestCase):
    def test_captures_subprocess_output(self):
        from cursor_saves.gui.runner import CommandRunner

        lines = []
        done = threading.Event()

        def on_line(text):
            lines.append(text)

        def on_done(code):
            self.assertEqual(code, 0)
            done.set()

        runner = CommandRunner(on_line=on_line, on_start=lambda _: None, on_done=on_done)
        runner.run([sys.executable, "-c", "print('hello from runner')"])
        self.assertTrue(done.wait(timeout=10))
        self.assertTrue(any("hello from runner" in line for line in lines))

    def test_stop_terminates_process(self):
        from cursor_saves.gui.runner import CommandRunner

        done = threading.Event()
        runner = CommandRunner(
            on_line=lambda _: None,
            on_start=lambda _: None,
            on_done=lambda _: done.set(),
        )
        runner.run([sys.executable, "-c", "import time; time.sleep(60)"])
        time.sleep(0.5)
        runner.stop()
        self.assertTrue(done.wait(timeout=10))

    def test_cursaves_argv_fallback(self):
        from cursor_saves.gui.runner import CommandRunner

        argv = CommandRunner.cursaves_argv("sync")
        self.assertIn("sync", argv)
        self.assertTrue(len(argv) >= 2)


if __name__ == "__main__":
    unittest.main()
