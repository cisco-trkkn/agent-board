from datetime import datetime, timezone
import importlib.util
import threading, urllib.error, urllib.request
from unittest import mock
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

    def test_deeply_nested_json_line_is_a_bad_line(self):
        self.f.write_text("[" * 200000 + "\n" + line("a"))
        self.assertEqual(usage.ingest(self.conn, self.f), 1)
        self.assertEqual(self.conn.execute("select bad_lines from files").fetchone()[0], 1)

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

    def test_thresholds_default_path_follows_module_alerts_path(self):
        self.p.write_text("{nope")
        with mock.patch.object(usage, "ALERTS_PATH", self.p):
            th, warn = usage.thresholds()
        self.assertTrue(warn)

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


    def test_thresholds_bad_values_fall_back_per_key(self):
        bad = {"burn_window_s": 0, "live_s": "1800", "context_pct": -5, "session_total": True,
               "mismatch_models": "opus", "mismatch_efforts": [1], "burn_per_hour": None}
        for k, v in bad.items():
            self.p.write_text(json.dumps({k: v, "session_total": 40} if k != "session_total" else {k: v}))
            th, warn = usage.thresholds(self.p)
            self.assertEqual(th[k], usage.DEFAULT_ALERTS[k], k)
            self.assertTrue(warn and k in warn and "\n" not in warn, (k, warn))
            if k != "session_total":
                self.assertEqual(th["session_total"], 40)   # the good key still applies

    def test_thresholds_accept_numbers_and_str_lists(self):
        self.p.write_text('{"burn_per_hour": 7.5, "context_pct": 90, "mismatch_models": ["opus"], "mismatch_efforts": []}')
        th, warn = usage.thresholds(self.p)
        self.assertEqual((th["burn_per_hour"], th["context_pct"], th["mismatch_models"], th["mismatch_efforts"]),
                         (7.5, 90, ["opus"], []))
        self.assertIsNone(warn)


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

    def test_report_bucket_edges_at_local_midnight(self):
        mk = lambda y, m, d, hh=0, mi=0, ss=0: time.mktime((y, m, d, hh, mi, ss, 0, 0, -1))
        at = lambda e: datetime.fromtimestamp(e, timezone.utc).isoformat().replace("+00:00", "Z")
        usd = lambda n: dict(inp=250_000 * n, out=0)       # $1 * n on opus
        self.put(line("t0", ts=at(mk(2026, 10, 19)), **usd(1)),          # exactly today's midnight: today
                 line("t1", ts=at(mk(2026, 10, 19) - 1), **usd(2)),      # 1 s before: week, not today
                 line("w0", ts=at(mk(2026, 10, 13)), **usd(4)),          # first second of the 7-day window
                 line("w1", ts=at(mk(2026, 10, 13) - 1), **usd(8)),      # 1 s before it: month only
                 line("m0", ts=at(mk(2026, 9, 20)), **usd(16)),          # first second of the 30-day window
                 line("m1", ts=at(mk(2026, 9, 20) - 1), **usd(32)))      # 1 s before it: excluded
        r = self.report()
        h = r["headline"]
        self.assertAlmostEqual(h["today"], 1.0)
        self.assertAlmostEqual(h["week"], 1 + 2 + 4)
        self.assertAlmostEqual(h["month"], 1 + 2 + 4 + 8 + 16)
        self.assertEqual(sum(x["calls"] for x in r["by_model"]), 5)
        self.assertAlmostEqual(r["daily"][0]["by_model"]["claude-opus-5-5"], 16.0)
        self.assertEqual(r["daily"][0]["date"], "2026-09-20")

    def test_report_week_and_month_edges_hold_across_dst_change(self):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Europe/Madrid"; time.tzset()
        try:
            mk = lambda y, m, d, hh=0, mi=0, ss=0: time.mktime((y, m, d, hh, mi, ss, 0, 0, -1))
            at = lambda e: datetime.fromtimestamp(e, timezone.utc).isoformat().replace("+00:00", "Z")
            now = mk(2026, 10, 28, 12)                       # DST ended 2026-10-25, so the windows span the change
            self.assertNotEqual(now - 6 * 86400, mk(2026, 10, 22, 12))   # sanity: N*86400 would be off by an hour
            self.put(line("w0", ts=at(mk(2026, 10, 22, 0, 30)), inp=1_000_000, out=0),    # 00:30, day 6 back: in week
                     line("w1", ts=at(mk(2026, 10, 21, 23, 59, 59)), inp=2_000_000, out=0),  # before it: month only
                     line("m0", ts=at(mk(2026, 9, 29, 0, 30)), inp=4_000_000, out=0),     # first day of the 30-day window
                     line("m1", ts=at(mk(2026, 9, 28, 23, 59, 59)), inp=8_000_000, out=0))   # excluded
            h = usage.report(self.conn, "/r", self.prices, self.th, now)["headline"]
            self.assertAlmostEqual(h["week"], 4.0)
            self.assertAlmostEqual(h["month"], 4.0 + 8.0 + 16.0)
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_report_unpriced_counted(self):
        self.put(line("a", ts=ts(60), model="mystery-1", inp=1_000_000), line("b", ts=ts(60), inp=1_000_000, out=0))
        r = self.report()
        self.assertEqual(r["headline"]["unpriced_calls"], 1)
        self.assertAlmostEqual(r["headline"]["month"], 4.0)
        by = {x["key"]: x for x in r["by_model"]}
        self.assertEqual((by["mystery-1"]["calls"], by["mystery-1"]["usd"], by["mystery-1"]["unpriced"]), (1, None, 1))
        self.assertEqual((by["claude-opus-5-5"]["usd"], by["claude-opus-5-5"]["unpriced"]), (4.0, 0))
        self.assertNotIn("mystery-1", r["daily"][-1]["by_model"])

    def test_report_partial_unpriced_row_keeps_partial_sum(self):
        self.put(line("a", ts=ts(60), model="mystery-1", inp=1_000_000, cwd="/r"),
                 line("b", ts=ts(60), model="claude-opus-5-5", inp=1_000_000, out=0, cwd="/r"))
        role = self.report()["by_role"][0]
        self.assertEqual((role["calls"], role["unpriced"]), (2, 1))
        self.assertAlmostEqual(role["usd"], 4.0)

    def test_report_all_unpriced_sorts_last(self):
        self.put(line("a", ts=ts(60), model="mystery-1", inp=1_000_000), line("b", ts=ts(60), inp=1, out=0))
        self.assertEqual([x["key"] for x in self.report()["by_model"]], ["claude-opus-5-5", "mystery-1"])

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


