"""Task 8: the tick (improve_eval) and `improve outcome status`. Every test uses a scratch engine DB, TC_STATE and a synthetic run log."""
import io, json, os, shutil, subprocess, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_store as S  # noqa: E402
import improve_trials as T  # noqa: E402
import improve_eval as E  # noqa: E402
import improve  # noqa: E402
import metrics  # noqa: E402
import improve_fixtures as F  # noqa: E402

EV = [{"type": "run", "ref": "r1"}]
PROSE = "--- a/docs/foo.md\n+++ b/docs/foo.md\n@@ -1 +1 @@\n-old\n+new\n"
CODE = "--- a/docs/foo.md\n+++ b/docs/foo.md\n@@ -1 +1 @@\n-old\n+$ tmux-ctl x\n"
BASE = {"base": {"baseline": True}}
GUARDS = ("failed_specs", "red_after_merge", "final_review_crit_imp_per_spec")


class Hooks(dict):
    """Recording hooks: calls is a list of (name, args)."""
    def __init__(self, **kw):
        super().__init__()
        self.calls = []
        for k in ("apply", "card", "pick", "digest"):
            if kw.get(k, True):
                self[k] = (lambda name: lambda *a, **k: self.calls.append((name, a)))(k)

    def named(self, n):
        return [a for k, a in self.calls if k == n]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp, self.state = tempfile.mkdtemp(), tempfile.mkdtemp()
        env = mock.patch.dict(os.environ, {"TC_ENGINE_DIR": self.tmp, "TC_STATE": self.state, "TC_OBSERVER_DIR": self.state})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(lambda: [shutil.rmtree(d, ignore_errors=True) for d in (self.tmp, self.state)])
        F.engine_db(self.tmp)
        self.s = S.Store("proj")
        self.hooks = Hooks()

    def trial(self, patch=PROSE, trial_len=5, target="docs/foo.md", kind="procedure", **kw):
        pid = self.s.insert("manual", kind, target, patch, EV, **kw)
        self.s.transition(pid, "trial", "go", trial_started_at=1.0, trial_len=trial_len)
        return pid

    def specs(self, pid, n_trial, n_ctl):
        t, c, i = [], [], 0
        while len(t) < n_trial or len(c) < n_ctl:
            sp = f"s{i}"
            i += 1
            (t if T.in_trial(sp, pid) else c).append(sp)
        return t[:n_trial], c[:n_ctl]

    def recs(self, pid, n_trial, n_ctl, trial_tok=500, ctl_tok=1000, trial_kw=None, ctl_kw=None):
        t, c = self.specs(pid, n_trial, n_ctl)
        out = [F.run(s, budget=1, variants=[pid], tokens={"total": trial_tok}, **(trial_kw or {})) for s in t]
        out += [F.run(s, budget=1, tokens={"total": ctl_tok}, **(ctl_kw or {})) for s in c]
        return out

    def ev(self, pid):
        c = self.s._conn()
        try:
            return [json.loads(d) for (d,) in c.execute("SELECT detail FROM events WHERE kind='improve' ORDER BY seq")
                    if json.loads(d).get("proposal") == pid]
        finally:
            c.close()

    def run_trials(self, runs, **kw):
        kw.setdefault("hooks", self.hooks)
        return E.evaluate_trials(self.s, runs, 1000.0, **kw)


