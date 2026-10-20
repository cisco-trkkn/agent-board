# Board Usage Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Agent Board's Activity drawer with a Usage | Runs drawer. Usage shows each project's API-equivalent cost, live-agent alerts and breakdowns, all built from an incremental SQLite index of Claude Code transcripts.

**Architecture:** A new `board/usage.py` handles four things. It tails `~/.claude/projects/**/*.jsonl` into `$TC_STATE/usage.sqlite`. It prices calls from `board/prices.json`, which is calibrated against Claude Code's own `cost-state` records. It computes per-project reports and per-live-session alerts. It runs in a server thread that keeps an in-memory snapshot. `board/server.py` serves `api/usage`, puts alert badges on `api/state`, and drops `api/feed`. `board/index.html` renders the Usage tab with hand-built inline SVG.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `json`, `threading`, `unittest`), vanilla JS/HTML/CSS, inline SVG.

**Spec:** `docs/superpowers/specs/2026-10-19-board-usage-dashboard-design.md`

**Where to work:** a git worktree, `.claude/worktrees/usage-dashboard`, on branch `feat/usage-dashboard`. The live install is symlinked to the main checkout, so never edit `~/agent-board` on `main` directly.

## Global Constraints

- Every dollar figure in the UI carries the label "API-equivalent estimate". It is never called a bill or a charge.
- An unknown model has cost `null` and is shown as "unpriced". It never adds $0, and aggregates report `unpriced_calls`.
- A session's headline total is `cost_state.total_usd` when one exists. Time buckets (today, 7d, 30d, last hour, burn, daily chart) always sum per-call costs.
- Project membership: `cwd == repo` or `cwd` starts with `repo + "/.claude/worktrees/"`.
- Role precedence: teammate (`agent_name` set) → subagent (`sidechain` or subagent file) → worker (`/.claude/worktrees/` in cwd) → lead.
- Context per call = `input + cache_read + cache_write_5m + cache_write_1h`. Window size comes from `prices.json`, with 200000 for an unpriced model.
- Live session: its newest call is less than 1800 s old.
- Alert defaults: context ≥ 80 %, burn > $15/h over the last 900 s, session total > $25, and `model_mismatch` (effort in {low, medium}, model contains `opus` or `fable`, `agent_name` set). Thresholds come from `~/.claude/usage-alerts.json`. No ack state.
- `api/state` never touches sqlite on its request path. It reads the indexer's in-memory snapshot.
- Days are local time (`time.localtime`).
- The indexer only reads `~/.claude/projects`, never writes to it. `USAGE_ROOT` overrides the root, and `TC_STATE` places the db.
- Commits are conventional with a scope (`feat(board): …`, `test(board): …`). End each commit with the attribution trailer your harness specifies.
- Python stdlib only. No new dependencies.

**User decisions (already made):**
- Cost unit: API-equivalent dollars, labelled as an estimate.
- Alerts: context nearly full, burn rate, session total, expensive model on cheap work.
- Breakdowns: over time, by agent role, by model, by plan/branch.
- Drawer: Usage first, Runs second. The command feed is dropped.
- Approach: an incremental transcript indexer into SQLite.
- The spec was approved as written on 2026-10-19.

---

## File structure

| File | Responsibility |
| --- | --- |
| `board/prices.json` | Per-model $/MTok rates and context windows (Task 1) |
| `board/tests/fixtures/usage/*.jsonl` | Real captured, content-stripped transcript excerpts (Task 1) |
| `tools/usage-capture-fixture.py` | Captures and strips a real session into a fixture (Task 1) |
| `board/usage.py` | Index store, ingest, pricing, roles (Task 2); reports and alerts (Task 3); indexer thread and snapshot (Task 4) |
| `board/tests/test_usage.py` | Unit tests for usage.py (Tasks 1–4) |
| `board/server.py` | `api/usage`, `usage_alerts` on `api/state`, indexer start, `api/feed` removed (Task 4) |
| `board/activity.py` | `feed()` removed (Task 4) |
| `board/index.html` | Usage \| Runs drawer, Usage tab, SVG charts, card badges (Task 5) |
| `tools/usage-sum.py` | Independent 30-day project total, straight from the jsonl files (Task 6) |

---

### Task 1: Real fixtures and a calibrated price table

**Goal:** Capture real, content-stripped transcript fixtures and produce `board/prices.json`, whose rates reproduce Claude Code's own `cost-state` totals within 1 %.

**Files:**
- Create: `tools/usage-capture-fixture.py`
- Create: `board/tests/fixtures/usage/` (at least 4 `.jsonl` files)
- Create: `board/prices.json`
- Create: `board/tests/test_usage.py` (the calibration test only; Task 2 extends it)

