import contextlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics, usage  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

SPEC1, SPEC2 = "docs/superpowers/specs/one.md", "docs/superpowers/specs/two.md"
OPUS, MYSTERY = "claude-opus-5-5", "claude-mystery-9"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SID_LEAD, SID_A, SID_B = "11111111-aaaa-4bbb-8ccc-000000000001", "22222222-aaaa-4bbb-8ccc-000000000002", "33333333-aaaa-4bbb-8ccc-000000000003"
ISO = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


_TEMPLATE = {}


def _template():
    """The scratch repo every test starts from, built once per process and copied (it holds no worktrees, so a copy
    is independent of the template and of every other copy)."""
    if not _TEMPLATE:
        tmp = tempfile.TemporaryDirectory()
        _TEMPLATE["tmp"] = tmp
        r = Path(tmp.name).resolve() / "repo"
        r.mkdir()
        git(r, "init", "-q", "-b", "main")
        (r / "f.txt").write_text("1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        git(r, "branch", "feat/x")
        git(r, "branch", "feat/y")
        _TEMPLATE["repo"] = r
    return _TEMPLATE["repo"]


class Base(unittest.TestCase):
    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name).resolve()
        self.t = t
        self.repo = t / "repo"
        self.repo.mkdir()
        self.proj = t / "proj"
        self.state = t / "state"
        self.lineage = t / "lineage"
        p = mock.patch.dict(os.environ, {"TC_STATE": str(self.state), "USAGE_ROOT": str(self.proj), "TC_LINEAGE": str(self.lineage)})
        p.start()
        self.addCleanup(p.stop)
        r = self.repo
        shutil.rmtree(r)
        shutil.copytree(_template(), r, symlinks=True)
        self.root = str(r)
        self.now = float(int(time.time()))
        self.t0 = self.now - 1800
        self.db = t / "usage.sqlite"
        self.conn = usage.connect(self.db)
        self.addCleanup(self.conn.close)
        self.n = 0
        metrics.append(r, {"kind": "batch", "batch": "B", "base": git(r, "rev-parse", "main"), "configs": ["cfg"],
                           "assignment": {SPEC1: "cfg", SPEC2: "cfg"}, "groups": [], "at": metrics.utc(self.t0 - 600)})

    def start(self, spec, at=None, limits=None, worktree=None):
        d = {"kind": "start", "batch": "B", "spec": spec, "at": metrics.utc(at or self.t0), "main": "x", "limits": limits}
        if worktree:
            d["worktree"] = worktree
        metrics.append(self.repo, d)

    def row(self, ts, model=OPUS, sid=SID_LEAD, agent=None, branch=None, cwd=None, side=0, sub=0, inp=1000, out=500, cr=0, cw5=0, cw1=0):
        self.n += 1
        t = (f"r{self.n}", sid, ts, model, None, agent, None, branch, self.root if cwd is None else cwd, side, sub, inp, out, cr, cw5, cw1)
        self.conn.execute(f"insert into calls ({','.join(usage.COLS)}) values ({','.join('?' * 16)})", t)
        self.conn.commit()

    def rec(self, spec=SPEC1, **kw):
        kw.setdefault("branch", "feat/x" if spec == SPEC1 else "feat/y")
        return metrics.build_record(self.repo, spec, "B", None, self.now, conn=self.conn, project="proj", **kw)


