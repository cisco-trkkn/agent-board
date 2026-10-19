import importlib, json, os, shutil, sqlite3, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIX = HERE / "tests" / "fixtures" / "usage"
sys.path.insert(0, str(HERE))
import usage  # noqa: E402


class PricesTest(unittest.TestCase):
    """Fixtures are real transcripts captured with tools/usage-capture-fixture.py.

    Calibration sources (model -> fixture):
      claude-opus-5-5        opus-lead, opus-teammate, opus-haiku-mixed
      claude-opus-5-5[1m]    opus-1m
      claude-sonnet-5-5      sonnet-lead
      claude-haiku-5-5       haiku-with-subagent (+ its subagents/ file), opus-haiku-mixed
      claude-fable-5-1       fable-teammate
    A fixture with a subagents/ directory is summed with its subagent file before the comparison.
    """

    def test_prices_match_cost_state(self):
        prices = json.loads((HERE / "prices.json").read_text())["models"]
        checked = 0
        for fx in sorted(FIX.glob("*.jsonl")):
            calls, cost_state = {}, None
            files = [fx] + sorted((FIX / fx.stem / "subagents").glob("*.jsonl"))
            for f in files:
                for line in f.read_text().splitlines():
                    d = json.loads(line)
                    if d.get("type") == "cost-state":
                        cost_state = d
                    elif (d.get("message") or {}).get("usage"):
                        calls[d.get("requestId") or line] = d
            if not cost_state:
                continue
            for model, mu in cost_state["modelUsage"].items():
                got = sum(usage.call_cost(usage.row_from_line(d, False), {"models": prices})
                          for d in calls.values() if usage.norm_model(d["message"]["model"]) == usage.norm_model(model))
                self.assertAlmostEqual(got, mu["costUSD"], delta=max(mu["costUSD"] * 0.01, 1e-6), msg=f"{fx.name} {model}")
                checked += 1
        self.assertGreaterEqual(checked, 3, "need cost-state sessions for at least 3 models")


