"""restore.tmux_server_cwd: the warning when the tmux server's own cwd is gone (spec restart-recovery §4)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restore  # noqa: E402

T = ["tmux", "-L", "x"]
WARN = ("tmux server cwd is gone (/gone/dir): new panes start there; restart the tmux server from ~ "
        "(tmux -S /tmp/tmux-1/sock kill-server ends every session on it; reopen each project with agent-board dev)")


def runner(pid=(0, "4242|/tmp/tmux-1/sock\n"), lsof=(0, "p4242\nfcwd\nn/gone/dir\n")):
    calls = []

    def run(cmd):
        calls.append(cmd)
        return pid if cmd[:len(T)] == T else lsof
    return run, calls


class TmuxServerCwdTest(unittest.TestCase):
    def test_gone_cwd_gives_the_warning(self):
        run, calls = runner()
        self.assertEqual(restore.tmux_server_cwd(run=run, tmux=T), WARN)
        self.assertEqual(calls[0], T + ["display", "-p", "#{pid}|#{socket_path}"])
        self.assertEqual(calls[1][1:], ["-a", "-p", "4242", "-d", "cwd", "-Fn"])

    def test_linux_lsof_deleted_suffix_is_stripped(self):   # Linux lsof prints a removed cwd as "/gone/dir (deleted)"
        run, _ = runner(lsof=(0, "p4242\nfcwd\nn/gone/dir (deleted)\n"))
        self.assertEqual(restore.tmux_server_cwd(run=run, tmux=T), WARN)

    def test_existing_cwd_gives_none(self):   # mutation: drop the isdir check -> the warning is returned
        with tempfile.TemporaryDirectory() as d:
            run, _ = runner(lsof=(0, f"p4242\nfcwd\nn{d}\n"))
            self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))

    def test_lsof_failure_gives_none(self):   # mutation: ignore lsof's exit code -> the n line is parsed, warning returned
        run, _ = runner(lsof=(1, "p4242\nfcwd\nn/gone/dir\n"))
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))

    def test_no_server_gives_none_and_skips_lsof(self):   # mutation: drop the pid check -> lsof is called
        run, calls = runner(pid=(1, ""))
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))
        self.assertEqual(len(calls), 1)

    def test_a_raising_runner_gives_none(self):   # mutation: drop the try/except -> OSError escapes
        def run(cmd):
            raise OSError("no tmux")
        self.assertIsNone(restore.tmux_server_cwd(run=run, tmux=T))


if __name__ == "__main__":
    unittest.main()
