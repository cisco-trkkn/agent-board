"""Run watch: overdue runs in queue-mode `✦` panes (spec docs/superpowers/specs/2026-11-24-run-watch-design.md §b).
Fixed `ps` outputs go through overview.parse_ps / pane_runs into shape-exact overview records; board/watch.py acts on
them with a fake clock and recorder seams (alert, nudge, tell, kill). Every test runs in a temp state dir (TC_STATE too)."""
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import notify, overview, watch  # noqa: E402

T0 = 1_800_000_000.0
CLAUDE = "/Users/u/.local/share/claude/versions/2.1.331 --agent-id fake@t --agent-name fake"
BASH = "/bin/zsh -c source /Users/u/.claude/shell-snapshots/snapshot-zsh-1.sh && eval 'npm test' < /dev/null"


def ps(etime="07:00", cpu="0:05.00", child_cpu="0:01.00", cmd="node /usr/local/bin/npm test"):
    """A ps sample of one teammate pane (claude 500): its MCP server and caffeinate (never runs), a Bash tool shell 600
    running `npm test` (700) whose child is `node --test` (701)."""
    return "\n".join([
        "    1     0 04-03:46:17  52:10.48 /sbin/launchd",
        f"  500     1    02:00:00   1:10.00 {CLAUDE}",
        "  510   500    02:00:00   0:00.08 node /Users/u/.claude/plugins/cache/discord/discord-mcp-stub.js",
        "  511   500    02:00:00   0:00.00 caffeinate -i -t 300",
        f"  600   500       {etime}   0:00.01 {BASH}",
        f"  700   600       {etime}   {cpu} {cmd}",
        f"  701   700       {etime}   {child_cpu} node --test test/",
    ]) + "\n"


def panes(name="p"):
    def run(*args, check=False):
        assert args[:2] == ("list-panes", "-s") and args[3] == f"={name}", args
        return "claude\t%1\t400\n✦ fake\t%9\t500\n"
    return run


def runs(text, name="p"):
    return overview.pane_runs(name, panes(name), overview.parse_ps(text))


def project(rs, name="p", queue=True, lead_ready=True, mate_state="working"):
    return {"project": name, "path": f"/{name}", "needs_you": [], "last_run": None, "alerts": [],
            "plan": {"name": "plan-a", "active": True, "done": 1, "total": 3, "in_progress": []},
            "lead": {"status": "working", "last_active": 100.0, "idle_s": 0}, "artifacts": [], "epoch": 0, "spend_today": 0.0,
            "queue": queue, "owned": [], "awake": True, "pace": None, "runs": rs,
            "agents": [{"window": "claude", "pane": "%1", "state": "ready" if lead_ready else "working", "state_s": None,
                        "turn_s": None, "tool": None},
                       {"window": "✦ fake", "pane": "%9", "state": mate_state, "state_s": None, "turn_s": None, "tool": None}]}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t