**Acceptance Criteria:**
- [ ] Fixtures cover, at minimum:
  - a lead session with a `cost-state` record;
  - a teammate turn with `agentName`;
  - a subagent file (`…/subagents/agent-*.jsonl`) or an `isSidechain: true` line;
  - one session per model family available on this machine (opus, sonnet, haiku, fable) that has a `cost-state` record.
- [ ] Every fixture line has `message.content` removed and keeps `type`, `requestId`, `timestamp`, `cwd`, `sessionId`, `gitBranch`, `effort`, `isSidechain`, `agentName`, `teamName`, `message.model` and `message.usage`. `cost-state` lines are kept whole. Cwds under `/Users/<name>` are rewritten to `/home/u`.
- [ ] Each fixture's first line is `{"_fixture_source": "<original path>", "_captured": "<date>"}`, and the indexer ignores it as an unknown type.
- [ ] `prices.json` has an entry for every model in the spec's price table, with keys `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h` and `context`.
- [ ] `test_prices_match_cost_state` passes for every fixture session with a `cost-state` record: for each model, the sum of calls (deduped by `requestId`, last line wins) priced with `prices.json` is within 1 % of `modelUsage[model].costUSD`.

**Verify:** `python3 -m unittest board.tests.test_usage -k prices -v` → `OK`

**Steps:**

- [ ] **Step 1: Capture tool.** Write `tools/usage-capture-fixture.py <src.jsonl> <dst.jsonl>`. It reads the source read-only and writes the header line. Then, for each line: keep `cost-state` lines whole; for lines with `message.usage`, keep only the fields listed above; drop every other line; rewrite `/Users/<name>` to `/home/u` in `cwd`.
- [ ] **Step 2: Pick sources.** Find small, complete sessions that have a `cost-state` record, preferring scratchpad sessions under 200 KB. Cover each model family, plus one teammate session (`grep -l '"agentName"'`) and one subagent file. Capture them into `board/tests/fixtures/usage/`. Prices change across model families, so record which source covers which model in the test's docstring.
- [ ] **Step 3: Write the failing calibration test.**

```python
class PricesTest(unittest.TestCase):
    def test_prices_match_cost_state(self):
        prices = json.loads((HERE / "prices.json").read_text())["models"]
        checked = 0
        for fx in sorted(FIX.glob("*.jsonl")):
            calls, cost_state = {}, None
            for line in fx.read_text().splitlines():
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
```

  Start `test_usage.py` with the module header from Task 2 Step 1 (the imports, `HERE`, `FIX` and `import usage`). `usage.row_from_line`, `usage.call_cost` and `usage.norm_model` are defined in Task 2. For this task, add a minimal `board/usage.py` with just these three functions, written exactly as in Task 2 Step 3, so the test can run.
- [ ] **Step 4: Run it and see it fail.** `prices.json` is missing.
- [ ] **Step 5: Calibrate.** Seed `prices.json` from the spec table:

```json
{"default_context": 200000,
 "models": {"claude-opus-5-5": {"input": 4, "output": 20, "cache_read": 0.20, "cache_write_5m": null, "cache_write_1h": null, "context": 1000000}}}
```

  Then fit the unknown rates (`cache_write_5m`, `cache_write_1h`, any missing `cache_read`). Each fixture session gives one linear equation per model, `Σ tokens_k × rate_k / 1e6 = costUSD`. Solve for the unknowns, then round to the nearest cent per MTok. Check whether thinking tokens are already inside `output_tokens`: compare `output_tokens` with `modelUsage.outputTokens + thinkingTokens`. If they are not, report it, because the cost model would need a column. A model with no fixture keeps `input × 1.25` / `input × 2` for the 5m/1h writes and `input × 0.1` for reads, and gets `"_calibrated": false` in its entry. A model with a fixture gets `"_calibrated": true`.
- [ ] **Step 6: Run the test until it passes.** Every checked model is within 1 %.
- [ ] **Step 7: Commit.** `test(board): real usage fixtures and calibrated price table`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/usage-capture-fixture.py", "board/tests/fixtures/usage/", "board/prices.json", "board/tests/test_usage.py", "board/usage.py"], "verifyCommand": "python3 -m unittest board.tests.test_usage -k prices -v", "acceptanceCriteria": ["fixtures cover lead+cost-state, teammate, subagent/sidechain, one session per available model family", "fixture lines content-stripped with header line naming the source", "prices.json has every spec model with 6 keys", "test_prices_match_cost_state passes within 1% for >=3 models"], "modelTier": "standard"}
```

---

### Task 2: Index store and ingest

**Goal:** `board/usage.py` incrementally ingests transcript files into sqlite and handles offsets, truncation, replaced files, partial lines, corrupt lines and duplicate `requestId`s. It also exposes pricing and role helpers.

**Files:**
- Modify: `board/usage.py`
- Modify: `board/tests/test_usage.py`

**Acceptance Criteria:**
- [ ] `connect(path)` creates the `calls`, `cost_state` and `files` tables from the spec, in WAL mode.
- [ ] `ingest(conn, path)` reads from the stored offset, consumes only complete lines, re-reads from 0 when the inode changed or the size shrank, stores a duplicate `requestId` once (last line wins), and counts corrupt lines in `files.bad_lines`.
- [ ] Lines with model `<synthetic>` are skipped.
- [ ] `call_cost` returns `None` for an unknown model. `role()` and `in_project()` follow the Global Constraints.
- [ ] Ingesting every Task 1 fixture gives the same per-session call count as a direct count of unique `requestId`s.

**Verify:** `python3 -m unittest board.tests.test_usage -v` → all pass

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_usage.py`, below the Task 1 test:

