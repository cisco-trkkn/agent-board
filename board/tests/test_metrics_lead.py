import json
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import metrics_lead as ml  # noqa: E402

LO, HI = 1_700_000_000.0, 1_700_001_000.0
PHRASE = "continue from where the previous session left off."


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def tool(name, **inp):
    return {"type": "tool_use", "id": "t", "name": name, "input": inp}


def read(p):
    return tool("Read", file_path=p)


def bash(c):
    return tool("Bash", command=c)


class Base(unittest.TestCase):
    def setUp(self):
        ml.cache_clear()
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.tdir = os.path.join(self.d, "tr")
        os.makedirs(self.tdir)
        self.lin = os.path.join(self.d, "lineage.jsonl")
        self.rid = 0

    def turn(self, ts, ctx=1, out=0, tools=(), cwd=None, side=False, rid=None):
        """One assistant line: input=ctx-5 + cache_read 2 + cache_creation 3 = ctx+0 (ctx>=5), plus out."""
        self.rid += 1
        d = {"type": "assistant", "timestamp": iso(ts), "isSidechain": side, "requestId": rid or f"r{self.rid}",
             "cwd": cwd or self.d,
             "message": {"usage": {"input_tokens": ctx - 5, "cache_read_input_tokens": 2,
                                   "cache_creation_input_tokens": 3, "output_tokens": out},
                         "content": list(tools)}}
        return d

    def user(self, ts, text, **extra):
        d = {"type": "user", "timestamp": iso(ts), "message": {"role": "user", "content": text}}
        d.update(extra)
        return d

    def transcript(self, sid, lines):
        with open(os.path.join(self.tdir, sid + ".jsonl"), "w") as f:
            for x in lines:
                f.write(json.dumps(x) + "\n")

    def successor_of(self, sid, doc, first_ts, turns):
        self.transcript(sid, [self.user(first_ts, f"Read {doc} and {PHRASE}")] + turns)

    def lineage(self, *rows):
        with open(self.lin, "w") as f:
            for ts, old, doc in rows:
                f.write(json.dumps({"ts": ts, "old_session_id": old, "doc": doc, "pane": "%1"}) + "\n")

    def fields(self, prev_end=None, lo=LO, hi=HI):
        return ml.lead_fields(self.tdir, self.lin, lo, hi, prev_end)


class TestWindow(Base):
    def test_two_sessions_peak_is_larger_in_window_and_out_of_window_turn_ignored(self):
        self.transcript("sidA", [self.turn(LO - 5, ctx=900), self.turn(LO + 10, ctx=100), self.turn(LO + 20, ctx=300),
                                 self.turn(HI + 5, ctx=950)])
        self.successor_of("sidB", "/h/d1.md", LO + 31, [self.turn(LO + 40, ctx=200), self.turn(LO + 50, ctx=250)])
        self.lineage((LO + 30, "sidA", "/h/d1.md"))
        r = self.fields()
        self.assertEqual(r["lead_context_peak"], 300)
        self.assertEqual(r["lead_handoffs"], 1)
        self.assertEqual((r["missing"], r["rereads"]), ([], [0]))

    def test_successor_can_hold_the_peak(self):
        self.transcript("sidA", [self.turn(LO + 10, ctx=100)])
        self.successor_of("sidB", "/h/d1.md", LO + 31, [self.turn(LO + 40, ctx=700)])
        self.lineage((LO + 30, "sidA", "/h/d1.md"))
        self.assertEqual(self.fields()["lead_context_peak"], 700)

    def test_no_lineage_line_in_or_before_window(self):
        self.transcript("sidA", [self.turn(LO + 10, ctx=100)])
        self.lineage((HI + 50, "sidA", "/h/d1.md"))
        r = self.fields()
        self.assertIsNone(r["lead_context_peak"])
        self.assertIn("lead_context_peak", r["missing"])
        self.assertEqual((r["lead_handoffs"], r["post_handoff_tokens"], r["rereads"]), (0, [], []))

    def test_missing_lineage_file(self):
        r = self.fields()
        self.assertEqual(r, {"lead_context_peak": None, "lead_handoffs": 0, "post_handoff_tokens": [], "rereads": [],
                             "missing": ["lead_context_peak"]})

    def test_missing_tdir(self):
        self.lineage((LO + 30, "sidA", "/h/d1.md"))
        r = ml.lead_fields(os.path.join(self.d, "nope"), self.lin, LO, HI)
        self.assertIsNone(r["lead_context_peak"])
        self.assertEqual((r["lead_handoffs"], r["post_handoff_tokens"], r["rereads"]), (1, [None], [None]))
        self.assertEqual(sorted(r["missing"]), ["lead_context_peak", "post_handoff_tokens", "rereads"])


