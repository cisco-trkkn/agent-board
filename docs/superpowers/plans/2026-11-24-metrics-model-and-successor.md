# Metrics: a model on every task record, and a fast successor() Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

```json:manifest
{"spec": "docs/superpowers/specs/2026-11-23-metrics-model-and-successor-design.md",
 "base": "0af42b5b388826b46ecd25063192c9d2f558f87d",
 "depends_on": [],
 "writes": [
  {"path": "board/metrics_lead.py", "mode": "modify"},
  {"path": "board/tests/test_metrics_lead.py", "mode": "modify"},
  {"path": "board/metrics_tasks.py", "mode": "modify"},
  {"path": "board/tests/test_metrics_tasks.py", "mode": "modify"},
  {"path": "board/metrics.py", "mode": "modify"},
  {"path": "board/tests/test_metrics_tasks_log.py", "mode": "modify"},
  {"path": "board/metrics_analyze.py", "mode": "modify"},
  {"path": "board/metrics_recommend.py", "mode": "modify"},
  {"path": "board/analytics_post.py", "mode": "modify"},
  {"path": "board/tests/test_metrics_analyze.py", "mode": "modify"},
  {"path": "board/tests/test_metrics_recommend.py", "mode": "modify"},
  {"path": "claude/skills/subagent-driven-development-extras/SKILL.md", "mode": "modify"},
  {"path": "docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md", "mode": "create"}
 ],
 "reads": ["board/tc_env.py", "board/usage.py", "board/ctxsize.py", "claude/hooks/spawn-record.sh",
           "docs/superpowers/metrics/tasks.jsonl", "docs/superpowers/metrics/runs.jsonl",
           "docs/superpowers/ledgers/2026-11-16-discord-replaces-telegram/progress.md",
           "docs/superpowers/ledgers/2026-11-19-discord-ideas-command/progress.md",
           "docs/superpowers/ledgers/2026-11-24-pcee-engine-part-2/progress.md"],
 "produces": ["metrics_lead.lead_session_ids", "metrics_tasks model_source", "metrics.spawns_path"],
 "consumes": ["spawns.jsonl rows of claude/hooks/spawn-record.sh"],
 "tests": ["board/tests/test_metrics_lead.py", "board/tests/test_metrics_tasks.py", "board/tests/test_metrics_tasks_log.py",
           "board/tests/test_metrics_analyze.py", "board/tests/test_metrics_recommend.py"]}
```

**Goal:** Every per-task metrics record names its model and where the model came from (`model_source`), and `metrics_lead.successor()` stops re-reading every transcript head on every call.

**Architecture:** `metrics_lead.successor()` gets a per-process cache: per transcript dir, a map path → (mtime_ns, size, PHRASE-bearing head lines, first timestamp), refreshed for changed files, plus a result cache keyed `(tdir, doc basename, old_session_id)` and invalidated by the dir's signature. `metrics_tasks.build_task_lines` resolves `model_used` in the order usage → spawn → ledger → none, taking spawn rows and lead session ids as new keyword arguments; `metrics.task_lines_for_run` reads `spawns.jsonl` and the lead lineage and passes them in. `backfill-tasks` re-derives the model of records that have no `model_source`. The analysis groups `model_source == "none"` as `nomodel`, and the weekly text names it "no model recorded".

**Tech Stack:** Python 3 standard library, `unittest`.

**Spec:** docs/superpowers/specs/2026-11-23-metrics-model-and-successor-design.md

## Global Constraints

