"""record writes tasks.jsonl; backfill-tasks fills it for past runs. Every path is a temp dir: the usage index, HOME, the
state dir and the metrics files are the test's own."""
import contextlib, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics, metrics_tasks, usage  # noqa: E402
from metrics_fixtures import cache_main_root  # noqa: E402

SPEC = "docs/superpowers/specs/a.md"
PLAN = "docs/superpowers/plans/2026-01-01-a.md"
LEDGER = "docs/superpowers/ledgers/2026-01-01-a/progress.md"
SONNET = "claude-sonnet-5"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-")
ABS_VALUE = re.compile(r'"/[A-Za-z]')
KEYS = set("spec batch task_id subject tier model_mapped model_used model_source escalated owner started_at ended_at active_s tokens usd "
           "review_tokens review_usd fix_rounds findings review_rounds outcome code_in_steps partial context_tokens missing".split())


def git(repo, *a, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = f"{int(date)} +0000"
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          check=True, capture_output=True, text=True, env=env).stdout.strip()


def tasks_json():
    out = []
    for i, tier in enumerate(("standard", "mechanical"), 1):
        meta = json.dumps({"files": ["src/a.py"], "modelTier": tier})
        out.append({"id": i - 1, "subject": f"Task {i}: t{i}", "status": "completed", "description": "x\n\n```json:metadata\n" + meta + "\n```\n"})
    return json.dumps({"planPath": PLAN, "tasks": out})