class TestBoundary(Base):
    def chain(self):
        # S0 -> S1 (line before lo) ; S1 -> S2 (line before lo) ; S2 -> S3 (line inside)
        self.transcript("S0", [self.turn(LO - 200, ctx=50)])
        self.successor_of("S1", "/h/d0.md", LO - 79, [self.turn(LO - 70, ctx=60, out=1)])
        self.successor_of("S2", "/h/d1.md", LO - 49, [self.turn(LO + 5, ctx=400, out=2)])
        self.successor_of("S3", "/h/d2.md", LO + 31, [self.turn(LO + 40, ctx=500, out=3)])

    def test_one_boundary_line(self):
        self.successor_of("S1", "/h/d0.md", LO - 49, [self.turn(LO + 5, ctx=400, out=2)])
        self.transcript("S0", [self.turn(LO - 200, ctx=50)])
        self.lineage((LO - 50, "S0", "/h/d0.md"))
        r = self.fields(prev_end=LO - 100)
        self.assertEqual(r["lead_handoffs"], 1)
        self.assertEqual(r["post_handoff_tokens"], [402])
        self.assertEqual(r["lead_context_peak"], 400)

    def test_two_before_lo_plus_one_inside(self):
        self.chain()
        self.lineage((LO - 80, "S0", "/h/d0.md"), (LO - 50, "S1", "/h/d1.md"), (LO + 30, "S2", "/h/d2.md"))
        r = self.fields(prev_end=LO - 100)
        self.assertEqual(r["lead_handoffs"], 3)
        self.assertEqual(len(r["post_handoff_tokens"]), 3)
        self.assertEqual(len(r["rereads"]), 3)

    def test_prev_end_none_counts_from_lo(self):
        self.chain()
        self.lineage((LO - 50, "S1", "/h/d1.md"))
        r = self.fields(prev_end=None)
        self.assertEqual((r["lead_handoffs"], r["post_handoff_tokens"], r["rereads"]), (0, [], []))

    def test_prev_end_after_line(self):
        self.chain()
        self.lineage((LO - 50, "S1", "/h/d1.md"))
        r = self.fields(prev_end=LO - 20)
        self.assertEqual((r["lead_handoffs"], r["post_handoff_tokens"], r["rereads"]), (0, [], []))

    def test_line_at_prev_end_not_counted_line_at_hi_counted(self):
        self.lineage((500.0, "S0", "/h/d0.md"), (2000.0, "S1", "/h/d1.md"))
        r = ml.lead_fields(self.tdir, self.lin, 1000.0, 2000.0, 500.0)
        self.assertEqual(r["lead_handoffs"], 1)
        self.assertEqual(r["post_handoff_tokens"], [None])

    def test_absent_successor(self):
        self.transcript("S0", [self.turn(LO + 5, ctx=50)])
        self.lineage((LO + 30, "S0", "/h/d0.md"))
        r = self.fields()
        self.assertEqual((r["post_handoff_tokens"], r["rereads"]), ([None], [None]))
        self.assertIn("post_handoff_tokens", r["missing"])
        self.assertIn("rereads", r["missing"])
        self.assertNotIn("lead_context_peak", r["missing"])


