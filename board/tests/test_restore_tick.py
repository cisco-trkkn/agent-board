"""board/restore.py part 2: tick, restore and the CLI. Every external call goes through a fake sh(); no tmux, launchctl,
route or claude runs."""
import contextlib
import fcntl
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import restore  # noqa: E402

BOOT_OLD, BOOT_NEW = 1000, 2000
PLUGIN = "plugin:discord@claude-plugins-official"
TMUX = ["tmux"]


class Sh:
    """sh(cmd, env=None, cwd=None) -> (rc, out): logs every call; scripted answers."""

    def __init__(self):
        self.calls = []            # (cmd, env, cwd)
        self.live = set()          # session names that already exist
        self.route_ok_after = 0    # route fails this many times first
        self.routes = 0
        self.fail = {}             # substring of " ".join(cmd) -> (rc, out)
        self.dev_makes = lambda path: Path(path).name   # session name bin/dev would create (None: none)
        self.panes = ""            # list-panes output
        self.ps = ""

    def __call__(self, cmd, env=None, cwd=None):
        self.calls.append((list(cmd), env, cwd))
        line = " ".join(cmd)
        for k, v in self.fail.items():
            if k in line:
                return v
        if "engine status --unfinished" in line:
            return 1, ""   # no unfinished engine queue unless a test says so (test_restore_engine)
        if cmd[0] == "/dev":
            made = self.dev_makes(cmd[1])
            if made:
                self.live.add(made)
            return 0, ""
        if cmd[0] == "/sbin/route":
            self.routes += 1
            return (0, "") if self.routes > self.route_ok_after else (1, "")
        if "has-session" in cmd:
            return (0, "") if cmd[-1].lstrip("=") in self.live else (1, "")
        if "list-panes" in cmd:
            return 0, self.panes
        if cmd[0] == "ps":
            return 0, self.ps
        return 0, ""

    def lines(self):
        return [" ".join(c) for c, _, _ in self.calls]

    def find(self, word):
        return [(c, e, w) for c, e, w in self.calls if word in " ".join(c)]


