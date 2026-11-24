"""restore_schedule: the LaunchAgent that runs `agent-board restore tick` every minute."""
import os
import plistlib
import stat
import subprocess
import sys
import contextlib
import io
import tempfile
import time
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restore_schedule as rs  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        # the tests drive a stub launchctl: pass the module's macOS-only guard on any host
        pl = mock.patch.object(sys, "platform", "darwin")
        pl.start()
        self.addCleanup(pl.stop)
        self.tmp = tempfile.mkdtemp()
        self.home = Path(self.tmp) / "home"
        self.home.mkdir()
        self.log = Path(self.tmp) / "launchctl.log"
        stub = Path(self.tmp) / "launchctl"
        stub.write_text(
            '#!/bin/sh\necho "$@" >> "%s"\n[ "$1" = print ] && [ -n "$RS_PRINT_FAIL" ] && exit 113\n'
            '[ "$1" = print ] && printf "\\tstate = running\\n"\nexit 0\n' % self.log)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        env = {"HOME": str(self.home), "RS_LAUNCHCTL": str(stub)}
        p = mock.patch.dict(os.environ, env)
        p.start()
        os.environ.pop("TC_STATE", None)
        self.addCleanup(p.stop)
        bindir = self.home / ".local" / "bin"
        bindir.mkdir(parents=True)
        self.cli = bindir / "agent-board"
        self.cli.write_text("#!/bin/sh\n")
        self.cli.chmod(0o755)
        self.plist = self.home / "Library" / "LaunchAgents" / "com.user.agent-board-restore.plist"

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class Install(Base):
    def test_plist_keys(self):
        rs.install()
        d = plistlib.loads(self.plist.read_bytes())
        cli = self.cli
        self.assertEqual(d["Label"], "com.user.agent-board-restore")
        self.assertIs(d["RunAtLoad"], True)
        self.assertEqual(d["StartInterval"], 60)
        self.assertNotIn("StartCalendarInterval", d)
        self.assertIs(d["AbandonProcessGroup"], True)
        self.assertEqual(d["EnvironmentVariables"]["LANG"], os.environ.get("LANG") or "en_US.UTF-8")
        self.assertEqual(d["WorkingDirectory"], str(self.home))
        self.assertEqual(d["ProgramArguments"], [str(cli), "restore", "tick"])
        h = str(self.home)
        self.assertEqual(d["EnvironmentVariables"]["PATH"],
                         f"{h}/.local/bin:/opt/homebrew/bin:{h}/.bun/bin:/usr/bin:/bin")
        log = f"{h}/.local/state/agent-board/restore/launchd.log"
        self.assertEqual(d["StandardOutPath"], log)
        self.assertEqual(d["StandardErrorPath"], log)
        self.assertTrue(Path(log).parent.is_dir())

    def test_no_executable_cli_raises_and_writes_nothing(self):
        self.cli.chmod(0o644)
        empty = Path(self.tmp) / "empty"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"AW_BIN_DIR": str(empty)}):
            with self.assertRaisesRegex(RuntimeError, "no executable agent-board"):
                rs.install()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [])

    def test_falls_back_to_cli_beside_module(self):
        self.cli.unlink()
        beside = Path(self.tmp) / "beside"
        beside.mkdir()
        (beside / "agent-board").write_text("#!/bin/sh\n")
        (beside / "agent-board").chmod(0o755)
        with mock.patch.dict(os.environ, {"AW_BIN_DIR": str(beside)}):
            rs.install()
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["ProgramArguments"][0], str(beside / "agent-board"))

    def test_bootout_then_bootstrap(self):
        rs.install()
        uid = os.getuid()
        self.assertEqual(self.calls(), [f"bootout gui/{uid}/com.user.agent-board-restore",
                                        f"bootstrap gui/{uid} {self.plist}"])

    def test_backs_up_existing_plist(self):
        self.plist.parent.mkdir(parents=True)
        self.plist.write_text("old")
        lines = rs.install()
        bak = self.plist.with_name(f"{self.plist.name}.bak-{datetime.now():%Y%m%d}")
        self.assertEqual(bak.read_text(), "old")
        self.assertTrue(any(str(bak) in l for l in lines))

    def test_bootstrap_failure_raises(self):
        Path(os.environ["RS_LAUNCHCTL"]).write_text("#!/bin/sh\n[ \"$1\" = bootstrap ] && { echo nope >&2; exit 5; }\nexit 0\n")
        with self.assertRaisesRegex(RuntimeError, "nope"):
            rs.install()


