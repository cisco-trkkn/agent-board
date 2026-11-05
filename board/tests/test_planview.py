import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import planview  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "planview"
SID1 = "11111111-1111-1111-1111-111111111111"
SID2 = "22222222-2222-2222-2222-222222222222"


def fake_tmux(claude_pane="@80.%82", windows=(("claude", "%82"), ("✦ parse", "%90")), status=None, group=""):
    status = status or {}

    def run(*args, check=False):
        if args[0] == "display" and "session_group" in args[-1]:
            return (group or "proj") + "\n"
        if args[0] == "display" and "#{window_id}.#{pane_id}" in args[-1]:
            return claude_pane + "\n"
        if args[0] == "list-windows":
            return "".join(f"{n}\t{p}\n" for n, p in windows)
        raise AssertionError(args)
    run.status = status
    return run


class Base(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        self.root = Path(self.td.name)
        self.home = self.root / "home"
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        shutil.copytree(FIX / "sessions", self.home / "sessions")
        shutil.copytree(FIX / "tasks", self.home / "tasks")
        shutil.copytree(FIX / "repo", self.repo)
        p = mock.patch("planview.pane_state", return_value="working")  # no capture-pane is faked
        p.start()
        self.addCleanup(p.stop)
        self.state.mkdir()
        shutil.copy(FIX / "artifacts-proj.jsonl", self.state / "artifacts-proj.jsonl")

    def view(self, tmux=None, session="proj"):
        return planview.view(session, self.repo, self.home, self.state, tmux or fake_tmux())

    def put_task(self, sid8, n, **kw):
        d = self.home / "tasks" / f"session-{sid8}"
        t = {"id": str(n), "subject": f"T{n}", "status": "pending", "owner": "", "blockedBy": [], "blocks": []}
        t.update(kw)
        (d / f"{n}.json").write_text(json.dumps(t))

    def clear_tasks(self, sid8):
        for f in (self.home / "tasks" / f"session-{sid8}").glob("*.json"):
            f.unlink()

    def write_manifest(self, lines):
        (self.state / "artifacts-proj.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines))


class TestPlanview(Base):
    def test_lead_matched_by_claude_pane(self):
        v = self.view()
        self.assertEqual([t["subject"] for t in v["tasks"]][0], "Task 1: x")
        self.assertEqual(len(v["tasks"]), 3)
        self.assertTrue(v["active"])
        v2 = self.view(fake_tmux(claude_pane="@81.%83"))
        self.assertEqual([t["subject"] for t in v2["tasks"]], ["decoy"])

    def test_tasks_sorted_numerically(self):
        self.clear_tasks("11111111")
        for n in (2, 10, 1):
            self.put_task("11111111", n)
        self.assertEqual([t["id"] for t in self.view()["tasks"]], ["1", "2", "10"])

    def test_pending_with_open_blocker_is_blocked(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="in_progress")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["in_progress", "blocked"])

    def test_pending_with_done_blocker_is_pending(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1, status="completed")
        self.put_task("11111111", 2, blockedBy=["1"])
        self.assertEqual([t["status"] for t in self.view()["tasks"]], ["completed", "pending"])

    def test_owner_state_mapping(self):
        self.clear_tasks("11111111")
        wins = (("claude", "%82"), ("✦ a", "%90"), ("✦ b", "%91"), ("✦ c", "%92"))
        for n, o in enumerate("abcd", 1):
            self.put_task("11111111", n, owner=o)
        side = {"%90": "working", "%91": "waiting", "%92": "ready"}
        with mock.patch("planview.pane_state", side_effect=lambda t, p: side[p]):
            v = self.view(fake_tmux(windows=wins))
        self.assertEqual([t["state"] for t in v["tasks"]], ["working", "waiting", "ready", "gone"])

    def test_unowned_task_has_empty_state(self):
        self.clear_tasks("11111111")
        self.put_task("11111111", 1)
        self.assertEqual(self.view()["tasks"][0]["state"], "")

    def test_name_from_newest_plan_line_of_this_lead(self):
        base = {"kind": "plan", "session_id": SID1}
        self.write_manifest([
            dict(base, ts=1, path="/p/a-old.md"),
            dict(base, ts=2, path="/p/b-new.md"),
            dict(base, ts=3, path="/p/c.md", session_id=SID2),
            {"ts": 4, "path": "/p/mark.md", "session_id": SID1},
        ])
        self.assertEqual(self.view()["name"], "b-new")

    def test_empty_live_list_falls_back_to_tasks_json(self):
        self.clear_tasks("11111111")
        v = self.view()
        self.assertEqual(v["name"], "2026-01-01-demo")
        self.assertFalse(v["active"])
        self.assertEqual([t["id"] for t in v["tasks"]], ["1", "2", "3"])
        self.assertEqual(v["tasks"][1]["status"], "completed")

    def test_no_plan_line_falls_back_to_newest_repo_tasks_json(self):
        self.clear_tasks("11111111")
        self.write_manifest([])
        d = self.repo / "docs/superpowers/plans"
        (d / "2026-02-02-newer.md.tasks.json").write_text(json.dumps({"tasks": [{"id": 7, "subject": "n", "status": "pending"}]}))
        import os
        os.utime(d / "2026-01-01-demo.md.tasks.json", (1, 1))
        v = self.view()
        self.assertEqual((v["name"], v["active"], [t["id"] for t in v["tasks"]]), ("2026-02-02-newer", False, ["7"]))

    def test_nothing_gives_empty_view(self):
        empty = {"name": "", "active": False, "tasks": []}
        shutil.rmtree(self.repo)
        shutil.rmtree(self.home)
        self.assertEqual(self.view(), empty)

    def test_missing_home_and_bad_json_do_not_raise(self):
        for f in (self.home / "tasks" / "session-11111111").glob("*.json"):
            f.write_text("{bad")
        (self.home / "sessions" / "1002.json").write_text("not json")
        (self.state / "artifacts-proj.jsonl").write_text("{bad\n")
        (self.repo / "docs/superpowers/plans/2026-01-01-demo.md.tasks.json").write_text("[")
        self.assertEqual(self.view()["tasks"], [])

    def _outside_plan(self, with_tasks):
        out = self.root / "elsewhere" / "docs" / "superpowers" / "plans"
        out.mkdir(parents=True)
        if with_tasks:
            (out / "new-plan.md.tasks.json").write_text(json.dumps({"tasks": [{"id": 1, "subject": "NEW", "status": "pending"}]}))
        self.clear_tasks("11111111")
        self.write_manifest([{"kind": "plan", "session_id": SID1, "ts": 1, "path": str(out / "new-plan.md")}])

    def test_idle_view_uses_the_manifest_path_tasks_json_outside_root(self):
        self._outside_plan(True)
        v = self.view()
        self.assertEqual((v["name"], [t["subject"] for t in v["tasks"]]), ("new-plan", ["NEW"]))

    def test_idle_fallback_shows_the_fallback_files_own_name(self):
        self._outside_plan(False)
        v = self.view()
        self.assertEqual((v["name"], v["active"], len(v["tasks"])), ("2026-01-01-demo", False, 3))

    def test_malformed_task_files_are_skipped_one_by_one(self):
        self.clear_tasks("11111111")
        d = self.home / "tasks" / "session-11111111"
        (d / "1.json").write_text(json.dumps({"id": "1", "subject": "bad blockedBy", "status": "pending", "blockedBy": 5}))
        (d / "2.json").write_text(json.dumps(["not", "a", "dict"]))
        (d / "3.json").write_text(json.dumps({"id": "3", "subject": "bad owner", "status": ["x"], "owner": {"a": 1}}))
        self.put_task("11111111", 4, subject="good")
        v = self.view()
        self.assertIn("good", [t["subject"] for t in v["tasks"]])
        self.assertNotIn("bad blockedBy", [t["subject"] for t in v["tasks"]])

    def test_tmux_raising_falls_back_to_newest_repo_tasks_json(self):
        def boom(*a, **k):
            raise RuntimeError("no tmux")
        for tmux in (boom, lambda *a, **k: ""):
            v = self.view(tmux)
            self.assertEqual((v["name"], v["active"], [t["id"] for t in v["tasks"]]), ("2026-01-01-demo", False, ["1", "2", "3"]))
            self.assertEqual({t["state"] for t in v["tasks"]}, {""})

    def test_tmux_raising_and_no_repo_gives_empty_view(self):
        def boom(*a, **k):
            raise RuntimeError("no tmux")
        shutil.rmtree(self.repo)
        self.assertEqual(self.view(boom), {"name": "", "active": False, "tasks": []})

    def test_no_matching_lead_falls_back_to_repo_tasks_json(self):
        v = self.view(fake_tmux(claude_pane="@99.%99"))
        self.assertEqual((v["name"], v["active"], len(v["tasks"])), ("2026-01-01-demo", False, 3))

    def test_manifest_keyed_by_session_group(self):
        (self.state / "artifacts-proj.jsonl").unlink()
        (self.state / "artifacts-grp.jsonl").write_text(json.dumps({"kind": "plan", "session_id": SID1, "ts": 1, "path": "/p/zz-grp.md"}) + "\n")
        for grp in ("grp", "grp-bg"):
            self.assertEqual(self.view(fake_tmux(group=grp), session="_web-1")["name"], "zz-grp", grp)

    def test_group_lookup_failure_uses_session_name(self):
        (self.state / "artifacts-proj.jsonl").write_text(json.dumps({"kind": "plan", "session_id": SID1, "ts": 1, "path": "/p/zz-own.md"}) + "\n")
        base = fake_tmux()

        def tmux(*args, check=False):
            if "session_group" in args[-1]:
                raise RuntimeError("no")
            return base(*args)
        self.assertEqual(self.view(tmux)["name"], "zz-own")


EMPTY_VIEW = {"name": "", "active": False, "tasks": []}


class TestTeamAndWorktree(Base):
    STARTED = 1793209013811  # startedAt of the fixture's lead (sessions/1001.json), ms

    def team(self, name="session-aaaaaaaa", lead_sid="aaaaaaaa-0000-0000-0000-000000000000", pid=1001, n=3,
             claimed=None, subject="team"):
        d = self.home / "teams" / name
        d.mkdir(parents=True)
        claimed = self.STARTED + 300 if claimed is None else claimed  # real teams claim a few hundred ms after the session starts
        (d / "config.json").write_text(json.dumps({
            "name": name, "createdAt": claimed, "leadAgentId": f"team-lead@{name}", "leadSessionId": lead_sid,
            "leadProcess": {"pid": pid, "pidSpace": "US5TKNM0JCWGW", "claimedAt": claimed}, "members": []}))
        td = self.home / "tasks" / name
        td.mkdir(parents=True)
        for i in range(1, n + 1):
            (td / f"{i}.json").write_text(json.dumps({"id": str(i), "subject": f"{subject}{i}", "status": "completed"}))

    def test_team_list_when_own_dir_is_empty_matched_by_lead_pid(self):
        self.clear_tasks("11111111")
        self.team()
        v = self.view()
        self.assertEqual([t["subject"] for t in v["tasks"]], ["team1", "team2", "team3"])
        self.assertTrue(v["active"])
        self.assertEqual(sorted(v), ["active", "name", "tasks"])

    def test_team_list_when_own_dir_is_missing_matched_by_lead_session_id(self):
        shutil.rmtree(self.home / "tasks" / "session-11111111")
        self.team(pid=9999, lead_sid=SID1)
        self.assertEqual([t["subject"] for t in self.view()["tasks"]], ["team1", "team2", "team3"])

    def test_old_team_with_a_reused_pid_is_ignored(self):
        self.clear_tasks("11111111")
        self.team(claimed=self.STARTED - 3600_000)
        self.assertFalse(self.view()["active"])

    def test_pid_claim_within_a_minute_before_the_session_start_is_accepted(self):
        self.clear_tasks("11111111")
        self.team(claimed=self.STARTED - 59_000)
        self.assertEqual(len(self.view()["tasks"]), 3)

    def test_newest_claim_wins_among_pid_matches(self):
        self.clear_tasks("11111111")
        self.team(name="session-aaaaaaaa", claimed=self.STARTED + 100, subject="old")
        self.team(name="session-bbbbbbbb", claimed=self.STARTED + 900, subject="new")
        self.assertEqual(self.view()["tasks"][0]["subject"], "new1")

    def test_lead_session_id_match_beats_a_pid_match(self):
        self.clear_tasks("11111111")
        self.team(name="session-aaaaaaaa", claimed=self.STARTED + 900, subject="pid")
        self.team(name="session-zzzzzzzz", lead_sid=SID1, pid=77, claimed=0, subject="sid")
        self.assertEqual(self.view()["tasks"][0]["subject"], "sid1")

    def test_own_list_wins_over_a_team_list(self):
        self.team()
        self.assertEqual(self.view()["tasks"][0]["subject"], "Task 1: x")

    def test_other_leads_team_is_ignored(self):
        self.clear_tasks("11111111")
        self.team(pid=4242)
        self.assertFalse(self.view()["active"])

    def test_newest_manifest_line_wins_even_with_blank_session_id(self):
        # tmux-ctl artifact records the worktree copy with session_id "": it must still beat the older main-checkout line
        self.clear_tasks("11111111")
        wt = self.root / "wt" / "2026-01-01-demo.md"
        wt.parent.mkdir(parents=True)
        Path(str(wt) + ".tasks.json").write_text(json.dumps({"tasks": [{"id": "1", "subject": "wt", "status": "completed"}]}))
        base = {"kind": "plan"}
        self.write_manifest([
            dict(base, ts=1, session_id=SID1, path="/proj/docs/superpowers/plans/2026-01-01-demo.md"),
            dict(base, ts=2, session_id="", path=str(wt)),
            dict(base, ts=3, session_id="", path="/other/unrelated.md"),
        ])
        v = self.view()
        self.assertEqual([t["subject"] for t in v["tasks"]], ["wt"])

    def test_blank_session_line_before_the_sessions_own_line_loses(self):
        base = {"kind": "plan"}
        self.write_manifest([
            dict(base, ts=1, session_id="", path="/early/2026-01-01-demo.md"),
            dict(base, ts=2, session_id=SID1, path="/proj/docs/superpowers/plans/2026-01-01-demo.md"),
        ])
        self.assertEqual(str(planview.plan_entry(self.state, "proj", SID1)), "/proj/docs/superpowers/plans/2026-01-01-demo.md")


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": os.environ["PATH"], "HOME": tmp, "TC_STATE": tmp, "TC_TMUX": "/nonexistent"}
            return subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), *args, "--root", tmp],
                                  capture_output=True, text=True, env=env, timeout=20)

    def test_view_without_tmux_prints_empty_line(self):
        r = self.run_cli("view", "nosuch")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "no plans yet \u00b7 prefix S for a shell"), r.stderr)

    def test_view_json(self):
        r = self.run_cli("view", "nosuch", "--json")
        self.assertEqual(json.loads(r.stdout), EMPTY_VIEW)

    def test_cli_default_home_reads_dot_claude_with_a_tmux_shim(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / ".claude" / "sessions").mkdir(parents=True)
            tdir = tmp / ".claude" / "tasks" / "session-cccccccc"
            tdir.mkdir(parents=True)
            (tmp / ".claude" / "sessions" / "1.json").write_text(json.dumps(
                {"sessionId": "cccccccc-0000-0000-0000-000000000000", "tmux": "proj:@7.%8", "updatedAt": 1}))
            (tdir / "1.json").write_text(json.dumps({"id": "1", "subject": "real default", "status": "in_progress", "owner": ""}))
            shim = tmp / "tmux-shim"
            shim.write_text("#!/bin/sh\nfor a in \"$@\"; do case \"$a\" in\n"
                            "display) case \"$*\" in *session_group*) echo proj;; *) echo @7.%8;; esac; exit 0;;\n"
                            "list-windows) printf 'claude\\t%%8\\n'; exit 0;; esac; done\nexit 1\n")
            shim.chmod(0o755)
            env = {"PATH": os.environ["PATH"], "HOME": str(tmp), "TC_STATE": str(tmp / "state"), "TC_TMUX": str(shim)}
            r = subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), "view", "proj", "--root", str(tmp / "repo"), "--json"],
                               capture_output=True, text=True, env=env, timeout=30)
        v = json.loads(r.stdout)
        self.assertTrue(v["active"], (r.stdout, r.stderr))
        self.assertEqual([t["subject"] for t in v["tasks"]], ["real default"])

    def test_snapshot_reads_sessions_and_tasks_under_dot_claude(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("planview.view") as v, \
                mock.patch("planview.Path.home", return_value=Path(tmp)), mock.patch("planview.paneclass.tmux_runner"):
            planview._snapshot("s", Path("."))
        self.assertEqual(v.call_args[0][2], Path(tmp) / ".claude")

    def test_watch_subcommand_is_gone(self):
        r = subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), "watch", "x", "--root", "."],
                           capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid choice", r.stderr)

    def test_positional_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, "-I", str(HERE / "planview.py"), "view", "nosuch", tmp],
                               capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)


