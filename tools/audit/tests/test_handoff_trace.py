import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import handoff_trace as H

_n = [0]

def ev(kind, sid, ts, agent="main", proj="/p/-r-repo", **kw):
    d = {"kind": kind, "session": sid, "agent": agent, "ts": ts, "file": "%s/%s.jsonl" % (proj, sid)}
    d.update(kw); return d

def usage(sid, ts, ctx, out=0, **kw):
    return ev("usage", sid, ts, request_id="r%f" % ts, model="m", input=ctx, output=out, cache_read=0, cache_creation=0, **kw)

def prompt(sid, ts, head, **kw):
    return ev("prompt", sid, ts, size=len(head), text_head=head, **kw)

def use(sid, ts, tool, target, **kw):
    _n[0] += 1
    return ev("tool_use", sid, ts, tool=tool, tool_use_id="u%d" % _n[0], args_key="k%d" % _n[0], target=target, **kw)

def get(out, sid):
    return [s for s in out["sessions"] if s["session"] == sid][0]


class Compaction(unittest.TestCase):
    def test_context_drop_rule(self):
        e = [usage("A", 1, 280000), usage("A", 2, 290000), usage("A", 3, 40000), usage("A", 4, 60000)]
        c = H.trace(e)["compactions"]
        self.assertEqual(len(c), 1)
        self.assertEqual((c[0]["rule"], c[0]["session"], c[0]["context_before"], c[0]["source"]), ("context_drop", "A", 290000, "derived"))

    def test_no_drop_at_exactly_half(self):
        e = [usage("A", 1, 100), usage("A", 2, 50)]
        self.assertEqual(H.trace(e)["compactions"], [])

    def test_subagent_drop_ignored(self):
        e = [usage("A", 1, 100, agent="sub:1"), usage("A", 2, 10, agent="sub:1")]
        self.assertEqual(H.trace(e)["compactions"], [])

    def test_continued_prompt_rule(self):
        e = [usage("A", 1, 280000), prompt("A", 2, "This session is being continued from a previous conversation"), usage("A", 3, 30000)]
        c = H.trace(e)["compactions"]
        rules = sorted(x["rule"] for x in c)
        self.assertIn("continued_prompt", rules)
        cp = [x for x in c if x["rule"] == "continued_prompt"][0]
        self.assertEqual(cp["context_before"], 280000)

    def test_compaction_distribution(self):
        e = [usage("A", 1, 100), usage("A", 2, 10), usage("A", 3, 300), usage("A", 4, 20)]
        d = H.trace(e)["context_at_handoff"]
        self.assertEqual((d["min"], d["median"], d["max"], d["n"]), (100, 200, 300, 2))
        self.assertEqual(d["source"], "derived")

    def test_distribution_null_when_empty(self):
        d = H.trace([usage("A", 1, 5)])["context_at_handoff"]
        self.assertIsNone(d["min"]); self.assertIn("min_reason", d)


DOC = "/Users/u/.local/state/agent-board/handoffs/2026-10-25-x.md"
RELAY = "Read %s and continue from where the previous session left off." % DOC


class Linking(unittest.TestCase):
    def test_relay_trigger_and_doc_link_beats_time(self):
        e = [use("W", 10, "Write", DOC), usage("W", 11, 250000),
             usage("Z", 50, 99999), use("Z", 51, "Read", "/zz"),          # unrelated, later-ending, same project
             prompt("B", 1000, RELAY), use("B", 1001, "Edit", "/f")]
        h = H.trace(e)["handoffs"][0]
        self.assertEqual((h["previous_session"], h["link_method"], h["trigger"]), ("W", "doc", "relay"))
        self.assertEqual(h["previous_context"], 250000)

    def test_writer_session_still_active_after_new_session_starts(self):
        e = [use("W", 10, "Write", DOC), usage("W", 11, 250000), usage("W", 1100, 400000), use("W", 1200, "Read", "/late"),
             prompt("B", 1000, RELAY), use("B", 1001, "Edit", "/f")]
        h = H.trace(e)["handoffs"][0]
        self.assertEqual((h["previous_session"], h["link_method"], h["previous_context"]), ("W", "doc", 250000))

    def test_doc_written_after_new_session_start_is_not_a_link(self):
        e = [use("W", 1500, "Write", DOC), prompt("B", 1000, RELAY)]
        self.assertNotEqual(H.trace(e)["handoffs"][0]["link_method"], "doc")

    def test_doc_writer_in_worktree_project_dir(self):
        wt = "/p/-Users-u-repo--claude-worktrees-w1"
        e = [use("W", 10, "Write", DOC, proj=wt), usage("W", 11, 120000, proj=wt),
             prompt("B", 1000, RELAY, proj="/p/-Users-u-repo"), use("B", 1001, "Edit", "/f", proj="/p/-Users-u-repo")]
        h = H.trace(e)["handoffs"][0]
        self.assertEqual((h["previous_session"], h["link_method"]), ("W", "doc"))

    def test_time_fallback_across_worktree_dir(self):
        wt = "/p/-Users-u-repo--claude-worktrees-w1"
        e = [usage("W", 11, 120000, proj=wt),
             prompt("B", 1000, RELAY, proj="/p/-Users-u-repo"), use("B", 1001, "Edit", "/f", proj="/p/-Users-u-repo")]
        h = H.trace(e)["handoffs"][0]
        self.assertEqual((h["previous_session"], h["link_method"]), ("W", "time"))

    def test_unrelated_repo_not_linked(self):
        e = [usage("W", 11, 1, proj="/p/-Users-u-other"), prompt("B", 1000, RELAY, proj="/p/-Users-u-repo")]
        h = H.trace(e)["handoffs"][0]
        self.assertEqual((h["previous_session"], h["link_method"]), (None, None))
        self.assertIn("previous_session_reason", h)

    def test_user_typed_resumption_is_keyword(self):
        e = [prompt("B", 1000, "follow the handoff file in the worktree")]
        self.assertEqual(H.trace(e)["handoffs"][0]["trigger"], "keyword")

    def test_doc_must_be_written_not_read(self):
        e = [use("R", 10, "Read", DOC), usage("R", 11, 5), prompt("B", 1000, RELAY)]
        self.assertEqual(H.trace(e)["handoffs"][0]["link_method"], "time")


