from datetime import datetime, timezone
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


NOW = time.mktime((2026, 10, 19, 12, 0, 0, 0, 0, -1))


def ts(delta):
    return datetime.fromtimestamp(NOW - delta, timezone.utc).isoformat().replace("+00:00", "Z")


class ThresholdsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.p = self.tmp / "usage-alerts.json"
    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_thresholds_missing_defaults(self):
        th, warn = usage.thresholds(self.p)
        self.assertEqual(th, usage.DEFAULT_ALERTS)
        self.assertIsNone(warn)

    def test_thresholds_partial_override(self):
        self.p.write_text('{"burn_per_hour": 2}')
        th, warn = usage.thresholds(self.p)
        self.assertEqual(th["burn_per_hour"], 2)
        self.assertEqual(th["context_pct"], usage.DEFAULT_ALERTS["context_pct"])
        self.assertIsNone(warn)

    def test_thresholds_invalid_warns(self):
        for text in ("{not json", "[1]"):
            self.p.write_text(text)
            th, warn = usage.thresholds(self.p)
            self.assertEqual(th, usage.DEFAULT_ALERTS)
            self.assertTrue(warn and "\n" not in warn)


class ReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.conn = usage.connect(self.tmp / "u.sqlite")
        self.f = self.tmp / "p" / "s1.jsonl"; self.f.parent.mkdir()
        self.text = ""
        self.prices = usage.load_prices()
        self.th = dict(usage.DEFAULT_ALERTS)
    def tearDown(self):
        self.conn.close(); shutil.rmtree(self.tmp)
    def put(self, *lines):
        self.text += "".join(lines); self.f.write_text(self.text); usage.ingest(self.conn, self.f)
    def live(self):
        return usage.live_sessions(self.conn, self.prices, self.th, NOW)
    def kinds(self, entry=None):
        live = self.live()
        return [a["kind"] for a in live[0]["alerts"]] if live else None
    def report(self, repo="/r"):
        return usage.report(self.conn, repo, self.prices, self.th, NOW)

    def test_live_excludes_older_than_30min(self):
        self.put(line("a", ts=ts(1700)), line("b", sess="s2", ts=ts(1900)))
        self.assertEqual([e["session_id"] for e in self.live()], ["s1"])

    def test_live_entry_fields(self):
        self.put(line("a", ts=ts(60), inp=100, out=0, cr=0, w1=0, agent="mate", cwd="/r"))
        e = self.live()[0]
        for k in ("session_id", "name", "role", "model", "effort", "agent_name", "cwd", "context", "context_pct",
                  "last_hour", "total", "alerts"):
            self.assertIn(k, e)
        self.assertEqual((e["name"], e["role"], e["context"]), ("mate", "teammate", 100))

    def test_live_total_prefers_cost_state(self):
        self.put(line("a", ts=ts(60), inp=1_000_000, out=0))   # $4 of calls
        with self.conn:
            self.conn.execute("insert into cost_state values ('s1', 0, 7.5, '{}', 0)")
        self.assertEqual(self.live()[0]["total"], 7.5)

    def test_alert_context_fires(self):
        self.put(line("a", ts=ts(60), inp=850_000, out=0))
        self.assertIn("context", self.kinds())
        self.assertEqual(self.live()[0]["context_pct"], 85)

    def test_alert_context_clears(self):
        self.put(line("a", ts=ts(60), inp=100, out=0))
        self.assertNotIn("context", self.kinds())

    def test_alert_burn_fires(self):
        self.put(line("a", ts=ts(60), inp=0, out=200_000))   # $4 in 15 min = $16/h
        self.assertIn("burn", self.kinds())

    def test_alert_burn_clears(self):
        self.put(line("a", ts=ts(1200), inp=0, out=200_000))   # same spend, outside the 900 s window
        self.assertEqual(len(self.live()), 1)
        self.assertNotIn("burn", self.kinds())

    def test_alert_total_fires_from_cost_state(self):
        self.put(line("a", ts=ts(60)))
        with self.conn:
            self.conn.execute("insert into cost_state values ('s1', 0, 30.0, '{}', 0)")
        self.assertIn("total", self.kinds())

    def test_alert_total_clears(self):
        self.put(line("a", ts=ts(60)))
        with self.conn:
            self.conn.execute("insert into cost_state values ('s1', 0, 5.0, '{}', 0)")
        self.assertNotIn("total", self.kinds())

    def test_alert_mismatch_fires(self):
        self.put(line("a", ts=ts(60), model="claude-opus-5-5", effort="low", agent="mate"))
        self.assertIn("model_mismatch", self.kinds())
        a = [a for a in self.live()[0]["alerts"] if a["kind"] == "model_mismatch"][0]
        self.assertEqual(a["label"], "opus@low")

    def test_alert_mismatch_clears_without_agent(self):
        self.put(line("a", ts=ts(60), model="claude-opus-5-5", effort="low"))
        self.assertNotIn("model_mismatch", self.kinds())

    def test_alert_mismatch_clears_on_sonnet(self):
        self.put(line("a", ts=ts(60), model="claude-sonnet-5-5", effort="low", agent="mate"))
        self.assertNotIn("model_mismatch", self.kinds())

    def test_alert_dict_shape(self):
        self.put(line("a", ts=ts(60), inp=850_000, out=0))
        a = self.live()[0]["alerts"][0]
        self.assertEqual(set(a), {"kind", "label", "detail"})
        self.assertEqual(a["label"], "ctx 85%")

    def test_report_project_filter(self):
        self.put(line("a", ts=ts(60), sess="s1", cwd="/r"), line("b", ts=ts(60), sess="s2", cwd="/r/.claude/worktrees/w"),
                 line("c", ts=ts(60), sess="s3", cwd="/other"), line("d", ts=ts(60), sess="s4", cwd="/r_x/.claude/worktrees/w"),
                 line("e", ts=ts(60), sess="s5", cwd="/rr"))
        r = self.report()
        self.assertEqual(sum(x["calls"] for x in r["by_role"]), 2)
        self.assertEqual(sorted(e["session_id"] for e in r["live"]), ["s1", "s2"])

    def test_report_alerts_carry_session_name(self):
        self.put(line("a", ts=ts(60), inp=850_000, out=0, agent="mate", cwd="/r", effort="high"))
        al = self.report()["alerts"]
        self.assertEqual([(a["kind"], a["session"]) for a in al], [("context", "mate")])

    def test_report_time_buckets(self):
        self.put(line("a", ts=ts(60), inp=1_000_000, out=0), line("b", ts=ts(86400), inp=1_000_000, out=0),
                 line("c", ts=ts(40 * 86400), inp=1_000_000, out=0))
        h = self.report()["headline"]
        self.assertAlmostEqual(h["today"], 4.0)
        self.assertAlmostEqual(h["week"], 8.0)
        self.assertAlmostEqual(h["month"], 8.0)
        self.assertEqual(sum(x["calls"] for x in self.report()["by_model"]), 2)

    def test_report_unpriced_counted(self):
        self.put(line("a", ts=ts(60), model="mystery-1", inp=1_000_000), line("b", ts=ts(60), inp=1_000_000, out=0))
        r = self.report()
        self.assertEqual(r["headline"]["unpriced_calls"], 1)
        self.assertAlmostEqual(r["headline"]["month"], 4.0)
        by = {x["key"]: x for x in r["by_model"]}
        self.assertEqual((by["mystery-1"]["calls"], by["mystery-1"]["usd"]), (1, 0))

    def test_report_daily_has_30_days_oldest_first(self):
        self.put(line("a", ts=ts(60), inp=1_000_000, out=0))
        d = self.report()["daily"]
        self.assertEqual(len(d), 30)
        self.assertEqual([x["date"] for x in d], sorted(x["date"] for x in d))
        self.assertEqual(d[-1]["date"], "2026-10-19")
        self.assertEqual(d[0]["date"], "2026-09-20")
        self.assertAlmostEqual(d[-1]["by_model"]["claude-opus-5-5"], 4.0)
        self.assertEqual(d[0]["by_model"], {})

    def test_report_by_model_cache_share(self):
        self.put(line("a", ts=ts(60), inp=10, out=0, cr=60, w5=10, w1=20))
        m = self.report()["by_model"][0]
        self.assertAlmostEqual(m["cache_share"], 60 / 100)

    def test_report_by_branch_falls_back_to_worktree_dir(self):
        d = json.loads(line("a", ts=ts(60), cwd="/r/.claude/worktrees/w")); d["gitBranch"] = ""
        self.put(json.dumps(d) + "\n", line("b", ts=ts(60), cwd="/r"))
        keys = {x["key"] for x in self.report()["by_branch"]}
        self.assertEqual(keys, {"w", "main"})

    def test_report_breakdowns_sorted_by_usd_desc(self):
        self.put(line("a", ts=ts(60), inp=1_000_000, out=0, cwd="/r"),
                 line("b", ts=ts(60), inp=3_000_000, out=0, cwd="/r/.claude/worktrees/w"))
        usds = [x["usd"] for x in self.report()["by_role"]]
        self.assertEqual(usds, sorted(usds, reverse=True))
        self.assertEqual(self.report()["by_role"][0]["key"], "worker")


if __name__ == "__main__":
    unittest.main()