class UninstallStatus(Base):
    def test_uninstall_boots_out_and_removes(self):
        rs.install()
        self.log.unlink()
        lines = rs.uninstall()
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [f"bootout gui/{os.getuid()}/com.user.agent-board-restore"])
        self.assertTrue(any("removed" in l for l in lines))
        self.assertEqual(rs.uninstall(), ["not installed"])

    def test_uninstall_marks_the_snapshot_restored(self):
        import restore
        with mock.patch.dict(os.environ, {"TC_STATE": str(Path(self.tmp) / "st")}):
            d = restore.restore_dir()
            restore.save(d, {"boot": 5, "saved_at": 1.0, "restored": False, "awake": None,
                             "projects": [{"name": "a", "path": "/x", "lead": None, "bridge": False}]})
            rs.install()
            lines = rs.uninstall()
            self.assertTrue(restore.load(d)["restored"])
            self.assertTrue(any("restored" in l for l in lines))

    def test_uninstall_without_a_snapshot_is_fine(self):
        with mock.patch.dict(os.environ, {"TC_STATE": str(Path(self.tmp) / "st2")}):
            rs.install()
            rs.uninstall()
            self.assertFalse((Path(self.tmp) / "st2" / "restore" / "snapshot.json").exists())

    def fake_restore(self, snap):
        m = types.ModuleType("restore")
        m.restore_dir = lambda: Path(self.tmp) / "r"
        m.load = lambda d: snap
        return mock.patch.dict(sys.modules, {"restore": m})

    def test_status_not_loaded(self):
        os.environ["RS_PRINT_FAIL"] = "1"
        self.addCleanup(os.environ.pop, "RS_PRINT_FAIL", None)
        with self.fake_restore(None):
            self.assertEqual(rs.status()[0], "not loaded")

    def test_status_loaded_with_snapshot(self):
        snap = {"boot": 1794897652, "saved_at": time.time() - 120,
                "projects": [{"name": "agent-board"}, {"name": "interiors"}]}
        with self.fake_restore(snap):
            out = "\n".join(rs.status())
        self.assertIn("loaded", out)
        self.assertNotIn("not loaded", out)
        self.assertRegex(out, r"age 2m")
        self.assertIn("1794897652", out)
        self.assertIn("agent-board, interiors", out)

    def test_status_loaded_no_snapshot(self):
        with self.fake_restore(None):
            out = "\n".join(rs.status())
        self.assertIn("no snapshot", out)


class NotMac(Base):
    def test_non_darwin_exit_2(self):
        with mock.patch.object(sys, "platform", "linux"):
            for fn in (rs.install, rs.uninstall, rs.status):
                with self.assertRaises(rs.MacOnly) as cm:
                    fn()
                self.assertEqual(cm.exception.code, 2)
                self.assertEqual(str(cm.exception), "macOS only")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(rs.main("install"), 2)
            self.assertEqual(out.getvalue().strip(), "macOS only")
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls(), [])


class RealPlatform(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "darwin", "launchctl is macOS only")
    def test_real_launchctl_runs(self):
        r = subprocess.run(["launchctl", "print", "gui/%d/com.user.nonexistent-rs-test" % os.getuid()],
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        r2 = rs._launchctl("print", "gui/%d/com.user.nonexistent-rs-test" % os.getuid())
        self.assertNotEqual(r2.returncode, 0)


if __name__ == "__main__":
    unittest.main()