```python
import importlib, json, os, shutil, sqlite3, sys, tempfile, time, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
FIX = HERE / "tests" / "fixtures" / "usage"
sys.path.insert(0, str(HERE))
import usage  # noqa: E402

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

    def test_truncated_file_is_reread_without_duplicates(self):
        self.f.write_text(line("a") + line("b"))
        usage.ingest(self.conn, self.f)
        self.f.write_text(line("a"))
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.count(), 2)   # rows are upserted, never deleted

    def test_replaced_file_new_inode_is_reread(self):
        self.f.write_text(line("a"))
        usage.ingest(self.conn, self.f)
        tmp = self.f.with_suffix(".new"); tmp.write_text(line("a") + line("c")); os.replace(tmp, self.f)
        usage.ingest(self.conn, self.f)
        self.assertEqual(self.count(), 2)

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
        for fx in FIX.glob("*.jsonl"):
            usage.ingest(self.conn, fx)
            want = {json.loads(l).get("requestId") for l in fx.read_text().splitlines()
                    if (json.loads(l).get("message") or {}).get("usage") and json.loads(l)["message"].get("model") != "<synthetic>"}
            sid = next(json.loads(l)["sessionId"] for l in fx.read_text().splitlines() if "sessionId" in json.loads(l))
            got = self.conn.execute("select count(*) from calls where session_id=?", (sid,)).fetchone()[0]
            self.assertEqual(got, len(want), fx.name)

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
```

- [ ] **Step 2: Run the tests and see them fail.** `python3 -m unittest board.tests.test_usage -v` fails with `AttributeError: module 'usage' has no attribute 'connect'`.
- [ ] **Step 3: Implement** `board/usage.py`:

