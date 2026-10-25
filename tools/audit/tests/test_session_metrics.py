import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import session_metrics as M
import transcripts as T

def write(dirpath, name, lines):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "w") as fh:
        for l in lines: fh.write(json.dumps(l) + "\n")
    return p

def asst(req, cwd, inp=1, out=2, cr=0, cc=0, ts="2026-10-20T10:00:00Z", model="claude-opus-5-5", sid="s1", **kw):
    d = {"type": "assistant", "requestId": req, "cwd": cwd, "sessionId": sid, "timestamp": ts,
         "message": {"model": model, "usage": {"input_tokens": inp, "output_tokens": out,
                     "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc},
                     "content": [{"type": "text", "text": "hi"}]}}
    d.update(kw); return d

def prompt(cwd, ts, sid="s1"):
    return {"type": "user", "cwd": cwd, "sessionId": sid, "timestamp": ts, "message": {"content": "do it"}}

class Metrics(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.repo = "/r/repo"; self.proj = os.path.join(self.root, "-r-repo")
        write(self.proj, "s1.jsonl", [
            prompt(self.repo, "2026-10-20T10:00:00Z"),
            asst("m1", self.repo, inp=10, out=5, cr=100, cc=0, ts="2026-10-20T10:00:10Z"),
            prompt(self.repo, "2026-10-20T10:01:00Z"),
            asst("m2", self.repo, inp=20, out=7, cr=300, cc=0, ts="2026-10-20T10:02:00Z"),
        ])
        write(os.path.join(self.proj, "s1", "subagents"), "agent-x.jsonl", [
            asst("x1", self.repo, inp=4, out=3, cr=50, cc=2, ts="2026-10-20T10:00:30Z", model="claude-haiku-5")])
        self.out = M.compute(T.iter_events(self.root, [self.repo], days=3650))
        self.s = self.out["sessions"][0]

    def test_peak_context_and_share(self):
        self.assertEqual(self.s["peak_context"], {"value": 320, "source": "measured"})
        main = (10 + 5 + 100) + (20 + 7 + 300)
        total = main + (4 + 3 + 50 + 2)
        self.assertEqual(self.s["orchestrator_share"]["source"], "derived")
        self.assertAlmostEqual(self.s["orchestrator_share"]["value"], main / total)

    def test_agents_turns_wall_clock_and_models(self):
        ag = {a["agent"]: a for a in self.s["agents"]}
        self.assertEqual(set(ag), {"main", "sub:x"})
        self.assertEqual((ag["main"]["requests"], ag["sub:x"]["requests"]), (2, 1))
        self.assertEqual(ag["sub:x"]["first_ts"], ag["sub:x"]["last_ts"])
        self.assertEqual(self.s["turns"], {"value": 2, "source": "measured"})
        self.assertEqual(self.s["wall_clock_s"], {"value": 120.0, "source": "measured"})
        self.assertEqual(self.s["tokens_by_model"]["claude-haiku-5"]["output"], 3)
        self.assertEqual(self.s["tokens_by_agent"]["main"]["cache_read"], 400)

    def test_totals_equal_sum_of_usage_events(self):
        ev = [e for e in T.iter_events(self.root, [self.repo], days=3650) if e["kind"] == "usage"]
        for k in ("input", "output", "cache_read", "cache_creation"):
            self.assertEqual(self.out["totals"]["tokens"][k], sum(e[k] for e in ev))
        self.assertEqual(self.out["totals"]["by_agent_kind"]["sub"]["output"], 3)
        self.assertEqual(self.out["totals"]["by_agent_kind"]["main"]["output"], 12)

    def test_unavailable_values_are_null_with_reason(self):
        root = tempfile.mkdtemp()
        write(os.path.join(root, "-r-repo"), "s2.jsonl", [prompt("/r/repo", "2026-10-20T10:00:00Z", sid="s2")])
        s = M.compute(T.iter_events(root, ["/r/repo"], days=3650))["sessions"][0]
        for k in ("peak_context", "orchestrator_share", "wall_clock_s"):
            self.assertIsNone(s[k]["value"]); self.assertTrue(s[k]["value_reason"]); self.assertIn("source", s[k])

    def test_teammate_session_attributed_to_team_agent(self):
        write(self.proj, "s3.jsonl", [asst("t1", self.repo, sid="s3", agentName="atlas")])
        out = M.compute(T.iter_events(self.root, [self.repo], days=3650))
        s3 = [s for s in out["sessions"] if s["session"] == "s3"][0]
        self.assertEqual(list(s3["tokens_by_agent"]), ["team:atlas"])
        self.assertIsNone(s3["peak_context"]["value"])   # no main requests
        self.assertGreater(out["totals"]["by_agent_kind"]["team"]["output"], 0)

    def test_cli_writes_json(self):
        out = os.path.join(tempfile.mkdtemp(), "m.json")
        subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "session_metrics.py"), "--root", self.root,
                        "--repo", self.repo, "--days", "3650", "--out", out], check=True)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(set(d), {"sessions", "totals"})
        self.assertEqual(d["totals"]["tokens"]["output"], 5 + 7 + 3)

class FixtureTotals(unittest.TestCase):
    def test_fixture_totals_equal_usage_sum(self):
        fx = os.path.join(HERE, "fixtures")
        ev = list(T.iter_events(fx, None, days=None))
        out = M.compute(iter(ev))
        u = [e for e in ev if e["kind"] == "usage"]
        self.assertTrue(u)
        for k in ("input", "output", "cache_read", "cache_creation"):
            self.assertEqual(out["totals"]["tokens"][k], sum(e[k] for e in u))
            self.assertEqual(sum(s["tokens_by_model"].get(m, {}).get(k, 0) for s in out["sessions"] for m in s["tokens_by_model"]),
                             sum(e[k] for e in u))

if __name__ == "__main__":
    unittest.main()