class SampleTest(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(overview._dur("07:00"), 420)
        self.assertEqual(overview._dur("04-03:46:17"), 4 * 86400 + 3 * 3600 + 46 * 60 + 17)
        self.assertEqual(overview._dur("1389:17.59"), 1389 * 60 + 17.59)   # macOS time: minutes past 60
        self.assertIsNone(overview._dur("??"))

    def test_the_run_is_npm_with_its_subtree_cpu(self):
        got = runs(ps())
        # mutation: follow claude's non-shell children too -> the MCP server and caffeinate show up, this fails
        self.assertEqual([(r["window"], r["pane"], r["pid"], r["cmd"]) for r in got], [("✦ fake", "%9", 700, "node /usr/local/bin/npm test")])
        self.assertEqual((got[0]["elapsed_s"], got[0]["cpu_s"], got[0]["pids"]), (420, 6.0, [700, 701]))

    def test_idle_shell_and_other_windows_are_not_runs(self):
        text = "  500     1  02:00:00  0:01.00 /bin/zsh\n  400     1  02:00:00  0:01.00 /bin/zsh\n  401   400  02:00:00  0:01.00 sleep 9999\n"
        # mutation: return [pid] for a shell with no child -> the idle zsh of ✦ fake is a run, this fails
        self.assertEqual(runs(text), [])   # 400 is the lead's `claude` window: not a ✦ pane

    def test_a_shell_with_one_child_stands_for_it(self):
        text = "  500     1  00:10  0:00.00 zsh\n  501   500  00:09  0:00.00 sh -c perl -e 'sleep 9999'; :\n  502   501  00:09  0:00.00 perl -e sleep 9999\n"
        self.assertEqual([r["pid"] for r in runs(text)], [502])

    def test_failing_tmux_gives_no_runs(self):
        def boom(*a, check=False):
            raise RuntimeError("no server")
        self.assertEqual(overview.pane_runs("p", boom, overview.parse_ps(ps())), [])


class CapsTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)

    def test_first_match_wins_else_default(self):
        caps = {"default_s": 900, "caps": [{"match": "npm test", "cap_s": 360}, {"match": "npm", "cap_s": 5}]}
        self.assertEqual(watch.cap_for("node /usr/local/bin/npm test", caps), 360)
        self.assertEqual(watch.cap_for("make", caps), 900)

    def test_missing_or_broken_file_gives_the_defaults(self):
        self.assertEqual(watch.load_caps(Path(self.td.name) / "none.json"), watch.DEFAULT_CAPS)
        bad = Path(self.td.name) / "bad.json"; bad.write_text("{not json")
        self.assertEqual(watch.load_caps(bad), watch.DEFAULT_CAPS)

    def test_the_repo_file_equals_the_built_in_defaults(self):
        self.assertEqual(watch.load_caps(watch.CAPS_FILE), watch.DEFAULT_CAPS)


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.addCleanup(self.td.cleanup)
        self.dir = Path(self.td.name)
        os.environ["TC_STATE"] = str(self.dir); self.addCleanup(os.environ.pop, "TC_STATE", None)
        self.caps = self.dir / "caps.json"
        self.caps.write_text(json.dumps(watch.DEFAULT_CAPS))
        self.clock = Clock()
        self.alerts, self.nudges, self.tells, self.kills = [], [], [], []
        self.alive = set()
        self.w = self.watch()

    def watch(self):
        def kill(pid, sig):
            if pid not in self.alive:
                raise ProcessLookupError(pid)
            self.kills.append((pid, sig))
        return watch.Watch(now=self.clock, alert=self.alerts.append, nudge=lambda p, line: self.nudges.append((p, line)),
                           tell=lambda pane, line: self.tells.append((pane, line)) or True, kill=kill,
                           state_dir=self.dir, caps_file=self.caps)

    def step(self, rec, dt=10):
        self.clock.t += dt
        return self.w.observe({"generated": self.clock.t, "projects": [rec]}, [])

    def terms(self):
        return [p for p, s in self.kills if s == signal.SIGTERM]