class TrialPaths(Base):
    def test_low_better_guardrails_equal_kept_and_apply_called(self):
        # mutation: kept branch skips hooks["apply"] -> no apply call
        pid = self.trial()
        self.run_trials(self.recs(pid, 5, 5))
        self.assertEqual(self.s.get(pid)["state"], "kept")
        self.assertEqual(self.hooks.named("apply"), [(self.s, pid)])

    def test_low_signal_worse_reverted(self):
        # mutation: `worse` signal treated as equal -> kept
        pid = self.trial()
        self.run_trials(self.recs(pid, 5, 5, trial_tok=1500, ctl_tok=1000))
        self.assertEqual(self.s.get(pid)["state"], "reverted")
        self.assertEqual(self.hooks.named("apply"), [])

    def test_r2_signal_better_but_red_after_merge_worse_reverts(self):
        # mutation: drop the guardrail check -> kept
        pid = self.trial()
        t, _ = self.specs(pid, 5, 5)
        runs = self.recs(pid, 5, 5)
        for r in runs[:3]:
            r["red_after_merge"] = True
        self.run_trials(runs)
        self.assertEqual(self.s.get(pid)["state"], "reverted")
        self.assertIn("red_after_merge", self.s.get(pid)["reason"])

    def test_high_any_verdict_awaits_you_with_numbers(self):
        # mutation: high class goes straight to kept on better -> state kept
        pid = self.trial(patch=CODE)
        self.assertEqual(self.s.get(pid)["class"], "high")
        self.run_trials(self.recs(pid, 5, 5))
        p = self.s.get(pid)
        self.assertEqual(p["state"], "awaiting_you")
        self.assertIn("index", p["reason"])
        self.assertIn("5/5", p["reason"])
        self.assertEqual(self.hooks.named("apply"), [])
        self.assertEqual(self.hooks.named("card")[0][0], "awaiting_you")

    def test_high_worse_is_still_carded(self):
        pid = self.trial(patch=CODE)
        self.run_trials(self.recs(pid, 5, 5, trial_tok=1500))
        self.assertEqual(self.s.get(pid)["state"], "awaiting_you")

    def test_too_early_with_7_trial_specs_stays_trial(self):
        # mutation: too early -> reverted at trial_len
        pid = self.trial()
        self.run_trials(self.recs(pid, 7, 3))   # control half has 3 specs: too early
        self.assertEqual(self.s.get(pid)["state"], "trial")

    def test_too_early_with_15_trial_specs_reverts_no_signal(self):
        # mutation: drop the 15-spec limit -> stays trial
        pid = self.trial()
        self.run_trials(self.recs(pid, 15, 3))
        p = self.s.get(pid)
        self.assertEqual((p["state"], p["reason"]), ("reverted", "no signal"))

    def test_over_spend_cap_reverts_over_budget(self):
        # mutation: cap check removed -> the worse signal reason replaces `over budget`
        pid = self.trial()
        self.run_trials(self.recs(pid, 5, 5, trial_tok=3000, ctl_tok=1000))   # 15000 > 2 x 1000 x 5
        p = self.s.get(pid)
        self.assertEqual((p["state"], p["reason"]), ("reverted", "over budget"))

    def test_no_cap_without_a_control_spec(self):
        pid = self.trial()
        self.run_trials(self.recs(pid, 5, 0, trial_tok=10**6))
        self.assertEqual(self.s.get(pid)["state"], "trial")

    def test_ruling_citing_trial_blames_the_variant(self):
        # mutation: ignore events -> the better trial is kept
        pid = self.trial()
        runs = self.recs(pid, 5, 5)
        c = self.s._conn()
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (1, ?, NULL, 'ruling', ?)",
                  (runs[0]["spec"], json.dumps({"text": f"Trial {pid} made the worker skip the review"})))
        seq = c.execute("SELECT max(seq) FROM events").fetchone()[0]
        c.close()
        self.run_trials(runs)
        p = self.s.get(pid)
        self.assertEqual((p["state"], p["reason"]), ("reverted", f"variant blamed: {seq}"))

    def test_ruling_citing_another_trial_is_not_blame(self):
        pid = self.trial()
        runs = self.recs(pid, 5, 5)
        c = self.s._conn()
        c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (1, ?, NULL, 'ruling', ?)",
                  (runs[0]["spec"], json.dumps({"text": f"Trial {pid}0 is unrelated"})))
        c.close()
        self.run_trials(runs)
        self.assertEqual(self.s.get(pid)["state"], "kept")

    def test_e1_shrinks_reads_judged_on_fix_rounds(self):
        # mutation: ignore shrinks_reads -> kept
        pid = self.trial(shrinks_reads=True)
        runs = self.recs(pid, 5, 5, trial_kw={"fix_rounds": 3}, ctl_kw={"fix_rounds": 0})
        self.run_trials(runs)
        p = self.s.get(pid)
        self.assertEqual(p["state"], "reverted")
        self.assertIn("fix_rounds_per_task", p["reason"])

    def test_without_shrinks_reads_fix_rounds_are_not_judged(self):
        pid = self.trial()
        runs = self.recs(pid, 5, 5, trial_kw={"fix_rounds": 3}, ctl_kw={"fix_rounds": 0})
        self.run_trials(runs)
        self.assertEqual(self.s.get(pid)["state"], "kept")

    def test_stalled_trial_keeps_state(self):
        pid = self.trial()
        self.run_trials(self.recs(pid, 4, 5))   # 4 < trial_len 5: not evaluated
        self.assertEqual(self.s.get(pid)["state"], "trial")
        self.run_trials([])
        self.assertEqual(self.s.get(pid)["state"], "trial")