class TestSuccessor(Base):
    LINE = {"ts": LO, "old_session_id": "old", "doc": "/h/the-doc.md"}

    def test_teammate_and_phraseless_are_not_successors(self):
        self.transcript("mate", [self.user(LO - 1, f"Read the-doc.md and {PHRASE}", agentName="w1")])
        self.transcript("chat", [self.user(LO, "please look at the-doc.md today")])
        self.assertIsNone(ml.successor(self.tdir, self.LINE))
        self.successor_of("real", "/h/the-doc.md", LO + 5, [])
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINE)), "real.jsonl")

    def test_earliest_first_timestamp_wins_and_own_session_excluded(self):
        self.successor_of("old", "/h/the-doc.md", LO - 100, [])
        self.successor_of("late", "/h/the-doc.md", LO + 50, [])
        self.successor_of("early", "/h/the-doc.md", LO + 10, [])
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINE)), "early.jsonl")

    def test_message_content_blocks(self):
        self.transcript("blk", [self.user(LO + 1, [{"type": "text", "text": f"Read the-doc.md and {PHRASE}"}])])
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINE)), "blk.jsonl")


import glob as _glob


def reference_successor(tdir, line):
    """metrics_lead.successor at base 0af42b5, cache-free: the behaviour the cached version must keep."""
    try:
        base = os.path.basename(str(line.get("doc") or ""))
        old = str(line.get("old_session_id") or "")
        if not base:
            return None
        best = None
        for p in sorted(_glob.glob(os.path.join(_glob.escape(tdir), "*.jsonl"))):
            if os.path.basename(p)[:-6] == old:
                continue
            head = ml._lines(p, ml.HEAD_LINES)
            if not any(d.get("type") == "user" and "agentName" not in d and base in (t := ml._text(d)) and ml.PHRASE in t
                       for d in head):
                continue
            first = next((e for e in (ml.ctxsize._epoch(d.get("timestamp")) for d in head) if e is not None), float("inf"))
            if best is None or first < best[0]:
                best = (first, p)
        return best[1] if best else None
    except Exception:
        return None


class TestSuccessorCache(Base):
    LINES = [{"ts": LO, "old_session_id": "old", "doc": "/h/the-doc.md"},
             {"ts": LO, "old_session_id": "early", "doc": "/h/the-doc.md"},
             {"ts": LO, "old_session_id": "x", "doc": "/h/other.md"},
             {"ts": LO, "old_session_id": "x", "doc": "/h/none.md"},
             {"ts": LO, "old_session_id": "x", "doc": ""},
             {"ts": LO, "old_session_id": "old"}]

    def fixture(self):
        self.transcript("mate", [self.user(LO - 1, f"Read the-doc.md and {PHRASE}", agentName="w1")])
        self.transcript("chat", [self.user(LO, "please look at the-doc.md today")])
        self.successor_of("old", "/h/the-doc.md", LO - 100, [])
        self.successor_of("late", "/h/the-doc.md", LO + 50, [])
        self.successor_of("early", "/h/the-doc.md", LO + 10, [])
        self.transcript("blk", [self.user(LO + 1, [{"type": "text", "text": f"Read other.md and {PHRASE}"}])])
        # first timestamp comes from a line before the PHRASE line
        self.transcript("pre", [{"type": "summary", "timestamp": iso(LO + 5)}, self.user(LO + 90, f"Read other.md and {PHRASE}")])

    def same(self):
        for line in self.LINES:
            self.assertEqual(ml.successor(self.tdir, line), reference_successor(self.tdir, line), line)

    def counting(self, attr):
        real, calls = getattr(ml, attr), []

        def wrap(*a, **k):
            calls.append(a[0])
            return real(*a, **k)
        p = unittest.mock.patch.object(ml, attr, wrap)
        p.start()
        self.addCleanup(p.stop)
        return calls

    def test_parity_with_reference_and_after_a_change(self):
        self.fixture()
        self.same()
        self.same()   # served from the caches
        p = os.path.join(self.tdir, "late.jsonl")
        with open(p, "w") as f:
            f.write(json.dumps(self.user(LO + 1, f"Read the-doc.md and {PHRASE}")) + "\n")
        os.utime(p, (LO + 999, LO + 999))
        self.same()
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINES[0])), "late.jsonl")

    def test_each_file_opened_once_and_only_the_changed_one_reopened(self):
        self.fixture()
        opens = self.counting("_open")
        for line in self.LINES[:3] * 2:
            ml.successor(self.tdir, line)
        names = sorted(os.path.basename(p) for p in opens)
        self.assertEqual(names, sorted(os.path.basename(p) for p in _glob.glob(os.path.join(self.tdir, "*.jsonl"))))
        p = os.path.join(self.tdir, "chat.jsonl")
        with open(p, "a") as f:
            f.write(json.dumps(self.user(LO + 2, "more")) + "\n")
        os.utime(p, (LO + 999, LO + 999))
        del opens[:]
        ml.successor(self.tdir, self.LINES[0])
        self.assertEqual([os.path.basename(p) for p in opens], ["chat.jsonl"])

    def test_lines_without_phrase_are_never_parsed(self):
        # mutation: parse every head line (drop the raw PHRASE pre-filter) -> this test fails
        for i in range(5):
            self.transcript(f"plain{i}", [self.user(LO + i, "the-doc.md but no handoff words"), self.turn(LO + i + 1)])
        loads = self.counting("_loads")
        self.assertIsNone(ml.successor(self.tdir, self.LINES[0]))
        self.assertEqual(loads, [])

    def test_deleted_successor_drops_out(self):
        # mutation: key _RESULTS without the dir signature -> the second assertion fails
        self.fixture()
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINES[0])), "early.jsonl")
        os.remove(os.path.join(self.tdir, "early.jsonl"))
        self.assertEqual(os.path.basename(ml.successor(self.tdir, self.LINES[0])), "late.jsonl")