def recent_line(rid, sess="s1", **kw):
    return line(rid, sess=sess, ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **kw)


class IndexerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "projects"
        self.p = self.root / "proj"; self.p.mkdir(parents=True)
        self.db = self.tmp / "u.sqlite"
        self.ix = usage.Indexer(self.root, self.db, alerts_path=self.tmp / "none.json")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.addCleanup(self.ix.close)
        self.old = self.p / "old.jsonl"; self.old.write_text(line("o", sess="so"))
        self.new = self.p / "new.jsonl"; self.new.write_text(recent_line("n", sess="sn"))
        os.utime(self.old, (1000, 1000))
        self.sub = self.p / "sn" / "subagents" / "agent-x.jsonl"; self.sub.parent.mkdir(parents=True)
        self.sub.write_text(recent_line("z", sess="sn"))
        os.utime(self.sub, (2000, 2000))

    def test_scan_ingests_newest_first_including_subagents(self):
        seen, real = [], usage.ingest
        def spy(conn, path):
            seen.append(Path(path).name); return real(conn, path)
        with mock.patch.object(usage, "ingest", spy):
            self.ix.scan()
        self.assertEqual(seen[0], "new.jsonl")
        self.assertEqual(seen[-1], "old.jsonl")
        self.assertEqual(sorted(seen), ["agent-x.jsonl", "new.jsonl", "old.jsonl"])

    def test_progress_counts_bytes_during_first_pass_then_is_none(self):
        self.assertEqual(self.ix.progress(), {"done": 0, "total": 0})
        mid, real = [], usage.ingest
        def spy(conn, path):
            r = real(conn, path); mid.append(self.ix.progress()); return r
        with mock.patch.object(usage, "ingest", spy):
            self.ix.scan()
        self.assertEqual(len(mid), 3)
        self.assertTrue(all(m["total"] > 0 for m in mid))
        self.assertLess(mid[0]["done"], mid[0]["total"])        # the first file is not everything
        self.assertGreater(mid[-1]["done"], mid[0]["done"])     # bytes accumulate as files finish
        self.assertEqual([m["done"] for m in mid], sorted(m["done"] for m in mid))
        self.assertIsNone(self.ix.progress())                   # complete: nothing to report any more

    def test_progress_stays_none_on_later_passes(self):
        self.ix.scan()
        seen, real = [], usage.ingest
        with mock.patch.object(usage, "ingest", lambda c, p: (seen.append(self.ix.progress()), real(c, p))[1]):
            self.ix.scan()
        self.assertTrue(seen and all(x is None for x in seen))
        self.assertIsNone(self.ix.progress())

    def test_snapshot_refreshed_each_scan(self):
        self.assertEqual(self.ix.snapshot(), [])
        self.ix.scan()
        self.assertEqual([e["session_id"] for e in self.ix.snapshot()], ["sn"])

    def test_exception_is_stored_and_next_pass_clears_it(self):
        real, calls = usage.ingest, []
        def flaky(conn, path):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(conn, path)
        import contextlib, io
        with mock.patch.object(usage, "ingest", flaky), contextlib.redirect_stderr(io.StringIO()):
            self.ix.scan()
            self.assertIn("boom", self.ix.error)
            self.assertEqual(len(calls), 3)      # the pass went on to the other files
            self.ix.scan()
        self.assertIsNone(self.ix.error)
        self.assertIsNone(self.ix.progress())

    def test_index_errors_are_logged_once_per_file_and_message(self):
        import contextlib, io
        real, state = usage.ingest, {"n": 0}
        def flaky(conn, path):
            if Path(path).name == "old.jsonl":
                state["n"] += 1
                raise RuntimeError("boom" if state["n"] < 4 else "different")
            return real(conn, path)
        err = io.StringIO()
        with mock.patch.object(usage, "ingest", flaky), contextlib.redirect_stderr(err):
            for _ in range(3):
                self.ix.scan()
            first = err.getvalue()
            self.ix.scan()
        self.assertEqual(first.count("boom"), 1)
        self.assertIn(str(self.old), first)
        self.assertEqual(err.getvalue().count("different"), 1)

    def test_bad_thresholds_warning_is_kept(self):
        bad = self.tmp / "alerts.json"; bad.write_text("{nope")
        ix = usage.Indexer(self.root, self.tmp / "u2.sqlite", alerts_path=bad)
        self.addCleanup(ix.close)
        ix.scan()
        self.assertTrue(ix.warning)

    def test_start_runs_thread_and_stop_ends_it(self):
        self.ix.start(interval=0.05)
        for _ in range(100):
            if self.ix.snapshot():
                break
            time.sleep(0.05)
        self.assertTrue(self.ix.snapshot())
        self.ix.stop()
        self.assertFalse(self.ix.thread.is_alive())

    def test_on_snapshot_gets_live_list(self):
        got = []
        ix = usage.Indexer(self.root, self.tmp / "u3.sqlite", alerts_path=self.tmp / "none.json", on_snapshot=got.append)
        self.addCleanup(ix.close)
        ix.scan()
        self.assertEqual(len(got), 1)
        self.assertEqual([e["session_id"] for e in got[0]], [e["session_id"] for e in ix.snapshot()])

    def test_on_snapshot_error_is_logged_not_fatal(self):
        import contextlib, io
        def boom(live): raise RuntimeError("tmux gone")
        ix = usage.Indexer(self.root, self.tmp / "u4.sqlite", alerts_path=self.tmp / "none.json", on_snapshot=boom)
        self.addCleanup(ix.close)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ix.scan(); ix.scan()
        self.assertEqual(err.getvalue().count("tmux gone"), 1)
        self.assertIsNone(ix.error)
        self.assertTrue(ix.snapshot())