class Breach(Base):
    def test_guardrail_breach_reverts_every_trial_and_cards_kept_changes(self):
        # mutation: breach check dropped -> the trials stay and no card
        kept = self.trial()
        self.s.transition(kept, "kept", "ok")
        p1, p2 = self.trial(target="docs/a.md"), self.trial(target="docs/b.md")
        runs = [F.run(f"e{i}", budget=1, outcome="failed" if i < 3 else "merged") for i in range(5)]
        runs += [F.run(f"b{i}", config="base") for i in range(4)]
        self.run_trials(runs, configs=BASE, last_tick=100.0)
        self.assertEqual([self.s.get(p)["state"] for p in (p1, p2)], ["reverted", "reverted"])
        self.assertEqual(self.s.get(p1)["reason"], "guardrail breach")
        self.assertEqual(self.s.get(kept)["state"], "kept")   # nothing is reverted by itself
        card = self.hooks.named("card")
        self.assertEqual((card[0][0], card[0][1]["kept"]), ("breach", [kept]))

    def test_breach_uses_compare_to_baseline_not_the_halves(self):
        pid = self.trial()
        runs = [F.run(f"e{i}", budget=1) for i in range(5)] + [F.run(f"b{i}", config="base", outcome="failed") for i in range(4)]
        self.run_trials(runs, configs=BASE, last_tick=100.0)
        self.assertEqual(self.s.get(pid)["state"], "trial")
        self.assertEqual(self.hooks.named("card"), [])

    def test_failures_before_the_last_tick_are_not_a_breach(self):
        # mutation: `since` dropped from the breach check -> old failures revert the trial
        pid = self.trial()
        runs = [F.run(f"e{i}", budget=1, outcome="failed", ended_at="2026-01-01T00:00:00Z") for i in range(5)]
        runs += [F.run(f"b{i}", config="base") for i in range(4)]
        self.run_trials(runs, configs=BASE, last_tick=1780000000.0)   # 2026-05-28
        self.assertEqual(self.s.get(pid)["state"], "trial")

    def test_kept_before_the_last_tick_is_not_listed(self):
        old = self.trial()
        self.s.now = lambda: 5.0
        self.s.transition(old, "kept", "ok")
        self.s.now = lambda: 10**12   # later kept changes get a later stamp
        new = self.trial(target="docs/b.md")
        self.s.transition(new, "kept", "ok")
        runs = [F.run(f"e{i}", budget=1, outcome="failed" if i < 3 else "merged") for i in range(5)]
        runs += [F.run(f"b{i}", config="base") for i in range(4)]
        self.run_trials(runs, configs=BASE, last_tick=100.0)
        self.assertEqual(self.hooks.named("card")[0][1]["kept"], [new])


def o1(**kw):
    o = {"id": "O1", "statement": "Cheaper", "signal": {"metric": "tokens_per_task"}, "completion": {"change": -0.25, "min_queues": 2},
         "guardrails": [{"metric": m, "rule": "not_worse"} for m in GUARDS], "state": "active"}
    o.update(kw)
    return o


def o1_runs(tok=500, batches=("b1", "b2")):
    runs = [F.run(f"e{i}", budget=1, batch=batches[i % len(batches)], tokens={"total": tok}) for i in range(4)]
    return runs + [F.run(f"b{i}", config="base", tokens={"total": 1000}) for i in range(4)]