class TestLeadSessionIds(Base):
    def test_ids_of_old_and_successor_sessions(self):
        self.transcript("old", [self.turn(LO + 1)])
        self.successor_of("new", "/h/d.md", LO + 20, [self.turn(LO + 30)])
        self.lineage((LO + 10, "old", "/h/d.md"))
        self.assertEqual(ml.lead_session_ids(self.tdir, self.lin, LO, HI), {"old", "new"})

    def test_error_gives_empty_set(self):
        self.assertEqual(ml.lead_session_ids(self.tdir, os.path.join(self.d, "missing.jsonl"), LO, HI), set())
        self.assertEqual(ml.lead_session_ids(None, None, "x", HI), set())


class TestPostHandoffTokens(Base):
    def run_n(self, n):
        self.transcript("S0", [self.turn(LO + 5, ctx=50)])
        self.successor_of("S1", "/h/d0.md", LO + 20, [self.turn(LO + 30 + i, ctx=10, out=4) for i in range(n)])
        self.lineage((LO + 25, "S0", "/h/d0.md"))
        return self.fields()["post_handoff_tokens"]

    def test_twelve_turns_sum_first_ten(self):
        self.assertEqual(self.run_n(12), [140])

    def test_three_turns(self):
        self.assertEqual(self.run_n(3), [42])