class RunWatchTest(Base):
    def test_under_cap_nothing(self):
        self.step(project(runs(ps(etime="05:59"))))   # npm test: cap 360 s
        self.assertEqual((self.alerts, self.kills), ([], []))
        self.assertFalse((self.dir / "watch.json").exists())

    def test_past_cap_one_alert(self):
        # mutation: compare elapsed_s < cap instead of <= -> the 360 s run alerts, this fails
        self.step(project(runs(ps(etime="06:00"))))
        self.assertEqual(self.alerts, [])
        self.step(project(runs(ps(etime="06:01"))))
        self.step(project(runs(ps(etime="06:11", cpu="0:06.00"))))
        self.assertEqual([(a["kind"], a["title"], a["text"]) for a in self.alerts],
                         [("run_overdue", "p", "fake run past cap: node /usr/local/bin/npm test (6 min, cap 6 min)")])

    def test_cpu_rising_is_never_killed(self):
        self.alive = {700, 701}
        for i in range(6):
            self.step(project(runs(ps(etime=f"{10 + i:02d}:00", child_cpu=f"0:{10 + i:02d}.00"))))
        self.assertEqual((len(self.alerts), self.kills), (1, []))   # mutation: drop the cpu comparison -> killed, this fails

    def test_flat_twice_one_kill_one_line_one_nudge(self):
        self.alive = {700, 701}
        rec = project(runs(ps(etime="10:00")))
        self.step(rec)                # first seen past cap: alert, cpu recorded
        self.step(rec)                # flat 1
        self.assertEqual(self.kills, [])   # mutation: FLAT_KILL = 1 -> killed here, this fails
        self.step(rec)                # flat 2: kill
        self.assertEqual(self.terms(), [700, 701])
        self.assertEqual(self.tells, [("%9", "[Watch] killed node /usr/local/bin/npm test after 10 min, no progress: report to the lead")])
        self.assertEqual(self.nudges, [("p", "[Watch] killed fake's node /usr/local/bin/npm test after 10 min, no progress: read its report.")])
        kl = [json.loads(l) for l in (self.dir / "watch" / "kills.jsonl").read_text().splitlines()]
        self.assertEqual(kl, [{"at": watch.iso(self.clock.t), "project": "p", "window": "✦ fake", "pid": 700,
                               "cmd": "node /usr/local/bin/npm test", "elapsed_s": 600, "cap_s": 360}])
        self.step(rec)                # still there on the next overview (TERM ignored): no second kill
        self.assertEqual(self.terms(), [700, 701])   # mutation: drop the killed_at check -> TERM again, this fails
        self.assertEqual((len(self.tells), len(self.nudges)), (1, 1))
        self.assertEqual([p for p, s in self.kills if s == signal.SIGKILL], [700, 701])   # KILL after 10 s, once
        self.step(rec)
        self.assertEqual(len(self.kills), 2 + 2 * 2)   # TERM x2, then (probe 0 + KILL) x2; nothing more

    def test_busy_lead_is_nudged_when_ready_and_a_waiting_teammate_is_not_typed_at(self):
        self.alive = {700, 701}
        for _ in range(3):
            self.step(project(runs(ps(etime="10:00")), lead_ready=False, mate_state="waiting"))
        self.assertEqual((self.terms(), self.nudges, self.tells), ([700, 701], [], []))
        self.step(project([], mate_state="ready"))   # the run is gone; the teammate is back at its prompt, the lead ready
        self.assertEqual((len(self.nudges), len(self.tells)), (1, 1))

    def test_gone_before_the_kill_clears(self):
        rec = project(runs(ps(etime="10:00")))
        self.step(rec); self.step(rec)
        self.step(rec)                # flat 2, but kill() raises ProcessLookupError (self.alive is empty)
        self.assertEqual((self.kills, self.tells, self.nudges), ([], [], []))
        self.assertEqual(json.loads((self.dir / "watch.json").read_text())["runs"], {})
        self.assertFalse((self.dir / "watch" / "kills.jsonl").exists())

    def test_queue_mode_off_nothing(self):
        self.alive = {700, 701}
        for _ in range(4):
            self.step(project(runs(ps(etime="30:00")), queue=False))
        self.assertEqual((self.alerts, self.kills, self.tells, self.nudges), ([], [], [], []))

    def test_a_caps_file_match_gives_its_cap(self):
        self.caps.write_text(json.dumps({"default_s": 900, "caps": [{"match": "npm test", "cap_s": 1}]}))
        self.step(project(runs(ps(etime="00:02"))))
        self.assertEqual(self.alerts[0]["text"], "fake run past cap: node /usr/local/bin/npm test (0 min, cap 0 min)")

    def test_missing_caps_file_uses_the_defaults(self):
        self.caps.unlink()
        self.step(project(runs(ps(etime="14:59", cmd="make all"))))   # default 900 s
        self.assertEqual(self.alerts, [])
        self.step(project(runs(ps(etime="15:01", cmd="make all"))))
        self.assertEqual(len(self.alerts), 1)

    def test_restart_from_watch_json_no_repeat(self):
        self.alive = {700, 701}
        rec = project(runs(ps(etime="10:00")))
        self.step(rec); self.step(rec)
        d = json.loads((self.dir / "watch.json").read_text())["runs"]
        self.assertEqual(set(d["✦ fake:700"]) >= {"first_at", "cpu", "flat_count", "killed_at"}, True)
        self.w = self.watch()         # a board restart: a fresh Watch reads watch.json
        # mutation: start self.runs empty instead of reading watch.json -> a second alert, this fails
        self.step(rec)
        self.assertEqual((len(self.alerts), self.terms()), (1, [700, 701]))
        self.w = self.watch()
        self.step(rec)
        self.assertEqual(self.terms(), [700, 701])   # killed before the restart: not killed twice
        self.assertEqual(len((self.dir / "watch" / "kills.jsonl").read_text().splitlines()), 1)


class TextTest(unittest.TestCase):
    def test_flat_cmd_and_kind_tier(self):
        self.assertEqual(notify.flat_cmd("a\n  b\tc", 80), "a b c")
        self.assertEqual(len(notify.flat_cmd("x" * 200, 80)), 80)
        self.assertIn("run_overdue", notify.KINDS)
        import discord_feed
        self.assertEqual(discord_feed.NOTIFY_TIERS["run_overdue"], "critical")


if __name__ == "__main__":
    unittest.main()