class Clock:
    def __init__(self):
        self.t = 5000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def snap(boot=BOOT_OLD, restored=False, projects=None, awake=None):
    return {"boot": boot, "saved_at": 1.0, "restored": restored, "awake": awake,
            "projects": projects if projects is not None else []}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dir = self.root / "state" / "restore"
        self.home = self.root / "home"
        self.home.mkdir()
        self.proj_a = self.root / "alpha"
        self.proj_a.mkdir()
        self.sh = Sh()
        self.clock = Clock()
        self.alive = set()
        env = {k: v for k, v in os.environ.items() if k not in ("TC_RESTORE", "TMUX", "TMUX_PANE", "DISCORD_STATE_DIR")}
        env["TC_STATE"] = str(self.root / "state")
        p = mock.patch.dict(os.environ, env, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def cfg(self, **kw):
        d = dict(sh=self.sh, tmux=TMUX, ctl=["/ctl"], dash_ctl=["/agent-board"], orch="/orch", dev="/dev",
                 sleep=self.clock.sleep, clock=self.clock, home=str(self.home), pid_alive=lambda p: p in self.alive,
                 now=lambda: 1_800_000_000.0)
        d.update(kw)
        return restore.Cfg(**d)

    def project(self, name="alpha", path=None, lead="sid", bridge=False, model="opus", discord=False):
        lead_d = None if lead is False else {"session_id": None if lead is None else lead, "model": model, "discord": discord}
        return {"name": name, "path": str(path or self.proj_a), "lead": lead_d, "bridge": bridge}

    def log(self):
        p = self.dir / "restore.log"
        return p.read_text() if p.exists() else ""

    def run_restore(self, s, **kw):
        self.dir.mkdir(parents=True, exist_ok=True)
        return restore.do_restore(self.dir, s, self.cfg(**kw))


class Restore(Base):
    def dev_call(self):
        c = self.sh.find("/dev ")
        self.assertEqual(len(c), 1, self.sh.lines())
        return c[0]

    def test_resume_lead_env(self):
        self.run_restore(snap(projects=[self.project(model="opus", discord=True)]))
        cmd, env, _ = self.dev_call()
        self.assertEqual(cmd, ["/dev", str(self.proj_a)])
        want = " ".join(["/orch", "--model", "opus", "--channels", PLUGIN, "--resume", "sid", shlex.quote(restore.RESUME_PROMPT)])
        self.assertEqual(env["DEV_CLAUDE_CMD"], want)
        self.assertEqual(env["DEV_NO_ATTACH"], "1")
        for k in ("TMUX", "TMUX_PANE", "DISCORD_STATE_DIR", "DEV_NO_LEAD"):
            self.assertNotIn(k, env)

    def test_no_model_no_discord_flags(self):
        self.run_restore(snap(projects=[self.project(model=None)]))
        self.assertEqual(self.dev_call()[1]["DEV_CLAUDE_CMD"], f"/orch --resume sid {shlex.quote(restore.RESUME_PROMPT)}")

    def test_lead_without_session_id_continues(self):
        self.run_restore(snap(projects=[self.project(lead=None)]))
        cmd = self.dev_call()[1]["DEV_CLAUDE_CMD"]
        self.assertIn(" --continue ", cmd)
        self.assertNotIn("--resume", cmd)

    def test_no_lead_sets_no_lead(self):
        self.run_restore(snap(projects=[self.project(lead=False)]))
        env = self.dev_call()[1]
        self.assertEqual(env["DEV_NO_LEAD"], "1")
        self.assertNotIn("DEV_CLAUDE_CMD", env)

    def test_inherited_dev_vars_and_discord_dir_dropped(self):
        with mock.patch.dict(os.environ, {"DEV_CLAUDE_CMD": "x", "DISCORD_STATE_DIR": "/d", "TMUX": "/s,1,0", "TMUX_PANE": "%1"}):
            self.run_restore(snap(projects=[self.project(lead=False)]))
        env = self.dev_call()[1]
        for k in ("DEV_CLAUDE_CMD", "DISCORD_STATE_DIR", "TMUX", "TMUX_PANE"):
            self.assertNotIn(k, env)

    def test_resume_prompt_text(self):
        self.assertIn("TaskList", restore.RESUME_PROMPT)
        self.assertIn("awake status", restore.RESUME_PROMPT)

    def test_bridge_started_only_when_true(self):
        b = self.root / "beta"
        b.mkdir()
        self.run_restore(snap(projects=[self.project(bridge=True), self.project("beta", b, bridge=False)]))
        starts = self.sh.find("bridge start")
        self.assertEqual([c for c, _, _ in starts], [["/ctl", "discord", "bridge", "start", "--project", "alpha"]])

    def test_gone_folder_reported_not_created(self):
        gone = self.root / "gone"
        res = self.run_restore(snap(projects=[self.project("gone", gone, bridge=True)]))
        self.assertFalse(gone.exists())
        self.assertEqual(self.sh.find("/dev "), [])
        self.assertIn("folder", res["gone"]["error"])
        self.assertIn("gone", self.log())

    def test_live_session_left_alone(self):
        self.sh.live.add("alpha")
        res = self.run_restore(snap(projects=[self.project(bridge=True)]))
        self.assertEqual(self.sh.find("/dev "), [])
        self.assertEqual(self.sh.find("bridge start"), [])
        self.assertEqual(res["alpha"]["status"], "already open")

    def test_session_checked_by_snapshot_name_not_path(self):
        sub = self.root / "repo" / "sub"
        sub.mkdir(parents=True)
        self.sh.dev_makes = lambda path: "alpha"
        res = self.run_restore(snap(projects=[self.project("alpha", sub, bridge=True)]))
        self.assertEqual({c[-1] for c, _, _ in self.sh.find("has-session")}, {"=alpha"})
        self.assertEqual(res["alpha"]["status"], "restored")
        self.assertEqual(len(self.sh.find("bridge start")), 1)

    def test_dev_that_creates_another_session_is_a_failure(self):
        self.sh.dev_makes = lambda path: "other"
        res = self.run_restore(snap(projects=[self.project(bridge=True)]))
        self.assertIn("session name: dev did not create alpha", res["alpha"]["error"])
        self.assertEqual(self.sh.find("bridge start"), [])

    def test_failure_does_not_stop_others(self):
        b = self.root / "beta"
        b.mkdir()
        self.sh.fail[f"/dev {self.proj_a}"] = (1, "boom")
        res = self.run_restore(snap(projects=[self.project(), self.project("beta", b)]))
        self.assertEqual(len(self.sh.find("/dev ")), 2)
        self.assertIn("boom", res["alpha"]["error"])
        self.assertNotIn("error", res["beta"])

    def test_dev_start_exception_is_a_failure(self):
        def sh(cmd, env=None, cwd=None):
            if cmd[0] == "/dev":
                raise OSError("no such file")
            return (1, "") if "has-session" in cmd else (0, "")
        res = self.run_restore(snap(projects=[self.project()]), sh=sh)
        self.assertIn("no such file", res["alpha"]["error"])


class Network(Base):
    def test_waits_for_route_then_dash_from_home(self):
        self.sh.route_ok_after = 2
        self.run_restore(snap())
        self.assertEqual(self.sh.routes, 3)
        self.assertEqual(self.clock.t, 5010.0)
        dash = self.sh.find("dash start")
        self.assertEqual(dash[0][0], ["/agent-board", "dash", "start"])
        self.assertEqual(dash[0][2], str(self.home))

    def test_route_called_by_absolute_path(self):
        self.run_restore(snap())
        self.assertEqual(self.sh.calls[0][0], ["/sbin/route", "-n", "get", "default"])

    def test_route_command_seam(self):
        with mock.patch.dict(os.environ, {"TC_RESTORE_ROUTE": "/usr/bin/true"}):
            self.run_restore(snap())
        self.assertEqual(self.sh.calls[0][0], ["/usr/bin/true", "-n", "get", "default"])

    def test_times_out_after_300s_and_carries_on(self):
        self.sh.route_ok_after = 10**6
        self.run_restore(snap())
        self.assertGreaterEqual(self.clock.t - 5000.0, 300)
        self.assertLessEqual(self.clock.t - 5000.0, 305)
        self.assertEqual(len(self.sh.find("dash start")), 1)
        self.assertIn("network", self.log())


class Awake(Base):
    def pane_fixture(self):
        self.sh.panes = "alpha\tclaude\t%1\t100\n"
        self.sh.ps = "100 1 -zsh\n101 100 claude --model opus\n"

    def awake_args(self):
        return [c for c, _, _ in self.sh.find("awake on")]

    def test_plain_pid(self):
        self.pane_fixture()
        self.run_restore(snap(projects=[self.project()], awake={"lid": False, "queue": False, "project": "alpha"}))
        self.assertEqual(self.awake_args(), [["/ctl", "awake", "on", "--pid", "101"]])

    def test_lid_pid(self):
        self.pane_fixture()
        self.run_restore(snap(projects=[self.project()], awake={"lid": True, "queue": False, "project": "alpha"}))
        self.assertEqual(self.awake_args(), [["/ctl", "awake", "on", "--pid", "101", "--lid"]])

    def test_queue_and_queue_lid(self):
        self.run_restore(snap(projects=[self.project()], awake={"lid": False, "queue": True, "project": "alpha"}))
        self.assertEqual(self.awake_args(), [["/ctl", "awake", "on", "--queue"]])
        self.sh.calls.clear()
        self.run_restore(snap(projects=[self.project()], awake={"lid": True, "queue": True, "project": "alpha"}))
        self.assertEqual(self.awake_args(), [["/ctl", "awake", "on", "--queue", "--lid"]])

    def test_already_open_lead_pid_is_found_by_name(self):
        self.pane_fixture()
        self.sh.live.add("alpha")
        self.run_restore(snap(projects=[self.project()], awake={"lid": False, "queue": False, "project": "alpha"}))
        self.assertEqual(self.awake_args(), [["/ctl", "awake", "on", "--pid", "101"]])

    def test_no_awake_no_call(self):
        self.run_restore(snap(projects=[self.project()]))
        self.assertEqual(self.awake_args(), [])

    def test_pid_never_found_polls_60s_and_fails(self):
        s = snap(projects=[self.project()], awake={"lid": False, "queue": False, "project": "alpha"})
        self.run_restore(s)
        self.assertEqual(self.awake_args(), [])
        self.assertGreaterEqual(self.clock.t - 5000.0, 60)
        self.assertIn("awake", self.log())


class Report(Base):
    def setUp(self):
        super().setUp()
        self.sent = []

    def bridge_up(self, name="alpha", pid=77):
        d = self.root / "state" / "discord" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "bridge.pid").write_text(str(pid))
        self.alive.add(pid)

    def texts(self):
        return [c[c.index("-m") + 1] for c, _, _ in self.sh.find("discord send")]

    def test_text_for_bridge_project(self):
        self.bridge_up()
        s = snap(boot=BOOT_OLD, projects=[self.project(bridge=True, lead="abcdef0123456789")],
                 awake={"lid": True, "queue": False, "project": "alpha"})
        self.sh.panes = "alpha\tclaude\t%1\t100\n"
        self.sh.ps = "101 100 claude\n"
        with mock.patch.object(restore, "_hhmm", side_effect=lambda t: "01:40" if t == BOOT_OLD else "02:05"):
            self.run_restore(s)
        sends = self.sh.find("discord send")
        self.assertEqual(sends[0][0][:5], ["/ctl", "discord", "send", "--project", "alpha"])
        self.assertEqual(self.texts(), ["Mac restarted at 01:40 (boot), restored at 02:05: lead resumed (abcdef01) · bridge · keep-awake lid"])

    def test_failure_lines_sent(self):
        self.bridge_up()
        self.sh.fail["bridge start"] = (1, "no token")
        self.run_restore(snap(projects=[self.project(bridge=True)]))
        t = self.texts()[0].splitlines()
        self.assertTrue(t[0].endswith("keep-awake none"), t)
        self.assertEqual(t[1:], ["failed: bridge start: no token"])

    def test_no_send_without_bridge(self):
        self.run_restore(snap(projects=[self.project(bridge=False)]))
        self.assertEqual(self.texts(), [])

    def test_waits_up_to_120s_for_bridge_then_sends_with_failure(self):
        self.run_restore(snap(projects=[self.project(bridge=True)]))
        self.assertGreaterEqual(self.clock.t - 5000.0, 120)
        self.assertIn("failed: bridge up", self.texts()[0])

    def test_continued_lead_wording(self):
        self.bridge_up()
        self.run_restore(snap(projects=[self.project(bridge=True, lead=None)]))
        self.assertIn("lead continued", self.texts()[0])