class TestPaneState(unittest.TestCase):
    def test_pane_state_maps_pane_status(self):
        for ret, want in ((("claude", "working"), "working"), (("claude", "waiting"), "waiting"),
                          (("claude", "ready"), "ready"), (("shell", "ready"), "ready")):
            with mock.patch("planview.paneclass.pane_status", return_value=ret):
                self.assertEqual(planview.pane_state(None, "%1"), want)

    def test_pane_state_error_is_ready(self):
        with mock.patch("planview.paneclass.pane_status", side_effect=RuntimeError):
            self.assertEqual(planview.pane_state(None, "%1"), "ready")


class TierAndBlockersTest(unittest.TestCase):
    def test_tier_from_description_fence(self):
        d = {"id": "1", "subject": "s", "status": "pending",
             "description": "**Goal:** x\n\n```json:metadata\n{\"modelTier\": \"mechanical\"}\n```"}
        self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "mechanical")

    def test_tier_from_metadata_wins(self):
        d = {"id": "1", "subject": "s", "status": "pending", "metadata": {"modelTier": "frontier"},
             "description": "```json:metadata\n{\"modelTier\": \"mechanical\"}\n```"}
        self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "frontier")

    def test_tier_missing_or_malformed_is_empty(self):
        for desc in ("", "no fence", "```json:metadata\n{not json\n```", "```json:metadata\n[1]\n```"):
            d = {"id": "1", "subject": "s", "status": "pending", "description": desc}
            self.assertEqual(planview._finish([planview._norm(d)])[0]["tier"], "", desc)

    def test_blocked_by_passes_through(self):
        a = {"id": "1", "subject": "a", "status": "pending"}
        b = {"id": "2", "subject": "b", "status": "pending", "blockedBy": ["1"]}
        out = planview._finish([planview._norm(a), planview._norm(b)])
        self.assertEqual([t["blockedBy"] for t in out], [[], ["1"]])
        self.assertEqual(out[1]["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