```python
"""usage: index Claude Code transcripts into sqlite and report API-equivalent cost per project."""
import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from artifacts import state_dir

HERE = Path(__file__).resolve().parent
SCHEMA = """
create table if not exists calls (request_id text primary key, session_id text, ts real, model text, effort text,
  agent_name text, team_name text, git_branch text, cwd text, sidechain int, subagent_file int,
  input int, output int, cache_read int, cache_write_5m int, cache_write_1h int);
create index if not exists calls_ts on calls(ts);
create index if not exists calls_session on calls(session_id, ts);
create table if not exists cost_state (session_id text primary key, ts real, total_usd real, model_usage text, unknown_model int);
create table if not exists files (path text primary key, inode int, size int, offset int, bad_lines int);
"""


def root():
    return Path(os.environ.get("USAGE_ROOT") or Path.home() / ".claude" / "projects")


def db_path():
    return state_dir() / "usage.sqlite"


def connect(path=None):
    p = Path(path or db_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10, check_same_thread=False)
    conn.execute("pragma journal_mode=wal")
    conn.executescript(SCHEMA)
    return conn


def norm_model(m):
    return re.sub(r"-\d{8}$", "", re.sub(r"\[1m\]$", "", m or ""))


def _epoch(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def row_from_line(d, subagent_file):
    """A usage-bearing assistant line as a calls row (dict), or None."""
    m = d.get("message") or {}
    u = m.get("usage")
    if not u or m.get("model") in (None, "<synthetic>"):
        return None
    cc = u.get("cache_creation") or {}
    w5, w1 = cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")
    if w5 is None and w1 is None:   # no split: count it all as 5m
        w5, w1 = u.get("cache_creation_input_tokens") or 0, 0
    return {"request_id": d.get("requestId"), "session_id": d.get("sessionId"), "ts": _epoch(d.get("timestamp")),
            "model": norm_model(m["model"]), "effort": d.get("effort"), "agent_name": d.get("agentName"),
            "team_name": d.get("teamName"), "git_branch": d.get("gitBranch"), "cwd": d.get("cwd") or "",
            "sidechain": int(bool(d.get("isSidechain"))), "subagent_file": int(bool(subagent_file)),
            "input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
            "cache_read": u.get("cache_read_input_tokens") or 0, "cache_write_5m": w5 or 0, "cache_write_1h": w1 or 0}


COLS = ["request_id", "session_id", "ts", "model", "effort", "agent_name", "team_name", "git_branch", "cwd",
        "sidechain", "subagent_file", "input", "output", "cache_read", "cache_write_5m", "cache_write_1h"]


def ingest(conn, path):
    """Read new complete lines of one transcript file; returns how many usage rows it upserted."""
    p = Path(path)
    st = p.stat()
    prev = conn.execute("select inode, size, offset, bad_lines from files where path=?", (str(p),)).fetchone()
    offset, bad = 0, 0
    if prev and prev[0] == st.st_ino and st.st_size >= prev[2]:
        if st.st_size == prev[1]:
            return 0
        offset, bad = prev[2], prev[3]
    with p.open("rb") as h:
        h.seek(offset)
        data = h.read(st.st_size - offset)
    end = data.rfind(b"\n") + 1
    sub = "/subagents/" in str(p)
    rows, costs, pos = [], [], offset
    for raw in data[:end].splitlines(keepends=True):
        try:
            d = json.loads(raw)
        except ValueError:
            bad += 1
            pos += len(raw)
            continue
        if d.get("type") == "cost-state" and d.get("sessionId"):
            costs.append((d["sessionId"], (d.get("startTime") or 0) / 1000, d.get("totalCostUSD"),
                          json.dumps(d.get("modelUsage") or {}), int(bool(d.get("hasUnknownModelCost")))))
        else:
            r = row_from_line(d, sub)
            if r:
                r["request_id"] = r["request_id"] or f"{r['session_id']}:{pos}"
                rows.append(tuple(r[c] for c in COLS))
        pos += len(raw)
    with conn:
        conn.executemany(f"insert or replace into calls ({','.join(COLS)}) values ({','.join('?' * len(COLS))})", rows)
        conn.executemany("insert or replace into cost_state values (?,?,?,?,?)", costs)
        conn.execute("insert or replace into files values (?,?,?,?,?)", (str(p), st.st_ino, st.st_size, offset + end, bad))
    return len(rows)


def load_prices():
    return json.loads((HERE / "prices.json").read_text())


def call_cost(r, prices):
    p = prices["models"].get(norm_model(r["model"]))
    if not p:
        return None
    return sum(r[k] * (p[k] or 0) for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")) / 1e6


def context_tokens(r):
    return r["input"] + r["cache_read"] + r["cache_write_5m"] + r["cache_write_1h"]


def context_window(model, prices):
    p = prices["models"].get(norm_model(model))
    return p["context"] if p else prices.get("default_context", 200000)


def role(r):
    if r["agent_name"]:
        return "teammate"
    if r["sidechain"] or r["subagent_file"]:
        return "subagent"
    if "/.claude/worktrees/" in (r["cwd"] or ""):
        return "worker"
    return "lead"


def in_project(cwd, repo):
    repo = repo.rstrip("/")
    return cwd == repo or (cwd or "").startswith(repo + "/.claude/worktrees/")
```

  Note: when the size shrank, `ingest` restarts from 0 and resets `bad`. When the size grew but the stored size is unchanged (a partial line is pending), the size check skips the file until it grows.
