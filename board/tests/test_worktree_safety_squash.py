"""test_worktree_safety, part "squash": Squash, Schedule (the fixtures are in worktree_fixtures.py)."""
import os
import plistlib
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from worktree_fixtures import (  # noqa: E402
    Base,
    CLI,
    add_worktree,
    git,
    glab_stub,
    head,
    write_stub,
    ws)


class Squash(Base):
    """Upstream gone + a merged MR whose sha is the worktree HEAD."""

    def setUp(self):
        super().setUp()
        self.origin = Path(self.tmp) / "origin.git"
        git("init", "--bare", "-b", "main", str(self.origin), cwd=self.tmp)
        git("remote", "add", "origin", str(self.origin), cwd=self.repo)
        git("push", "-u", "origin", "main", cwd=self.repo)
        self.wt = add_worktree(self.repo, "w1", commits=1, age_days=1)
        git("push", "-u", "origin", "w1", cwd=self.wt)
        git("push", "origin", "--delete", "w1", cwd=self.repo)
        git("fetch", "--prune", cwd=self.repo)
        self.marker = Path(self.tmp) / "glab-called"

    def test_gone_upstream_is_really_gone(self):
        out = git("for-each-ref", "--format=%(upstream:track)", "refs/heads/w1", cwd=self.repo).stdout
        self.assertEqual(out.strip(), "[gone]")

    def test_equal_sha_is_safe_squash(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt)))
        item = self.one(fetch=True)
        self.assertEqual((item["state"], item["squash"]), ("safe", True))

    def test_aw_glab_is_word_split(self):
        sha = head(self.wt)
        stub = write_stub(self.bin / "glabargs", '[ "$1" = "--flag" ] || exit 1\nshift\n'
                          'echo \'[{"iid":1,"sha":"%s","state":"merged"}]\'\n' % sha)
        self.set_env(AW_GLAB=f"{stub} --flag")
        self.assertEqual(self.one(fetch=True)["squash"], True)

    def test_other_sha_is_kept(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", "0" * 40))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertFalse(item["squash"])

    def test_glab_failure_is_kept_cant_verify(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", "x", exit_code=1))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertIn("can't verify MR", item["reason"])

    def test_glab_missing_is_kept_cant_verify(self):
        self.set_env(AW_GLAB=str(self.bin / "nope"))
        item = self.one(fetch=True)
        self.assertEqual(item["state"], "kept")
        self.assertIn("can't verify MR", item["reason"])

    def test_offline_never_calls_glab_or_fetch(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt), marker=self.marker))
        real = subprocess.run
        calls = []

        def spy(cmd, *a, **k):
            calls.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", spy):
            item = self.one(fetch=False)
        self.assertEqual(item["state"], "kept")
        self.assertIn("offline", item["reason"])
        self.assertFalse(self.marker.exists())
        self.assertFalse([c for c in calls if "fetch" in c])

    def test_fetch_true_fetches(self):
        self.set_env(AW_GLAB=glab_stub(self.bin / "glab", head(self.wt)))
        real = subprocess.run
        calls = []

        def spy(cmd, *a, **k):
            calls.append(list(cmd))
            return real(cmd, *a, **k)
        with mock.patch.object(ws.subprocess, "run", spy):
            self.one(fetch=True)
        self.assertTrue([c for c in calls if c[:2] == ["git", "fetch"]])


# Captured from `launchctl print gui/$UID/com.apple.Finder` (macOS 26.0, 2026-10-26): top-level keys have one
# leading tab, nested blocks two or more; nested blocks also carry `state = active`.
LAUNCHCTL_PRINT = ("gui/503/com.apple.Finder = {\n\tactive count = 5\n\tstate = running\n\n\tprogram = /System/x\n"
                   "\tpid = 5388\n\tlast exit code = (never exited)\n\n\tevent triggers = {\n"
                   "\t\tcom.apple.x => {\n\t\t\tstate = active\n\t\t}\n\t}\n}\n")