class Outcomes(Base):
    def ev_out(self):
        c = self.s._conn()
        try:
            return [json.loads(d) for (d,) in c.execute("SELECT detail FROM events WHERE kind='improve_outcome' ORDER BY seq")]
        finally:
            c.close()

    def run_out(self, runs, outcomes, **kw):
        return E.evaluate_outcomes(self.s, runs, outcomes, None, configs=BASE, hooks=self.hooks, since_of=lambda o: None, **kw)

    def test_o1_met_reports_achieved_once_and_leaves_file_alone(self):
        # mutation: min_queues ignored / event not deduped -> second call posts again
        f = Path(self.state, "O1.json")
        f.write_text(json.dumps(o1()))
        before = f.read_bytes()
        self.run_out(o1_runs(), [o1()])
        self.run_out(o1_runs(), [o1()])
        self.assertEqual(len(self.ev_out()), 1)
        self.assertEqual(self.ev_out()[0]["status"], "achieved")
        self.assertEqual(len(self.hooks.named("card")), 1)
        self.assertEqual(self.hooks.named("card")[0][0], "achieved")
        self.assertEqual(f.read_bytes(), before)

    def test_o1_needs_two_batches(self):
        self.run_out(o1_runs(batches=("b1",)), [o1()])
        self.assertEqual(self.ev_out(), [])

    def test_o1_not_met_when_index_above_threshold(self):
        self.run_out(o1_runs(tok=900), [o1()])
        self.assertEqual(self.ev_out(), [])

    def test_o1_not_met_when_a_guardrail_is_worse(self):
        runs = o1_runs()
        for r in runs[:3]:
            r["red_after_merge"] = True   # signal still better, red_after_merge worse
        self.run_out(runs, [o1()])
        self.assertEqual(self.ev_out(), [])

    def test_paused_and_achieved_outcomes_are_not_evaluated(self):
        # mutation: state not checked -> an event for the paused one
        for st in ("paused", "achieved"):
            self.run_out(o1_runs(), [o1(state=st)])
        self.assertEqual(self.ev_out(), [])

    def test_zero_engine_run_records_is_too_early_everywhere(self):
        # mutation: engine-run filter dropped -> lead-run records transition the trial / report achieved
        pid = self.trial()
        t, c = self.specs(pid, 6, 6)
        runs = [F.run(s, variants=[pid], tokens={"total": 100}) for s in t] + [F.run(s, tokens={"total": 1000}) for s in c]
        counts = self.run_trials(runs, configs=BASE)
        self.run_out(runs, [o1()])
        self.assertEqual(self.s.get(pid)["state"], "trial")
        self.assertEqual((self.ev_out(), self.hooks.named("card")), ([], []))
        self.assertEqual(counts["too_early"], 1)
        self.assertEqual(E.outcome_status(runs, o1(), BASE, None)["verdict"], "too early")


class StatusCli(Base):
    def test_outcome_status_prints_value_vs_baseline_guardrails_and_verdict(self):
        od = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, od, True)
        (od / "O1.json").write_text(json.dumps(o1()))
        log = F.write_log(self.state, o1_runs())
        cfg = Path(self.state, "cfg")
        with mock.patch.object(improve, "OUTCOMES", od), mock.patch.object(metrics, "LOG_OVERRIDE", str(log)), \
                mock.patch.object(improve, "load_configs", lambda: BASE), io.StringIO() as buf, redirect_stdout(buf):
            rc = improve.main(["--project", "proj", "outcome", "status"])
            out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("O1", out)
        self.assertIn("tokens_per_merged_task", out)
        self.assertRegex(out, r"index 0\.50")
        for g in GUARDS:
            self.assertIn(g, out)
        self.assertIn("achieved-ready", out)

    def test_status_with_no_engine_records_is_too_early(self):
        od = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, od, True)
        (od / "O1.json").write_text(json.dumps(o1()))
        log = F.write_log(self.state, [F.run("s1")])
        with mock.patch.object(improve, "OUTCOMES", od), mock.patch.object(metrics, "LOG_OVERRIDE", str(log)), \
                mock.patch.object(improve, "load_configs", lambda: BASE), io.StringIO() as buf, redirect_stdout(buf):
            improve.main(["--project", "proj", "outcome", "status", "O1"])
            self.assertIn("too early", buf.getvalue())