- [ ] **Step 4: Run the tests until all pass.** `python3 -m unittest board.tests.test_usage -v`
- [ ] **Step 5: Run the full board suite.** `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` must give OK.
- [ ] **Step 6: Commit.** `feat(board): usage index store and incremental transcript ingest`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/usage.py", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest board.tests.test_usage -v", "acceptanceCriteria": ["connect creates calls/cost_state/files tables in WAL", "ingest handles offset, partial line, truncation, new inode, duplicate requestId, corrupt line count", "<synthetic> skipped", "call_cost None for unknown model; role/in_project per constraints", "fixture ingest call counts equal unique requestIds"], "modelTier": "standard"}
```

---

### Task 3: Project report and alerts

**Goal:** `usage.report(conn, repo, prices, th, now)` returns the full `api/usage` payload for one project. `usage.live_sessions(conn, prices, th, now)` returns every live session with its computed alerts.

**Files:**
- Modify: `board/usage.py`
- Modify: `board/tests/test_usage.py`

**Acceptance Criteria:**
- [ ] `thresholds(path)` returns `(dict, warning)`. A missing file gives the defaults and `None`. An unreadable or invalid file gives the defaults and a one-line warning. A partial file overrides only the keys it names.
- [ ] `live_sessions(conn, prices, th, now)` lists sessions whose newest call is less than 1800 s old. Each entry has `session_id`, `name`, `role`, `model`, `effort`, `agent_name`, `cwd`, `context`, `context_pct`, `last_hour`, `total` and `alerts`. `total` is the cost-state total when one exists, else the sum of priced calls.
- [ ] There is one firing test and one clearing test for each of the `context`, `burn`, `total` and `model_mismatch` alerts.
- [ ] `report(conn, repo, prices, th, now)` returns `headline{today, week, month, unpriced_calls}`, `alerts`, `live`, `daily` (30 local-date entries, oldest first, each `{date, by_model}`), `by_role`, `by_model` (with `cache_share`) and `by_branch`. Everything is filtered to the project by `in_project`. The threshold-file `warning` is added by the server (Task 4), not by `report`.
- [ ] A call more than 30 days old is excluded from `month`, `daily` and the breakdowns. A call from yesterday is excluded from `today` but included in `week`.

**Verify:** `python3 -m unittest board.tests.test_usage -v` → all pass

**Steps:**

- [ ] **Step 1: Write failing tests.** Use a fixed `now`, built as `time.mktime((2026,10,19,12,0,0,0,0,-1))`, and the `line()` helper from Task 2 with a `ts` argument built from `datetime.fromtimestamp(now - delta, timezone.utc).isoformat().replace("+00:00","Z")`. Cover:
  - `test_thresholds_missing_defaults`, `test_thresholds_partial_override`, `test_thresholds_invalid_warns`;
  - `test_live_excludes_older_than_30min`;
  - `test_alert_context_fires` (input 850000 on a 1M-window model) and `test_alert_context_clears` (input 100);
  - `test_alert_burn_fires`: calls in the last 900 s totalling > $3.75, so > $15/h;
  - `test_alert_burn_clears`: the same spend 20 minutes ago is outside the window;
  - `test_alert_total_fires_from_cost_state` (cost_state 30.0) and `test_alert_total_clears`;
  - `test_alert_mismatch_fires`: opus, effort low, agent set;
  - `test_alert_mismatch_clears_without_agent`, and a second clearing case on sonnet;
  - `test_report_project_filter`: a call in `/other` is excluded and one in `/r/.claude/worktrees/w` is included;
  - `test_report_time_buckets`: today, yesterday and 40 days ago;
  - `test_report_unpriced_counted`;
  - `test_report_daily_has_30_days_oldest_first`;
  - `test_report_by_model_cache_share`: `cache_read / (input + cache_read + cache_write_5m + cache_write_1h)`;
  - `test_report_by_branch_falls_back_to_worktree_dir`: an empty `git_branch` with cwd `/r/.claude/worktrees/w` gives key `w`.
- [ ] **Step 2: Run the tests and see them fail.** `report` and `live_sessions` don't exist yet.
- [ ] **Step 3: Implement.** Write `DEFAULT_ALERTS = {"context_pct": 80, "burn_per_hour": 15, "burn_window_s": 900, "session_total": 25, "mismatch_efforts": ["low", "medium"], "mismatch_models": ["opus", "fable"], "live_s": 1800}` and `ALERTS_PATH = Path.home() / ".claude" / "usage-alerts.json"`. Read rows with `conn.row_factory = sqlite3.Row` and convert them to dicts so `call_cost`, `role` and `context_tokens` apply unchanged.
  - **Project filter, in SQL:** `where ts >= ? and (cwd = ? or substr(cwd, 1, ?) = ?)`, with the prefix `repo + "/.claude/worktrees/"`. Don't use LIKE, because `_` is a wildcard.
  - **Live sessions:** `select session_id, max(ts) from calls where ts >= now - live_s group by session_id`. Then fetch the newest row of each live session, plus all of its rows from the last hour and the last `burn_window_s`.
  - **`name`:** `agent_name`, else the last path component of `cwd` for a worker, else `session_id[:8]`.
  - **Alert dicts:** each is `{"kind", "label", "detail"}`. Labels are `ctx 84%`, `$22/h`, `$31 total` and `opus@low`. The detail is one sentence that names the threshold.
  - **`report()`:** `report()["alerts"]` is the concatenation of the alerts of live sessions in the project. Each one adds `session` (the name) to its dict.
  - **Headline windows:** `today` starts at local midnight of `now`; `week` starts at local midnight six days earlier; `month` starts at local midnight 29 days earlier (30 days including today).
- [ ] **Step 4: Run the tests until all pass.** Then run the full board suite through `tmux-ctl run tests "python3 -m unittest discover -s board/tests"`.
- [ ] **Step 5: Commit.** `feat(board): usage report and live-session alerts`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/usage.py", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest board.tests.test_usage -v", "acceptanceCriteria": ["thresholds: missing->defaults, partial override, invalid->defaults+warning", "live_sessions: <1800s, fields per spec, total prefers cost_state", "fire+clear test for each of context/burn/total/model_mismatch", "report payload keys per spec, project-filtered", "time buckets: today/week/month boundaries tested"], "modelTier": "standard"}
```