class AttributionTest(Base):
    def test_branch_rows_in_window_only(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, branch="feat/x", cwd="/elsewhere")
        self.row(self.t0 - 10, branch="feat/x", cwd="/elsewhere")      # before the window
        self.row(self.t0 + 20, branch="feat/other", cwd="/elsewhere")  # other branch
        r = self.rec()
        self.assertEqual(r["tokens"]["total"], 1500)
        self.assertEqual(r["tokens"]["input"], 1000)

    def test_worktree_cwd_rows_counted(self):
        self.start(SPEC1)
        wt = f"{self.root}/.claude/worktrees/wt1"
        self.row(self.t0 + 10, branch="feat/x", cwd=wt)                 # teaches the worktree dir
        self.row(self.t0 + 20, branch=None, cwd=wt + "/board", agent="w1")   # worktree row without branch
        self.row(self.t0 + 30, branch="main", cwd=f"{self.root}/.claude/worktrees/wt2", agent="w2")  # other worktree
        r = self.rec()
        self.assertEqual(r["tokens"]["total"], 3000)  # the branch row and the branchless worktree row; wt2 is out

    def test_real_git_worktree_dir_and_main_root(self):
        wt = self.repo / ".claude" / "worktrees" / "wty"
        git(self.repo, "worktree", "add", "-q", str(wt), "feat/y")
        self.assertEqual(metrics.main_root(wt), self.root)
        self.assertEqual(metrics.main_root(self.repo), self.root)
        self.start(SPEC2)
        self.row(self.t0 + 10, branch=None, cwd=str(wt) + "/board", agent="w")   # no branch field: only the worktree dir ties it
        r = self.rec(SPEC2)
        self.assertEqual(r["tokens"]["total"], 1500)

    def test_lead_root_rows_only_inside_window(self):
        self.start(SPEC1)
        self.row(self.t0 + 10)
        self.row(self.t0 - 10)
        self.row(self.now + 100)
        r = self.rec()
        self.assertEqual(r["tokens"]["total"], 1500)
        self.assertFalse(r["lead_shared"])

    def test_agent_rows_at_the_repo_root_are_counted_and_stay_agent_rows(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, inp=100, out=0)                          # lead at the root
        self.row(self.t0 + 11, agent="spike", inp=40, out=0)            # named agent in the main checkout
        self.row(self.t0 + 12, agent="other", cwd=f"{self.root}/.claude/worktrees/elsewhere", inp=999, out=0)   # another worktree: out
        self.row(self.t0 - 30, agent="early", inp=777, out=0)           # agent at the root before the window: out
        self.row(self.now + 500, agent="late", inp=555, out=0)          # and after it: out
        r = self.rec()
        self.assertEqual(r["tokens"]["total"], 140)
        self.assertEqual((r["by_role"]["lead"]["tokens"], r["by_role"]["agents"]["tokens"]), (100, 40))

    def test_overlap_splits_lead_row_evenly(self):
        self.start(SPEC1, self.t0)
        self.start(SPEC2, self.t0 + 600)
        self.row(self.t0 + 100)   # only spec 1's window
        self.row(self.t0 + 900)   # both windows
        a, b = self.rec(SPEC1), self.rec(SPEC2, branch="feat/y")
        self.assertEqual(a["tokens"]["total"], 1500 + 750)
        self.assertEqual(b["tokens"]["total"], 750)
        self.assertTrue(a["lead_shared"])
        self.assertTrue(b["lead_shared"])

    def test_sequential_when_other_has_no_start(self):
        self.start(SPEC1)
        self.row(self.t0 + 10)
        self.assertEqual(self.rec()["tokens"]["total"], 1500)
        self.assertFalse(self.rec()["lead_shared"])

    def test_unpriced_rows_counted_without_usd(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, branch="feat/x")
        self.row(self.t0 + 11, branch="feat/x", model=MYSTERY)
        r = self.rec()
        self.assertEqual(r["unpriced_calls"], 1)
        prices = usage.load_prices()
        only_opus = usage.call_cost({"model": OPUS, "input": 1000, "output": 500, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}, prices)
        self.assertAlmostEqual(r["usd"], only_opus, places=6)
        self.assertEqual(r["by_model"], {OPUS: 1500, MYSTERY: 1500})

    def test_lead_vs_agents_not_usage_role(self):
        self.start(SPEC1)
        wt = f"{self.root}/.claude/worktrees/wt1"
        self.row(self.t0 + 10, branch="feat/x", cwd=wt, inp=100, out=0)                 # lead in a worktree (role() says worker)
        self.row(self.t0 + 11, branch="feat/x", cwd=wt, sub=1, inp=20, out=0)            # subagent row, no agent name
        self.row(self.t0 + 12, branch="feat/x", cwd=wt, side=1, inp=30, out=0)           # sidechain row, no agent name
        self.row(self.t0 + 13, branch="feat/x", cwd=wt, agent="impl", inp=40, out=0)    # named agent
        r = self.rec()
        self.assertEqual(r["by_role"]["lead"]["tokens"], 100)
        self.assertEqual(r["by_role"]["agents"]["tokens"], 90)
        self.assertAlmostEqual(r["lead_share"], 100 / 190, places=3)

    def test_lead_share_null_when_no_tokens(self):
        self.start(SPEC1)
        r = self.rec()
        self.assertEqual(r["tokens"]["total"], 0)
        self.assertIsNone(r["lead_share"])

    def test_cache_write_is_sum_of_both(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, branch="feat/x", inp=1, out=2, cr=3, cw5=4, cw1=5)
        t = self.rec()["tokens"]
        self.assertEqual((t["input"], t["output"], t["cache_read"], t["cache_write"], t["total"]), (1, 2, 3, 9, 15))


    def test_removed_worktree_rows_counted_when_start_names_it(self):   # mutation: drop the wt union in build_record -> fails
        self.start(SPEC1, worktree=".claude/worktrees/gone")
        self.row(self.t0 + 60, agent="impl", branch="main", cwd=self.root + "/.claude/worktrees/gone/board")   # dir never existed
        self.assertEqual(self.rec()["tokens"]["total"], 1500)

    def test_removed_worktree_rows_not_counted_without_it(self):
        self.start(SPEC1)
        self.row(self.t0 + 60, agent="impl", branch="main", cwd=self.root + "/.claude/worktrees/gone/board")
        self.assertEqual(self.rec()["tokens"]["total"], 0)

    def test_branch_and_worktree_row_counted_once(self):
        self.start(SPEC1, worktree=".claude/worktrees/gone")
        self.row(self.t0 + 60, agent="impl", branch="feat/x", cwd=self.root + "/.claude/worktrees/gone")
        self.assertEqual(self.rec()["tokens"]["total"], 1500)