class FirstCommit(unittest.TestCase):
    def test_first_commit_of_a_file_in_a_real_repo(self):
        # one real unpatched git run (the deciding external command)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", d], check=True)
        f = Path(d, "O1.json")
        f.write_text("{}")
        env = {**os.environ, "GIT_AUTHOR_DATE": "2026-03-04T05:06:07Z", "GIT_COMMITTER_DATE": "2026-03-04T05:06:07Z"}
        subprocess.run(g + ["add", "O1.json"], cwd=d, check=True)
        subprocess.run(g + ["commit", "-qm", "a"], cwd=d, check=True, env=env)
        f.write_text('{"x": 1}')
        subprocess.run(g + ["commit", "-qam", "b"], cwd=d, check=True)
        self.assertEqual(E.first_commit(f), "2026-03-04T05:06:07Z")
        self.assertIsNone(E.first_commit(Path(d, "nope.json")))


class TickOrder(Base):
    def steps(self):
        c = self.s._conn()
        try:
            return [(seq, json.loads(d)) for seq, d in c.execute("SELECT seq, detail FROM events WHERE kind='improve_step' ORDER BY seq")]
        finally:
            c.close()

    def test_order_one_event_per_step_and_tick_id_reaches_insert(self):
        # mutation: swap trials/outcomes, or drop the tick id from insert -> assertion on order / tick fails
        order = []

        def adapters(project, store=None, only=None):
            order.append("adapters")
            store.insert("manual", "retire", "docs/r.md", None, EV)
            return {"dream": 0}
        h = Hooks()
        h["pick"] = lambda *a: order.append("pick") or {"picked": 0}
        h["digest"] = lambda *a: order.append("digest") or {}
        E.tick(self.s, "proj", [F.run("s1")], [], configs=BASE, hooks=h, adapters=adapters)
        st = self.steps()
        self.assertEqual([d["step"] for _, d in st], ["start", "adapters", "observe", "trials", "outcomes", "pick", "digest"])
        self.assertEqual(order, ["adapters", "pick", "digest"])
        self.assertTrue(all("counts" in d for _, d in st))
        tid = st[0][0]
        ins = [e for e in self.s_events() if e.get("from") is None and e.get("kind") == "retire"]
        self.assertEqual(ins[0]["tick"], tid)

    def s_events(self):
        c = self.s._conn()
        try:
            return [json.loads(d) for (d,) in c.execute("SELECT detail FROM events WHERE kind='improve'")]
        finally:
            c.close()

    def test_absent_pick_and_digest_are_skipped(self):
        # mutation: calling a missing hook -> TypeError
        E.tick(self.s, "proj", [], [], configs=BASE, hooks={}, adapters=lambda *a, **k: {})
        self.assertEqual([d["step"] for _, d in self.steps()], ["start", "adapters", "observe", "trials", "outcomes"])

    def test_observe_counts_engine_run_records_through_last_runs(self):
        lines = [F.run("s1", budget=1), F.run("s1", budget=1), F.run("s2"), {"kind": "batch"}]
        E.tick(self.s, "proj", lines, [], configs=BASE, hooks={}, adapters=lambda *a, **k: {})
        obs = [d for _, d in self.steps() if d["step"] == "observe"][0]
        self.assertEqual(obs["counts"], {"records": 2, "engine_run": 1})

    def test_second_tick_knows_the_first_tick_time(self):
        E.tick(self.s, "proj", [], [], configs=BASE, hooks={}, adapters=lambda *a, **k: {})
        self.assertIsNotNone(E.last_tick_ts(self.s))


class Docstring(unittest.TestCase):
    def test_improve_docstring_states_r3_with_stop_hook_active(self):
        self.assertIn("stop_hook_active", improve.__doc__)


if __name__ == "__main__":
    unittest.main()