class Marking(Base):
    def test_marked_restored_after_a_failure(self):
        self.sh.fail["bridge start"] = (1, "boom")
        self.sh.fail[f"/dev {self.proj_a}"] = (1, "dev failed")
        s = snap(projects=[self.project(bridge=True)])
        restore.save(self.dir, s)
        self.run_restore(s)
        saved = restore.load(self.dir)
        self.assertTrue(saved["restored"])
        self.assertEqual(saved["restored_at"], 1_800_000_000.0)
        self.assertIn("dev failed", saved["results"]["alpha"]["error"])

    def test_marked_even_with_zero_projects(self):
        s = snap(projects=[])
        restore.save(self.dir, s)
        self.run_restore(s)
        self.assertTrue(restore.load(self.dir)["restored"])


class Tick(Base):
    def tick(self, run=None, **kw):
        def run_(cmd, env=None, cwd=None):
            return (0, f"{{ sec = {BOOT_NEW}, usec = 1 }} x\n") if cmd[0] == "/usr/sbin/sysctl" else (1, "")
        return restore.tick(self.dir, self.cfg(**kw), run=run or run_)

    def test_off_switches(self):
        restore.save(self.dir, snap(projects=[self.project()]))
        before = (self.dir / "snapshot.json").read_text()
        with mock.patch.dict(os.environ, {"TC_RESTORE": "0"}):
            self.assertEqual(self.tick(), 0)
        (self.dir / "restore.off").write_text("")
        self.assertEqual(self.tick(), 0)
        self.assertEqual((self.dir / "snapshot.json").read_text(), before)
        self.assertEqual(self.sh.calls, [])

    def test_lock_held_elsewhere_does_no_work(self):
        self.dir.mkdir(parents=True)
        fd = os.open(self.dir / "tick.lock", os.O_CREAT | os.O_RDWR)
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        restore.save(self.dir, snap(boot=BOOT_OLD, projects=[self.project()]))
        self.assertEqual(self.tick(), 0)
        self.assertEqual(self.sh.calls, [])
        self.assertFalse(restore.load(self.dir)["restored"])

    def test_newer_boot_restores(self):
        restore.save(self.dir, snap(boot=BOOT_OLD, projects=[self.project()]))
        self.assertEqual(self.tick(), 0)
        self.assertEqual(len(self.sh.find("/dev ")), 1)
        self.assertTrue(restore.load(self.dir)["restored"])

    def test_restored_snapshot_is_not_restored_again_but_replaced(self):
        restore.save(self.dir, snap(boot=BOOT_OLD, restored=True, projects=[self.project()]))
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[self.project("n")])):
            self.tick()
        self.assertEqual(self.sh.find("/dev "), [])
        self.assertEqual(restore.load(self.dir)["boot"], BOOT_NEW)

    def test_same_boot_snapshots_and_logs_once(self):
        restore.save(self.dir, snap(boot=BOOT_NEW, restored=True, projects=[]))
        new = snap(boot=BOOT_NEW, projects=[self.project("a"), self.project("b")])
        with mock.patch.object(restore, "snapshot", return_value=new) as m:
            self.tick()
            self.tick()
        self.assertEqual(m.call_count, 2)
        self.assertEqual([p["name"] for p in restore.load(self.dir)["projects"]], ["a", "b"])
        lines = self.log().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("snapshot 2 projects"), lines)

    def test_snapshot_none_or_boot_none_does_nothing(self):
        with mock.patch.object(restore, "snapshot", return_value=None):
            self.assertEqual(self.tick(), 0)
        self.assertIsNone(restore.load(self.dir))
        self.assertEqual(self.tick(run=lambda cmd, env=None, cwd=None: (1, "")), 0)
        self.assertIsNone(restore.load(self.dir))

    def test_boot_unreadable_logs_once_per_hour(self):
        bad = lambda cmd, env=None, cwd=None: (1, "")
        t = [1_800_000_000.0]
        for _ in range(3):
            self.tick(run=bad, now=lambda: t[0])
        self.assertEqual(self.log().count("boot time unreadable"), 1)
        t[0] += 3601
        self.tick(run=bad, now=lambda: t[0])
        self.assertEqual(self.log().count("boot time unreadable"), 2)
        self.assertIsNone(restore.load(self.dir))

    def test_boot_within_60s_does_not_restore(self):
        restore.save(self.dir, snap(boot=BOOT_NEW - 30, projects=[self.project()]))
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[self.project()])):
            self.tick()
        self.assertEqual(self.sh.find("/dev "), [])
        restore._write(self.dir, snap(boot=BOOT_NEW - 61, projects=[self.project()]))
        self.tick()
        self.assertEqual(len(self.sh.find("/dev ")), 1)

    def test_snapshot_error_logged_once_per_hour(self):
        t = [1_800_000_000.0]
        for _ in range(3):
            with mock.patch.object(restore, "_snapshot", side_effect=ValueError("bad")):
                self.tick(now=lambda: t[0])
        self.assertEqual(self.log().count("snapshot error: ValueError: bad"), 1)
        t[0] += 3601
        with mock.patch.object(restore, "_snapshot", side_effect=ValueError("bad")):
            self.tick(now=lambda: t[0])
        self.assertEqual(self.log().count("snapshot error: ValueError: bad"), 2)

    def test_zero_projects_replace_only_after_two_ticks_50s_apart(self):
        restore.save(self.dir, snap(boot=BOOT_NEW, projects=[self.project()]))
        t = [1_800_000_000.0]
        zero = snap(boot=BOOT_NEW, projects=[])
        with mock.patch.object(restore, "snapshot", return_value=zero):
            self.tick(now=lambda: t[0])
            self.assertEqual(len(restore.load(self.dir)["projects"]), 1)   # first sighting: kept
            t[0] += 40
            self.tick(now=lambda: t[0])
            self.assertEqual(len(restore.load(self.dir)["projects"]), 1)   # under 50 s: kept
            t[0] += 15
            self.tick(now=lambda: t[0])
        self.assertEqual(restore.load(self.dir)["projects"], [])           # 55 s after the first: replaced

    def test_a_tick_with_projects_resets_the_zero_clock(self):
        restore.save(self.dir, snap(boot=BOOT_NEW, projects=[self.project()]))
        t = [1_800_000_000.0]
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[])):
            self.tick(now=lambda: t[0])
        t[0] += 30
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[self.project("n")])):
            self.tick(now=lambda: t[0])
        t[0] += 60
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[])):
            self.tick(now=lambda: t[0])
        self.assertEqual([p["name"] for p in restore.load(self.dir)["projects"]], ["n"])

    def test_server_down_never_replaces(self):
        restore.save(self.dir, snap(boot=BOOT_NEW, projects=[self.project()]))
        t = [1_800_000_000.0]
        with mock.patch.object(restore, "snapshot", return_value=None):
            for _ in range(4):
                self.tick(now=lambda: t[0])
                t[0] += 60
        self.assertEqual(len(restore.load(self.dir)["projects"]), 1)

    def test_again_after_a_later_tick_still_restores_the_failed_project(self):
        restore.save(self.dir, snap(boot=BOOT_OLD, projects=[self.project()]))
        self.sh.fail[f"/dev {self.proj_a}"] = (1, "dev failed")
        self.tick()                                              # restore: alpha fails, snapshot marked restored
        self.assertTrue((self.dir / "last-restore.json").exists())
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=BOOT_NEW, projects=[self.project("other")])):
            self.tick()                                          # the next tick saves a fresh snapshot without alpha
        self.assertEqual([p["name"] for p in restore.load(self.dir)["projects"]], ["other"])
        self.sh.fail.clear()
        self.sh.calls.clear()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(restore.main(["again"], run=lambda cmd, env=None, cwd=None: (0, f"{{ sec = {BOOT_NEW}, usec = 1 }}")), 0)
        self.tick()
        self.assertEqual(len(self.sh.find("/dev ")), 1, self.sh.lines())

    def test_keeps_previous_session_id_when_new_is_null(self):
        restore.save(self.dir, snap(boot=BOOT_NEW, projects=[self.project("a", lead="old-sid"), self.project("b", lead="b-sid")]))
        new = snap(boot=BOOT_NEW, projects=[self.project("a", lead=None), self.project("b", lead="b-new"),
                                            self.project("c", lead=None)])
        with mock.patch.object(restore, "snapshot", return_value=new):
            self.tick()
        got = {p["name"]: p["lead"]["session_id"] for p in restore.load(self.dir)["projects"]}
        self.assertEqual(got, {"a": "old-sid", "b": "b-new", "c": None})

    def test_does_not_carry_session_id_across_boots(self):
        restore.save(self.dir, snap(boot=BOOT_OLD, restored=True, projects=[self.project("a", lead="old-sid")]))
        new = snap(boot=BOOT_NEW, projects=[self.project("a", lead=None)])
        with mock.patch.object(restore, "snapshot", return_value=new):
            self.tick()
        self.assertIsNone(restore.load(self.dir)["projects"][0]["lead"]["session_id"])