class StartWorktreeTest(Base):
    def run_start(self, wt):
        err = io.StringIO()
        before = metrics.read_log(self.repo)[0]
        with contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), "start", SPEC1, "--batch", "B", "--worktree", wt])
        return rc, err.getvalue(), before

    def test_bad_paths_exit_2_and_append_nothing(self):   # mutation: skip rel_worktree validation -> fails
        for bad in ("/tmp/elsewhere", ".claude/worktrees/../../x", ".claude/worktrees"):
            rc, err, before = self.run_start(bad)
            self.assertEqual(rc, 2, bad)
            self.assertEqual(err, "metrics: start: --worktree must be under .claude/worktrees/\n", bad)
            added = metrics.read_log(self.repo)[0][len(before):]   # main's convention: a failure logs one kind:error line
            self.assertEqual([d["kind"] for d in added], ["error"], bad)
            self.assertEqual(metrics.read_log(self.repo)[0][:len(before)], before, bad)
            before = before + added

    def test_valid_worktree_recorded(self):
        for given in (".claude/worktrees/w1", self.root + "/.claude/worktrees/w1/"):
            rc, err, before = self.run_start(given)
            self.assertEqual((rc, err), (0, ""))
            st = [d for d in metrics.read_log(self.repo)[0] if d["kind"] == "start"][-1]
            self.assertEqual(st["worktree"], ".claude/worktrees/w1")

    def test_no_flag_no_key(self):
        with contextlib.redirect_stderr(io.StringIO()):
            rc = metrics.main(["--repo", str(self.repo), "start", SPEC1, "--batch", "B"])
        self.assertEqual(rc, 0)
        st = [d for d in metrics.read_log(self.repo)[0] if d["kind"] == "start"][-1]
        self.assertNotIn("worktree", st)