class UsageSumTest(unittest.TestCase):
    def test_root_without_transcripts_exits_2(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, str(HERE.parent / "tools" / "usage-sum.py"), "--repo", "/r", "--root", d],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("no .jsonl", r.stderr)


class CardAlertsTest(unittest.TestCase):
    AL = [{"kind": "context", "label": "ctx 90%", "detail": "d"}]

    def sess(self):
        return {"name": "p", "path": "/r", "windows": [
            {"name": "claude", "teammate": False, "worker": False, "panes": [{"id": "%1", "path": "/r"}]},
            {"name": "\u2726 mate", "teammate": True, "worker": False, "panes": [{"id": "%2", "path": "/r"}]},
            {"name": "w1", "teammate": False, "worker": True, "panes": [{"id": "%3", "path": "/r/.claude/worktrees/w1"}]},
        ]}

    def live(self, **kw):
        e = {"session_id": "x", "name": "n", "agent_name": None, "cwd": "/r", "alerts": self.AL}
        e.update(kw); return e

    def test_teammate_window_matches_agent_name(self):
        s = self.sess(); usage.card_alerts([s], [self.live(agent_name="mate", cwd="/r/.claude/worktrees/elsewhere")])
        self.assertEqual(s["usage_alerts"], {"%2": self.AL})

    def test_worker_pane_matches_cwd(self):
        s = self.sess(); usage.card_alerts([s], [self.live(cwd="/r/.claude/worktrees/w1")])
        self.assertEqual(s["usage_alerts"], {"%3": self.AL})

    def test_teammate_with_same_name_in_another_project_does_not_badge(self):
        a, b = self.sess(), self.sess()
        a["path"] = "/a"; b["path"] = "/b"
        usage.card_alerts([a, b], [self.live(agent_name="mate", cwd="/b/.claude/worktrees/x", alerts=self.AL)])
        self.assertEqual((a["usage_alerts"], a["usage_alert_count"]), ({}, 0))
        self.assertEqual((b["usage_alerts"], b["usage_alert_count"]), ({"%2": self.AL}, 1))

    def test_worker_and_lead_cards_are_scoped_to_their_project(self):
        a = self.sess(); a["path"] = "/a"
        a["windows"][2]["panes"][0]["path"] = "/b/.claude/worktrees/w1"     # a worker pane sitting in another repo's worktree
        usage.card_alerts([a], [self.live(cwd="/b/.claude/worktrees/w1", alerts=self.AL), self.live(cwd="/a", session_id="lead", alerts=[])])
        self.assertEqual(a["usage_alerts"], {})

    def test_worker_pane_ignores_teammate_session_sharing_its_cwd(self):
        s = self.sess(); wt = "/r/.claude/worktrees/w1"
        mate_al = [{"kind": "total", "label": "mate $9", "detail": "d"}]
        usage.card_alerts([s], [self.live(session_id="mate", agent_name="mate", cwd=wt, alerts=mate_al),
                                self.live(session_id="wk", cwd=wt, alerts=self.AL)])
        self.assertEqual(s["usage_alerts"].get("%3"), self.AL)
        s2 = self.sess()
        usage.card_alerts([s2], [self.live(session_id="mate", agent_name="mate", cwd=wt, alerts=mate_al)])
        self.assertNotIn("%3", s2["usage_alerts"])     # only a teammate lives there: the worker card gets no badge

    def test_claude_window_matches_newest_no_agent_session_in_repo(self):
        s = self.sess()
        live = [self.live(session_id="newest-mate", agent_name="mate", alerts=[]),
                self.live(session_id="lead-new", alerts=self.AL), self.live(session_id="lead-old", alerts=[])]
        usage.card_alerts([s], live)
        self.assertEqual(s["usage_alerts"], {"%1": self.AL})

    def test_unmatched_session_has_no_badge_but_counts(self):
        s = self.sess(); usage.card_alerts([s], [self.live(cwd="/r/.claude/worktrees/gone")])
        self.assertEqual(s["usage_alerts"], {})
        self.assertEqual(s["usage_alert_count"], 1)

    def test_no_alerts_and_no_live(self):
        s = self.sess(); usage.card_alerts([s], [])
        self.assertEqual((s["usage_alerts"], s["usage_alert_count"]), ({}, 0))

    def test_other_projects_sessions_do_not_count(self):
        s = self.sess(); usage.card_alerts([s], [self.live(cwd="/other")])
        self.assertEqual(s["usage_alert_count"], 0)