class Base(unittest.TestCase):
    def setUp(self):
        cache_main_root(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = self.t = Path(self.tmp.name).resolve()
        for d in ("home", "state", "proj", "lin"):
            (t / d).mkdir()
        p = mock.patch.dict(os.environ, {"TC_STATE": str(t / "state"), "USAGE_ROOT": str(t / "proj"), "TC_LINEAGE": str(t / "lin"),
                                         "HOME": str(t / "home")})
        p.start()
        os.environ.pop("AGENT_BOARD_SPAWNS", None)
        self.addCleanup(p.stop)
        self.repo = r = t / "repo"
        r.mkdir()
        self.root = str(r)
        self.now = int(time.time())
        self.t0 = self.now - 1800
        git(r, "init", "-q", "-b", "main")
        self.write("f.txt", "1\n")
        git(r, "add", "."); git(r, "commit", "-q", "-m", "base", date=self.t0 - 900)
        self.write(PLAN, f"# Plan A\n\n**Spec:** `{SPEC}`\n")
        self.write(PLAN + ".tasks.json", tasks_json())
        git(r, "add", "."); git(r, "commit", "-q", "-m", "plan", date=self.t0 - 800)
        git(r, "commit", "-q", "--allow-empty", "-m", "c1", date=self.t0 + 100)
        self.c1 = git(r, "rev-parse", "HEAD")
        git(r, "commit", "-q", "--allow-empty", "-m", "c2", date=self.t0 + 200)
        self.c2 = git(r, "rev-parse", "HEAD")
        self.write(LEDGER, self.ledger())
        self.db = t / "usage.sqlite"
        self.conn = usage.connect(self.db)
        self.addCleanup(self.conn.close)
        self.n = 0
        metrics.append(r, {"kind": "batch", "batch": "B", "base": git(r, "rev-parse", "main"), "configs": ["cfg"],
                           "assignment": {SPEC: "cfg"}, "groups": [], "at": metrics.utc(self.t0 - 600)})

    def ledger(self):
        return (f"Task 1: dispatched w1 (sonnet, base {self.c1[:7]})\n"
                f"Task 1: complete (commits 1111111..{self.c1}, review clean)\n"
                f"Task 2: dispatched w1 (haiku, base {self.c1[:7]})\n"
                f"Task 2: complete (commits {self.c1}..{self.c2}, review clean)\n")

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def row(self, ts, agent="w1", cwd=None, model=SONNET, out=1000, branch="main"):
        """Real row shape (usage index, teammate rows): cwd inside a worktree under the main root that no longer
        exists when `record` runs, git_branch 'main' (not the queue branch), agent_name set."""
        self.n += 1
        tup = (f"r{self.n}", "sid", float(ts), model, "medium", agent, "team", branch,
               f"{self.root}/.claude/worktrees/gone" if cwd is None else cwd, 0, 0, 0, out, 0, 0, 0)
        self.conn.execute(f"insert into calls ({','.join(usage.COLS)}) values ({','.join('?' * 16)})", tup)
        self.conn.commit()

    def cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = metrics.main(["--repo", str(self.repo), *argv])
        return rc, out.getvalue(), err.getvalue()

    def record(self, *extra):
        return self.cli("record", SPEC, "--batch", "B", "--usage-db", str(self.db), "--no-ingest", "--project", "proj", *extra)

    def tasks(self, path=None):
        p = Path(path) if path else metrics.tasks_path(self.repo)
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def runs(self):
        return [d for d in metrics.read_log(self.repo)[0] if d.get("kind") == "run"]


class RecordTest(Base):
    def test_record_appends_task_lines(self):
        self.row(self.t0 + 50, out=1000)     # before c1: Task 1
        self.row(self.t0 + 150, out=2000)    # between c1 and c2: Task 2
        self.row(self.t0 + 160, agent=None, out=9999)    # a lead row: not an agent row
        rc, out, err = self.record()
        self.assertEqual((rc, err), (0, ""), err)
        lines = self.tasks()
        self.assertEqual([l["task_id"] for l in lines], [1, 2])
        self.assertTrue(all(set(l) == KEYS for l in lines))
        self.assertEqual((lines[0]["spec"], lines[0]["batch"], lines[0]["owner"]), (SPEC, "B", "w1"))
        self.assertEqual([l["tokens"] for l in lines], [1000, 2000])   # commit times from real git split the owner's rows
        self.assertEqual([l["model_mapped"] for l in lines], [None, None])   # no routing file in the repo
        self.assertEqual(len(self.runs()), 1)

    def test_code_in_steps_read_from_the_plan_text(self):
        self.write(PLAN, f"# Plan A\n\n**Spec:** `{SPEC}`\n\n### Task 1: t1\n\n```python\nx = 1\n```\n\n### Task 2: t2\n\nprose\n")
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        self.assertEqual([l["code_in_steps"] for l in self.tasks()], [True, False])

    def test_routing_file_maps_tier(self):
        self.write("docs/superpowers/model-routing.json", json.dumps({"mechanical": "haiku", "standard": "sonnet"}))
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        lines = self.tasks()
        self.assertEqual([l["model_mapped"] for l in lines], ["sonnet", "haiku"])
        self.assertTrue(lines[1]["escalated"] is False and lines[1]["partial"] is True)   # no rows for Task 2

    def test_record_survives_task_error(self):
        self.row(self.t0 + 50)
        with mock.patch.object(metrics_tasks, "build_task_lines", side_effect=RuntimeError("boom")):
            rc, out, err = self.record()
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "metrics: record: task lines skipped: boom")
        self.assertEqual(len(self.runs()), 1)
        self.assertEqual(self.tasks(), [])

    def test_record_without_plan_still_records(self):
        spec2 = "docs/superpowers/specs/none.md"
        rc, out, err = self.cli("record", spec2, "--batch", "B", "--usage-db", str(self.db), "--no-ingest", "--project", "proj")
        self.assertEqual((rc, err), (0, ""))   # the run line's `missing` already names the plan
        self.assertEqual(self.tasks(), [])

    def test_plan_without_tasks_json_is_skipped_loudly(self):
        git(self.repo, "rm", "-q", PLAN + ".tasks.json")
        rc, out, err = self.record()
        self.assertEqual(rc, 0)
        self.assertEqual(err.strip(), "metrics: record: task lines skipped: plan has no .tasks.json")

    def test_no_ledger_is_partial(self):
        (self.repo / LEDGER).unlink()
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        lines = self.tasks()
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(l["partial"] and l["tokens"] is None and l["fix_rounds"] == 0 for l in lines))

    def test_live_ledger_in_the_worktree(self):
        (self.repo / LEDGER).unlink()
        git(self.repo, "branch", "feat/x")
        wt = self.repo / ".claude" / "worktrees" / "wt1"
        git(self.repo, "worktree", "add", "-q", str(wt), "feat/x")
        live = wt / ".superpowers" / "sdd" / "2026-01-01-a" / "progress.md"
        live.parent.mkdir(parents=True)
        live.write_text(self.ledger())
        self.row(self.t0 + 50, cwd=str(wt) + "/board")
        self.assertEqual(self.record("--branch", "feat/x")[0], 0)
        lines = self.tasks()
        self.assertEqual((lines[0]["owner"], lines[0]["tokens"], lines[0]["partial"]), ("w1", 1000, False))

    def test_rows_outside_the_spec_are_not_counted(self):
        self.row(self.t0 + 50, cwd="/elsewhere", out=7)                                  # another checkout
        self.row(self.t0 + 60, agent="nobody", out=7)                                    # another agent
        self.row(self.t0 - 700, out=7)                                                   # before the window
        self.row(self.t0 + 70, out=1000)
        self.assertEqual(self.record()[0], 0)
        self.assertEqual(self.tasks()[0]["tokens"], 1000)