---

### Task 4: Indexer thread, API and badges in `api/state`

**Goal:** The board server runs the indexer in a background thread, serves `api/usage?session=<p>`, adds `usage_alerts` and `usage_alert_count` to each session in `api/state` from an in-memory snapshot, and drops `api/feed` and `activity.feed()`.

**Files:**
- Modify: `board/usage.py` (add the `Indexer` class)
- Modify: `board/server.py`
- Modify: `board/activity.py` (remove `feed()` and its helpers that nothing else uses)
- Modify: `board/tests/test_activity.py` (remove the feed tests)
- Modify: `board/tests/test_usage.py`

**Acceptance Criteria:**
- [ ] `Indexer(root, db).scan()` ingests files newest-mtime first. `progress()` returns `{done, total}` in bytes, and `done == total` after a full pass. Each scan refreshes `snapshot()`, a list from `live_sessions`. An exception inside a pass is caught and stored as `error`, and the next pass still runs.
- [ ] `Indexer.start()` runs a daemon thread that scans every 5 s. It is started only under `if __name__ == "__main__"`, never on import, so tests don't index the real home.
- [ ] `GET api/usage?session=<p>` returns 400 for a bad name. Otherwise it returns `report(...)` for the session's repo path from `state()`, plus `indexing` and `index_error`. The handler opens its own sqlite connection per request (read-only use).
- [ ] `card_alerts(sessions, live)` attaches alerts to panes using the spec's three matching rules: teammate window name `✦ <n>` against `agent_name`, worker pane path against `cwd`, and the `claude` window against the newest no-agent session with `cwd == repo`. It sets `s["usage_alerts"] = {pane_id: [alerts]}` and `s["usage_alert_count"]`. There is one test per matching rule, plus one for an unmatched session.
- [ ] `build_state()` calls `card_alerts` with `INDEXER.snapshot()`, or `[]` when there's no indexer. No sqlite call happens on the `api/state` path.
- [ ] `api/feed` returns 404. `python3 -m unittest discover -s board/tests` passes.

**Verify:** `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` → `OK`

**Steps:**

- [ ] **Step 1: Write failing tests.**
  - **Indexer:** use a temp root with two fixture copies. Check that `scan()` gives `progress()["done"] == progress()["total"] > 0`. Patch `usage.ingest` to raise once and check that `error` is set and the next `scan()` clears it.
  - **`card_alerts`:** build session dicts shaped like `build_state()` output, with `windows[].name`, `teammate`, `worker` and `panes[].id/path`, and a `path`. Add a hand-built `live` list.
  - **Server:** load it the way `test_activity.py` does, with `os.environ["USAGE_ROOT"]` and `TC_STATE` pointing at temp dirs. Start a `ThreadingHTTPServer` on port 0 in a thread. `GET /<token>/api/usage?session=..bad` returns 400. With `server.state` patched to return one session whose `path` is the fixture repo cwd, `GET api/usage?session=p` returns 200 with a `headline` key. `GET api/feed` returns 404.
- [ ] **Step 2: Run them and see them fail.**
- [ ] **Step 3: Implement.**
  - **`usage.Indexer`:** add a `threading.Lock` around `_snapshot`. The first pass sorts by mtime, descending. Later passes iterate all files, and `ingest` skips unchanged ones cheaply through the stat check. The file list is `root.glob("*/*.jsonl")` plus `root.glob("*/*/subagents/*.jsonl")`.
  - **`server.py`:** add `INDEXER = None` at module level. In `__main__`, set `INDEXER = usage.Indexer(usage.root(), usage.db_path()); INDEXER.start()` before `serve_forever`. In the `api/usage` handler, use `project_arg(q)` and look up the session's `path` in `state()["sessions"]`; an unknown session gives 404 `{"error": "no such session"}`. Then run `th, warn = usage.thresholds(); r = usage.report(conn, path, usage.load_prices(), th, time.time())` and respond with `{**r, "warning": warn, "indexing": INDEXER.progress() if INDEXER else None, "index_error": INDEXER.error if INDEXER else None}`. Close the connection in `finally`. `Indexer.scan()` loads prices and thresholds at the start of each pass and passes them to `live_sessions`.