def line(rid, sess="s1", model="claude-opus-5-5", ts="2026-10-19T10:00:00.000Z", cwd="/r", agent=None,
         inp=10, out=20, cr=0, w5=0, w1=0, effort="medium", side=False):
    d = {"type": "assistant", "requestId": rid, "timestamp": ts, "cwd": cwd, "sessionId": sess,
         "gitBranch": "main", "effort": effort, "isSidechain": side,
         "message": {"model": model, "usage": {"input_tokens": inp, "output_tokens": out,
             "cache_read_input_tokens": cr, "cache_creation_input_tokens": w5 + w1,
             "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}}}
    if agent:
        d["agentName"] = agent
    return json.dumps(d) + "\n"

class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = usage.connect(self.tmp / "u.sqlite")
        self.f = self.tmp / "p" / "s1.jsonl"; self.f.parent.mkdir()
    def tearDown(self):
        self.conn.close(); shutil.rmtree(self.tmp)
    def count(self):
        return self.conn.execute("select count(*) from calls").fetchone()[0]

    def test_incremental_append_reads_from_offset(self):
        self.f.write_text(line("a"))
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        with self.f.open("a") as h: h.write(line("b"))
        self.assertEqual(usage.ingest(self.conn, self.f), 1)   # only the new line
        self.assertEqual(usage.ingest(self.conn, self.f), 0)   # unchanged file is skipped
        self.assertEqual(self.count(), 2)

    def test_partial_trailing_line_waits_for_newline(self):
        full = line("a")
        self.f.write_text(full[:-10])
        self.assertEqual(usage.ingest(self.conn, self.f), 0)
        self.f.write_text(full)
        self.assertEqual(usage.ingest(self.conn, self.f), 1)

    def test_truncated_file_is_reread_from_zero(self):
        self.f.write_text(line("a") + line("b"))
        usage.ingest(self.conn, self.f)
        self.f.write_text(line("c"))   # shorter than before, new row
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertIn(("c",), self.conn.execute("select request_id from calls").fetchall())

    def test_replaced_file_new_inode_is_reread(self):
        self.f.write_text(line("a"))
        usage.ingest(self.conn, self.f)
        tmp = self.f.with_suffix(".new"); tmp.write_text(line("c")); os.replace(tmp, self.f)   # same size, new inode
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertIn(("c",), self.conn.execute("select request_id from calls").fetchall())

    def test_rewrite_between_offset_and_size_with_partial_pending(self):
        a, b = line("a"), line("b")
        self.f.write_text(a + b[:-10])           # offset = len(a), size = len(a) + len(b) - 10
        usage.ingest(self.conn, self.f)
        c = line("ccc")
        self.assertTrue(len(a) <= len(c) < len(a) + len(b) - 10)
        self.f.write_text(c)                     # same inode, size shrank below the stored size but not below offset
        usage.ingest(self.conn, self.f)
        self.assertIn(("ccc",), self.conn.execute("select request_id from calls").fetchall())

    def test_complete_line_then_partial_then_completed(self):
        a, b = line("a"), line("b")
        self.f.write_text(a + b[:-10])
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertEqual(self.conn.execute("select offset from files").fetchone()[0], len(a.encode()))
        self.f.write_text(a + b)
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.conn.execute("select offset from files").fetchone()[0], len((a + b).encode()))

    def test_bad_lines_accumulate_then_reset_on_reread(self):
        bad = lambda: self.conn.execute("select bad_lines from files").fetchone()[0]
        self.f.write_text(line("a") + "{bad\n")
        usage.ingest(self.conn, self.f)
        with self.f.open("a") as h: h.write("{bad2\n" + line("b"))
        usage.ingest(self.conn, self.f)
        self.assertEqual(bad(), 2)
        self.f.write_text("{x\n")               # shrinks: re-read from 0, counter starts over
        usage.ingest(self.conn, self.f)
        self.assertEqual(bad(), 1)

    def test_non_object_json_lines_are_bad_lines(self):
        self.f.write_text("[1, 2]\nnull\n" + line("a"))
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertEqual(self.conn.execute("select bad_lines from files").fetchone()[0], 2)
        self.assertEqual(usage.ingest(self.conn, self.f), 0)

    def test_fallback_key_is_per_file_and_stable_on_reread(self):
        self.f.write_text(line(None) + line(None))
        sub = self.tmp / "p" / "s1" / "subagents" / "agent-x.jsonl"; sub.parent.mkdir(parents=True)
        sub.write_text(line(None))                # same session, same offset 0 as the parent's first line
        usage.ingest(self.conn, self.f); usage.ingest(self.conn, sub)
        self.assertEqual(self.count(), 3)
        tmp = self.f.with_suffix(".new"); tmp.write_text(line(None) + line(None)); os.replace(tmp, self.f)   # new inode, re-read from 0
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.count(), 3)

    def test_empty_file(self):
        self.f.write_text("")
        self.assertEqual(usage.ingest(self.conn, self.f), 0)
        self.assertEqual(self.conn.execute("select size, offset from files").fetchone(), (0, 0))
        self.f.write_text(line("a"))
        self.assertEqual(usage.ingest(self.conn, self.f), 1)

    def test_connect_creates_tables_in_wal(self):
        names = {r[0] for r in self.conn.execute("select name from sqlite_master where type='table'")}
        self.assertLessEqual({"calls", "cost_state", "files"}, names)
        self.assertEqual(self.conn.execute("pragma journal_mode").fetchone()[0], "wal")

    def test_duplicate_request_id_stored_once_last_wins(self):
        self.f.write_text(line("a", out=5) + line("a", out=99))
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.conn.execute("select output from calls").fetchall(), [(99,)])

    def test_corrupt_line_is_counted(self):
        self.f.write_text(line("a") + "{not json\n" + line("b"))
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.count(), 2)
        self.assertEqual(self.conn.execute("select bad_lines from files").fetchone()[0], 1)

    def test_synthetic_model_skipped(self):
        self.f.write_text(line("a", model="<synthetic>"))
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.count(), 0)

    def test_cost_state_latest_wins(self):
        cs = lambda v: json.dumps({"type": "cost-state", "sessionId": "s1", "totalCostUSD": v, "startTime": 1, "modelUsage": {}, "hasUnknownModelCost": False}) + "\n"
        self.f.write_text(cs(1.0) + cs(2.5))
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.conn.execute("select total_usd from cost_state").fetchall(), [(2.5,)])

    def test_subagent_file_flag(self):
        sub = self.tmp / "p" / "s1" / "subagents" / "agent-x.jsonl"; sub.parent.mkdir(parents=True)
        sub.write_text(line("z"))
        usage.ingest(self.conn, sub)
        self.assertEqual(self.conn.execute("select subagent_file from calls").fetchone()[0], 1)

    def test_fixtures_ingest_unique_request_ids(self):
        # A subagent fixture shares its parent's sessionId, so compare per sessionId over all fixture files.
        want = {}
        for fx in sorted(FIX.rglob("*.jsonl")):
            usage.ingest(self.conn, fx)
            for l in fx.read_text().splitlines():
                d = json.loads(l)
                if (d.get("message") or {}).get("usage") and d["message"].get("model") != "<synthetic>":
                    want.setdefault(d["sessionId"], set()).add(d["requestId"])
        self.assertTrue(want)
        for sid, rids in want.items():
            got = self.conn.execute("select count(*) from calls where session_id=?", (sid,)).fetchone()[0]
            self.assertEqual(got, len(rids), sid)

