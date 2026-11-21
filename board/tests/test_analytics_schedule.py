"""analytics_schedule: the LaunchAgent that runs `tmux-ctl metrics weekly` Mondays at 09:00."""
import contextlib
import io
import json
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
import analytics_schedule as ds  # noqa: E402

LABEL = "com.user.agent-board-analytics"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.home = Path(self.tmp) / "home"
        self.home.mkdir()
        self.log = Path(self.tmp) / "launchctl.log"
        stub = Path(self.tmp) / "launchctl"
        stub.write_text('#!/bin/sh\necho "$@" >> "%s"\n[ "$1" = print ] && [ -n "$AS_PRINT_FAIL" ] && exit 113\nexit 0\n' % self.log)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "AS_LAUNCHCTL": str(stub),
                                         "TC_ANALYTICS": "1"})
        p.start()
        self.addCleanup(p.stop)
        for k in ("TC_STATE", "AS_PRINT_FAIL", "TC_ANALYTICS"):
            os.environ.pop(k, None)
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        self.cli = bindir / "tmux-ctl"
        self.cli.write_text("#!/bin/sh\n")
        self.cli.chmod(0o755)
        self.plist = self.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def loaded(self):
        return plistlib.loads(self.plist.read_bytes())


class Plist(Base):
    def test_plist_keys(self):
        ds.install()
        d = self.loaded()
        h = str(self.home)
        log = f"{h}/.local/state/agent-board/analytics.launchd.log"
        self.assertEqual(d["Label"], LABEL)
        self.assertEqual(d["ProgramArguments"], [str(self.cli), "metrics", "weekly"])
        self.assertEqual(d["StartCalendarInterval"], {"Weekday": 1, "Hour": 9, "Minute": 0})
        self.assertEqual(d["WorkingDirectory"], h)
        self.assertEqual(d["StandardOutPath"], log)
        self.assertEqual(d["StandardErrorPath"], log)
        self.assertEqual(d["EnvironmentVariables"]["PATH"], f"{h}/.local/bin:/opt/homebrew/bin:{h}/.bun/bin:/usr/bin:/bin")
        self.assertIn("LANG", d["EnvironmentVariables"])
        self.assertTrue(Path(log).parent.is_dir())

    def test_no_run_at_load(self):
        ds.install()
        d = self.loaded()
        for k in ("RunAtLoad", "StartInterval", "AbandonProcessGroup"):
            self.assertNotIn(k, d)

    def test_tmpdir_written_when_tc_state_unset(self):
        with mock.patch.dict(os.environ, {"TMPDIR": "/var/folders/xx/T/"}):
            ds.install()
        env = self.loaded()["EnvironmentVariables"]
        self.assertEqual(env["TMPDIR"], "/var/folders/xx/T/")
        self.assertNotIn("TC_STATE", env)

    def test_tc_state_written_when_set(self):
        with mock.patch.dict(os.environ, {"TC_STATE": str(Path(self.tmp) / "st"), "TMPDIR": "/var/folders/xx/T/"}):
            ds.install()
        env = self.loaded()["EnvironmentVariables"]
        self.assertEqual(env["TC_STATE"], str(Path(self.tmp) / "st"))
        self.assertNotIn("TMPDIR", env)

    @unittest.skipUnless(sys.platform == "darwin", "plutil is macOS only")
    def test_plutil_lint(self):
        f = Path(self.tmp) / "x.plist"
        f.write_bytes(ds.plist_text(self.cli, self.home, self.home / "l.log"))
        r = subprocess.run(["plutil", "-lint", str(f)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class Install(Base):
    def test_no_executable_cli_raises_and_writes_nothing(self):
        self.cli.chmod(0o644)
        empty = Path(self.tmp) / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"TW_BIN_DIR": str(empty), "AS_BIN_DIR": str(empty)}):
            with self.assertRaisesRegex(RuntimeError, "no executable tmux-ctl"):
                ds.install()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [])

    def test_falls_back_to_cli_beside_checkout(self):
        self.cli.unlink()
        beside = Path(self.tmp) / "beside"
        beside.mkdir()
        (beside / "tmux-ctl").write_text("#!/bin/sh\n")
        (beside / "tmux-ctl").chmod(0o755)
        with mock.patch.dict(os.environ, {"AS_BIN_DIR": str(beside)}):
            ds.install()
        self.assertEqual(self.loaded()["ProgramArguments"][0], str(beside / "tmux-ctl"))

    def test_bootout_then_bootstrap(self):
        ds.install()
        uid = os.getuid()
        self.assertEqual(self.calls(), [f"bootout gui/{uid}/{LABEL}", f"bootstrap gui/{uid} {self.plist}"])

    def test_backs_up_existing_plist(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("old")
        lines = ds.install()
        bak = self.plist.with_name(f"{self.plist.name}.bak-{datetime.now():%Y%m%d}")
        self.assertEqual(bak.read_text(), "old")
        self.assertTrue(any(str(bak) in l for l in lines))

    def test_bootstrap_failure_exits_1_with_message(self):
        Path(os.environ["AS_LAUNCHCTL"]).write_text('#!/bin/sh\n[ "$1" = bootstrap ] && { echo nope >&2; exit 5; }\nexit 0\n')
        with self.assertRaisesRegex(RuntimeError, "nope"):
            ds.install()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ds.main("install"), 1)
        self.assertIn("nope", err.getvalue())