- [ ] **Step 4: Remove the feed.** Delete the `api/feed` branch, `activity.feed`, and any helper only `feed` used. Delete the three `test_feed_*` tests. Grep `bin/` and `tools/` for `api/feed` (none expected) and report the result.
- [ ] **Step 5: Run the full board suite and the tmux suite until both pass.** Use `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` and `tmux-ctl run tests "zsh tools/tests/run-all.zsh"`.
- [ ] **Step 6: Commit.** `feat(board): usage indexer thread, api/usage and alert badges; drop the command feed`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/usage.py", "board/server.py", "board/activity.py", "board/tests/test_activity.py", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["Indexer scan newest-first, progress done==total, snapshot refreshed, error caught and cleared", "thread started only in __main__", "api/usage 400 bad name, 404 unknown session, 200 report", "card_alerts: one test per matching rule + unmatched", "api/state uses snapshot only, no sqlite on request path", "api/feed 404, feed code and tests removed, both suites pass"], "modelTier": "standard"}
```

---

### Task 5: Usage | Runs drawer UI

**Goal:** In `board/index.html`, the Activity drawer becomes **Usage | Runs**, with Usage as the default. The Usage tab renders the headline, alerts, live sessions, a 30-day stacked chart and three sortable breakdowns. Agent cards show alert badges, and the closed drawer toggle shows "N alerts".

**Files:**
- Modify: `board/index.html`

**Acceptance Criteria:**
- [ ] The drawer tabs are `Usage` and `Runs`. The "Commands" tab, the `#act-agent` select, `#act-cmds` and `renderCmds` are gone. The chosen tab is saved in `localStorage["dash.actTab"]`, with reads and writes wrapped in try/catch. The default is `usage`. The jump nav link still says "Activity".
- [ ] The closed-drawer toggle shows `N alert(s)` from `usage_alert_count` of the current session in `api/state`, next to the existing failed-runs count.
- [ ] An agent card whose pane id is in `usage_alerts` shows one badge per alert: the `label` text, with `detail` as its `title`. Context and burn badges use amber; total and model-mismatch badges use red.
- [ ] Usage tab, in order:
  1. The headline, with today, 7 days and 30 days in `$` (2 decimals), the caption "API-equivalent estimate", and "N unpriced calls" when non-zero.
  2. The alerts list, plus the threshold-file `warning` if one is present.
  3. The live sessions table: name, role, model, effort, a context % bar (amber at the threshold or above), $ for the last hour and $ total.
  4. The 30-day SVG chart: daily bars stacked by model, with a legend, a y-axis in $, and a hover `title` per segment giving the date, model and $.
  5. The by-role, by-model (with a cache-share %) and by-branch tables. Clicking a column header sorts by it.
- [ ] While `indexing.done < indexing.total`, the tab shows "indexing… N%" above the figures computed so far. If `index_error` is present, it shows as one muted line.
- [ ] `api/usage` is fetched only while the drawer is open with the Usage tab selected. The DOM is rebuilt only when the payload signature changes, so sort order and scroll survive polls. The chart reads correctly in light and dark themes, using the colour tokens in `:root` and its dark override, with no hard-coded hex outside them. Series colours come from new `--series-1…6` tokens defined for both themes.

**Verify:** a live check against a scratch board on port 7713 (Task 6 does the full e2e). For this task: `python3 -m unittest discover -s board/tests` → OK, plus screenshots of the Usage tab in both themes attached to the report.

**Steps:**

- [ ] **Step 1: Load the `dataviz` skill.** Choose the series palette and the chart marks with it. Then define `--series-1…6` in `:root` and in the dark-theme override.
- [ ] **Step 2: Markup.** Replace the drawer's nav with `<nav class="tabs"><button data-tab="usage">Usage</button><button data-tab="runs">Runs</button></nav>`, and the bodies with `<div id="act-usage"></div><div id="act-runs" hidden></div>`. Rename the toggle's count span to hold both counts: `<span class="fails" id="act-fails"></span> <span class="alerts" id="act-alerts"></span>`.
- [ ] **Step 3: JS.**
  - Change the `ACT.tab` default to the stored value, or `"usage"`.
  - `pollActivity()` keeps the runs logic unchanged, and when `ACT.tab === "usage"` it calls a new `renderUsage(s)` instead of `renderCmds`.
  - `renderUsage` fetches `api/usage?session=…`, computes `sig = JSON.stringify(payload)`, and returns early if it is unchanged.
  - Build the parts with the existing `el()` helper: `usageHeadline(d)`, `usageAlerts(d)`, `usageLive(d)`, `usageChart(d.daily)` (SVG built with `document.createElementNS`) and `sortableTable(rows, cols, key)`, which keeps its sort key in `ACT.sort[key]`.
  - In `refresh()`, after the state is fetched, set `#act-alerts` text from `s.usage_alert_count`. In `card()`, append the badges from `s.usage_alerts?.[p.id]`.
