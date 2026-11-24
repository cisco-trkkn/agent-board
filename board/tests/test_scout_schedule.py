"""scout_schedule: three LaunchAgents (poll 06:00, weekly Sun 07:00, weekly --retry Mon 07:00), launchctl faked."""
import contextlib
import io
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scout_schedule as ss  # noqa: E402

POLL = "com.user.agent-board-scout-poll"
WEEKLY = "com.user.agent-board-scout-weekly"
RETRY = "com.user.agent-board-scout-weekly-retry"
LABELS = [POLL, WEEKLY, RETRY]


class Base(unittest.TestCase):
    def setUp(self):
        # the tests drive a stub launchctl: pass the module's macOS-only guard on any host
        pl = mock.patch.object(sys, "platform", "darwin")
        pl.start()
        self.addCleanup(pl.stop)
        self.tmp = tempfile.mkdtemp()
        self.home = Path(self.tmp) / "home"
        self.home.mkdir()
        self.sdir = Path(self.tmp) / "scout"
        self.log = Path(self.tmp) / "launchctl.log"
        stub = Path(self.tmp) / "launchctl"
        stub.write_text('#!/bin/sh\necho "$@" >> "%s"\n'
                        '[ "$1" = print ] && [ -n "$SS_PRINT_FAIL" ] && case "$2" in *"$SS_PRINT_FAIL") exit 113;; esac\n'
                        '[ "$1" = bootstrap ] && [ -n "$SS_BOOT_FAIL" ] && { echo nope >&2; exit 5; }\nexit 0\n' % self.log)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "AS_LAUNCHCTL": str(stub),
                                         "TC_SCOUT_DIR": str(self.sdir), "TC_STATE": str(Path(self.tmp) / "st")})
        p.start()
        self.addCleanup(p.stop)
        for k in ("SS_PRINT_FAIL", "SS_BOOT_FAIL", "TC_SCOUT", "AS_BIN_DIR"):
            os.environ.pop(k, None)
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        self.cli = bindir / "tmux-ctl"
        self.cli.write_text("#!/bin/sh\n")
        self.cli.chmod(0o755)

    def plist(self, label):
        return self.home / "Library" / "LaunchAgents" / f"{label}.plist"

    def loaded(self, label):
        return plistlib.loads(self.plist(label).read_bytes())

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class Plist(Base):
    def test_poll(self):
        ss.install()
        d = self.loaded(POLL)
        self.assertEqual(d["Label"], POLL)
        self.assertEqual(d["ProgramArguments"], [str(self.cli), "scout", "poll"])
        self.assertEqual(d["StartCalendarInterval"], {"Hour": 6, "Minute": 0})
        self.assertEqual(d["StandardOutPath"], str(self.sdir / "launchd-poll.log"))
        self.assertEqual(d["StandardErrorPath"], str(self.sdir / "launchd-poll.log"))

    def test_weekly(self):
        ss.install()
        d = self.loaded(WEEKLY)
        self.assertEqual(d["ProgramArguments"], [str(self.cli), "scout", "weekly"])
        self.assertEqual(d["StartCalendarInterval"], {"Weekday": 0, "Hour": 7, "Minute": 0})
        self.assertEqual(d["StandardOutPath"], str(self.sdir / "launchd-weekly.log"))

    def test_weekly_retry(self):
        ss.install()
        d = self.loaded(RETRY)
        self.assertEqual(d["ProgramArguments"], [str(self.cli), "scout", "weekly", "--retry"])
        self.assertEqual(d["StartCalendarInterval"], {"Weekday": 1, "Hour": 7, "Minute": 0})
        self.assertEqual(d["StandardOutPath"], str(self.sdir / "launchd-weekly.log"))

    def test_common_keys_and_env(self):
        ss.install()
        h = str(self.home)
        root = str(Path(ss.__file__).resolve().parent.parent)
        for label in LABELS:
            d = self.loaded(label)
            self.assertEqual(d["WorkingDirectory"], root)
            self.assertNotIn("--root", d["ProgramArguments"])
            for k in ("RunAtLoad", "StartInterval", "AbandonProcessGroup"):
                self.assertNotIn(k, d)
            env = d["EnvironmentVariables"]
            self.assertEqual(env["PATH"], f"{h}/.local/bin:/opt/homebrew/bin:{h}/.bun/bin:/usr/bin:/bin")
            self.assertEqual(env["TC_SCOUT_DIR"], str(self.sdir))
            self.assertEqual(env["TC_STATE"], str(Path(self.tmp) / "st"))
            self.assertIn("LANG", env)

    def test_env_without_pins(self):
        for k in ("TC_SCOUT_DIR", "TC_STATE"):
            os.environ.pop(k)
        with mock.patch.dict(os.environ, {"TMPDIR": "/var/folders/xx/T/"}):
            ss.install()
        env = self.loaded(POLL)["EnvironmentVariables"]
        self.assertNotIn("TC_SCOUT_DIR", env)
        self.assertNotIn("TC_STATE", env)
        self.assertEqual(env["TMPDIR"], "/var/folders/xx/T/")

    @unittest.skipUnless(sys.platform == "darwin", "plutil is macOS only")
    def test_plutil_lint(self):
        ss.install()
        for label in LABELS:
            r = subprocess.run(["plutil", "-lint", str(self.plist(label))], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Install(Base):
    def test_writes_three_and_bootstraps_three(self):
        lines = ss.install()
        uid = os.getuid()
        for label in LABELS:
            self.assertTrue(self.plist(label).is_file())
        expect = []
        for label in LABELS:
            expect += [f"bootout gui/{uid}/{label}", f"bootstrap gui/{uid} {self.plist(label)}"]
        self.assertEqual(self.calls(), expect)
        self.assertEqual(len(lines), 3)
        self.assertTrue(any("scout poll" in l and "06:00" in l for l in lines))
        self.assertTrue(any("weekly --retry" in l and "Monday" in l for l in lines))

    def test_no_executable_cli_writes_nothing(self):
        self.cli.chmod(0o644)
        empty = Path(self.tmp) / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"AS_BIN_DIR": str(empty)}):
            with self.assertRaisesRegex(RuntimeError, "no executable tmux-ctl"):
                ss.install()
        for label in LABELS:
            self.assertFalse(self.plist(label).exists())
        self.assertEqual(self.calls(), [])

    def test_backs_up_existing_plist(self):
        self.plist(POLL).parent.mkdir(parents=True)
        self.plist(POLL).write_text("old")
        lines = ss.install()
        bak = self.plist(POLL).with_name(f"{POLL}.plist.bak-{datetime.now():%Y%m%d}")
        self.assertEqual(bak.read_text(), "old")
        self.assertTrue(any(str(bak) in l for l in lines))

    def test_bootstrap_failure_exits_1(self):
        os.environ["SS_BOOT_FAIL"] = "1"
        with self.assertRaisesRegex(RuntimeError, "nope"):
            ss.install()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ss.main("install"), 1)
        self.assertIn("nope", err.getvalue())