class TimeTest(Base):
    def test_time_fields_and_active_minutes(self):
        self.start(SPEC1)
        base = (int(self.t0) // 60 + 1) * 60
        self.row(base + 5, branch="feat/x", agent="a", sid=SID_A)
        self.row(base + 10, branch="feat/x", agent="b", sid=SID_B)          # same minute, second session
        self.row(base + 65, branch="feat/x", agent="a", sid=SID_A)          # next minute, one session
        self.row(base + 125)                                                # lead only minute
        r = self.rec()
        self.assertEqual(r["ready_at"], metrics.utc(self.t0 - 600))
        self.assertEqual(r["started_at"], metrics.utc(self.t0))
        self.assertEqual(r["ended_at"], metrics.utc(self.now))
        self.assertEqual(r["wait_s"], 600)
        self.assertEqual(r["elapsed_s"], 1800)
        self.assertEqual(r["active_min"], 3)  # base+5 and base+10 share a minute

    def test_agents_active_buckets(self):
        self.start(SPEC1)
        base = (int(self.t0) // 60 + 1) * 60
        self.row(base + 5, branch="feat/x", agent="a", sid=SID_A)
        self.row(base + 10, branch="feat/x", agent="b", sid=SID_B)
        self.row(base + 65, branch="feat/x", agent="a", sid=SID_A)
        self.row(base + 125)
        self.assertEqual(self.rec()["agents_active_min"], {"0": 1, "1": 1, "2+": 1})

    def test_window_kind_and_config(self):
        r = self.rec()
        self.assertEqual((r["window"], r["backfilled"], r["config"]), ("derived", False, "cfg"))
        self.start(SPEC1)
        r = self.rec()
        self.assertEqual((r["window"], r["backfilled"], r["config"]), ("stamped", False, "cfg"))

    def test_late_joining_spec_takes_the_only_config(self):
        late = "docs/superpowers/specs/late.md"
        r = metrics.build_record(self.repo, late, "B", None, self.now, conn=self.conn, project="proj", branch="feat/y")
        self.assertEqual(r["config"], "cfg")
        self.assertNotIn("config", r["missing"])

    def test_late_joining_spec_in_a_two_config_batch_is_null_and_missing(self):
        late = "docs/superpowers/specs/late.md"
        metrics.append(self.repo, {"kind": "batch", "batch": "C", "base": "x", "configs": ["a", "b"],
                                   "assignment": {SPEC1: "a"}, "groups": [], "at": metrics.utc(self.t0 - 600)})
        r = metrics.build_record(self.repo, late, "C", None, self.now, conn=self.conn, project="proj", branch="feat/y")
        self.assertIsNone(r["config"])
        self.assertIn("config", r["missing"])

    def test_limits_start_and_record(self):
        self.start(SPEC1, limits={"five_hour": {"used_percentage": 5}, "seven_day": None})
        r = self.rec()
        self.assertEqual(r["limits"]["start"], {"five_hour": {"used_percentage": 5}, "seven_day": None})
        self.assertIsNone(r["limits"]["record"])
        self.assertIn("limits", r["missing"])
        d = self.state / "statusline"
        d.mkdir(parents=True)
        (d / "x.json").write_text(json.dumps({"session_id": SID_LEAD, "received_at": time.time(),
                                              "rate_limits": {"five_hour": {"used_percentage": 9}, "seven_day": {"used_percentage": 2}}}))
        r = self.rec()
        self.assertEqual(r["limits"]["record"], {"five_hour": {"used_percentage": 9}, "seven_day": {"used_percentage": 2}})
        self.assertNotIn("limits", r["missing"])
        self.assertNotIn(SID_LEAD, json.dumps(r))


class QuestionsHandoffsTest(Base):
    def slugdir(self, name=None):
        slug = name or self.root.replace("/", "-").replace(".", "-")
        d = self.proj / slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def ask(self, ts, **extra):
        d = {"type": "assistant", "timestamp": metrics.utc(ts), "sessionId": SID_LEAD,
             "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "AskUserQuestion", "id": "t", "input": {}}]}}
        d.update(extra)
        return json.dumps(d) + "\n"

    def test_questions_counted_in_lead_transcripts_inside_window(self):
        self.start(SPEC1)
        d = self.slugdir()
        (d / "lead.jsonl").write_text(self.ask(self.t0 + 10) + self.ask(self.t0 + 20) + self.ask(self.t0 - 50)
                                      + self.ask(self.t0 + 30, agentName="impl") + "not json\n")
        (d / "sub").mkdir()
        (d / "sub" / "subagents").mkdir()
        (d / "sub" / "subagents" / "agent-1.jsonl").write_text(self.ask(self.t0 + 40))
        wt = self.slugdir(self.root.replace("/", "-").replace(".", "-") + "--claude-worktrees-wt1")
        (wt / "w.jsonl").write_text(self.ask(self.t0 + 50))
        self.assertEqual(self.rec()["questions"], 3)

    def test_old_files_are_skipped_by_mtime(self):
        self.start(SPEC1)
        f = self.slugdir() / "old.jsonl"
        f.write_text(self.ask(self.t0 + 10))
        os.utime(f, (self.t0 - 3600, self.t0 - 3600))
        self.assertEqual(self.rec()["questions"], 0)

    def test_no_transcripts_dir_is_null_and_missing(self):
        self.start(SPEC1)
        r = self.rec()
        self.assertIsNone(r["questions"])
        self.assertIn("questions", r["missing"])

    def test_handoffs_counted_in_window(self):
        self.start(SPEC1)
        self.lineage.mkdir()
        lines = [{"ts": self.t0 + 5, "old_session_id": SID_A, "doc": "/Users/x/a.md", "pane": "%1"},
                 {"ts": self.t0 + 6, "old_session_id": SID_B, "doc": "/Users/x/b.md", "pane": "%1"},
                 {"ts": self.t0 - 5, "old_session_id": SID_B, "doc": "/Users/x/c.md", "pane": "%1"}]
        (self.lineage / "proj.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\nbroken\n")
        r = self.rec()
        self.assertEqual(r["handoffs"], 2)
        self.assertNotIn("Users", json.dumps(r))

    def test_no_lineage_file_is_zero(self):
        self.start(SPEC1)
        self.assertEqual(self.rec()["handoffs"], 0)


class LeadFieldsTest(Base):
    """The four lead fields, missing_reason and the failure fence (Task 7)."""
    PHRASE = "continue from where the previous session left off"

    def slugdir(self):
        d = self.proj / self.root.replace("/", "-").replace(".", "-")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def turn(self, ts, rid, inp):
        return json.dumps({"type": "assistant", "timestamp": metrics.utc(ts), "requestId": rid, "isSidechain": False,
                           "message": {"role": "assistant", "content": [], "usage": {
                               "input_tokens": inp, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                               "output_tokens": 5}}}) + "\n"

    def transcript(self, sid, turns, doc=None):
        text = ""
        if doc:
            text += json.dumps({"type": "user", "timestamp": metrics.utc(turns[0][0] - 1),
                                "message": {"role": "user", "content": f"{self.PHRASE} {doc}"}}) + "\n"
        for i, (ts, inp) in enumerate(turns):
            text += self.turn(ts, f"{sid[:4]}-{i}", inp)
        (self.slugdir() / f"{sid}.jsonl").write_text(text)

    def lineage_lines(self, *lines):
        self.lineage.mkdir(exist_ok=True)
        (self.lineage / "proj.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")

    def two_sessions(self, handoff_ts=None):
        handoff_ts = handoff_ts or self.t0 + 300
        self.lineage_lines({"ts": handoff_ts, "old_session_id": SID_A, "doc": "/Users/x/handoff-one.md", "pane": "%1"})
        self.transcript(SID_A, [(self.t0 + 10, 1000), (self.t0 + 200, 4000)])
        self.transcript(SID_B, [(self.t0 + 400, 2500), (self.t0 + 500, 3000)], doc="/Users/x/handoff-one.md")

    def test_two_lead_sessions_give_peak_and_one_handoff(self):
        self.start(SPEC1)
        self.two_sessions()
        r = self.rec()
        self.assertEqual(r["lead_context_peak"], 4000)
        self.assertEqual(r["lead_handoffs"], 1)
        self.assertEqual(len(r["post_handoff_tokens"]), 1)
        self.assertEqual(len(r["rereads"]), 1)
        for k in ("lead_context_peak", "post_handoff_tokens", "rereads"):
            self.assertNotIn(k, r["missing"])

    def test_record_json_holds_no_path_and_no_session_id(self):
        self.start(SPEC1)
        self.two_sessions()
        text = json.dumps(self.rec())
        for bad in ("Users", str(self.t), SID_A, SID_B, "handoff-one"):
            self.assertNotIn(bad, text)

    def test_no_lineage_file_is_null_peak_missing_and_zero_handoffs(self):
        self.start(SPEC1)
        r = self.rec()
        self.assertIsNone(r["lead_context_peak"])
        self.assertEqual(r["lead_handoffs"], 0)
        self.assertEqual((r["post_handoff_tokens"], r["rereads"]), ([], []))
        self.assertIn("lead_context_peak", r["missing"])

    def test_boundary_handoff_counted_with_a_previous_run_in_the_batch(self):
        # SPEC2's window starts after SPEC1's run ended; the handoff sits between the two
        prev_end = self.t0 - 300
        metrics.append(self.repo, {"kind": "run", "batch": "B", "spec": SPEC1, "ended_at": metrics.utc(prev_end),
                                   "at": metrics.utc(prev_end)})
        self.start(SPEC2, at=self.t0)
        self.two_sessions(handoff_ts=self.t0 - 100)
        self.assertEqual(self.rec(SPEC2)["lead_handoffs"], 1)

    def test_boundary_handoff_not_counted_without_a_previous_run(self):
        self.start(SPEC2, at=self.t0)
        self.two_sessions(handoff_ts=self.t0 - 100)
        self.assertEqual(self.rec(SPEC2)["lead_handoffs"], 0)

    def test_lead_fields_failure_never_fails_the_record(self):
        self.start(SPEC1)
        err = io.StringIO()
        with mock.patch("metrics_lead.lead_fields", side_effect=RuntimeError("boom /Users/x/secret")), \
                contextlib.redirect_stderr(err):
            r = self.rec()
        self.assertIsNone(r["lead_context_peak"])
        self.assertEqual((r["lead_handoffs"], r["post_handoff_tokens"], r["rereads"]), (0, [], []))
        for k in ("lead_context_peak", "lead_handoffs", "post_handoff_tokens", "rereads"):
            self.assertIn(k, r["missing"])
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("metrics: record: lead fields skipped: "))
        self.assertNotIn("/Users", lines[0])


class MissingReasonTest(Base):
    def test_no_taps_gives_the_record_time_reason(self):
        self.start(SPEC1)
        r = self.rec()
        self.assertEqual(r["missing_reason"], {"limits": "no statusline tap with rate_limits at record time"})

    def test_backfilled_record_gives_the_backfill_reason(self):
        self.start(SPEC1)
        r = self.rec(backfilled=True)
        self.assertEqual(r["missing_reason"], {"limits": "backfilled run: no tap reading exists for a past window"})
        self.assertEqual(r["limits"], {"start": None, "record": None})

    def test_tap_reading_has_no_missing_reason(self):
        self.start(SPEC1)
        d = self.state / "statusline"
        d.mkdir(parents=True)
        (d / "x.json").write_text(json.dumps({"session_id": SID_LEAD, "received_at": time.time(),
                                              "rate_limits": {"five_hour": {"used_percentage": 9}, "seven_day": None}}))
        r = self.rec()
        self.assertNotIn("missing_reason", r)
        self.assertNotIn("limits", r["missing"])

    def test_start_without_taps_writes_the_start_reason(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            metrics.main(["--repo", str(self.repo), "start", SPEC1, "--batch", "B"])
        rec = [d for d in metrics.read_log(self.repo)[0] if d.get("kind") == "start"][-1]
        self.assertEqual(rec["missing"], ["limits"])
        self.assertEqual(rec["missing_reason"], {"limits": "no statusline tap with rate_limits at start"})
        self.assertIsNone(rec["limits"])


class MergeMissingTest(Base):
    def test_unmerged_kept_is_not_missing_but_merged_outcome_is(self):
        self.start(SPEC1)
        self.assertNotIn("merge", self.rec()["missing"])
        r = metrics.build_record(self.repo, SPEC1, "B", "merged", self.now, conn=self.conn, project="proj", branch="feat/x")
        self.assertIn("merge", r["missing"])
        r = metrics.build_record(self.repo, SPEC1, "B", "mr", self.now, conn=self.conn, project="proj", branch="feat/x")
        self.assertIn("merge", r["missing"])


class RecordCommandTest(Base):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = metrics.main(["--repo", str(self.repo), *argv])
            except SystemExit as e:
                rc = e.code
        return rc or 0, out.getvalue(), err.getvalue()

    def test_record_appends_run_line_and_prints_summary(self):
        self.start(SPEC1)
        self.row(self.t0 + 10, branch="feat/x", agent="impl", sid=SID_A, cwd=f"{self.root}/.claude/worktrees/wt1")
        rc, out, err = self.run_main("record", SPEC1, "--batch", "B", "--branch", "feat/x", "--project", "proj",
                                     "--usage-db", str(self.db), "--no-ingest")
        self.assertEqual((rc, err), (0, ""))
        self.assertRegex(out, r"^recorded docs/superpowers/specs/one\.md B: \? tasks, 0\.00M tokens, 1 active min\n$")
        runs = [l for l in metrics.read_log(self.repo)[0] if l["kind"] == "run"]
        self.assertEqual(len(runs), 1)
        s = json.dumps(runs[0])
        self.assertEqual(runs[0]["backfilled"], False)
        self.assertEqual(runs[0]["window"], "stamped")
        self.assertEqual(runs[0]["config"], "cfg")
        self.assertNotIn("/Users/", s)
        self.assertNotIn(str(self.t), s)
        self.assertIsNone(UUID.search(s))
        self.assertNotIn("impl", s)
        print(f"private-data check: 1 run line checked ({len(s)} chars)")

    def test_record_ingests_transcripts(self):
        self.start(SPEC1)
        slug = self.root.replace("/", "-").replace(".", "-")
        d = self.proj / slug
        d.mkdir(parents=True)
        line = {"type": "assistant", "requestId": "rq1", "sessionId": SID_LEAD, "timestamp": metrics.utc(self.t0 + 30),
                "cwd": self.root, "gitBranch": "feat/x",
                "message": {"model": OPUS, "usage": {"input_tokens": 7, "output_tokens": 3}}}
        (d / "s.jsonl").write_text(json.dumps(line) + "\n")
        rc, out, err = self.run_main("record", SPEC1, "--batch", "B", "--branch", "feat/x", "--usage-db", str(self.db))
        self.assertEqual((rc, err), (0, ""))
        run = [l for l in metrics.read_log(self.repo)[0] if l["kind"] == "run"][0]
        self.assertEqual(run["tokens"]["total"], 10)

    def test_record_unknown_batch_one_line(self):
        rc, out, err = self.run_main("record", SPEC1, "--batch", "nope", "--usage-db", str(self.db), "--no-ingest")
        self.assertEqual((rc, out, err), (1, "", "metrics: record: unknown batch nope\n"))

    def test_missing_sources_still_write(self):
        self.start(SPEC1)
        rc, _, _ = self.run_main("record", SPEC1, "--batch", "B", "--branch", "feat/x", "--usage-db", str(self.db), "--no-ingest")
        self.assertEqual(rc, 0)
        run = [l for l in metrics.read_log(self.repo)[0] if l["kind"] == "run"][0]
        self.assertIn("limits", run["missing"])
        self.assertIn("questions", run["missing"])


if __name__ == "__main__":
    unittest.main()