- [ ] **Step 4: CSS** for `.usage-head`, `.ctx-bar`, `.alert-badge.amber/.red` and the table headers (`cursor: pointer`), using the existing tokens.
- [ ] **Step 5: Live look.**
  1. Start a scratch board. Set `TMUX_DASH_TMUX_ARGS='-L ub -f /dev/null'`, `TC_STATE=$(mktemp -d)` and `TC_IDEAS_DIR=$(mktemp -d)`. Leave `USAGE_ROOT` unset, so it indexes the real `~/.claude/projects` read-only.
  2. Run it on `TMUX_DASH_PORT=7713` with `tmux-ctl send`.
  3. Open it in Chrome in a new tab and override `window.confirm`.
  4. Check both themes and take screenshots.
  5. Stop the scratch board by PID, and kill the scratch tmux server with `tmux -L ub kill-server`.
- [ ] **Step 6: Run the board suite.** `tmux-ctl run tests "python3 -m unittest discover -s board/tests"` → OK.
- [ ] **Step 7: Commit.** `feat(board): Usage | Runs drawer with cost headline, alerts, live sessions and 30-day chart`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["tabs Usage|Runs, Commands/feed UI removed, tab persisted in localStorage with try/catch", "closed toggle shows N alerts from api/state", "card badges per alert with detail title, amber/red", "Usage tab sections in spec order with API-equivalent estimate label", "indexing N% and index_error shown", "fetch only when open+usage tab, sig-guarded rebuild, theme tokens incl --series-1..6 in both themes"], "modelTier": "standard"}
```

---

### Task 6: Live read-only e2e against real transcripts

**Goal:** Prove, against the user's real long-lived `~/.claude/projects` (read-only), that the Usage tab's 30-day total for `agent-board` equals an independent sum. Every probe must be able to fail.

**Files:**
- Create: `tools/usage-sum.py`

**Acceptance Criteria:**
- [ ] `tools/usage-sum.py --repo <path> --days 30` never imports `board/usage.py`. It does its own parsing: dedupe by `requestId` (last line wins), apply the project filter, compute local-midnight windows, and load `board/prices.json` for rates. It prints `month=<dollars to 2dp> calls=<n> unpriced=<n>`.
- [ ] **Negative control 1:** `tools/usage-sum.py --repo /nonexistent` prints `month=0.00 calls=0`. This shows the filter can exclude rows.
- [ ] **Negative control 2:** the comparison step, run with a deliberately wrong expected value (the real one + $1), exits non-zero. This shows the comparison can fail.
- [ ] A scratch board on port 7713 (scratch `TC_STATE`, scratch tmux socket, real `~/.claude/projects`) finishes indexing (`indexing.done == indexing.total`). Its `api/usage?session=agent-board` `headline.month` matches `usage-sum.py` within $0.01. If live sessions write during the check, there is a tolerance of one burst: re-run both within 10 s.
- [ ] The value shown in the Usage tab's DOM, read through Chrome from the 30-day headline element, equals `headline.month` formatted to 2 dp.
- [ ] The real state is aged. The check reports `daily` entries spanning at least 3 distinct dates with non-zero spend, and at least 2 roles in `by_role`. If either is missing, the report says so; it is not a silent pass.
- [ ] The scratch board and scratch tmux server are stopped afterwards. `~/.claude/projects` mtimes are unchanged by the check (compare `find ~/.claude/projects -newer <marker> -name '*.jsonl' | wc -l` with the files the live sessions wrote).

**Verify:** `python3 tools/usage-sum.py --repo ~/agent-board --days 30` and the `api/usage` `headline.month` agree within $0.01. Both negative controls behave as stated. Report the exact numbers.

**Steps:**

- [ ] **Step 1:** Write `tools/usage-sum.py`, independent of `board/usage.py`. Run both negative controls and record their output.
- [ ] **Step 2:** Start the scratch board as in Task 5 Step 5. Poll `api/usage` until indexing completes, then record `headline.month`, the `daily` dates and `by_role`.
- [ ] **Step 3:** Run `usage-sum.py` immediately afterwards and compare the two totals.
- [ ] **Step 4:** Use Chrome (new tab, `window.confirm` overridden) to read the 30-day headline text from the DOM. Compare it with the API value.
- [ ] **Step 5:** Stop the scratch board by PID and kill the scratch tmux server. Report every number, every command and its output.
- [ ] **Step 6: Commit.** `test(board): independent usage sum for the live e2e check`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["tools/usage-sum.py"], "verifyCommand": "python3 tools/usage-sum.py --repo ~/agent-board --days 30", "acceptanceCriteria": ["usage-sum.py independent of board/usage.py, prints month/calls/unpriced", "negative control: nonexistent repo gives 0", "negative control: wrong expected value exits non-zero", "api headline.month == usage-sum within $0.01 after indexing completes", "DOM 30-day value == api value", "aged real state: >=3 dates with spend, >=2 roles, reported", "scratch board and tmux server stopped; ~/.claude/projects untouched"], "modelTier": "standard"}
```