class BackfillTasksTest(Base):
    def run_line(self):
        metrics.append(self.repo, {"kind": "run", "batch": "B", "spec": SPEC, "plan": PLAN, "branch": None,
                                   "started_at": metrics.utc(self.t0 - 600), "ended_at": metrics.utc(self.now),
                                   "at": metrics.utc(self.now)})

    def bf(self, out_path, *extra):
        return self.cli("backfill-tasks", "--log", str(out_path), "--usage-db", str(self.db), "--no-ingest", *extra)

    def test_backfill_tasks_idempotent(self):
        self.run_line()
        self.row(self.t0 + 50)
        out = self.t / "tasks-out.jsonl"
        rc, o, e = self.bf(out)
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(o.strip(), "backfilled tasks for 1 specs (2 tasks, 1 partial)")
        self.assertEqual(len(self.tasks(out)), 2)
        rc, o, e = self.bf(out)
        self.assertEqual(o.strip(), "backfilled tasks for 0 specs (0 tasks, 0 partial)")
        self.assertEqual(len(self.tasks(out)), 2)

    def test_backfill_tasks_log_override(self):
        self.run_line()
        runs_before = metrics.log_path(self.repo).read_text()
        out = self.t / "elsewhere" / "t.jsonl"
        self.assertEqual(self.bf(out)[0], 0)
        self.assertTrue(out.exists())
        self.assertFalse((self.repo / "docs/superpowers/metrics/tasks.jsonl").exists())
        self.assertEqual(metrics.log_path(self.repo).read_text(), runs_before)
        self.assertIsNone(metrics.TASKS_OVERRIDE)
        self.assertIsNone(metrics.LOG_OVERRIDE)

    def test_backfill_tasks_failure_goes_to_the_given_log(self):
        self.run_line()
        runs_before = metrics.log_path(self.repo).read_text()
        out = self.t / "err.jsonl"
        (self.t / "afile").write_text("x")   # a file where the db's parent directory should be
        rc, o, e = self.cli("backfill-tasks", "--log", str(out), "--usage-db", str(self.t / "afile" / "u.sqlite"), "--no-ingest")
        self.assertEqual(rc, 1)
        self.assertIn("metrics: backfill-tasks:", e)
        lines = [json.loads(l) for l in out.read_text().splitlines()]
        self.assertEqual([(l["kind"], l["sub"]) for l in lines], [("error", "backfill-tasks")])
        self.assertEqual(metrics.log_path(self.repo).read_text(), runs_before)   # the tracked runs.jsonl is untouched

    def test_backfill_tasks_default_path_is_main_metrics_dir(self):
        self.run_line()
        self.assertEqual(self.cli("backfill-tasks", "--usage-db", str(self.db), "--no-ingest")[0], 0)
        self.assertEqual(len(self.tasks(self.repo / "docs/superpowers/metrics/tasks.jsonl")), 2)

    def test_run_without_plan_is_skipped(self):
        metrics.append(self.repo, {"kind": "run", "batch": "B", "spec": "docs/superpowers/specs/none.md", "plan": None,
                                   "started_at": metrics.utc(self.t0), "ended_at": metrics.utc(self.now), "at": metrics.utc(self.now)})
        self.run_line()
        out = self.t / "t.jsonl"
        rc, o, e = self.bf(out)
        self.assertEqual(rc, 0)
        self.assertEqual(o.strip(), "backfilled tasks for 1 specs (2 tasks, 2 partial)")
        self.assertEqual(e, "")
        self.assertEqual({l["spec"] for l in self.tasks(out)}, {SPEC})

    def test_privacy(self):
        self.run_line()
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        out = self.t / "bf.jsonl"
        self.assertEqual(self.bf(out)[0], 0)
        lines = [l for p in (metrics.tasks_path(self.repo), out) for l in p.read_text().splitlines()]
        self.assertGreater(len(lines), 0)
        home = os.path.expanduser("~")
        for l in lines:
            self.assertNotIn("/Users/", l)
            self.assertNotIn(home, l)
            self.assertIsNone(UUID.search(l))
            self.assertIsNone(ABS_VALUE.search(l))
            for root in sorted({tempfile.gettempdir(), os.path.realpath(tempfile.gettempdir())} - {"/"}):
                self.assertNotIn(root, l)


def spawn_row(ts, name, model, lead="L1"):
    return {"ts": int(ts), "lead_session": lead, "name": name, "subagent_type": "general-purpose", "model": model,
            "tier": None, "reason": None}