class Handoff(unittest.TestCase):
    def setUp(self):
        self.e = [
            usage("A", 100, 280000), use("A", 101, "Read", "/f1"), use("A", 102, "Read", "/f2"), usage("A", 103, 285000),
            prompt("B", 1000, RELAY),
            usage("B", 1001, 20000, out=5), use("B", 1002, "Read", "/f1"), use("B", 1003, "Read", "/f3"),
            usage("B", 1004, 30000, out=7), use("B", 1010, "Edit", "/f1"), usage("B", 1010, 40000, out=1),
            use("B", 1020, "Read", "/f9"),
        ]

    def test_detect_and_link(self):
        h = H.trace(self.e)["handoffs"]
        self.assertEqual(len(h), 1)
        self.assertEqual((h[0]["session"], h[0]["previous_session"]), ("B", "A"))
        self.assertEqual(h[0]["previous_context"], 285000)

    def test_resumed_metrics(self):
        r = get(H.trace(self.e), "B")["resumed"]
        self.assertEqual(r["seconds_to_first_edit"]["value"], 10)
        self.assertEqual(r["tokens_to_first_edit"]["value"], 20005 + 30007 + 40001)
        self.assertEqual(r["reads_before_first_edit"]["value"], 2)
        self.assertEqual(r["reread_overlap"]["value"], 0.5)
        self.assertEqual(r["reread_overlap"]["source"], "derived")

    def test_other_session_not_resumed(self):
        self.assertNotIn("resumed", get(H.trace(self.e), "A"))

    def test_no_previous_session(self):
        out = H.trace([prompt("B", 5, "see handoff doc"), use("B", 6, "Read", "/a"), use("B", 7, "Write", "/b")])
        h = out["handoffs"][0]
        self.assertIsNone(h["previous_session"]); self.assertIn("previous_session_reason", h)
        self.assertIsNone(get(out, "B")["resumed"]["reread_overlap"]["value"])
        self.assertIn("value_reason", get(out, "B")["resumed"]["reread_overlap"])

    def test_previous_must_be_same_project_and_earlier(self):
        e = [usage("A", 1, 10, proj="/p/other"), usage("L", 5000, 10),
             prompt("B", 100, "handoff", proj="/p/-r-repo"), use("B", 101, "Edit", "/x")]
        h = H.trace(e)["handoffs"][0]
        self.assertIsNone(h["previous_session"])

    def test_no_edit(self):
        out = H.trace([prompt("B", 5, "/handoffs/z.md"), use("B", 6, "Read", "/a")])
        r = get(out, "B")["resumed"]
        self.assertIsNone(r["tokens_to_first_edit"]["value"]); self.assertIn("value_reason", r["tokens_to_first_edit"])
        self.assertIsNone(r["seconds_to_first_edit"]["value"])

    def test_first_prompt_only(self):
        out = H.trace([prompt("B", 5, "fix the bug"), prompt("B", 6, "write a handoff doc")])
        self.assertEqual(out["handoffs"], [])


class Cli(unittest.TestCase):
    def test_cli(self):
        root = tempfile.mkdtemp(); repo = "/r/repo"; proj = os.path.join(root, "-r-repo"); os.makedirs(proj)
        ln = lambda d: json.dumps(dict({"cwd": repo, "sessionId": "s1", "timestamp": "2026-10-20T10:00:00Z"}, **d)) + "\n"
        with open(os.path.join(proj, "s1.jsonl"), "w") as fh:
            fh.write(ln({"type": "user", "message": {"content": "Read /x/handoffs/a.md and continue from where the previous session left off."}}))
        out = os.path.join(tempfile.mkdtemp(), "sub", "h.json")
        p = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "handoff_trace.py"), "--root", root,
                            "--repo", repo, "--days", "3650", "--out", out], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        with open(out) as fh:
            d = json.load(fh)
        self.assertEqual(d["handoffs"][0]["session"], "s1")


if __name__ == "__main__":
    unittest.main()