class UninstallStatus(Base):
    def test_uninstall_boots_out_and_removes_all(self):
        ss.install()
        self.log.unlink()
        lines = ss.uninstall()
        for label in LABELS:
            self.assertFalse(self.plist(label).exists())
        self.assertEqual(self.calls(), [f"bootout gui/{os.getuid()}/{l}" for l in LABELS])
        self.assertEqual(len([l for l in lines if "removed" in l]), 3)
        self.assertEqual(ss.uninstall(), ["not installed"])

    def test_status_loaded_per_job(self):
        out = ss.status()
        self.assertEqual(out[:3], ["poll: loaded", "weekly: loaded", "weekly (Monday retry): loaded"])
        self.assertEqual(self.calls(), [f"print gui/{os.getuid()}/{l}" for l in LABELS])

    def test_status_not_loaded_is_per_label(self):
        os.environ["SS_PRINT_FAIL"] = "weekly-retry"
        out = ss.status()
        self.assertEqual(out[:3], ["poll: loaded", "weekly: loaded", "weekly (Monday retry): not loaded"])

    def test_status_last_lines_none(self):
        self.assertEqual(ss.status()[3:], ["last poll: none", "last weekly: none"])

    def test_status_last_log_lines(self):
        self.sdir.mkdir(parents=True)
        (self.sdir / "poll.log").write_text("2026-11-20T06:00:01 old\n2026-11-21T06:00:02 polled 4 sources\n\n")
        (self.sdir / "weekly.log").write_text("2026-11-15T07:00:00 drafted 2\n")
        self.assertEqual(ss.status()[3:], ["last poll: 2026-11-21T06:00:02 polled 4 sources",
                                           "last weekly: 2026-11-15T07:00:00 drafted 2"])

    def test_status_off_switches(self):
        self.assertEqual([l for l in ss.status() if l.startswith("off:")], [])
        os.environ["TC_SCOUT"] = "0"
        self.assertIn("off: TC_SCOUT=0", ss.status())
        del os.environ["TC_SCOUT"]
        self.sdir.mkdir(parents=True)
        (self.sdir / "off").write_text("")
        self.assertIn("off: off file", ss.status())

    def test_main_usage_and_status(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ss.main("bogus"), 2)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ss.main("status"), 0)
        self.assertEqual(out.getvalue().splitlines()[0], "poll: loaded")


class NotMac(Base):
    def test_non_darwin_exit_2(self):
        with mock.patch.object(sys, "platform", "linux"):
            for fn in (ss.install, ss.uninstall, ss.status):
                with self.assertRaises(ss.MacOnly) as cm:
                    fn()
                self.assertEqual(str(cm.exception), "macOS only")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(ss.main("install"), 2)
            self.assertEqual(out.getvalue().strip(), "macOS only")
        for label in LABELS:
            self.assertFalse(self.plist(label).exists())
        self.assertEqual(self.calls(), [])


REAL = [Path(os.path.expanduser("~")) / "Library" / "LaunchAgents" / f"{l}.plist" for l in LABELS]
_BEFORE = None


def setUpModule():
    global _BEFORE
    _BEFORE = [p.exists() for p in REAL]


def tearDownModule():
    assert [p.exists() for p in REAL] == _BEFORE, "real scout plist existence changed"


if __name__ == "__main__":
    unittest.main()
