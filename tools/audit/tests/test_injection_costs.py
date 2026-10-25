import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import injection_costs as I

def inj(session, source, size, **kw):
    d = {"kind": "injection", "session": session, "agent": "main", "ts": 1.0, "file": "f", "source": source, "size": size}
    d.update(kw); return d

def use(session, agent, ts, inp=1, cr=0, cc=0, out=9):
    return {"kind": "usage", "session": session, "agent": agent, "ts": ts, "file": "f", "request_id": "%s%s%s" % (session, agent, ts),
            "model": "m", "input": inp, "output": out, "cache_read": cr, "cache_creation": cc}

class Costs(unittest.TestCase):
    def setUp(self):
        self.ev = [
            inj("s1", "attachment:environment", 100), inj("s1", "attachment:environment", 50),
            inj("s1", "system-reminder", 10),
            inj("s2", "attachment:environment", 30),
            inj("s2", "attachment:hook_additional_context", 7, hook_event="SessionStart"),
            inj("s2", "attachment:hook_additional_context", 5, hook_event=None),
            inj("s2", "hook:unknown", 3),
            use("s1", "main", 20.0, inp=1, cr=2, cc=3), use("s1", "main", 10.0, inp=10, cr=200, cc=3000),
            use("s1", "sub:x", 5.0, inp=999),
            use("s2", "team:atlas", 7.0, inp=4, cr=5, cc=6), use("s2", "team:atlas", 3.0, inp=40, cr=50, cc=60),
            use("s3", "sub:y", 1.0),
        ]
        self.r = I.costs(iter(self.ev))

    def test_per_source_stats(self):
        e = self.r["sources"]["attachment:environment"]
        self.assertEqual((e["sessions"], e["total_chars"], e["median_chars_per_session"]), (2, 180, 90.0))
        self.assertEqual(e["count_per_session"], {"by_session": {"s1": 2, "s2": 1}, "median": 1.5, "max": 2})
        self.assertEqual(e["source"], "measured")
        self.assertEqual(self.r["sources"]["system-reminder"]["total_chars"], 10)

    def test_hook_event_source_split(self):
        s = self.r["sources"]
        self.assertEqual(s["hook:SessionStart"]["total_chars"], 7)
        self.assertEqual(s["attachment:hook_additional_context"]["total_chars"], 5)   # no hook_event: stays an attachment source
        self.assertEqual(s["hook:unknown"]["total_chars"], 3)

    def test_first_request_prompt_tokens(self):
        f = {x["session"]: x for x in self.r["first_request_prompt_tokens"]}
        self.assertEqual((f["s1"]["agent"], f["s1"]["value"], f["s1"]["source"]), ("main", 3210, "measured"))   # earliest main, not the sub
        self.assertEqual((f["s2"]["agent"], f["s2"]["value"]), ("team:atlas", 150))
        self.assertIsNone(f["s3"]["value"]); self.assertTrue(f["s3"]["value_reason"])

class StaticFiles(unittest.TestCase):
    def test_sizes_and_missing(self):
        d = tempfile.mkdtemp(); p = os.path.join(d, "a.md")
        with open(p, "w") as fh: fh.write("x" * 41)
        r = I.static_files([("claude-md", p), ("gone", os.path.join(d, "nope.md"))])
        self.assertEqual(r[0], {"label": "claude-md", "path": p, "chars": 41, "source": "measured",
                                "tokens_estimate": {"value": 10.25, "source": "derived"}})
        self.assertIsNone(r[1]["chars"]); self.assertTrue(r[1]["chars_reason"])

    def test_cli(self):
        root = tempfile.mkdtemp(); repo = tempfile.mkdtemp()
        out = os.path.join(tempfile.mkdtemp(), "i.json")
        with open(os.path.join(repo, "CLAUDE.md"), "w") as fh: fh.write("abcd")
        subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "injection_costs.py"), "--root", root,
                        "--repo", repo, "--days", "30", "--out", out], check=True)
        with open(out) as fh: d = json.load(fh)
        self.assertEqual(set(d), {"sources", "first_request_prompt_tokens", "static_files"})
        self.assertIn(os.path.join(repo, "CLAUDE.md"), [f["path"] for f in d["static_files"]])

if __name__ == "__main__":
    unittest.main()