class RulesTest(unittest.TestCase):
    P = {"models": {"m": {"input": 1, "output": 2, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2, "context": 1000}}, "default_context": 200}
    def row(self, **kw):
        r = {"model": "m", "input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000, "cache_write_5m": 0, "cache_write_1h": 1_000_000,
             "agent_name": None, "sidechain": 0, "subagent_file": 0, "cwd": "/r"}
        r.update(kw); return r
    def test_cost(self):
        self.assertAlmostEqual(usage.call_cost(self.row(), self.P), 1 + 2 + 0.1 + 2)
    def test_unknown_model_unpriced(self):
        self.assertIsNone(usage.call_cost(self.row(model="nope"), self.P))
    def test_norm_model(self):
        self.assertEqual(usage.norm_model("claude-opus-5-5[1m]"), "claude-opus-5-5")
        self.assertEqual(usage.norm_model("claude-haiku-4-5-20251001"), "claude-haiku-4-5")
    def test_roles(self):
        self.assertEqual(usage.role(self.row(agent_name="x", sidechain=1)), "teammate")
        self.assertEqual(usage.role(self.row(sidechain=1)), "subagent")
        self.assertEqual(usage.role(self.row(subagent_file=1)), "subagent")
        self.assertEqual(usage.role(self.row(cwd="/r/.claude/worktrees/w")), "worker")
        self.assertEqual(usage.role(self.row()), "lead")
    def test_in_project(self):
        self.assertTrue(usage.in_project("/r", "/r"))
        self.assertTrue(usage.in_project("/r/.claude/worktrees/w/sub", "/r"))
        self.assertFalse(usage.in_project("/r2", "/r"))
        self.assertFalse(usage.in_project("/r/sub", "/r"))
    def test_context(self):
        r = self.row(input=10, cache_read=20, cache_write_5m=3, cache_write_1h=4)
        self.assertEqual(usage.context_tokens(r), 37)
        self.assertEqual(usage.context_window("m", self.P), 1000)
        self.assertEqual(usage.context_window("nope", self.P), 200)


if __name__ == "__main__":
    unittest.main()