class CardLabelsTest(unittest.TestCase):
    def sess(self):
        return CardAlertsTest.sess(self)

    def live(self, **kw):
        e = {"session_id": "x", "name": "n", "role": "lead", "model": "claude-sonnet-5-5", "effort": "medium",
             "agent_name": None, "cwd": "/r", "alerts": []}
        e.update(kw); return e

    def test_teammate_label(self):
        s = self.sess()
        out = usage.card_labels([s], [self.live(role="teammate", agent_name="mate", model="claude-haiku-5-5", effort="low",
                                                cwd="/r/.claude/worktrees/x")])
        want = {"role": "teammate", "model": "haiku", "effort": "low", "label": "✦ mate · haiku·low"}
        self.assertEqual(s["usage_labels"]["%2"], want)
        self.assertEqual(out["%2"], want)

    def test_lead_label(self):
        s = self.sess(); usage.card_labels([s], [self.live(model="claude-opus-5-5", effort="high")])
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · opus·high")

    def test_worker_label_uses_window_name(self):
        s = self.sess(); usage.card_labels([s], [self.live(role="worker", cwd="/r/.claude/worktrees/w1")])
        self.assertEqual(s["usage_labels"]["%3"]["label"], "w1 · sonnet·med")

    def test_effort_abbreviations(self):
        for eff, ab in [("low", "low"), ("medium", "med"), ("high", "high"), ("max", "max"), ("xhigh", "xhigh")]:
            s = self.sess(); usage.card_labels([s], [self.live(effort=eff)])
            self.assertEqual(s["usage_labels"]["%1"]["effort"], ab, eff)

    def test_no_effort_drops_suffix(self):
        s = self.sess(); usage.card_labels([s], [self.live(effort=None)])
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · sonnet")
        self.assertEqual(s["usage_labels"]["%1"]["effort"], "")

    def test_unmatched_agent_windows_map_to_none(self):
        s = self.sess(); out = usage.card_labels([s], [])
        self.assertEqual(out, {"%1": None, "%2": None, "%3": None})
        self.assertEqual(s["usage_labels"], {})

    def test_non_agent_window_not_returned(self):
        s = self.sess(); s["windows"].append({"name": "shell", "teammate": False, "worker": False, "panes": [{"id": "%4", "path": "/r"}]})
        self.assertNotIn("%4", usage.card_labels([s], [self.live()]))

    def test_same_name_teammate_in_other_project_gets_no_label(self):
        a, b = self.sess(), self.sess(); a["path"] = "/a"; b["path"] = "/b"
        usage.card_labels([a, b], [self.live(role="teammate", agent_name="mate", cwd="/b/.claude/worktrees/x")])
        self.assertNotIn("%2", a["usage_labels"])
        self.assertIn("%2", b["usage_labels"])


class UsageApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.env = {k: os.environ.get(k) for k in ("TC_STATE", "USAGE_ROOT", "TMUX_DASH_TOKEN")}
        os.environ["TC_STATE"] = str(self.tmp / "state"); os.environ["USAGE_ROOT"] = str(self.tmp / "projects")
        os.environ.setdefault("TMUX_DASH_TOKEN", "test-token")
        alerts = mock.patch.object(usage, "ALERTS_PATH", self.tmp / "no-alerts.json"); alerts.start(); self.addCleanup(alerts.stop)   # never read the real ~/.claude file
        spec = importlib.util.spec_from_file_location("tmux_dash_server_usage", HERE / "server.py")
        self.server = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.server)
        self.assertIsNone(self.server.INDEXER)     # importing must not start the indexer
        self.httpd = self.server.ThreadingHTTPServer(("127.0.0.1", 0), self.server.Handler)
        port = self.httpd.server_address[1]
        self.hosts = mock.patch.object(self.server, "ALLOWED_HOSTS", {f"127.0.0.1:{port}"}); self.hosts.start()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True); self.thread.start()
        self.base = f"http://127.0.0.1:{port}/{self.server.TOKEN}"
    def tearDown(self):
        self.httpd.shutdown(); self.httpd.server_close(); self.thread.join(5); self.hosts.stop()
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)
    def get(self, path):
        try:
            with urllib.request.urlopen(f"{self.base}/{path}", timeout=5) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            try:
                return e.code, e.read().decode()
            finally:
                e.close()
    def seed(self):
        src = self.tmp / "p" / "s1.jsonl"; src.parent.mkdir()
        src.write_text(recent_line("a", inp=1_000_000, out=0, cwd="/r"))
        conn = usage.connect(usage.db_path()); usage.ingest(conn, src); conn.close()

    def test_bad_session_name_is_400(self):
        self.assertEqual(self.get("api/usage?session=..bad")[0], 400)

    def test_unknown_session_is_404(self):
        with mock.patch.object(self.server, "state", return_value={"sessions": []}):
            code, body = self.get("api/usage?session=p")
        self.assertEqual((code, json.loads(body)["error"]), (404, "no such session"))

    def test_usage_returns_report_for_session_repo(self):
        self.seed()
        with mock.patch.object(self.server, "state", return_value={"sessions": [{"name": "p", "path": "/r"}]}):
            code, body = self.get("api/usage?session=p")
        d = json.loads(body)
        self.assertEqual(code, 200)
        self.assertAlmostEqual(d["headline"]["month"], 4.0)
        for k in ("alerts", "live", "daily", "by_role", "by_model", "by_branch", "warning", "indexing", "index_error"):
            self.assertIn(k, d)
        self.assertIsNone(d["indexing"])    # no indexer in tests

    def test_usage_other_repo_is_empty(self):
        self.seed()
        with mock.patch.object(self.server, "state", return_value={"sessions": [{"name": "q", "path": "/elsewhere"}]}):
            d = json.loads(self.get("api/usage?session=q")[1])
        self.assertEqual(d["headline"]["month"], 0)

    def test_usage_failure_is_500_and_connection_closed(self):
        conns = []
        real = usage.connect
        def spy(*a, **k):
            c = real(*a, **k); conns.append(c); return c
        with mock.patch.object(self.server, "state", return_value={"sessions": [{"name": "p", "path": "/r"}]}), \
             mock.patch.object(usage, "connect", spy), mock.patch.object(usage, "report", side_effect=RuntimeError("boom")):
            code, body = self.get("api/usage?session=p")
        self.assertEqual((code, json.loads(body)), (500, {"error": "boom"}))
        self.assertEqual(len(conns), 1)
        with self.assertRaises(sqlite3.ProgrammingError):
            conns[0].execute("select 1")

    def test_usage_connect_failure_is_500(self):
        with mock.patch.object(self.server, "state", return_value={"sessions": [{"name": "p", "path": "/r"}]}), \
             mock.patch.object(usage, "connect", side_effect=sqlite3.OperationalError("locked")):
            code, body = self.get("api/usage?session=p")
        self.assertEqual((code, json.loads(body)["error"]), (500, "locked"))

    def test_feed_endpoint_is_gone(self):
        self.assertEqual(self.get("api/feed?session=p")[0], 404)

    def test_build_state_uses_snapshot_not_sqlite(self):
        fake = mock.Mock(); fake.snapshot.return_value = [{"session_id": "x", "name": "n", "agent_name": None, "cwd": "/r",
                                                             "alerts": [{"kind": "context", "label": "l", "detail": "d"}]}]
        S = self.server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", ""])
        with mock.patch.object(self.server, "INDEXER", fake), mock.patch.object(self.server, "tmux", return_value=row), \
             mock.patch.object(self.server, "pane_text", return_value=[]), mock.patch.object(self.server, "cached_worktrees", return_value=[]), \
             mock.patch.object(usage, "connect", side_effect=AssertionError("sqlite on the state path")):
            s = self.server.build_state()["sessions"][0]
        self.assertEqual(s["usage_alerts"], {"%1": fake.snapshot.return_value[0]["alerts"]})
        self.assertEqual(s["usage_alert_count"], 1)


    def label_rows(self, *rows):
        return "\n".join(self.server.SEP.join(r) for r in rows)

    def fake_tmux(self, listing):
        calls = []
        def run(*a, check=False):
            if a[0] == "list-panes":
                return listing
            calls.append(a); return ""
        return run, calls

    LEAD = {"session_id": "x", "role": "lead", "model": "claude-sonnet-5-5", "effort": "medium", "agent_name": None, "cwd": "/r", "alerts": []}

    def test_sync_labels_sets_wanted_label(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""]))
        self.server.sync_labels([self.LEAD], run=run)
        self.assertEqual(calls, [("set-option", "-w", "-t", "%1", "@tc_label", "claude · sonnet·med")])

    def test_sync_labels_writes_only_on_change(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", "claude · sonnet·med"]))
        self.server.sync_labels([self.LEAD], run=run)
        self.assertEqual(calls, [])

    def test_sync_labels_unsets_unmatched_agent_window(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""],
                                                    ["p", "2", "✦ gone", "", "1", "", "%2", "/r", "old label"]))
        self.server.sync_labels([], run=run)
        self.assertEqual(calls, [("set-option", "-wu", "-t", "%2", "@tc_label")])

    def test_sync_labels_leaves_non_agent_and_bg_windows(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""],
                                                    ["p", "2", "shell", "", "", "", "%2", "/r", "x"],
                                                    ["p-bg", "1", "claude", "", "", "1", "%3", "/r", "y"],
                                                    ["_web-1", "1", "claude", "", "", "", "%4", "/r", "z"]))
        self.server.sync_labels([], run=run)
        self.assertEqual(calls, [])

    def test_build_state_carries_usage_labels(self):
        fake = mock.Mock(); fake.snapshot.return_value = [dict(self.LEAD)]
        S = self.server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", ""])
        with mock.patch.object(self.server, "INDEXER", fake), mock.patch.object(self.server, "tmux", return_value=row), \
             mock.patch.object(self.server, "pane_text", return_value=[]), mock.patch.object(self.server, "cached_worktrees", return_value=[]):
            s = self.server.build_state()["sessions"][0]
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · sonnet·med")


if __name__ == "__main__":
    unittest.main()