class UninstallStatus(Base):
    def test_uninstall_boots_out_and_removes(self):
        ds.install()
        self.log.unlink()
        lines = ds.uninstall()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [f"bootout gui/{os.getuid()}/{LABEL}"])
        self.assertTrue(any("removed" in l for l in lines))
        self.assertEqual(ds.uninstall(), ["not installed"])

    def test_status_not_loaded_first_line(self):
        os.environ["AS_PRINT_FAIL"] = "1"
        self.assertEqual(ds.status()[0], "not loaded")

    def test_status_loaded_first_line(self):
        self.assertEqual(ds.status()[0], "loaded")
        self.assertEqual(self.calls(), [f"print gui/{os.getuid()}/{LABEL}"])

    def _runs(self, *lines):
        d = Path(self.tmp) / "repo"
        d.mkdir(exist_ok=True)
        (d / "runs.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))
        return mock.patch.object(ds, "_runs_path", return_value=d / "runs.jsonl")

    def test_status_last_run_none(self):
        with self._runs():
            self.assertEqual(ds.status(), ["loaded", "last run: none"])

    def test_status_last_run_newest_analytics_line(self):
        with self._runs({"kind": "analytics", "at": "2026-11-16T07:00:00Z", "outcome": "posted"},
                        {"kind": "run", "at": "2026-11-17T07:00:00Z"},
                        {"kind": "analytics", "at": "2026-11-23T07:00:00Z", "outcome": "no-runs"},
                        {"kind": "run", "at": "2026-11-24T07:00:00Z"}):
            self.assertEqual(ds.status(), ["loaded", "last run: 2026-11-23T07:00:00Z no-runs"])

    def test_status_off_switches(self):
        os.environ["TC_ANALYTICS"] = "0"
        self.assertIn("off: TC_ANALYTICS=0", ds.status())
        del os.environ["TC_ANALYTICS"]
        self.assertNotIn("off: analytics.off", ds.status())
        base = Path(self.home) / ".local" / "state" / "agent-board"
        base.mkdir(parents=True)
        (base / "analytics.off").write_text("")
        self.assertIn("off: analytics.off", ds.status())

    def test_main_prints_status(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ds.main("status"), 0)
        self.assertEqual(out.getvalue().splitlines()[0], "loaded")


class NotMac(Base):
    def test_non_darwin_exit_2(self):
        with mock.patch.object(sys, "platform", "linux"):
            for fn in (ds.install, ds.uninstall, ds.status):
                with self.assertRaises(ds.MacOnly) as cm:
                    fn()
                self.assertEqual(str(cm.exception), "macOS only")
            for cmd in ("install", "uninstall", "status"):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(ds.main(cmd), 2)
                self.assertEqual(out.getvalue().strip(), "macOS only")
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [])


REAL_PLIST = Path(os.path.expanduser("~")) / "Library" / "LaunchAgents" / f"{LABEL}.plist"
_BEFORE = None


def setUpModule():
    global _BEFORE
    _BEFORE = REAL_PLIST.exists()


def tearDownModule():
    # the tests patch HOME: the real plist must not appear or vanish
    assert REAL_PLIST.exists() == _BEFORE, f"real plist existence changed: {REAL_PLIST}"


if __name__ == "__main__":
    unittest.main()
