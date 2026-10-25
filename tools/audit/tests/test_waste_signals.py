import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import waste_signals as W

_n = [0]

def use(tool, key, target, agent="main", ts=1.0, sid="s1", uid=None):
    _n[0] += 1
    uid = uid or "u%d" % _n[0]
    return {"kind": "tool_use", "session": sid, "agent": agent, "ts": ts, "file": "f", "tool": tool,
            "tool_use_id": uid, "args_key": key, "target": target}

def res(use_ev, size=10, err=False, ts=None):
    return {"kind": "tool_result", "session": use_ev["session"], "agent": use_ev["agent"],
            "ts": ts if ts is not None else use_ev["ts"], "file": "f",
            "tool_use_id": use_ev["tool_use_id"], "size": size, "is_error": err}

def other(kind, size, sid="s1", agent="main", ts=1.0, **kw):
    d = {"kind": kind, "session": sid, "agent": agent, "ts": ts, "file": "f", "size": size}
    d.update(kw); return d

def sess(out, sid="s1"):
    return [s for s in out["sessions"] if s["session"] == sid][0]

def pair(tool, key, target, size=10, err=False, **kw):
    u = use(tool, key, target, **kw)
    return [u, res(u, size, err)]

class Signals(unittest.TestCase):
    def test_repeat_reads_threshold_three_and_family(self):
        ev = []
        for _ in range(3): ev += pair("Read", "k1", "/a.py")
        for _ in range(2): ev += pair("Read", "k2", "/b.py")
        for _ in range(3): ev += pair("Bash", "k3", "cat /c.txt")
        for _ in range(3): ev += pair("Bash", "k4", "ls -l")
        r = sess(W.signals(ev))["repeat_reads"]
        self.assertEqual(r["source"], "measured")
        got = {(x["agent"], x["target"]): x["count"] for x in r["value"]}
        self.assertEqual(got, {("main", "/a.py"): 3, ("main", "cat /c.txt"): 3})

    def test_repeat_reads_distinguishes_identical_rereads(self):
        ev = pair("Read", "same", "/a.py") + pair("Read", "same", "/a.py") + pair("Read", "slice2", "/a.py")
        (x,) = sess(W.signals(ev))["repeat_reads"]["value"]
        self.assertEqual((x["count"], x["distinct_args"], x["identical_count"]), (3, 2, 2))

    def test_repeat_failures_not_merged_across_tools(self):
        ev = pair("Bash", "shared", "x", err=True) + pair("Read", "shared", "x", err=True)
        self.assertEqual(sess(W.signals(ev))["repeat_failures"]["value"], [])
        ev += pair("Bash", "shared", "x", err=True)
        (f,) = sess(W.signals(ev))["repeat_failures"]["value"]
        self.assertEqual((f["tool"], f["count"]), ("Bash", 2))

    def test_repeat_reads_split_by_agent(self):
        ev = []
        for _ in range(2): ev += pair("Read", "k", "/a", agent="main")
        for _ in range(2): ev += pair("Read", "k", "/a", agent="sub:1")
        self.assertEqual(sess(W.signals(ev))["repeat_reads"]["value"], [])

    def test_bash_read_prefixes(self):
        for cmd in ("cat x", "sed -n 1,5p x", "head x", "grep foo x"):
            ev = []
            for _ in range(3): ev += pair("Bash", "k", cmd)
            self.assertEqual(len(sess(W.signals(ev))["repeat_reads"]["value"]), 1, cmd)

    def test_repeat_commands_needs_identical_outcome(self):
        ev = pair("Bash", "a", "make", size=5) + pair("Bash", "a", "make", size=5)
        ev += pair("Bash", "b", "ls", size=5) + pair("Bash", "b", "ls", size=6)
        ev += pair("Bash", "c", "t", size=5) + pair("Bash", "c", "t", size=5, err=True)
        ev += pair("Read", "d", "/x") + pair("Read", "d", "/x")
        r = sess(W.signals(ev))["repeat_commands"]
        self.assertEqual(r["source"], "derived")
        self.assertEqual([(x["target"], x["count"]) for x in r["value"]], [("make", 2)])

    def test_repeat_commands_ignores_unpaired(self):
        ev = [use("Bash", "a", "make"), use("Bash", "a", "make")]
        self.assertEqual(sess(W.signals(ev))["repeat_commands"]["value"], [])

    def test_repeat_failures(self):
        ev = pair("Bash", "a", "bad", size=1, err=True) + pair("Bash", "a", "bad", size=9, err=True)
        ev += pair("Bash", "b", "ok", err=True) + pair("Bash", "b", "ok")
        r = sess(W.signals(ev))["repeat_failures"]
        self.assertEqual([(x["target"], x["count"]) for x in r["value"]], [("bad", 2)])

    def test_tool_output_share(self):
        ev = [other("tool_result", 60, tool_use_id="x", is_error=False), other("prompt", 20, text_head=""),
              other("injection", 20, source="hook:SessionStart"), other("usage", 999)]
        m = sess(W.signals(ev))["tool_output_share"]
        self.assertEqual(m["source"], "derived")
        self.assertAlmostEqual(m["value"], 0.6)

    def test_tool_output_share_null_when_empty(self):
        m = sess(W.signals([other("usage", 1)]))["tool_output_share"]
        self.assertIsNone(m["value"]); self.assertIn("value_reason", m)

    def test_cross_agent_duplicate_reads(self):
        ev = pair("Read", "a", "/shared", agent="main") + pair("Read", "a", "/shared", agent="sub:1")
        ev += pair("Read", "b", "/solo", agent="main") + pair("Read", "b", "/solo", agent="main")
        r = sess(W.signals(ev))["cross_agent_duplicate_reads"]
        self.assertEqual(len(r["value"]), 1)
        self.assertEqual(r["value"][0]["target"], "/shared")
        self.assertEqual(r["value"][0]["agents"], ["main", "sub:1"])

    def test_idle_tail(self):
        ev = [use("Read", "a", "/x", agent="sub:1", ts=100.0), other("usage", 0, agent="sub:1", ts=160.0),
              use("Read", "a", "/x", agent="team:bob", ts=10.0), other("usage", 0, agent="team:bob", ts=11.5),
              use("Read", "a", "/x", agent="main", ts=1.0), other("usage", 0, agent="main", ts=900.0),
              use("Read", "a", "/x", agent="sub:2", ts=None)]
        r = sess(W.signals(ev))["idle_tail_s"]
        self.assertEqual(r["source"], "derived")
        by = {x["agent"]: x for x in r["value"]}
        self.assertEqual(set(by), {"sub:1", "team:bob", "sub:2"})
        self.assertEqual(by["sub:1"]["value"], 60.0)
        self.assertEqual(by["team:bob"]["value"], 1.5)
        self.assertIsNone(by["sub:2"]["value"]); self.assertIn("value_reason", by["sub:2"])
        self.assertEqual(by["sub:2"]["source"], "derived")

    def test_idle_tail_no_tool_use(self):
        r = sess(W.signals([other("usage", 0, agent="sub:9", ts=5.0)]))["idle_tail_s"]
        x = r["value"][0]
        self.assertIsNone(x["value"]); self.assertIn("value_reason", x)

    def test_sessions_separate(self):
        ev = []
        for _ in range(3): ev += pair("Read", "k", "/a", sid="A")
        out = W.signals(ev + pair("Read", "k", "/a", sid="B"))
        self.assertEqual(len(sess(out, "A")["repeat_reads"]["value"]), 1)
        self.assertEqual(sess(out, "B")["repeat_reads"]["value"], [])


class Cli(unittest.TestCase):
    def test_cli_writes_json(self):
        root = tempfile.mkdtemp(); repo = "/r/repo"; proj = os.path.join(root, "-r-repo"); os.makedirs(proj)
        ln = lambda d: json.dumps(dict({"cwd": repo, "sessionId": "s1", "timestamp": "2026-10-20T10:00:00Z"}, **d)) + "\n"
        with open(os.path.join(proj, "s1.jsonl"), "w") as fh:
            fh.write(ln({"type": "user", "message": {"content": "hello"}}))
        out = os.path.join(tempfile.mkdtemp(), "sub", "w.json")
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "waste_signals.py"),
                            "--root", root, "--repo", repo, "--days", "3650", "--out", out],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(d["sessions"][0]["session"], "s1")
        self.assertEqual(d["sessions"][0]["tool_output_share"]["value"], 0.0)


if __name__ == "__main__":
    unittest.main()