class Schedule(Base):
    def setUp(self):
        super().setUp()
        self.home = Path(self.tmp) / "home"
        self.home.mkdir()
        self.calls = Path(self.tmp) / "launchctl-calls"
        printed = LAUNCHCTL_PRINT.replace(chr(10), "\\n").replace(chr(9), "\\t")   # outside the f-string: Python 3.9 refuses a backslash in an f-string expression
        self.stub = write_stub(self.bin / "launchctl", f'echo "$@" >> "{self.calls}"\n'
                               f'case "$1" in print) [ -f "{self.tmp}/loaded" ] && {{ printf "%b" \'{printed}\'; exit 0; }}; echo "Could not find service" >&2; exit 113;; '
                               f'bootout) exit 3;; bootstrap) touch "{self.tmp}/loaded"; exit 0;; esac\n')
        self.sibling = Path(self.tmp) / "sibling-bin"   # where "the agent-board beside this CLI" is looked up
        self.sibling.mkdir()
        self.link = self.home / ".local" / "bin" / "agent-board"
        self.link.parent.mkdir(parents=True)
        write_stub(self.link, "exit 0\n")
        self.set_env(AW_LAUNCHCTL=self.stub, AW_HOME=str(self.home), AW_BIN_DIR=str(self.sibling))
        self.plist = self.home / "Library" / "LaunchAgents" / "com.user.agent-worktree-sweep.plist"
        real = Path.home() / "Library" / "LaunchAgents" / "com.user.agent-worktree-sweep.plist"
        before = (real.exists(), real.stat().st_mtime if real.exists() else None)
        self.addCleanup(lambda: self.assertEqual(
            (real.exists(), real.stat().st_mtime if real.exists() else None), before,
            "a schedule test touched the real LaunchAgents plist"))

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_plist_fields(self):
        cli = str(self.home / ".local" / "bin" / "agent-board")
        d = plistlib.loads(ws.plist_text(cli, str(self.home)))
        self.assertEqual(d["Label"], "com.user.agent-worktree-sweep")
        self.assertEqual(d["ProgramArguments"], [cli, "worktrees", "sweep", "--recent"])
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 4, "Minute": 0})
        log = str(self.home / ".local" / "state" / "agent-board" / "worktree-sweep.launchd.log")
        self.assertEqual((d["StandardOutPath"], d["StandardErrorPath"]), (log, log))
        path = d["EnvironmentVariables"]["PATH"]
        self.assertIn(f"{self.home}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin", path)

    @unittest.skipUnless(shutil.which("plutil"), "plutil is macOS only")
    def test_plist_passes_plutil_lint(self):
        f = Path(self.tmp) / "x.plist"
        f.write_bytes(ws.plist_text(str(self.home / ".local/bin/agent-board"), str(self.home)))
        r = subprocess.run(["plutil", "-lint", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_install_writes_plist_and_runs_bootout_then_bootstrap(self):
        lines = ws.schedule_install()
        d = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(d["ProgramArguments"][0], str(self.home / ".local" / "bin" / "agent-board"))
        uid = os.getuid()
        self.assertEqual(self.called(), [f"bootout gui/{uid}/com.user.agent-worktree-sweep",
                                         f"bootstrap gui/{uid} {self.plist}"])
        self.assertTrue((self.home / ".local" / "state" / "agent-board").is_dir())
        self.assertTrue(lines)

    def test_install_falls_back_to_the_agent_board_beside_the_cli(self):
        self.link.unlink()
        beside = self.sibling / "agent-board"
        write_stub(beside, "exit 0\n")
        ws.schedule_install()
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"][0], str(beside))

    def test_home_link_wins_over_the_sibling(self):
        write_stub(self.sibling / "agent-board", "exit 0\n")
        ws.schedule_install()
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"][0], str(self.link))

    def test_install_refuses_when_no_agent_board_is_executable(self):
        self.link.unlink()
        (self.sibling / "agent-board").write_text("not executable")   # present but not executable
        with self.assertRaises(RuntimeError) as cm:
            ws.schedule_install()
        self.assertIn(str(self.link), str(cm.exception))
        self.assertIn(str(self.sibling / "agent-board"), str(cm.exception))
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.called(), [])

    def test_cli_install_refuses_with_exit_1(self):
        self.link.unlink()
        env = {**os.environ, "AW_LAUNCHCTL": self.stub, "AW_HOME": str(self.home), "AW_BIN_DIR": str(self.sibling)}
        r = subprocess.run([sys.executable, str(CLI), "schedule", "install"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("agent-board", r.stderr)
        self.assertFalse(self.plist.exists())

    def test_status_says_when_the_target_is_missing(self):
        ws.schedule_install()
        self.link.unlink()
        out = ws.schedule_status()
        self.assertIn("state = running", out)
        self.assertIn(f"target missing: {self.link}", out)

    def test_status_without_plist_does_not_mention_a_target(self):
        self.assertEqual(ws.schedule_status(), ["not installed"])

    def test_install_backs_up_an_existing_plist(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("old")
        ws.schedule_install()
        baks = list(self.plist.parent.glob(self.plist.name + ".bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertRegex(baks[0].name, r"\.bak-\d{8}$")
        self.assertEqual(baks[0].read_text(), "old")
        self.assertNotEqual(self.plist.read_text(), "old")

    def test_install_bootstrap_failure_raises(self):
        write_stub(self.bin / "launchctl", 'case "$1" in bootstrap) echo "Bootstrap failed: 5" >&2; exit 5;; esac\n')
        with self.assertRaisesRegex(RuntimeError, "Bootstrap failed"):
            ws.schedule_install()

    def test_uninstall_boots_out_and_removes_the_file(self):
        ws.schedule_install()
        self.calls.unlink()
        ws.schedule_uninstall()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.called(), [f"bootout gui/{os.getuid()}/com.user.agent-worktree-sweep"])

    def test_uninstall_when_not_installed_is_fine(self):
        self.assertTrue(ws.schedule_uninstall())

    def test_status_not_installed(self):
        self.assertEqual(ws.schedule_status(), ["not installed"])

    def test_status_prints_only_the_service_state_and_exit_code(self):
        ws.schedule_install()
        self.assertEqual(ws.schedule_status(), ["state = running", "last exit code = (never exited)"])

    def test_launchctl_is_word_split(self):
        stub = write_stub(self.bin / "lcargs", '[ "$1" = "--flag" ] || exit 9\nexit 0\n')
        self.set_env(AW_LAUNCHCTL=f"{stub} --flag")
        with mock.patch.object(ws.subprocess, "run", wraps=subprocess.run) as run:
            ws.schedule_install()
        self.assertTrue(all(c.args[0][1] == "--flag" for c in run.call_args_list if c.args[0][0] == stub))

    def test_cli_schedule_install_status_uninstall(self):
        env = {**os.environ, "AW_LAUNCHCTL": self.stub, "AW_HOME": str(self.home)}
        run = lambda *a: subprocess.run([sys.executable, str(CLI), "schedule", *a], capture_output=True, text=True, env=env)
        r = run("install")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.plist.exists())
        self.assertIn("state = running", run("status").stdout)
        self.assertEqual(run("uninstall").returncode, 0)
        self.assertFalse(self.plist.exists())


if __name__ == "__main__":
    unittest.main()