- `model_source` is one of `"usage"`, `"spawn"`, `"ledger"`, `"none"`. `model_used` is the full model id when the source is `usage`, the alias as written (`sonnet`, `haiku`, `opus`, `fable`) for `spawn` and `ledger`, `None` for `none`.
- A spawn row or ledger model counts as a hit only when `metrics_tasks.family(model)` is not `None`: `inherit`, a missing model and anything else `family()` cannot map fall through to the next source.
- `successor()` returns the same path or `None` as the code at base `0af42b5` for every input in the tests (a cache-free copy of the base code is the test's reference).
- `metrics_lead` keeps importing only `ctxsize` and the standard library, and never raises.
- Every test sets `TC_STATE` to a temp dir and never reads the real `~/.local/state/agent-board/spawns.jsonl`: tests that reach `task_lines_for_run` also pop `AGENT_BOARD_SPAWNS` from the environment.
- Readers that take the last line per (batch, spec, task_id) stay unchanged; `tasks.jsonl` stays append-only.
- Board suite gotchas (shared context): never edit a `board/*.py` file while a board suite runs; read a suite's exit code directly, never through `| tail`.
- Commit steps end with the attribution trailer your harness specifies.

**User decisions (already made):** the spec was approved on Discord 2026-11-23 (G-Q1 1, design "Ok"). The 15 s backfill target is measured once in the run and noted in the final report, not asserted in a test.

**Assumptions (planner, unreviewed by the user):**

- A1. "The task's first activity" for the spawn step: the spawn step only runs when the task has no usage rows (usage would have won), so there is no first-row time. The upper bound is the task's end as `build_task_lines` already computes it (`end_of(n)`: commit time of the task's last commit range end, else the run end, else no bound). The lower bound is the run's start (`run_start`), because teammate names (`impl1`, `w1`) repeat across runs.
- A2. The `DISPATCH` regex also accepts `(<tier>/<model>…)`: the real ledgers hold 17 `(standard/sonnet)` dispatch lines next to 31 `(standard, sonnet)` ones (pcee-engine-part-2 uses the slash form).
- A3. The pre-filter tests `PHRASE` against the raw line text. For a transcript with at least one PHRASE line, the first timestamp is found by parsing head lines in order until the first that carries one (the base code takes the first timestamp over the whole head, so it cannot come from PHRASE lines alone). The "never JSON-parsed" test is therefore stated for transcripts without a PHRASE line. A phrase split across two content blocks (found only by the base code's `" ".join` of blocks) is not matched; no real transcript has one, and the parity test covers string and block content.
- A4. Re-derivation in `backfill-tasks` changes only `model_used` and `model_source` of an existing record: a record whose `model_used` is set keeps it with `model_source: "usage"`, one without takes the rebuilt line's model. The rest of the old line is kept, because usage rows of old runs may have been pruned since and a full rebuild would erase their tokens.
- A5. The report line names tasks as `<spec slug>#<task_id>` (the `_spec_slug` form, e.g. `metrics-model-and-successor#3`), sorted, since a batch holds several specs.
- A6. The `backfill-tasks`, report and spawn-wiring tests go in `board/tests/test_metrics_tasks_log.py`, which already holds the scratch repo and CLI harness for `record` and `backfill-tasks`; the spec's list names `test_metrics_tasks.py` for them.
- A7. `spawns.jsonl` path: `$AGENT_BOARD_SPAWNS`, else `tc_env.agent_base() / "spawns.jsonl"` (`$TC_STATE`, else `$HOME/.local/state/agent-board`): the hook's default, and inside `TC_STATE` for tests.

Probes (planner, 2026-11-24): one `successor()` call on the real transcript dir (671 transcripts) at base took 4.63 s (load average 5.53); this plan's Tasks 1-3 code ran the whole-lineage `lead_fields` in 9.22 s with 138 `successor()` calls (load average 4.76). The plan's code for Tasks 1-4 passed `test_metrics_*.py`, `test_analytics_post.py` and every named mutation in a scratch clone; `test_metrics_backfill.RealStateTest` fails in a plain clone on base code too (it needs the main checkout's worktree layout) and passes in this worktree.

---

### Task 1: A cached successor() and lead_session_ids()

**Goal:** `successor()` reads each transcript head once per process (refreshed when its mtime or size changes), JSON-parses only lines whose raw text holds `PHRASE`, answers repeated lookups from a result cache, and returns the same results as before; `lead_session_ids()` exposes the spec's lead session ids.

**Files:**
- Modify: `board/metrics_lead.py` (`successor`, new `_open`, `_loads`, `_HEADS`, `_RESULTS`, `cache_clear`, `_head_entry`, `lead_session_ids`)
- Test: `board/tests/test_metrics_lead.py`

**Acceptance Criteria:**
- [ ] A parity test runs the cached `successor()` and a cache-free reference (the base code copied into the test) over one fixture dir and at least 6 lineage lines (teammate, phraseless, own session excluded, earliest wins, content blocks, no doc), then changes one transcript (new content and mtime) and compares again: equal every time.
- [ ] Repeated calls (3 different lines, each called twice) open each transcript file exactly once, counted through the `ml._open` seam; after `os.utime` plus a rewrite of one file, the next call opens only that file.
- [ ] Over a dir of transcripts with no PHRASE line, `ml._loads` is never called on any line (counted through the seam); mutation: drop the raw pre-filter → this test fails.
- [ ] A deleted transcript drops out of the result (signature change invalidates the result cache): mutation: key the result cache without the signature → the deletion test fails.
- [ ] `lead_session_ids(tdir, lineage_file, lo, hi)` returns the session ids (file names without `.jsonl`) of `_lead_sessions`, and `set()` on any error.
- [ ] Every existing test in `test_metrics_lead.py` passes unchanged.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_lead.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `board/tests/test_metrics_lead.py`, add `ml.cache_clear()` as the first line of `Base.setUp`, and add after `TestSuccessor`:

```python
import glob as _glob

from datetime import datetime as _dt


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
```

Add `import unittest.mock` to the imports.

- [ ] **Step 2: Run to see them fail.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_lead.py'`. Expected: errors `module 'metrics_lead' has no attribute 'cache_clear'` (setUp), so every test in the file errors. Comment out the `cache_clear()` line for one run to see `TestSuccessorCache` fail on `_open`/`_loads` attributes and `TestLeadSessionIds` on `lead_session_ids`; restore it.

- [ ] **Step 3: Implement.** In `board/metrics_lead.py`, replace `successor` with:

```python
_open = open          # seam: tests count file opens
_loads = json.loads   # seam: tests count JSON parses
_HEADS = {}           # tdir -> {path: ((mtime_ns, size), phrase_dicts, first_epoch)}
_RESULTS = {}         # (tdir, doc basename, old session id) -> (dir signature, path or None)
_PHRASE_B = PHRASE.encode()


def cache_clear():
    _HEADS.clear()
    _RESULTS.clear()


def _head_entry(p):
    """(phrase_dicts, first_epoch) of a transcript head. Only lines whose raw bytes hold PHRASE are parsed for
    matching; the first epoch (base rule: first timestamp of any head line) is read only when such a line exists."""
    raws = []
    try:
        with _open(p, "rb") as f:
            for i, raw in enumerate(f):
                if i >= HEAD_LINES:
                    break
                raws.append(raw)
    except OSError:
        return [], float("inf")

    def parse(raw):
        try:
            d = _loads(raw.decode("utf-8", "replace"))
        except (ValueError, RecursionError):
            return None
        return d if isinstance(d, dict) else None
    hits = [d for d in (parse(r) for r in raws if _PHRASE_B in r) if d is not None]
    if not hits:
        return [], float("inf")
    first = float("inf")
    for raw in raws:
        d = parse(raw)
        e = ctxsize._epoch(d.get("timestamp")) if d is not None else None
        if e is not None:
            first = e
            break
    return hits, first


def _heads(tdir):
    """The dir's cached heads, refreshed for new or changed files, removed files dropped. Returns (heads, signature)."""
    cache = _HEADS.setdefault(tdir, {})
    seen, sig = set(), []
    for p in sorted(glob.glob(os.path.join(glob.escape(tdir), "*.jsonl"))):
        try:
            st = os.stat(p)
        except OSError:
            continue
        key = (st.st_mtime_ns, st.st_size)
        seen.add(p)
        sig.append((p, key))
        if p not in cache or cache[p][0] != key:
            hits, first = _head_entry(p)
            cache[p] = (key, hits, first)
    for p in [p for p in cache if p not in seen]:
        del cache[p]
    return cache, tuple(sig)


def successor(tdir, line):
    """Path of the line's successor transcript, or None (Metric definitions: successor)."""
    try:
        base = os.path.basename(str(line.get("doc") or ""))
        old = str(line.get("old_session_id") or "")
        if not base:
            return None
        tdir = str(tdir)
        heads, sig = _heads(tdir)
        rkey = (tdir, base, old)
        got = _RESULTS.get(rkey)
        if got and got[0] == sig:
            return got[1]
        best = None
        for p in sorted(heads):
            if os.path.basename(p)[:-6] == old:
                continue
            _, hits, first = heads[p]
            if not any(d.get("type") == "user" and "agentName" not in d and base in (t := _text(d)) and PHRASE in t
                       for d in hits):
                continue
            if best is None or first < best[0]:
                best = (first, p)
        out = best[1] if best else None
        _RESULTS[rkey] = (sig, out)
        return out
    except Exception:
        return None
```

and after `_lead_sessions` add:

```python
def lead_session_ids(tdir, lineage_file, lo, hi):
    """Session ids of the lead sessions of [lo, hi] (old sessions and successors of the lineage lines); set() on error."""
    try:
        return {os.path.basename(p)[:-6] for p in _lead_sessions(str(tdir), lineage(lineage_file), float(lo), float(hi))}
    except Exception:
        return set()
```

Note: `lineage(None)` must not raise out of `lead_session_ids`: the `try` covers it.

- [ ] **Step 4: Run the mutations** named in the tests (drop `if _PHRASE_B in r`; key `_RESULTS` without comparing `sig`), confirm the named test fails each time, restore.

- [ ] **Step 5: Run to see them pass.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_lead.py'`. Expected: `OK`.

- [ ] **Step 6: Commit.** `git add board/metrics_lead.py board/tests/test_metrics_lead.py && git commit -m "perf(metrics): cache successor() heads and results; lead_session_ids" -- board/metrics_lead.py board/tests/test_metrics_lead.py`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/metrics_lead.py", "board/tests/test_metrics_lead.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_lead.py'", "modelTier": "standard"}
```

---

### Task 2: model_used resolution and model_source in metrics_tasks

**Goal:** `build_task_lines` sets `model_used` from usage rows, else the newest matching spawn row, else the ledger's last dispatch model, and records which in `model_source`; `DISPATCH` reads the `(<tier>, <model>)` and `(<tier>/<model>)` forms.

**Files:**
- Modify: `board/metrics_tasks.py` (`DISPATCH`, `KEYS`, `build_task_lines`, new `_spawn_model`, `_ledger_model`)
- Modify: `board/tests/test_metrics_tasks_log.py` (the `KEYS` set gains `model_source`)
- Test: `board/tests/test_metrics_tasks.py`

**Acceptance Criteria:**
- [ ] `parse_ledger` gives `dispatch_models == ["sonnet"]` for each verbatim real line: `Task 1: dispatched id-core (standard, sonnet), BASE f428acb` (ledger 2026-11-19-discord-ideas-command), `Task 1: dispatched impl1 (standard/sonnet), BASE 83daf99` (ledger 2026-11-24-pcee-engine-part-2), `Task 1: dispatched dc-launch (sonnet, base 22b8f60)`; and `[]` for `Task 1: dispatched w9 (standard)`. Mutation: restore the base regex → the first two fail.
- [ ] With usage rows: `model_source == "usage"`, `model_used` the full id (existing behaviour).
- [ ] No rows, a spawn row for the last owner inside `[run_start, task end]`: `model_source == "spawn"`, `model_used` the alias. A spawn row after the task's end, one before `run_start`, and one with model `inherit` are each ignored (each mutation of the matching bound → its test fails).
- [ ] Two in-window spawn rows: the one whose `lead_session` is in `lead_sessions` wins over a newer one from another session; without `lead_sessions` the newer wins.
- [ ] No rows, no spawn hit, a ledger model: `model_source == "ledger"`, `model_used == "sonnet"`.
- [ ] All three miss: `model_used is None`, `model_source == "none"`.
- [ ] `KEYS` holds `model_source` and every line has exactly `KEYS` (`test_keys_exact` and the `test_metrics_tasks_log.py` key test both pass once each gains the key).
- [ ] `test_no_rows_partial` asserts `("sonnet", "ledger")` instead of `None` (the only existing assertion this task changes besides the key lists).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks*.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `board/tests/test_metrics_tasks.py`, change `build` to pass the new keyword arguments:

```python
def build(progress, tasks, rows, ends=None, run_end=None, plan_text=None, spawns=None, lead_sessions=None, run_start=None):
    return metrics_tasks.build_task_lines(
        "docs/superpowers/specs/s.md", "2026-11-16-1", tasks, progress, ROUTING, rows,
        (ends or {}).get, run_end, prices=PRICES, plan_text=plan_text,
        spawns=spawns, lead_sessions=lead_sessions, run_start=run_start)
```

and add:

```python
# verbatim real dispatch lines: 2026-11-19-discord-ideas-command, 2026-11-24-pcee-engine-part-2, 2026-11-16-discord-replaces-telegram
TIER_COMMA = "Task 1: dispatched id-core (standard, sonnet), BASE f428acb"
TIER_SLASH = "Task 1: dispatched impl1 (standard/sonnet), BASE 83daf99"
MODEL_FIRST = "Task 1: dispatched dc-launch (sonnet, base 22b8f60)"


def spawn(ts, name, model, lead="L1"):
    # real row shape of claude/hooks/spawn-record.sh
    return {"ts": ts, "lead_session": lead, "name": name, "subagent_type": "general-purpose", "model": model,
            "tier": None, "reason": None}


class TestDispatchForms(unittest.TestCase):
    def test_tier_then_model_forms(self):
        # mutation: restore the base DISPATCH regex -> TIER_COMMA and TIER_SLASH fail
        for line in (TIER_COMMA, TIER_SLASH, MODEL_FIRST):
            self.assertEqual(metrics_tasks.parse_ledger(line)[1]["dispatch_models"], ["sonnet"], line)

    def test_tier_alone_names_no_model(self):
        t = metrics_tasks.parse_ledger("Task 1: dispatched w9 (standard)")[1]
        self.assertEqual((t["owners"], t["dispatch_models"]), (["w9"], []))


class TestModelSource(unittest.TestCase):
    TASKS = tasks_json(("Task 1: a", "standard", ""), ("Task 2: b", "standard", ""))
    ENDS = {"28b98dd": 1000, "0bc8efc": 2000}
    NOMODEL = "Task 1: dispatched dc-launch, base 22b8f60\nTask 1: complete (commits 4e9d2cf..28b98dd, review clean)\n"

    def first(self, progress=None, rows=(), **kw):
        return build(progress or self.NOMODEL, self.TASKS, list(rows), ends=self.ENDS, **kw)[0]

    def test_usage_wins(self):
        t = self.first(DISCORD, [row(900, "dc-launch")], spawns=[spawn(100, "dc-launch", "haiku")], run_start=0)
        self.assertEqual((t["model_used"], t["model_source"]), ("claude-sonnet-5", "usage"))

    def test_spawn_when_no_rows(self):
        t = self.first(DISCORD, spawns=[spawn(100, "dc-launch", "haiku")], run_start=0)
        self.assertEqual((t["model_used"], t["model_source"]), ("haiku", "spawn"))

    def test_spawn_after_task_end_ignored(self):
        # mutation: drop the `ts <= until` bound -> spawn wins, test fails
        t = self.first(DISCORD, spawns=[spawn(1500, "dc-launch", "haiku")], run_start=0)
        self.assertEqual((t["model_used"], t["model_source"]), ("sonnet", "ledger"))

    def test_spawn_before_run_start_ignored(self):
        # mutation: drop the `ts >= run_start` bound -> spawn wins, test fails
        t = self.first(DISCORD, spawns=[spawn(100, "dc-launch", "haiku")], run_start=500)
        self.assertEqual(t["model_source"], "ledger")

    def test_inherit_spawn_ignored(self):
        # mutation: drop the family() check on spawn rows -> model_used "inherit", test fails
        t = self.first(DISCORD, spawns=[spawn(100, "dc-launch", "inherit")], run_start=0)
        self.assertEqual((t["model_used"], t["model_source"]), ("sonnet", "ledger"))

    def test_lead_session_preferred_over_newer_row(self):
        sp = [spawn(100, "dc-launch", "haiku", lead="L1"), spawn(200, "dc-launch", "opus", lead="OTHER")]
        self.assertEqual(self.first(spawns=sp, run_start=0, lead_sessions={"L1"})["model_used"], "haiku")
        self.assertEqual(self.first(spawns=sp, run_start=0)["model_used"], "opus")

    def test_other_name_ignored(self):
        t = self.first(spawns=[spawn(100, "someone-else", "haiku")], run_start=0)
        self.assertEqual((t["model_used"], t["model_source"]), (None, "none"))

    def test_ledger_when_no_spawn(self):
        t = self.first(DISCORD)
        self.assertEqual((t["model_used"], t["model_source"]), ("sonnet", "ledger"))

    def test_none_when_all_miss(self):
        t = self.first()
        self.assertEqual((t["model_used"], t["model_source"]), (None, "none"))
```

Two existing tests in `board/tests/test_metrics_tasks.py` change with the new behaviour:

- `TestBuild.test_no_rows_partial`: the DISCORD ledger names `sonnet` for both tasks, so replace `self.assertIsNone(t["model_used"])` with `self.assertEqual((t["model_used"], t["model_source"]), ("sonnet", "ledger"))`.
- `TestBuild.test_keys_exact`: add `model_source` to its key string, after `model_used`.

In `board/tests/test_metrics_tasks_log.py`, add `model_source` to the `KEYS` string (after `model_used`).

- [ ] **Step 2: Run to see them fail.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks*.py'`. Expected: `TypeError: build_task_lines() got an unexpected keyword argument 'spawns'` in every test that calls `build`, `TestDispatchForms` failing on `TIER_COMMA`, and the key test in `test_metrics_tasks_log.py` failing on the missing `model_source`.

- [ ] **Step 3: Implement.** In `board/metrics_tasks.py`:

```python
DISPATCH = re.compile(r"^(?:fix round \d+(?:/\d+)? )?dispatched (?:to )?(?:fresh )?([A-Za-z0-9_-]+)"
                      r"(?: \((?:(?:mechanical|standard|frontier)\s*[,/]\s*)?(haiku|sonnet|opus|fable|inherit)\b)?")
```

`KEYS`: insert `"model_source"` right after `"model_used"`.

Add before `build_task_lines`:

```python
def _spawn_model(spawns, owner, lo, until, leads):
    """Model of the newest spawn row named `owner` with lo <= ts <= until whose model family() maps, preferring rows of
    the lead sessions `leads`; None when there is none."""
    if not owner or not spawns:
        return None
    c = [s for s in spawns if isinstance(s, dict) and s.get("name") == owner and isinstance(s.get("ts"), (int, float))
         and (lo is None or s["ts"] >= lo) and s["ts"] <= until and family(s.get("model"))]
    pref = [s for s in c if s.get("lead_session") in (leads or ())]
    pick = max(pref or c, key=lambda s: s["ts"], default=None)
    return pick["model"] if pick else None


def _ledger_model(led):
    """The last dispatch model of the task that family() maps, else None."""
    return next((m for m in reversed(led["dispatch_models"]) if family(m)), None)
```

Change the signature to `def build_task_lines(spec, batch, tasks_text, progress, routing, rows, commit_time, run_end, prices=None, plan_text=None, spawns=None, lead_sessions=None, run_start=None):` and extend its docstring: `spawns: spawns.jsonl rows; lead_sessions: the spec's lead session ids; run_start: epoch of the run start (spawn rows before it are other runs').`

In the per-task loop, replace `used = max(per_model, key=per_model.get) if per_model else None` with:

```python
        owner = led["owners"][-1] if led["owners"] else None
        if per_model:
            used, source = max(per_model, key=per_model.get), "usage"
        else:
            used = _spawn_model(spawns, owner, run_start, end_of(n), lead_sessions)
            source = "spawn" if used else None
            if not used:
                used = _ledger_model(led)
                source = "ledger" if used else "none"
```

and in the dict: `"model_used": used, "model_source": source,` and `"owner": owner,`.

- [ ] **Step 4: Run each mutation** named in the tests, confirm the named test fails, restore.

- [ ] **Step 5: Run to see them pass.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks*.py'`. Expected: `OK` for both files.

- [ ] **Step 6: Commit.** `git commit -m "feat(metrics): model_source on task lines; spawn and ledger fallbacks; (tier, model) dispatch form" -- board/metrics_tasks.py board/tests/test_metrics_tasks.py board/tests/test_metrics_tasks_log.py`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/metrics_tasks.py", "board/tests/test_metrics_tasks.py", "board/tests/test_metrics_tasks_log.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_tasks*.py'", "modelTier": "standard"}
```

---

### Task 3: Wire spawns and lead sessions into record, backfill-tasks re-derivation, report line

**Goal:** `task_lines_for_run` passes `spawns.jsonl` rows of the run window and the spec's lead session ids to `build_task_lines`; `backfill-tasks` re-derives the model of existing records without `model_source`; `metrics report` prints `tasks without a model: <k> (<task ids>)` when any task of the batch has `model_source == "none"`.

**Files:**
- Modify: `board/metrics.py` (new `spawns_path`, `read_spawns`; `task_lines_for_run`, `cmd_backfill_tasks`, `report_text`)
- Test: `board/tests/test_metrics_tasks_log.py`

**Acceptance Criteria:**
- [ ] `spawns_path()` is `$AGENT_BOARD_SPAWNS` when set, else `tc_env.agent_base() / "spawns.jsonl"`; the tests' `Base.setUp` pops `AGENT_BOARD_SPAWNS` inside its env patch, so every test reads `<TC_STATE>/spawns.jsonl`.
- [ ] `record` on a run whose Task 2 has no usage rows and a `TC_STATE/spawns.jsonl` row for `w1` at `t0+150` with model `opus` writes Task 2 with `model_used == "opus"`, `model_source == "spawn"`; with the spawn file absent it writes `("haiku", "ledger")` (the fixture ledger's Task 2 model).
- [ ] `task_lines_for_run` passes `lead_sessions` from `metrics_lead.lead_session_ids(usage.root() / slug_of(root), tc_env.lineage_dir() / f"{Path(root).name}.jsonl", lo, hi)` and `run_start=lo`; a test patches `metrics.metrics_lead.lead_session_ids` to return `{"L1"}` and sees an `L1` row win over a newer `L2` row.
- [ ] `backfill-tasks` on a tasks log whose lines lack `model_source` appends one new line per such task: a line with `model_used` set keeps it and gets `"usage"`; a line with `model_used: null` gets the rebuilt model and source; every other field equals the old line's. Output gains the line `re-derived models for 1 specs (2 tasks)`. A second run appends nothing and prints `backfilled tasks for 0 specs (0 tasks, 0 partial)` alone. Mutation: re-derive keys whose last lines already carry `model_source` → the second-run assertion fails.
- [ ] The existing `test_backfill_tasks_idempotent` output assertions pass unchanged (new keys get full builds as today).
- [ ] `metrics report B` prints `tasks without a model: 1 (a#2)` when the batch's last Task 2 line has `model_source: "none"`, and prints no such line when none has it (including old lines without the key).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_*.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests** in `board/tests/test_metrics_tasks_log.py`.

In `Base.setUp`, right after `p.start()`, add `os.environ.pop("AGENT_BOARD_SPAWNS", None)` (the patch restores it at stop).

Add:

```python
def spawn_row(ts, name, model, lead="L1"):
    return {"ts": int(ts), "lead_session": lead, "name": name, "subagent_type": "general-purpose", "model": model,
            "tier": None, "reason": None}


class SpawnWiringTest(Base):
    def spawns(self, *rows):
        p = self.t / "state" / "spawns.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def test_spawns_path_default_and_override(self):
        self.assertEqual(metrics.spawns_path(), self.t / "state" / "spawns.jsonl")
        with mock.patch.dict(os.environ, {"AGENT_BOARD_SPAWNS": str(self.t / "x.jsonl")}):
            self.assertEqual(metrics.spawns_path(), self.t / "x.jsonl")

    def test_record_task_without_rows_takes_the_spawn_model(self):
        self.row(self.t0 + 50)                     # Task 1 has usage rows; Task 2 has none
        self.spawns(spawn_row(self.t0 + 150, "w1", "opus"))
        self.assertEqual(self.record()[0], 0)
        t = {d["task_id"]: d for d in self.tasks()}
        self.assertEqual((t[1]["model_used"], t[1]["model_source"]), (SONNET, "usage"))
        self.assertEqual((t[2]["model_used"], t[2]["model_source"]), ("opus", "spawn"))

    def test_record_without_spawn_file_uses_the_ledger(self):
        self.row(self.t0 + 50)
        self.assertEqual(self.record()[0], 0)
        t = {d["task_id"]: d for d in self.tasks()}
        self.assertEqual((t[2]["model_used"], t[2]["model_source"]), ("haiku", "ledger"))

    def test_lead_session_rows_preferred(self):
        self.row(self.t0 + 50)
        self.spawns(spawn_row(self.t0 + 120, "w1", "opus", lead="L1"), spawn_row(self.t0 + 150, "w1", "fable", lead="L2"))
        with mock.patch.object(metrics.metrics_lead, "lead_session_ids", return_value={"L1"}):
            self.assertEqual(self.record()[0], 0)
        self.assertEqual({d["task_id"]: d for d in self.tasks()}[2]["model_used"], "opus")


class RederiveTest(Base):
    def run_line(self):
        metrics.append(self.repo, {"kind": "run", "batch": "B", "spec": SPEC, "plan": PLAN, "branch": None,
                                   "started_at": metrics.utc(self.t0 - 600), "ended_at": metrics.utc(self.now),
                                   "at": metrics.utc(self.now)})

    def old_lines(self, out):
        # lines as base 0af42b5 wrote them: no model_source; Task 2 had no rows, so no model
        base = {"spec": SPEC, "batch": "B", "tier": "standard", "tokens": 5, "usd": 0.1, "partial": False}
        rows = [dict(base, task_id=1, subject="Task 1: t1", model_used=SONNET),
                dict(base, task_id=2, subject="Task 2: t2", model_used=None, tokens=None, partial=True)]
        out.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return rows

    def bf(self, out):
        return self.cli("backfill-tasks", "--log", str(out), "--usage-db", str(self.db), "--no-ingest")

    def test_rederive_appends_model_fields_only_once(self):
        # mutation: re-derive keys whose last lines already carry model_source -> the second run appends again
        self.run_line()
        out = self.t / "tasks.jsonl"
        old = self.old_lines(out)
        rc, o, e = self.bf(out)
        self.assertEqual((rc, e), (0, ""), e)
        self.assertEqual(o.splitlines(), ["backfilled tasks for 0 specs (0 tasks, 0 partial)",
                                          "re-derived models for 1 specs (2 tasks)"])
        lines = self.tasks(out)
        self.assertEqual(len(lines), 4)
        new1, new2 = lines[2], lines[3]
        self.assertEqual(new1, dict(old[0], model_source="usage"))
        self.assertEqual(new2, dict(old[1], model_used="haiku", model_source="ledger"))
        rc, o, e = self.bf(out)
        self.assertEqual(o.splitlines(), ["backfilled tasks for 0 specs (0 tasks, 0 partial)"])
        self.assertEqual(len(self.tasks(out)), 4)


class ReportNoModelTest(Base):
    def report(self):
        return self.cli("report", "B")[1]

    def test_line_when_a_task_has_no_model(self):
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "usage"})
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 2, "model_source": "none"})
        self.assertIn("tasks without a model: 1 (a#2)\n", self.report())

    def test_no_line_otherwise(self):
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "none"})
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 1, "model_source": "spawn"})  # last line wins
        metrics.append_task(self.repo, {"spec": SPEC, "batch": "B", "task_id": 2, "model_used": None})       # old line, no key
        self.assertNotIn("tasks without a model", self.report())
```

(`report B` succeeds on this fixture, a batch line with no run lines: checked by the planner against this plan's code.)

- [ ] **Step 2: Run to see them fail.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_tasks_log.py'`. Expected: `AttributeError: module 'metrics' has no attribute 'spawns_path'`, the spawn record test failing on `model_source` `ledger`, the re-derive test seeing only the first output line, the report test missing the line.

- [ ] **Step 3: Implement** in `board/metrics.py`.

Near `tasks_path`:

```python
def spawns_path():
    """spawns.jsonl of claude/hooks/spawn-record.sh: $AGENT_BOARD_SPAWNS, else <agent_base>/spawns.jsonl."""
    env = os.environ.get("AGENT_BOARD_SPAWNS")
    return Path(env) if env else tc_env.agent_base() / "spawns.jsonl"


def read_spawns(lo, hi):
    """Spawn rows with a numeric ts in [lo, hi]; [] when the file is missing or unreadable."""
    try:
        rows = _read_jsonl(spawns_path())[0]
    except OSError:
        return []
    return [r for r in rows if isinstance(r.get("ts"), (int, float)) and lo <= r["ts"] <= hi]
```

In `task_lines_for_run`, replace the final `return`:

```python
    leads = metrics_lead.lead_session_ids(usage.root() / slug_of(root), tc_env.lineage_dir() / f"{Path(root).name}.jsonl",
                                          lo, hi)
    return metrics_tasks.build_task_lines(spec, batch, tasks_text, progress or "", routing, rows, _commit_time(repo), hi,
                                          plan_text=plan_text, spawns=read_spawns(lo, hi), lead_sessions=leads,
                                          run_start=lo)
```

Replace `cmd_backfill_tasks` whole with (the new-key path, its counters and its first output line are today's; a key whose last lines all carry `model_source` is skipped):

```python
def cmd_backfill_tasks(repo, args):
    """Task lines for every run line whose (batch, spec) has none yet; for one that has lines without `model_source`,
    one re-derived line per such task (model fields only). A run whose lines cannot be built is named on stderr."""
    global TASKS_OVERRIDE
    TASKS_OVERRIDE = args.tasks_log
    try:
        last = {}
        for d in read_tasks(repo)[0]:
            last[(d.get("batch"), d.get("spec"), d.get("task_id"))] = d
        olds = {}
        for (b, sp, _), d in last.items():
            olds.setdefault((b, sp), []).append(d)
        conn = usage.connect(args.usage_db or usage.db_path())
        specs = tasks = partial = rspecs = rtasks = 0
        try:
            if not args.no_ingest:
                ingest_project(conn, main_root(repo))
            for key, run in last_runs(read_log(repo)[0]).items():
                stale = [d for d in olds.get(key, []) if "model_source" not in d]
                if key in olds and not stale:
                    continue
                try:
                    lines = task_lines_for_run(repo, run, conn)
                except Exception as e:
                    print(f"metrics: backfill-tasks: skipped {run.get('spec')}: {clean_reason(e, repo)}", file=sys.stderr)
                    continue
                if key in olds:   # re-derive: the model fields of the old line change, nothing else
                    by_id = {t["task_id"]: t for t in lines}
                    for old in stale:
                        if old.get("model_used") is not None:
                            upd = dict(old, model_source="usage")
                        else:
                            new = by_id.get(old.get("task_id")) or {}
                            upd = dict(old, model_used=new.get("model_used"), model_source=new.get("model_source") or "none")
                        append_task(repo, upd)
                    rspecs += 1
                    rtasks += len(stale)
                    continue
                if not lines:
                    continue
                for t in lines:
                    append_task(repo, t)
                specs += 1
                tasks += len(lines)
                partial += sum(1 for t in lines if t["partial"])
        finally:
            conn.close()
        print(f"backfilled tasks for {specs} specs ({tasks} tasks, {partial} partial)")
        if rspecs:
            print(f"re-derived models for {rspecs} specs ({rtasks} tasks)")
    finally:
        TASKS_OVERRIDE = None
```

In `report_text`, before `out.append("Excluded: " ...)`:

```python
    last_t = {}
    for d in read_tasks(repo)[0]:
        if d.get("batch") == batch_id:
            last_t[(d.get("spec"), d.get("task_id"))] = d
    nomodel = sorted(f"{_spec_slug(str(sp))}#{tid}" for (sp, tid), d in last_t.items() if d.get("model_source") == "none")
    if nomodel:
        out.append(f"tasks without a model: {len(nomodel)} ({', '.join(nomodel)})")
```

`_spec_slug` is defined after `report_text` in the file; it is resolved at call time, so no move is needed.

- [ ] **Step 4: Run the mutation** named in `test_rederive_appends_model_fields_only_once`, confirm it fails, restore.

- [ ] **Step 5: Run to see them pass.** Run: `python3 -m unittest discover -s board/tests -p 'test_metrics_*.py'`. Expected: `OK` (every metrics test file, including `test_metrics_report.py` unchanged).

- [ ] **Step 6: Commit.** `git commit -m "feat(metrics): spawn rows and lead sessions in task lines; backfill-tasks re-derives models; report names tasks without a model" -- board/metrics.py board/tests/test_metrics_tasks_log.py`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_tasks_log.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_*.py'", "modelTier": "standard"}
```

---

### Task 4: nomodel group in the analysis and "no model recorded" in the weekly text

**Goal:** `by_tier_model` keys a task with `model_source == "none"` as `<tier>|nomodel` (old lines without the key stay `unknown`), and the weekly text (terminal and Discord) prints that group as `<tier>|no model recorded`.

**Files:**
- Modify: `board/metrics_analyze.py` (line ~150, new `_model_key`)
- Modify: `board/metrics_recommend.py` (new `tier_model_label`, used in `_flag_lines`)
- Modify: `board/analytics_post.py` (`_flag_rows` uses `metrics_recommend.tier_model_label`)
- Test: `board/tests/test_metrics_analyze.py`, `board/tests/test_metrics_recommend.py`

**Acceptance Criteria:**
- [ ] `analyze` over tasks `{model_source: "none", model_used: None}`, `{model_used: None}` (no key) and a sonnet task gives keys `{"standard|nomodel", "standard|unknown", "standard|sonnet"}`. Mutation: drop the `model_source` check → `standard|nomodel` missing.
- [ ] `metrics_recommend._flag_lines` with an underpowered `standard|nomodel` flag prints `- underpowered: standard|no model recorded: <reason>`; `analytics_post._flag_rows` prints `underpowered: ` + `escape('standard|no model recorded')` + `: <reason>` (Discord text escapes `|`); a `standard|sonnet` flag prints unchanged.
- [ ] The existing `test_groups_by_tier_and_family_with_stats` passes unchanged.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py' && python3 -m unittest discover -s board/tests -p 'test_metrics_recommend.py' && python3 -m unittest discover -s board/tests -p 'test_analytics_post.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests.** In `board/tests/test_metrics_analyze.py`, in `class ByTierModelTest`, add:

```python
    def test_model_source_none_is_nomodel_and_old_lines_stay_unknown(self):
        # mutation: drop the model_source check in _model_key -> "standard|nomodel" is missing
        tasks = [task("s", 1, model_used=None, model_source="none"), task("s", 2, model_used=None), task("s", 3)]
        s = self.one([run("s", cur())], tasks)["by_tier_model"]
        self.assertEqual(set(s), {"standard|nomodel", "standard|unknown", "standard|sonnet"})
```

In `board/tests/test_metrics_recommend.py`, add:

```python
class NoModelLabelTest(unittest.TestCase):
    def flags(self, key):
        return {"overpowered": [], "costly_steps": [], "handoffs": [],
                "underpowered": [{"tier_model": key, "tasks": 6, "median_fix_rounds": 2.0, "escalation_rate": 0.0,
                                  "reason": "median fix rounds 2.0 over 6 tasks"}],
                "forecast": {"median_precision": None, "median_recall": None, "below_half": []}}

    def test_terminal_and_discord_say_no_model_recorded(self):
        self.assertEqual(metrics_recommend._flag_lines(self.flags("standard|nomodel")),
                         ["- underpowered: standard|no model recorded: median fix rounds 2.0 over 6 tasks"])
        rows = analytics_post._flag_rows(self.flags("standard|nomodel"))
        esc = analytics_post.escape   # Discord text escapes markdown characters, `|` included
        self.assertEqual([r[2] for r in rows],
                         [f"underpowered: {esc('standard|no model recorded')}: {esc('median fix rounds 2.0 over 6 tasks')}"])

    def test_other_keys_unchanged(self):
        self.assertEqual(metrics_recommend._flag_lines(self.flags("standard|sonnet")),
                         ["- underpowered: standard|sonnet: median fix rounds 2.0 over 6 tasks"])
```

`board/tests/test_metrics_recommend.py` imports `metrics, metrics_analyze, metrics_recommend` on one line: make it `import analytics_post, metrics, metrics_analyze, metrics_recommend  # noqa: E402`.

- [ ] **Step 2: Run to see them fail.** Run the Verify command. Expected: the analyze test fails (`standard|unknown` holds both no-model tasks), the label tests fail (`standard|nomodel` printed raw).

- [ ] **Step 3: Implement.** `board/metrics_analyze.py`, next to `family`:

```python
def _model_key(t):
    """by_tier_model model part: `nomodel` when the record says no source named a model, else the family or `unknown`."""
    if t.get("model_source") == "none":
        return "nomodel"
    return family(t.get("model_used")) or "unknown"
```

and line ~150: `groups.setdefault(f"{t.get('tier') or 'unspecified'}|{_model_key(t)}", []).append(t)`.

`board/metrics_recommend.py`, before `_flag_lines`:

```python
def tier_model_label(key):
    """A by_tier_model key for readers: the `nomodel` group reads "no model recorded"."""
    tier, sep, model = str(key).partition("|")
    return f"{tier}|no model recorded" if sep and model == "nomodel" else str(key)
```

and in `_flag_lines`: `out.append(f"- underpowered: {tier_model_label(r['tier_model'])}: {r['reason']}")`.

`board/analytics_post.py`, `_flag_rows`: `f"underpowered: {escape(metrics_recommend.tier_model_label(r['tier_model']))}: {escape(_cap(r['reason'], 100))}"`.

- [ ] **Step 4: Run the mutation** named in the analyze test, confirm it fails, restore.

- [ ] **Step 5: Run to see them pass.** Run the Verify command. Expected: three `OK`.

- [ ] **Step 6: Commit.** `git commit -m "feat(metrics): nomodel group in by_tier_model; weekly text says no model recorded" -- board/metrics_analyze.py board/metrics_recommend.py board/analytics_post.py board/tests/test_metrics_analyze.py board/tests/test_metrics_recommend.py`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/metrics_analyze.py", "board/metrics_recommend.py", "board/analytics_post.py", "board/tests/test_metrics_analyze.py", "board/tests/test_metrics_recommend.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_metrics_analyze.py' && python3 -m unittest discover -s board/tests -p 'test_metrics_recommend.py' && python3 -m unittest discover -s board/tests -p 'test_analytics_post.py'", "modelTier": "mechanical"}
```

---

### Task 5: Dispatch line format in the SDD extras skill

**Goal:** `claude/skills/subagent-driven-development-extras/SKILL.md` tells the lead that every dispatch ledger line names the tier and the model.

**Files:**
- Modify: `claude/skills/subagent-driven-development-extras/SKILL.md`

**Acceptance Criteria:**
- [ ] The file holds the exact text `dispatched <name> (<tier>, <model>)` once, in a paragraph after the routing-gate paragraph and before `## 1. Green before review`.
- [ ] No other line of the file changes (`git diff --stat` shows 2 insertions: the paragraph and one blank line).

**Verify:** `test "$(grep -cF 'dispatched <name> (<tier>, <model>)' claude/skills/subagent-driven-development-extras/SKILL.md)" -eq 1 && echo ok`

**Steps:**

- [ ] **Step 1: Edit.** After the paragraph that ends `change the dispatch to a model the gate allows.`, insert a blank line and:

```markdown
Ledger dispatch lines name the tier and the model: `Task <N>: dispatched <name> (<tier>, <model>) …`, e.g. `Task 3: dispatched impl3 (standard, sonnet), BASE 8f46426`. `metrics record` reads the model from this line when no usage row or spawn row names one.
```

- [ ] **Step 2: Verify.** Run the Verify command. Expected: `ok`. Run `git diff --stat -- claude/skills/subagent-driven-development-extras/SKILL.md`. Expected: `1 file changed, 2 insertions(+)`.

- [ ] **Step 3: Commit.** `git commit -m "docs(sdd-extras): dispatch ledger lines name tier and model" -- claude/skills/subagent-driven-development-extras/SKILL.md`, ending with the attribution trailer your harness specifies. (The live `~/.claude/skills/subagent-driven-development-extras` links into the main checkout, so this takes effect when the branch merges.)

```json:metadata
{"files": ["claude/skills/subagent-driven-development-extras/SKILL.md"], "verifyCommand": "test \"$(grep -cF 'dispatched <name> (<tier>, <model>)' claude/skills/subagent-driven-development-extras/SKILL.md)\" -eq 1 && echo ok", "modelTier": "mechanical"}
```

---

### Task 6: Real-state measurement: lineage time and the re-derived records

**Goal:** One measured run on this machine's real state, read-only, recorded in `docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md`: the whole-lineage lead-field time before (base code) and after (branch code), and how many real task records the new resolution gives a model.

**Files:**
- Create: `docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md`

**Constraints:**
- Read-only against real state: the real usage index is opened with `--no-ingest`; the tasks log is a scratch copy (`--log`); nothing under `~/.local/state`, `~/.claude/projects` or `docs/superpowers/metrics/` changes. Check with `git status --short docs/superpowers/metrics` (empty) after the run.
- Base timing runs the main checkout's `board/` (`/Users/francisco.ruiz/agent-board/board`, on `main` = base for `metrics_lead.py`; confirm with `git -C /Users/francisco.ruiz/agent-board diff --quiet 0af42b5 -- board/metrics_lead.py && echo same`). A full base run is about 139 calls × ~4.6 s, so base time is measured as 5 `successor()` calls and extrapolated per call; the branch run is the full `lead_fields` over the whole lineage.
- Each timing line records `uptime`'s load average next to it. Wrap each run in `perl -e 'alarm N; exec @ARGV' …` (macOS has no `timeout`): 900 s for the timings, 3600 s for the backfill.
- The planner's partial run saw 0 `ledger` hits. If the full run also shows 0, take one re-derived `none` record, read its archived ledger (`docs/superpowers/ledgers/<plan-basename>/progress.md`) for the task's dispatch lines, and say in the doc why no model was read (no model in the line, a form the regex misses, or no ledger found): a missed form is a finding for the lead, not fixed here.
- Target: the whole-lineage branch run under 15 s. A miss is recorded, not fixed here: the doc says which part dominates (profile with `python3 -m cProfile -s cumtime` and quote the top 5 lines).

**Acceptance Criteria:**
- [ ] The doc has exactly these sections: `## Lineage timing`, `## Model resolution on real records`, `## Verdict`.
- [ ] `## Lineage timing` holds: base per-call seconds (mean of 5) with load average, the number of `successor()` calls one whole-lineage `lead_fields` makes, the branch whole-lineage seconds with load average, transcript count, lineage line count.
- [ ] `## Model resolution on real records` holds the backfill's wall time and exit code, and: last-line records without a model before (count over a scratch copy of the committed `docs/superpowers/metrics/tasks.jsonl`), and after `backfill-tasks` the counts per `model_source` (`usage`, `spawn`, `ledger`, `none`) over the re-derived lines, plus the standard-tier `none` count; the command lines used are quoted.
- [ ] `## Verdict` states pass or miss against the 15 s target with its scope (this machine, the load average measured, one run).
- [ ] `git status --short docs/superpowers/metrics` is empty after the run.

**Verify:** `f=docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md; test "$(grep -c '^## ' $f)" -eq 3 && grep -q '^## Lineage timing' $f && grep -q '^## Model resolution on real records' $f && grep -q '^## Verdict' $f && grep -q 'load average' $f && test -z "$(git status --short docs/superpowers/metrics)" && echo ok`

**Steps:**

- [ ] **Step 1: Time the base.** From the worktree root, with `S` a scratch dir:

```zsh
uptime
perl -e 'alarm 900; exec @ARGV' python3 - /Users/francisco.ruiz/agent-board/board <<'EOF'
import os, sys, time
sys.path.insert(0, sys.argv[1]); import metrics_lead as ml
t = os.path.expanduser("~/.claude/projects/-Users-francisco-ruiz-agent-board")
L = ml.lineage(os.path.expanduser("~/.local/state/agent-board/lineage/agent-board.jsonl"))
ts = []
for line in L[-5:]:
    t0 = time.time(); ml.successor(t, line); ts.append(time.time() - t0)
print("base per call", round(sum(ts) / len(ts), 2), "s over", len(ts), "calls; lineage lines", len(L),
      "; transcripts", len([f for f in os.listdir(t) if f.endswith(".jsonl")]))
EOF
```

- [ ] **Step 2: Time the branch, counting calls.**

```zsh
uptime
perl -e 'alarm 900; exec @ARGV' python3 - "$PWD/board" <<'EOF'
import os, sys, time
sys.path.insert(0, sys.argv[1]); import metrics_lead as ml
real, n = ml.successor, [0]
def counted(*a):
    n[0] += 1
    return real(*a)
ml.successor = counted
t = os.path.expanduser("~/.claude/projects/-Users-francisco-ruiz-agent-board")
lin = os.path.expanduser("~/.local/state/agent-board/lineage/agent-board.jsonl")
t0 = time.time(); r = ml.lead_fields(t, lin, 0, time.time()); dt = time.time() - t0
print("branch whole lineage", round(dt, 2), "s;", n[0], "successor calls; handoffs", r["lead_handoffs"])
EOF
```

If over 15 s, rerun the same script under `python3 -m cProfile -s cumtime` and keep the top 5 lines.

- [ ] **Step 3: Re-derive real records on a scratch copy.**

```zsh
S=$(mktemp -d)
cp docs/superpowers/metrics/tasks.jsonl $S/tasks.jsonl
python3 - $S/tasks.jsonl <<'EOF'
import json, sys
last = {}
for l in open(sys.argv[1]):
    if l.strip():
        d = json.loads(l); last[(d.get("batch"), d.get("spec"), d.get("task_id"))] = d
v = list(last.values())
print("before: no model", sum(1 for d in v if d.get("model_used") is None),
      "; standard no model", sum(1 for d in v if d.get("model_used") is None and d.get("tier") == "standard"))
EOF
date; time perl -e 'alarm 3600; exec @ARGV' python3 board/metrics.py --repo . backfill-tasks --log $S/tasks.jsonl --no-ingest > $S/bf.out 2>&1; echo rc=$? >> $S/bf.out; cat $S/bf.out
python3 - $S/tasks.jsonl <<'EOF'
import json, sys, collections
last = {}
for l in open(sys.argv[1]):
    if l.strip():
        d = json.loads(l); last[(d.get("batch"), d.get("spec"), d.get("task_id"))] = d
v = list(last.values())
print("after by source", dict(collections.Counter(d.get("model_source") for d in v)),
      "; standard none", sum(1 for d in v if d.get("model_source") == "none" and d.get("tier") == "standard"))
EOF
git status --short docs/superpowers/metrics
```

Expected: `rc=0` in `bf.out` and the last command prints nothing. Run this step in the background (it is long): the planner's run of this plan's code was killed by a 900 s alarm after re-deriving 105 of the 326 last-line records (61 usage, 7 spawn, 0 ledger, 37 none; 125 without a model before, 83 of them standard-tier), so give it the 3600 s alarm and record its wall time in the doc. An `rc=142` (alarm) is recorded as a miss with the partial counts, not retried.

- [ ] **Step 4: Write the doc** with the three sections and the numbers above, then run the Verify command. Expected: `ok`.

- [ ] **Step 5: Commit.** `git commit -m "docs(metrics): model-and-successor real-state measurement" -- docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md"], "verifyCommand": "f=docs/superpowers/plans/2026-11-24-metrics-model-and-successor-measure.md; test \"$(grep -c '^## ' $f)\" -eq 3 && grep -q '^## Lineage timing' $f && grep -q '^## Model resolution on real records' $f && grep -q '^## Verdict' $f && grep -q 'load average' $f && test -z \"$(git status --short docs/superpowers/metrics)\" && echo ok", "modelTier": "standard"}
```