class Cli(Base):
    def main(self, *argv, **kw):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = restore.main(list(argv), **kw)
        return rc, out.getvalue()

    def test_help_exits_zero(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as e:
            restore.main(["--help"])
        self.assertEqual(e.exception.code, 0)
        self.assertIn("tick", out.getvalue())

    def test_again_clears_restored(self):
        restore.save(self.dir, snap(restored=True, projects=[self.project()]))
        s = restore.load(self.dir)
        s["restored_at"] = 1
        restore._write(self.dir, s)
        rc, _ = self.main("again")
        self.assertEqual(rc, 0)
        self.assertFalse(restore.load(self.dir)["restored"])

    def test_snapshot_print_does_not_save(self):
        with mock.patch.object(restore, "snapshot", return_value=snap(boot=5, projects=[self.project()])):
            rc, out = self.main("snapshot", "--print")
        self.assertEqual(json.loads(out)["boot"], 5)
        self.assertIsNone(restore.load(self.dir))

    def test_status_prints_age_boot_projects(self):
        s = snap(boot=BOOT_OLD, projects=[self.project("a"), self.project("b")])
        s["saved_at"] = restore.time.time() - 125
        restore.save(self.dir, s)
        rc, out = self.main("status")
        self.assertIn("boot 1000", out)
        self.assertIn("projects: a, b", out)
        self.assertIn("2m", out)

    def test_status_without_snapshot(self):
        self.assertIn("no snapshot", self.main("status")[1])

    def test_schedule_delegates(self):
        import restore_schedule
        with mock.patch.object(restore_schedule, "main", return_value=2) as m:
            rc, _ = self.main("schedule", "status")
        m.assert_called_once_with("status")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
