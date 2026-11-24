"""board/restore.py: the engine of an unfinished queue is started again after a restart (spec section 11, Task 12).
Recorder tests drive do_restore through the Cfg seams; one test runs the real bin/tmux-ctl on a scratch tmux server with
a stub node; one reads the real restore snapshot and executes nothing. Python 3.9 syntax only (launchd runs /usr/bin/python3)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import restore  # noqa: E402
from test_restore_tick import Base, Sh  # noqa: E402

REPO = Path(__file__).resolve().parent.parent.parent


class EngineSh(Sh):
    """`engine status --unfinished --project X` answers by self.unfinished (project -> rc, default 1); `engine start` by self.start_rc."""

    def __init__(self):
        Sh.__init__(self)
        self.unfinished = {}
        self.start_rc = {}

    def __call__(self, cmd, env=None, cwd=None):
        line = " ".join(cmd)
        if "engine status --unfinished" in line:
            self.calls.append((list(cmd), env, cwd))
            return self.unfinished.get(cmd[cmd.index("--project") + 1], 1), ""
        if "engine start" in line:
            self.calls.append((list(cmd), env, cwd))
            return self.start_rc.get(cmd[cmd.index("--session") + 1], 0), "engine started"
        return Sh.__call__(self, cmd, env, cwd)


class Resume(Base):
    def setUp(self):
        Base.setUp(self)
        self.sh = EngineSh()
        self.proj_b = self.root / "beta"
        self.proj_b.mkdir()

    def snap(self, *projects, **kw):
        d = {"boot": 1, "saved_at": 1.0, "restored": False, "awake": None, "projects": list(projects)}
        d.update(kw)
        return d

    def test_unfinished_queue_without_lead_starts_the_engine_and_no_lead(self):
        self.sh.unfinished["alpha"] = 0
        res = self.run_restore(self.snap(self.project(lead=False)))
        dev = self.sh.find("/dev")
        self.assertEqual(len(dev), 1)
        self.assertEqual(dev[0][1].get("DEV_NO_LEAD"), "1")
        self.assertNotIn("DEV_CLAUDE_CMD", dev[0][1])
        starts = self.sh.find("engine start")
        self.assertEqual([c for c, _, _ in starts], [["/ctl", "engine", "start", "--session", "alpha"]])
        self.assertEqual(starts[0][2], str(self.proj_a))
        self.assertEqual(self.sh.find("/orch"), [])
        self.assertEqual(res["alpha"]["engine"], "resumed")
        self.assertIn("alpha: engine start ok", self.log())

    # Mutation: "start the engine without the --unfinished check" -> an engine start call for beta.
    def test_finished_queue_starts_no_engine(self):
        self.sh.unfinished["alpha"] = 0
        res = self.run_restore(self.snap(self.project(lead=False), self.project("beta", self.proj_b, lead=False)))
        self.assertEqual(len(self.sh.find("engine status --unfinished --project beta")), 1)
        self.assertEqual([c[-1] for c, _, _ in self.sh.find("engine start")], ["alpha"])
        self.assertNotIn("engine", res["beta"])

    def test_failing_engine_start_is_one_failure_and_others_restore(self):
        self.sh.unfinished.update({"alpha": 0, "beta": 0})
        self.sh.start_rc["alpha"] = 1
        res = self.run_restore(self.snap(self.project(lead=False), self.project("beta", self.proj_b, lead=False)))
        self.assertEqual(res["alpha"]["status"], "restored")
        self.assertEqual(res["alpha"]["error"], "engine start: engine started")
        self.assertNotIn("engine", res["alpha"])
        self.assertEqual(res["beta"]["engine"], "resumed")
        self.assertNotIn("error", res["beta"])

    def test_exit_4_is_already_running_and_counts_as_success(self):
        self.sh.unfinished["alpha"] = 0
        self.sh.start_rc["alpha"] = 4
        res = self.run_restore(self.snap(self.project(lead=False)))
        self.assertEqual(res["alpha"]["engine"], "already running")
        self.assertNotIn("error", res["alpha"])

    def test_awake_rearmed_once_for_two_resumed_projects(self):
        self.sh.unfinished.update({"alpha": 0, "beta": 0})
        self.run_restore(self.snap(self.project(lead=False), self.project("beta", self.proj_b, lead=False)))
        self.assertEqual([c for c, _, _ in self.sh.find("awake on")], [["/ctl", "awake", "on", "--queue", "--lid"]])

    def test_awake_not_added_when_the_snapshot_already_rearms_it(self):
        self.sh.unfinished["alpha"] = 0
        self.run_restore(self.snap(self.project(lead=False), awake={"queue": True, "lid": False, "project": None}))
        self.assertEqual([c for c, _, _ in self.sh.find("awake on")], [["/ctl", "awake", "on", "--queue"]])

    def test_no_engine_no_awake(self):
        self.run_restore(self.snap(self.project(lead=False)))
        self.assertEqual(self.sh.find("awake on"), [])

    def test_report_names_engine_resumed(self):
        self.sh.unfinished["alpha"] = 0
        (self.home / ".").mkdir(exist_ok=True)
        pidfile = Path(os.environ["TC_STATE"]) / "discord" / "alpha" / "bridge.pid"
        pidfile.parent.mkdir(parents=True)
        pidfile.write_text("99")
        self.alive.add(99)
        self.run_restore(self.snap(self.project(lead=False, bridge=True)))
        sends = self.sh.find("discord send")
        self.assertEqual(len(sends), 1)
        self.assertIn("no lead · engine resumed · bridge", " ".join(sends[0][0]))

    def test_project_name_is_the_feed_key_not_the_folder(self):
        other = self.root / "folder-name"
        other.mkdir()
        self.sh.unfinished["grp"] = 0
        self.sh.dev_makes = lambda path: "grp"
        self.run_restore(self.snap(self.project("grp", other, lead=False)))
        self.assertEqual(len(self.sh.find("engine status --unfinished --project grp")), 1)
        self.assertEqual([c[-1] for c, _, _ in self.sh.find("engine start")], ["grp"])


class RealSnapshot(unittest.TestCase):
    """Read-only: the engine selection over the real restore snapshot, with a recorder that executes nothing."""

    def test_one_status_call_per_existing_project(self):
        snap = restore.load(restore.restore_dir())
        if not snap:
            print("real snapshot: none at %s, 0 projects" % restore.restore_dir())
            return
        calls = []

        def sh(cmd, env=None, cwd=None):
            calls.append((list(cmd), cwd))
            return 1, ""
        projects = snap.get("projects") or []
        existing = [p for p in projects if p.get("path") and os.path.isdir(p["path"])]
        cfg = restore.Cfg(sh=sh, ctl=["/ctl"])
        opened = {}
        for p in existing:
            opened[p["name"]] = p["name"]
            restore._resume_engine("/nonexistent", cfg, p, p["name"], p["path"], {}, [], opened)
        status = [c for c, _ in calls if "status" in c]
        print("real snapshot: %d projects, %d with a folder, %d status calls" % (len(projects), len(existing), len(status)))
        self.assertEqual(len(status), len(existing))
        self.assertEqual([c for c, _ in calls if "start" in c], [])


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("tmux") and shutil.which("git"), "needs tmux and git")
class Scratch(unittest.TestCase):
    """The real bin/tmux-ctl on a scratch tmux server with a stub node on PATH."""

    def run_case(self, unfinished):
        root = tempfile.mkdtemp(prefix="re", dir="/tmp")
        self.addCleanup(shutil.rmtree, root, True)
        sock = "re%d" % os.getpid()
        proj = os.path.join(root, "proj")
        subprocess.run(["git", "init", "-q", proj], check=True)
        subprocess.run(["git", "-C", proj, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
        stubs = os.path.join(root, "bin")
        os.makedirs(stubs)
        answer, log = os.path.join(root, "unfinished"), os.path.join(root, "node.log")
        if unfinished:
            Path(answer).write_text("1")
        node = Path(stubs) / "node"
        node.write_text('#!/bin/sh\necho "$@" >> "%s"\ncase "$*" in *"status --unfinished"*) [ -e "%s" ]; exit $?;; esac\nsleep 30\n' % (log, answer))
        node.chmod(0o755)
        state = os.path.join(root, "state")
        os.makedirs(os.path.join(state, "restore"))
        tmuxbin = shutil.which("tmux")
        env = {"PATH": stubs + ":" + os.environ["PATH"], "HOME": root, "TC_STATE": state, "TC_ENGINE_DIR": os.path.join(root, "eng"),
               "TMUX_TMPDIR": os.environ.get("TMUX_TMPDIR", "/tmp"), "TMUX_DASH_TMUX_ARGS": "-L " + sock, "TC_LAYOUT": "/usr/bin/true"}
        tm = [tmuxbin, "-L", sock, "-f", "/dev/null"]
        self.addCleanup(lambda: subprocess.run(tm + ["kill-server"], capture_output=True, env={**os.environ, **env}))
        full = {**os.environ, **env}
        full.pop("TMUX", None)
        subprocess.run(tm + ["new-session", "-d", "-s", "proj", "-c", proj], check=True, env=full)
        subprocess.run(tm + ["new-session", "-d", "-s", "proj-bg", "-c", proj], check=True, env=full)
        subprocess.run(tm + ["set-option", "-t", "=proj-bg:", "@tc_bg", "1"], env=full)
        os.environ_backup = dict(os.environ)
        cfg = restore.Cfg(tmux=tm[:3], ctl=[str(REPO / "bin" / "tmux-ctl")], dash_ctl=["/usr/bin/true"], orch="/usr/bin/true",
                          dev="/usr/bin/true", home=root, sleep=lambda s: None)
        old = dict(os.environ)
        os.environ.clear()
        os.environ.update(full)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ["TC_RESTORE_ROUTE"] = "/usr/bin/true"
        d = Path(state) / "restore"
        snap = {"boot": 1, "saved_at": 1.0, "restored": False, "awake": None,
                "projects": [{"name": "proj", "path": proj, "lead": None, "bridge": False}]}
        res = restore.do_restore(d, snap, cfg)
        wins = subprocess.run(tm + ["list-windows", "-a", "-F", "#{session_name}:#{window_name}"], capture_output=True, text=True, env=full).stdout.split()
        print("scratch run (unfinished=%s): looked at %d windows: %s" % (unfinished, len(wins), wins))
        return res, wins, log

    def test_unfinished_gives_an_engine_window_and_no_claude_window(self):
        res, wins, log = self.run_case(True)
        self.assertEqual(res["proj"].get("engine"), "resumed", res)
        self.assertIn("proj-bg:engine", wins)
        self.assertFalse([w for w in wins if w.endswith(":claude")], wins)

    def test_finished_gives_no_engine_window(self):
        res, wins, log = self.run_case(False)
        self.assertNotIn("engine", res["proj"])
        self.assertNotIn("proj-bg:engine", wins)
        self.assertGreater(len(wins), 0)


if __name__ == "__main__":
    unittest.main()