class SpawnWiringTest(Base):
    def spawns(self, *rows):
        p = self.t / "state" / "spawns.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_spawns_path_default_and_override(self):
        self.assertEqual(metrics.spawns_path(), self.t / "state" / "spawns.jsonl")
        with mock.patch.dict(os.environ, {"AGENT_BOARD_SPAWNS": str(self.t / "x.jsonl")}):
            self.assertEqual(metrics.spawns_path(), self.t / "x.jsonl")

    def test_record_task_without_rows_takes_the_spawn_model(self):
        self.row(self.t0 + 50)                     # Task 1 has usage rows; Task 2 has none
        self.spawns(spawn_row(self.t0 + 150, "w1", "opus"))
        self.assertEqual(self.record()[0], 0)
        t = {d["task_id"]: d for d in self.tasks()}
        self.assertEqual((t[1]["model_used"], t[1]["model_source"]), (SONNET, "usage"))
        self.assertEqual((t[2]["model_used"], t[2]["model_source"]), ("opus", "spawn"))

    def test_record_without_spawn_file_uses_the_ledger(self):
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        t = {d["task_id"]: d for d in self.tasks()}
        self.assertEqual((t[2]["model_used"], t[2]["model_source"]), ("haiku", "ledger"))

    def test_lead_session_rows_preferred(self):
        self.row(self.t0 + 50)
        self.spawns(spawn_row(self.t0 + 120, "w1", "opus", lead="L1"), spawn_row(self.t0 + 150, "w1", "fable", lead="L2"))
        with mock.patch.object(metrics.metrics_lead, "lead_session_ids", return_value={"L1"}):
            self.assertEqual(self.record()[0], 0)
        self.assertEqual({d["task_id"]: d for d in self.tasks()}[2]["model_used"], "opus")


class RederiveTest(Base):
    def run_line(self):
        metrics.append(self.repo, {"kind": "run", "batch": "B", "spec": SPEC, "plan": PLAN, "branch": None,
                                   "started_at": metrics.utc(self.t0 - 600), "ended_at": metrics.utc(self.now),
                                   "at": metrics.utc(self.now)})

    def old_lines(self, out):
        # lines as base 0af42b5 wrote them: no model_source; Task 2 had no rows, so no model
        base = {"spec": SPEC, "batch": "B", "tier": "standard", "tokens": 5, "usd": 0.1, "partial": False}
        rows = [dict(base, task_id=1, subject="Task 1: t1", model_used=SONNET),
                dict(base, task_id=2, subject="Task 2: t2", model_used=None, tokens=None, partial=True)]
        out.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return rows

    def bf(self, out):
        return self.cli("backfill-tasks", "--log", str(out), "--usage-db", str(self.db), "--no-ingest")

    def test_rederive_appends_model_fields_only_once(self):
        # mutation: re-derive keys whose last lines already carry model_source -> the second run appends again
        self.run_line()
        out = self.t / "tasks.jsonl"
        old = self.old_lines(out)
        rc, o, e = self.bf(out)
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(o.splitlines(), ["backfilled tasks for 0 specs (0 tasks, 0 partial)",
                                          "re-derived models for 1 specs (2 tasks)"])
        lines = self.tasks(out)
        self.assertEqual(len(lines), 4)
        new1, new2 = lines[2], lines[3]
        self.assertEqual(new1, dict(old[0], model_source="usage"))
        self.assertEqual(new2, dict(old[1], model_used="haiku", model_source="ledger"))
        rc, o, e = self.bf(out)
        self.assertEqual(o.splitlines(), ["backfilled tasks for 0 specs (0 tasks, 0 partial)"])
        self.assertEqual(len(self.tasks(out)), 4)


class ReportNoModelTest(Base):
    def report(self):
        return self.cli("report", "B")[1]

    def test_line_when_a_task_has_no_model(self):
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "usage"})
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 2, "model_source": "none"})
        self.assertIn("tasks without a model: 1 (a#2)\n", self.report())

    def test_no_line_otherwise(self):
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "none"})
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "spawn"})  # last line wins
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 2, "model_used": None})       # old line, no key
        self.assertNotIn("tasks without a model", self.report())


class ReadTasksTest(Base):
    def test_malformed_line_skipped_and_counted(self):
        p = metrics.tasks_path(self.repo)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"spec": "s", "task_id": 1}\nnot json\n[1]\n')
        lines, bad = metrics.read_tasks(self.repo)
        self.assertEqual((len(lines), bad), (1, 2))


if __name__ == "__main__":
    unittest.main()