class TestRereads(Base):
    def setUp(self):
        super().setUp()
        self.f = {}
        for n in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt", "rel.txt", "late.txt", "side.txt"):
            p = os.path.join(self.d, n)
            with open(p, "w") as fh:
                fh.write("x")
            self.f[n] = p
        self.gone = os.path.join(self.d, "gone.txt")

    def build(self, new_extra=()):
        t, f = self.turn, self.f
        old = [t(LO + 1, tools=[read(f["a.txt"])]),
               t(LO + 2, tools=[bash("sed -n 1,5p b.txt")]),
               t(LO + 3, tools=[bash("grep -n x c.txt d.txt")]),
               t(LO + 4, tools=[bash("cd z && tail e.txt")]),
               t(LO + 5, tools=[bash("cat rel.txt")]),
               t(LO + 6, tools=[read(f["late.txt"])]),
               t(LO + 7, tools=[read(self.gone)]),
               t(LO + 8, tools=[read(f["side.txt"])], side=True)]
        self.transcript("S0", old)
        new = [t(LO + 31, tools=[read(os.path.join(self.d, ".", "a.txt"))]),
               t(LO + 32, tools=[bash("cat a.txt | head")]),
               t(LO + 33, tools=[bash("cat b.txt")]),
               t(LO + 34, tools=[bash("grep -n x c.txt")]),
               t(LO + 35, tools=[bash("tail e.txt")]),
               t(LO + 36, tools=[read(f["rel.txt"])]),
               t(LO + 37, tools=[read(self.gone)]),
               t(LO + 38, tools=[read(f["d.txt"])], side=True),
               t(LO + 39), t(LO + 40), t(LO + 40.5),
               t(LO + 41, tools=[read(f["late.txt"])])] + list(new_extra)
        self.successor_of("S1", "/h/d0.md", LO + 30, new)
        self.lineage((LO + 25, "S0", "/h/d0.md"))
        return self.fields()

    def test_read_set_rules(self):
        r = self.build()
        # a, b, c, e, rel.txt: a by Read and cat counts once; late is the 11th turn; d is a sidechain read;
        # gone does not exist; x is a pattern, not a file
        self.assertEqual(r["rereads"], [5])

    def test_read_set_function(self):
        self.build()
        s = ml.read_set(os.path.join(self.tdir, "S1.jsonl"), first_turns=10)
        self.assertEqual(s, {self.f[n] for n in ("a.txt", "b.txt", "c.txt", "e.txt", "rel.txt")})
        whole = ml.read_set(os.path.join(self.tdir, "S1.jsonl"))
        self.assertIn(self.f["late.txt"], whole)

    def test_unreadable_command_skipped(self):
        self.transcript("S0", [self.turn(LO + 1, tools=[bash("cat 'unterminated a.txt"), read(self.f["a.txt"])])])
        self.assertEqual(ml.read_set(os.path.join(self.tdir, "S0.jsonl")), {self.f["a.txt"]})

    def test_previous_lead_missing(self):
        self.successor_of("S1", "/h/d0.md", LO + 30, [self.turn(LO + 31, tools=[read(self.f["a.txt"])])])
        self.lineage((LO + 25, "S0", "/h/d0.md"))
        r = self.fields()
        self.assertEqual(r["rereads"], [None])
        self.assertIn("rereads", r["missing"])
        self.assertEqual(len(r["post_handoff_tokens"]), 1)
        self.assertIsNotNone(r["post_handoff_tokens"][0])


class TestRobust(Base):
    def test_binary_transcript_and_broken_lineage(self):
        with open(os.path.join(self.tdir, "x.jsonl"), "wb") as f:
            f.write(bytes(range(256)) * 50)
        self.transcript("S0", [self.turn(LO + 5, ctx=50)])
        with open(self.lin, "w") as f:
            f.write("{broken\n")
            f.write(json.dumps({"ts": LO + 30, "old_session_id": "S0", "doc": "/h/d0.md"}) + "\n")
            f.write(json.dumps(["not", "a", "dict"]) + "\n")
            f.write(json.dumps({"ts": "bad", "old_session_id": "S0", "doc": "/h/d0.md"}) + "\n")
        r = self.fields()
        self.assertIsInstance(r, dict)
        self.assertEqual(r["lead_handoffs"], 1)

    def test_no_private_strings_in_result(self):
        secret = os.path.join(self.d, "secretfile-zq.txt")
        with open(secret, "w") as fh:
            fh.write("x")
        self.transcript("sess-old-9f3", [self.turn(LO + 1, tools=[read(secret)])])
        self.successor_of("sess-new-7c1", "/h/handoffdoc-zq.md", LO + 30,
                          [self.turn(LO + 31, ctx=20, tools=[read(secret)])])
        self.lineage((LO + 25, "sess-old-9f3", "/h/handoffdoc-zq.md"))
        r = self.fields()
        self.assertEqual(r["rereads"], [1])
        blob = json.dumps(r)
        for s in (self.d, "sess-old-9f3", "sess-new-7c1", "secretfile-zq", "handoffdoc-zq"):
            self.assertNotIn(s, blob)


if __name__ == "__main__":
    unittest.main()
