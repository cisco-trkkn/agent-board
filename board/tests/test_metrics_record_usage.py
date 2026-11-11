import contextlib, io, json, os, re, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import metrics, usage  # noqa: E402

SPEC1, SPEC2 = "docs/superpowers/specs/one.md", "docs/superpowers/specs/two.md"
OPUS, MYSTERY = "claude-opus-5-5", "claude-mystery-9"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
SID_LEAD, SID_A, SID_B = "11111111-aaaa-4bbb-8ccc-000000000001", "22222222-aaaa-4bbb-8ccc-000000000002", "33333333-aaaa-4bbb-8ccc-000000000003"
ISO = r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$"


def git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
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
        git(r, "init", "-q", "-b", "main")
        (r / "f.txt").write_text("1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base")
        git(r, "branch", "feat/x")
        git(r, "branch", "feat/y")
        self.root = str(r)
        self.now = float(int(time.time()))
        self.t0 = self.now - 1800
        self.db = t / "usage.sqlite"
        self.conn = usage.connect(self.db)
        self.addCleanup(self.conn.close)
        self.n = 0
        metrics.append(r, {"kind": "batch", "batch": "B", "base": git(r, "rev-parse", "main"), "configs": ["cfg"],
                           "assignment": {SPEC1: "cfg", SPEC2: "cfg"}, "groups": [], "at": metrics.utc(self.t0 - 600)})

    def start(self, spec, at=None, limits=None):
        metrics.append(self.repo, {"kind": "start", "batch": "B", "spec": spec, "at": metrics.utc(at or self.t0),
                                   "main": "x", "limits": limits})

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
