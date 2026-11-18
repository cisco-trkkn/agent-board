"""board/restore.py part 1: boot_time, snapshot and the save guards. Every external read goes through a fake run()."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restore  # noqa: E402

BOOT_LINE = "{ sec = 1794897652, usec = 269307 } Tue Nov 17 01:40:52 2026\n"
NOW = 1794896100.0
DISCORD = "plugin:discord@claude-plugins-official"
BRIDGE_ARGS = "node /x/discord-bridge/bridge.js"
TMUX = ["tmux"]


class Fake:
    """run(cmd) -> (rc, out) for sysctl, tmux list-sessions / list-panes and ps."""

    def __init__(self, sessions="", panes="", ps="", fail=()):
        self.sessions, self.panes, self.ps, self.fail = sessions, panes, ps, set(fail)
        self.calls = []

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        for key, out in (("sysctl", BOOT_LINE), ("list-sessions", self.sessions), ("list-panes", self.panes), ("ps", self.ps)):
            if key in cmd or os.path.basename(cmd[0]) == key:
                return (1, "") if key in self.fail else (0, out)
        return 1, ""


def sess(*rows):
    return "".join("\t".join(r) + "\n" for r in rows)   # name, group, path, @tc_bg


def panes(*rows):
    return "".join("\t".join(r) + "\n" for r in rows)   # session, window, pane_id, pane_pid


def ps(*rows):
    return "".join(f"{p} {pp} {a}\n" for p, pp, a in rows)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.sdir = self.dir / "agent-status"
        self.sdir.mkdir()
        self.awake = self.dir / "awake.json"

    def status(self, sid, pane, updated=NOW):
        (self.sdir / f"{sid}.json").write_text(json.dumps({"session_id": sid, "pane": pane, "state": "ready", "updatedAt": updated}))

    def snap(self, fake, pid_alive=None):
        return restore.snapshot(run=fake, tmux=TMUX, status_dir=self.sdir, awake_file=self.awake, now=NOW,
                                pid_alive=pid_alive or (lambda p: True))

    def proj(self, snap, name):
        return next(p for p in snap["projects"] if p["name"] == name)


class BootTime(unittest.TestCase):
    def test_parses_sec(self):
        self.assertEqual(restore.boot_time(run=lambda c: (0, BOOT_LINE)), 1794897652)

    @unittest.skipUnless(sys.platform == "darwin", "kern.boottime is macOS")
    def test_real_sysctl_on_this_host(self):
        b = restore.boot_time()
        self.assertIsInstance(b, int)
        self.assertGreater(b, 1_000_000_000)

    def test_sysctl_called_by_absolute_path(self):
        seen = []
        restore.boot_time(run=lambda c: (seen.append(c), (0, BOOT_LINE))[1])
        self.assertEqual(seen[0][0], "/usr/sbin/sysctl")

    @unittest.skipUnless(sys.platform == "darwin", "kern.boottime is macOS")
    def test_real_boot_time_under_the_launchd_environment(self):
        home = os.environ.get("HOME", "")
        plist_path = f"{home}/.local/bin:/opt/homebrew/bin:{home}/.bun/bin:/usr/bin:/bin"
        board = str(Path(restore.__file__).resolve().parent)
        code = f"import sys; sys.path.insert(0, {board!r}); import restore; print(restore.boot_time())"
        r = subprocess.run(["/usr/bin/env", "-i", f"HOME={home}", f"PATH={plist_path}", sys.executable, "-I", "-c", code],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertGreater(int(r.stdout.strip()), 1_000_000_000)

    def test_none_when_unreadable_or_failing(self):
        self.assertIsNone(restore.boot_time(run=lambda c: (0, "garbage")))
        self.assertIsNone(restore.boot_time(run=lambda c: (1, BOOT_LINE)))

    def test_none_when_run_raises(self):
        def boom(c):
            raise OSError("no sysctl")
        self.assertIsNone(restore.boot_time(run=boom))


class Projects(Base):
    def test_one_entry_per_project_group_wins_and_skips(self):
        f = Fake(
            sessions=sess(("alpha", "", "/p/alpha", ""), ("alpha-2", "alpha", "/p/alpha", ""), ("beta", "", "/p/beta", ""),
                          ("alpha-bg", "", "/p/alpha", ""), ("hid", "", "/p/hid", "1"), ("_web-1", "", "/p/w", ""),
                          ("overseer", "", "/p/o", ""), ("nolead", "", "/p/n", "")),
            panes=panes(*[(s, "claude", f"%{i}", "1") for i, s in enumerate(
                ["alpha", "alpha-2", "beta", "alpha-bg", "hid", "_web-1", "overseer"])] + [("nolead", "shell", "%9", "1")]))
        snap = self.snap(f)
        self.assertEqual(sorted(p["name"] for p in snap["projects"]), ["alpha", "beta"])
        self.assertEqual(self.proj(snap, "alpha")["path"], "/p/alpha")
        self.assertEqual(snap["boot"], 1794897652)
        self.assertEqual(snap["saved_at"], NOW)
        self.assertIs(snap["restored"], False)

    def test_unexpected_error_goes_to_on_error(self):
        seen = []

        def boom(c):
            raise RuntimeError("x")
        self.assertIsNone(restore.snapshot(run=boom, tmux=TMUX, status_dir=self.sdir, awake_file=self.awake, now=NOW,
                                           on_error=seen.append))
        self.assertEqual([type(e).__name__ for e in seen], ["RuntimeError"])

    def test_tmux_failure_returns_none_and_never_raises(self):
        self.assertIsNone(self.snap(Fake(fail=["list-sessions"])))

        def boom(c):
            raise RuntimeError("x")
        self.assertIsNone(restore.snapshot(run=boom, tmux=TMUX, status_dir=self.sdir, awake_file=self.awake, now=NOW))


class Lead(Base):
    def one(self, args, extra_ps=()):
        f = Fake(sessions=sess(("alpha", "", "/p/alpha", "")), panes=panes(("alpha", "claude", "%1", "100")),
                 ps=ps((100, 1, "-zsh"), (101, 100, args), *extra_ps))
        return self.proj(self.snap(f), "alpha")

    def test_lead_fields(self):
        self.status("sid-1", "%1")
        p = self.one(f"/bin/claude --model opus --channels {DISCORD}")
        self.assertEqual(p["lead"], {"session_id": "sid-1", "model": "opus", "discord": True})

    def test_missing_fields_are_null_false(self):
        p = self.one("/usr/local/bin/claude --dangerously-skip-permissions")
        self.assertEqual(p["lead"], {"session_id": None, "model": None, "discord": False})

    def test_pane_pid_itself_may_be_claude(self):
        f = Fake(sessions=sess(("alpha", "", "/p", "")), panes=panes(("alpha", "claude", "%1", "100")),
                 ps=ps((100, 1, "claude --model sonnet")))
        self.assertEqual(self.proj(self.snap(f), "alpha")["lead"]["model"], "sonnet")

    def test_lead_null_when_pane_runs_a_shell(self):
        self.assertIsNone(self.one("vim x")["lead"])

    def test_ps_failure_leaves_lead_null(self):
        f = Fake(sessions=sess(("alpha", "", "/p", "")), panes=panes(("alpha", "claude", "%1", "100")), fail=["ps"])
        self.assertIsNone(self.proj(self.snap(f), "alpha")["lead"])

    def test_stale_status_record_ignored(self):
        self.status("sid-1", "%1", updated=NOW - 1000)
        self.assertIsNone(self.one("claude")["lead"]["session_id"])


class Bridge(Base):
    def run_with(self, bridge_panes, bridge_ps):
        f = Fake(sessions=sess(("alpha", "", "/p", ""), ("alpha-bg", "", "/p", "")),
                 panes=panes(("alpha", "claude", "%1", "100"), *bridge_panes), ps=ps((100, 1, "claude"), *bridge_ps))
        return self.proj(self.snap(f), "alpha")["bridge"]

    def test_bridge_true(self):
        self.assertTrue(self.run_with([("alpha-bg", "discord", "%5", "200")], [(201, 200, BRIDGE_ARGS)]))

    def test_bridge_false_without_window_or_process(self):
        self.assertFalse(self.run_with([], []))
        self.assertFalse(self.run_with([("alpha-bg", "discord", "%5", "200")], [(201, 200, "-zsh")]))


class Awake(Base):
    def setUp(self):
        super().setUp()
        self.f = Fake(sessions=sess(("alpha", "", "/p/a", ""), ("beta", "", "/p/b", "")),
                      panes=panes(("alpha", "claude", "%1", "100"), ("beta", "claude", "%2", "300")),
                      ps=ps((100, 1, "-zsh"), (101, 100, "claude"), (300, 1, "-zsh"), (301, 300, "claude")))

    def hold(self, **kw):
        self.awake.write_text(json.dumps({"caffeinatePid": 999, "since": 1, **kw}))

    def test_queue_hold_names_first_lead_project(self):
        self.hold(pid=4242, queue=True)
        self.assertEqual(self.snap(self.f)["awake"], {"lid": False, "queue": True, "project": "alpha"})

    def test_pid_hold_matches_lead_or_ancestor(self):
        self.hold(pid=301)
        self.assertEqual(self.snap(self.f)["awake"], {"lid": False, "queue": False, "project": "beta"})
        self.hold(pid=300, lid=True)
        self.assertEqual(self.snap(self.f)["awake"], {"lid": True, "queue": False, "project": "beta"})

    def test_dead_or_absent_hold_is_null(self):
        self.assertIsNone(self.snap(self.f)["awake"])
        self.hold(pid=101)
        self.assertIsNone(self.snap(self.f, pid_alive=lambda p: False)["awake"])

    def test_unreadable_awake_file_is_null(self):
        self.awake.write_text("{not json")
        self.assertIsNone(self.snap(self.f)["awake"])


def snap_of(boot, n=1, restored=False):
    return {"boot": boot, "saved_at": 1.0, "restored": restored, "awake": None,
            "projects": [{"name": f"p{i}", "path": "/x", "lead": None, "bridge": False} for i in range(n)]}


class Save(Base):
    def test_writes_snapshot_json_via_next_and_loads_back(self):
        d = self.dir / "restore"
        self.assertTrue(restore.save(d, snap_of(10)))
        self.assertEqual(restore.load(d)["boot"], 10)
        self.assertEqual(sorted(os.listdir(d)), ["snapshot.json"])

    def test_load_none_when_absent_or_corrupt(self):
        self.assertIsNone(restore.load(self.dir / "nope"))
        (self.dir / "snapshot.json").write_text("{")
        self.assertIsNone(restore.load(self.dir))

    def test_zero_project_snapshot_never_replaces(self):
        restore.save(self.dir, snap_of(10, n=2, restored=True))
        self.assertFalse(restore.save(self.dir, snap_of(10, n=0)))
        self.assertEqual(len(restore.load(self.dir)["projects"]), 2)

    def test_earlier_boot_unrestored_never_replaced(self):
        restore.save(self.dir, snap_of(1000, restored=False))
        self.assertFalse(restore.save(self.dir, snap_of(2000)))
        self.assertEqual(restore.load(self.dir)["boot"], 1000)

    def test_boot_within_60s_counts_as_the_same_boot(self):
        restore.save(self.dir, snap_of(1000, restored=False))
        self.assertTrue(restore.save(self.dir, snap_of(1060)))
        self.assertFalse(restore.save(self.dir, snap_of(1121)))

    def test_earlier_boot_restored_is_replaced_and_same_boot_is_replaced(self):
        restore.save(self.dir, snap_of(1000, restored=True))
        self.assertTrue(restore.save(self.dir, snap_of(2000)))
        self.assertTrue(restore.save(self.dir, snap_of(2000, n=2)))
        self.assertEqual(len(restore.load(self.dir)["projects"]), 2)

    def test_boot_none_or_snapshot_none_not_saved(self):
        self.assertFalse(restore.save(self.dir, None))
        self.assertFalse(restore.save(self.dir, snap_of(None)))
        self.assertIsNone(restore.load(self.dir))

    def test_restore_dir_is_agent_base_restore(self):
        with mock.patch.dict(os.environ, {"TC_STATE": "/tmp/zz"}):
            self.assertEqual(restore.restore_dir(), Path("/tmp/zz/restore"))


if __name__ == "__main__":
    unittest.main()
