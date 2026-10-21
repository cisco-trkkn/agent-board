# Runtime Audit and Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure how the current Claude Code setup behaves and publish an evidence-labelled audit (architecture, baseline, ranked findings, roadmap draft) as a Claude Doc, without changing live behaviour.

**Architecture:** A stdlib-Python toolkit in `tools/audit/` turns transcripts into metrics JSON (Tasks 1–7). Three read-only discovery areas read code plus that JSON and write findings in one format (Tasks 8–10). One synthesis owner drafts the report, an independent reviewer re-checks its evidence, and the corrected report is published (Tasks 11–13).

**Tech Stack:** Python 3 stdlib, `unittest`, zsh/bash, Claude Docs connector (`mcp__claude_ai_Claude_Docs__*`).

**Spec:** `docs/superpowers/specs/2026-10-21-runtime-audit-baseline-design.md`

## Global Constraints

- Work only in the worktree `~/agent-board/.claude/worktrees/runtime-audit` on branch `audit/runtime-baseline`. This repo is the live install: never edit the live checkout, `~/.claude`, `~/.local/bin`, plugin caches or settings files.
- Transcripts are read-only input. Default root `~/.claude/projects`; never write under it.
- Scope: sessions whose line `cwd` is `/Users/francisco.ruiz/master-gcp-repo` or `/Users/francisco.ruiz/agent-board`, or under `<repo>/.claude/worktrees/`; window = last 30 days (local midnight, same rule as `tools/usage-sum.py:window_start`).
- Python 3 stdlib only. Tests: `python3 -m unittest discover -s tools/audit/tests -p 'test_*.py'`.
- Every metric object carries `"source": "measured"` or `"derived"`. A value the transcripts do not expose is `null` with a sibling `"<field>_reason"`; never an estimate.
- Raw toolkit output goes to `audit-out/` (gitignored). Committed fixtures and reports must contain no secrets: `tools/audit/redact_check.sh` must pass on them.
- Findings use the spec's format (`### F-<area>-<n>`, `Label:`, `Evidence:`, `Confidence:` …) and pass `tools/audit/check_findings.py`.
- Scratch tmux servers, if any probe needs one, start with `-f /dev/null`.
- Nothing is pushed. Commit messages: conventional with scope (`feat(audit): …`, `docs(audit): …`), ending with the attribution trailer your harness specifies.
- Agent Bash runs zsh: quote words starting with `=`, never name a variable `path`.

**User decisions (already made):**
- Scope this round to sub-project 1 (audit + baseline) only.
- Mine master-gcp-repo and agent-board (+ worktrees) transcripts, last 30 days; full content may be quoted as evidence, secrets redacted.
- Lean, script-first budget: scripts mine transcripts; agents read code and script output.
- Approach A: toolkit → three parallel discovery areas → one synthesis owner.
- Report is a Claude Doc.
- D4 (routing policy) and D5 (context/handoff design) are deferred to sub-project 3.

---

## File map

| File | Responsibility |
| --- | --- |
| `tools/audit/transcripts.py` | Only module that knows the transcript format; yields normalised events |
| `tools/audit/session_metrics.py` | Per-session and per-agent usage, lifetimes, peak context |
| `tools/audit/waste_signals.py` | Deterministic duplication and stagnation signals |
| `tools/audit/injection_costs.py` | Size and frequency of always-on and injected text |
| `tools/audit/handoff_trace.py` | Handoff/compaction events and re-exploration cost after them |
| `tools/audit/check_findings.py` | Validates the findings format in a report file |
| `tools/audit/redact_check.sh` | Fails on secret-shaped strings |
| `tools/audit/capture_fixture.py` | Cuts a redacted fixture from a real transcript |
| `tools/audit/run_baseline.sh` | Runs all metrics over the agreed scope into `audit-out/<date>/` |
| `tools/audit/tests/` | unittest tests + `fixtures/` |
| `docs/superpowers/reports/runtime-audit/*.md` | Area findings, draft report, probe review |

## Normalised event schema (shared contract, defined in Task 1)

Every event is a dict with `kind`, `session` (session id), `agent` (`"main"`, `"sub:<agent-id>"` for `subagents/agent-*.jsonl`, or `"team:<agentName>"` when the line carries `agentName`), `ts` (epoch float or `None`), `file` (source path). Per kind:

| kind | extra keys |
| --- | --- |
| `usage` | `request_id`, `model`, `input`, `output`, `cache_read`, `cache_creation` (ints) — one event per request id, latest line wins |
| `tool_use` | `tool`, `tool_use_id`, `args_key` (sha1 of canonical-JSON input, first 12 hex), `target` (`file_path`/`path`/`command`/`pattern` from input, else `None`) |
| `tool_result` | `tool_use_id`, `size` (chars of content), `is_error` (bool) |
| `injection` | `source` (`"hook:<event>"`, `"attachment:<type>"`, `"system-reminder"`, `"claude-md"`), `size` (chars) |
| `system` | `subtype`, `raw_keys` (sorted top-level keys) |
| `prompt` | `size`, `text_head` (first 200 chars of a human prompt) |

---

### Task 1: Transcript parser and fixtures

**Goal:** `transcripts.py` yields normalised events for the agreed scope, and its usage totals reconcile with the independent `tools/usage-sum.py`.

**Files:**
- Create: `tools/audit/transcripts.py`, `tools/audit/capture_fixture.py`, `tools/audit/tests/test_transcripts.py`, `tools/audit/tests/fixtures/*.jsonl`
- Modify: `.gitignore` (add `audit-out/`)

**Acceptance Criteria:**
- [ ] `iter_events(root, repos, days)` yields the schema above for main, subagent and teammate files
- [ ] Duplicate lines sharing a `requestId` produce one `usage` event (latest line wins); a final line without `\n` is skipped
- [ ] Fixtures are cut from real transcripts by `capture_fixture.py` (one with subagents, one with a system/compaction-style line), and pass `redact_check.sh` once Task 6 lands
- [ ] Real-state reconciliation: count of `usage` events for `--repo /Users/francisco.ruiz/agent-board --days 30` equals `calls=` printed by `tools/usage-sum.py` for the same arguments

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_transcripts.py' -v` → all tests OK, including `test_real_reconciles_with_usage_sum`

**Steps:**

- [ ] **Step 1: Inspect the real format before writing code.** Read-only:

```bash
P=~/.claude/projects/-Users-francisco-ruiz-agent-board
python3 - $P <<'EOF'
import json,sys,glob,collections
sub=collections.Counter(); att=collections.Counter()
for f in glob.glob(sys.argv[1]+'/**/*.jsonl', recursive=True)[:80]:
    for l in open(f, errors='replace'):
        try: o=json.loads(l)
        except Exception: continue
        if o.get('type')=='system': sub[o.get('subtype')]+=1
        if o.get('type')=='attachment': att[(o.get('attachment') or {}).get('type')]+=1
print('system subtypes', sub.most_common()); print('attachment types', att.most_common())
EOF
ls $P/*/subagents | head; cat "$(ls $P/*/subagents/*.meta.json | head -1)"
```

Record the subtypes and attachment types in the test file's docstring; they drive `injection` and `system` mapping.

- [ ] **Step 2: Write `capture_fixture.py`.** Usage: `capture_fixture.py <src.jsonl> <dst.jsonl> [--max-lines N]`. Keeps every line's structural keys (`type`, `subtype`, `requestId`, `timestamp`, `cwd`, `sessionId`, `isSidechain`, `agentName`, `teamName`, `message.model`, `message.usage`, `attachment.type`, `hookInfos`), keeps `tool_use` blocks' `name`, `id` and `input` with string values replaced by `"<redacted:len=N>"` except `file_path`/`path`/`command`, which keep their value with `/Users/<name>` → `/home/u`; replaces all other text with `"x" * min(len, 50)` plus a `"_len"` key holding the original length. First output line: `{"type":"fixture-header","source":"<src basename>","captured":"<date>"}`. Capture two fixtures from real sessions in the agent-board project dir: `fx_subagents/` (a session dir with its `subagents/` files, copied as a dir tree) and `fx_system.jsonl` (a session containing system lines).

- [ ] **Step 3: Write the failing tests** in `tools/audit/tests/test_transcripts.py`:

```python
import json, os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import transcripts as T

def write(dirpath, name, lines, partial_tail=None):
    os.makedirs(dirpath, exist_ok=True)
    p = os.path.join(dirpath, name)
    with open(p, "w") as fh:
        for l in lines: fh.write(json.dumps(l) + "\n")
        if partial_tail: fh.write(partial_tail)
    return p

def asst(req, cwd, inp=1, out=2, ts="2026-10-20T10:00:00Z", **kw):
    d = {"type": "assistant", "requestId": req, "cwd": cwd, "sessionId": "s1", "timestamp": ts,
         "message": {"model": "claude-opus-5-5", "usage": {"input_tokens": inp, "output_tokens": out,
                     "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                     "content": [{"type": "text", "text": "hi"}]}}
    d.update(kw); return d

class Synthetic(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(); self.repo = "/r/repo"
        self.proj = os.path.join(self.root, "-r-repo")

    def events(self, kind=None):
        ev = list(T.iter_events(self.root, [self.repo], days=3650))
        return [e for e in ev if kind is None or e["kind"] == kind]

    def test_duplicate_request_ids_count_once_latest_wins(self):
        write(self.proj, "s1.jsonl", [asst("r1", self.repo, out=1), asst("r1", self.repo, out=9)])
        u = self.events("usage")
        self.assertEqual(len(u), 1); self.assertEqual(u[0]["output"], 9)

    def test_partial_last_line_skipped(self):
        write(self.proj, "s1.jsonl", [asst("r1", self.repo)], partial_tail='{"type":"assistant"')
        self.assertEqual(len(self.events("usage")), 1)

    def test_out_of_scope_cwd_ignored_worktree_included(self):
        write(self.proj, "s1.jsonl", [asst("r1", "/other"), asst("r2", self.repo + "/.claude/worktrees/x")])
        self.assertEqual([e["request_id"] for e in self.events("usage")], ["r2"])

    def test_subagent_file_gets_sub_agent_id(self):
        write(os.path.join(self.proj, "s1", "subagents"), "agent-abc.jsonl", [asst("r3", self.repo)])
        self.assertEqual(self.events("usage")[0]["agent"], "sub:abc")

    def test_teammate_line_gets_team_agent_id(self):
        write(self.proj, "s1.jsonl", [asst("r4", self.repo, agentName="atlas")])
        self.assertEqual(self.events("usage")[0]["agent"], "team:atlas")

    def test_tool_use_and_result(self):
        a = asst("r5", self.repo)
        a["message"]["content"] = [{"type": "tool_use", "id": "t1", "name": "Read",
                                    "input": {"file_path": "/r/repo/x.py"}}]
        u = {"type": "user", "cwd": self.repo, "sessionId": "s1", "timestamp": "2026-10-20T10:00:01Z",
             "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "abcd", "is_error": False}]}}
        write(self.proj, "s1.jsonl", [a, u])
        tu = self.events("tool_use")[0]; tr = self.events("tool_result")[0]
        self.assertEqual((tu["tool"], tu["target"], len(tu["args_key"])), ("Read", "/r/repo/x.py", 12))
        self.assertEqual((tr["tool_use_id"], tr["size"], tr["is_error"]), ("t1", 4, False))

class Fixtures(unittest.TestCase):
    def test_fixtures_parse_and_have_usage(self):
        fx = os.path.join(HERE, "fixtures")
        ev = list(T.iter_events(fx, None, days=None))   # repos=None, days=None: no scope filter
        self.assertTrue(any(e["kind"] == "usage" for e in ev))
        self.assertTrue(any(e["agent"].startswith("sub:") for e in ev))
        self.assertTrue(any(e["kind"] == "system" for e in ev))

class RealState(unittest.TestCase):
    def test_real_reconciles_with_usage_sum(self):
        repo = "/Users/francisco.ruiz/agent-board"
        tools = os.path.dirname(os.path.dirname(HERE))
        out = subprocess.run([sys.executable, os.path.join(tools, "usage-sum.py"), "--repo", repo, "--days", "30"],
                             capture_output=True, text=True, check=True).stdout
        calls = int(out.split("calls=")[1].split()[0])
        n = sum(1 for e in T.iter_events(os.path.expanduser("~/.claude/projects"), [repo], days=30) if e["kind"] == "usage")
        self.assertEqual(n, calls)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run the tests to see them fail.** `python3 -m unittest discover -s tools/audit/tests -p 'test_transcripts.py' -v` → FAIL / ImportError on `transcripts`.

- [ ] **Step 5: Implement `transcripts.py`.** Public API: `iter_events(root, repos, days)` (`repos=None` and `days=None` disable the scope and window filters) and `load_session_meta(path)`. Rules that are not obvious:
  - Walk `root` with `glob(**/*.jsonl, recursive=True)`; sort files by mtime ascending so a later line for the same `requestId` overwrites an earlier one; buffer `usage` per request id and emit after all files are read.
  - Scope: keep a line when `cwd == repo` or `cwd.startswith(repo + "/.claude/worktrees/")` (same rule as `tools/usage-sum.py:in_repo`); a line without `cwd` inherits the last `cwd` seen in that file.
  - Window: match `tools/usage-sum.py:window_start` (local midnight, `days - 1` days back); skip files whose mtime is before it.
  - Agent id: path contains `/subagents/agent-<id>.jsonl` → `sub:<id>`; else line `agentName` → `team:<agentName>`; else `main`.
  - Skip a final line not ending in `\n`; skip lines that fail `json.loads`.
  - `args_key`: `hashlib.sha1(json.dumps(input, sort_keys=True).encode()).hexdigest()[:12]`.
  - `injection` events: `attachment` lines (`attachment:<type>`, size = len of its JSON), `system` lines with `hookAdditionalContext` (`hook:<hookInfos event or "unknown">`), and each `<system-reminder>…</system-reminder>` span inside user message text (`system-reminder`).
  Must cross-check against usage-sum independently: do not import from `usage-sum.py`.

- [ ] **Step 6: Run tests to pass.** Same command → all OK. If the real-state test differs, debug with superpowers-extended-cc:systematic-debugging (likely causes: cwd inheritance, window boundary, partial lines) — never loosen the assertion.

- [ ] **Step 7: Commit.** `git add .gitignore tools/audit/transcripts.py tools/audit/capture_fixture.py tools/audit/tests` → `feat(audit): transcript parser with usage-sum reconciliation` + your harness's attribution trailer.

```json:metadata
{"files": ["tools/audit/transcripts.py", "tools/audit/capture_fixture.py", "tools/audit/tests/test_transcripts.py", "tools/audit/tests/fixtures/", ".gitignore"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_transcripts.py' -v", "acceptanceCriteria": ["iter_events yields schema for main/sub/team", "requestId dedupe latest wins; partial line skipped", "fixtures captured from real transcripts", "usage event count equals usage-sum.py calls= for agent-board 30d"], "modelTier": "standard"}
```

---

### Task 2: Session metrics

**Goal:** `session_metrics.py` writes per-session and per-agent usage, lifetime and context figures as JSON.

**Files:**
- Create: `tools/audit/session_metrics.py`, `tools/audit/tests/test_session_metrics.py`

**Acceptance Criteria:**
- [ ] CLI `session_metrics.py --root R --repo P [--repo P2] --days N --out F` writes `{"sessions": [...], "totals": {...}}`
- [ ] Per session: tokens by model and by agent (input/output/cache_read/cache_creation), `orchestrator_share` = main's tokens ÷ all tokens, `peak_context` = max over main requests of input+cache_read+cache_creation, `turns` (prompt events), `wall_clock_s`, `agents` list with first/last ts and request count
- [ ] Every metric object has `source`; unavailable values are `null` with `_reason`
- [ ] Totals over a fixture equal the sum of its `usage` events (test)

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_session_metrics.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Write failing tests** using the `write`/`asst` helpers pattern from Task 1's test (copy them into this test file; there are no differences in behaviour): one session with main requests (inputs 10 and 20, cache_read 100 and 300) and one `sub:x` request; assert `peak_context == 320`, `orchestrator_share` computed from those numbers, `agents` has two entries, and `totals.output` equals the sum of outputs.
- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implement** with `transcripts.iter_events`; output `peak_context` with `"source": "measured"` and `orchestrator_share` with `"source": "derived"`. Usage of a teammate session (separate session file with `agentName`) is attributed to its `team:` agent but kept under its own session id; also emit `totals.by_agent_kind` (`main`/`sub`/`team`).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(audit): session metrics` + attribution trailer.

```json:metadata
{"files": ["tools/audit/session_metrics.py", "tools/audit/tests/test_session_metrics.py"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_session_metrics.py' -v", "acceptanceCriteria": ["CLI writes sessions+totals JSON", "per-session model/agent tokens, orchestrator_share, peak_context, turns, wall_clock, agents", "source tags and null+reason", "totals equal fixture usage sum"], "modelTier": "standard"}
```

---

### Task 3: Waste signals

**Goal:** `waste_signals.py` reports deterministic duplication and stagnation signals per session.

**Files:**
- Create: `tools/audit/waste_signals.py`, `tools/audit/tests/test_waste_signals.py`

**Acceptance Criteria:**
- [ ] `repeat_reads`: per (agent, target) for Read-family tools, count ≥ 3 listed with count
- [ ] `repeat_commands`: same Bash `args_key` run ≥ 2 times whose results had equal `size` and `is_error` (identical-outcome proxy, labelled `derived`)
- [ ] `repeat_failures`: same `args_key` with `is_error` true ≥ 2 times
- [ ] `tool_output_share`: sum of tool_result sizes ÷ (sum of tool_result + prompt + injection sizes), chars, `derived`
- [ ] `cross_agent_duplicate_reads`: targets Read by ≥ 2 distinct agents in one session
- [ ] `idle_tail_s` per sub/team agent: seconds between its last tool_use and its last event (`derived`, null with reason if no ts)
- [ ] CLI `--root --repo --days --out` like Task 2

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_waste_signals.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Write failing tests**, one per criterion, on synthetic events (build the event dicts directly and pass them to a pure function `signals(events) -> dict`, so tests don't depend on file parsing).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** `signals(events)` plus the CLI wrapper over `transcripts.iter_events`. Read-family = `Read`, `Grep`, `Glob`, and Bash commands starting with `cat `, `sed -n`, `head `, `grep ` (target = the command).
- [ ] **Step 4: Run → PASS.**
- [ ] **Step 5: Commit** `feat(audit): waste signals` + attribution trailer.

```json:metadata
{"files": ["tools/audit/waste_signals.py", "tools/audit/tests/test_waste_signals.py"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_waste_signals.py' -v", "acceptanceCriteria": ["repeat_reads", "repeat_commands identical-outcome proxy", "repeat_failures", "tool_output_share", "cross_agent_duplicate_reads", "idle_tail_s", "CLI"], "modelTier": "standard"}
```

---

### Task 4: Injection costs

**Goal:** `injection_costs.py` measures what always-on and injected text costs per session, by source.

**Files:**
- Create: `tools/audit/injection_costs.py`, `tools/audit/tests/test_injection_costs.py`

**Acceptance Criteria:**
- [ ] Per source (`injection.source`): sessions seen, total chars, median chars per session, count per session
- [ ] `first_request_prompt_tokens` per session = first main request's input + cache_read + cache_creation (`measured`): the real size of the always-on prompt
- [ ] `static_files`: char size of each file that is always loaded, read from disk now — `~/.claude/CLAUDE.md`, each repo's `CLAUDE.md`, the orchestrator prompt file (find its path from `bin/` or `claude/` in this repo; record the path used) — with `source: measured` and `"tokens_estimate"` = chars/4 marked `derived`
- [ ] CLI `--root --repo --days --out`

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_injection_costs.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Find the orchestrator prompt source.** `grep -rn "Orchestrator mode" ~/agent-board/bin ~/agent-board/claude ~/agent-board/config | head` — record the file in the module docstring.
- [ ] **Step 2: Write failing tests** for a pure `costs(events) -> dict` on synthetic injection and usage events (two sessions, two sources) and for `static_files(paths)` on temp files.
- [ ] **Step 3: Run → FAIL.**
- [ ] **Step 4: Implement**, then **Step 5: Run → PASS.**
- [ ] **Step 6: Commit** `feat(audit): injection costs` + attribution trailer.

```json:metadata
{"files": ["tools/audit/injection_costs.py", "tools/audit/tests/test_injection_costs.py"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_injection_costs.py' -v", "acceptanceCriteria": ["per-source sessions/total/median/count", "first_request_prompt_tokens measured", "static_files sizes incl. orchestrator prompt path", "CLI"], "modelTier": "standard"}
```

---

### Task 5: Handoff trace

**Goal:** `handoff_trace.py` finds handoffs and compactions and measures what the following session spends before new work.

**Files:**
- Create: `tools/audit/handoff_trace.py`, `tools/audit/tests/test_handoff_trace.py`

**Acceptance Criteria:**
- [ ] Detects compaction events (the `system.subtype` value(s) Task 1 Step 1 found for compaction; record which) with the main context size at the last request before it
- [ ] Detects handoff-started sessions: first prompt's `text_head` mentions `/handoffs/` or `handoff`; links it to the previous session in the same repo by time, where determinable (else `null` + reason)
- [ ] For each resumed session: `tokens_to_first_edit` and `seconds_to_first_edit` (first `Edit`/`Write`/`NotebookEdit` tool_use), `reads_before_first_edit`, and `reread_overlap` = share of its pre-edit Read targets that the previous session also read (`derived`)
- [ ] Distribution summary: context size at handoff/compaction (min/median/max)
- [ ] CLI `--root --repo --days --out`

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_handoff_trace.py' -v` → all OK

**Steps:**

- [ ] **Step 1: Find how handoffs are triggered**, read-only: `grep -rln "300" ~/agent-board/claude/plugin/hooks ~/agent-board/bin | xargs grep -ln -i handoff` and read the handoff skill `~/agent-board/claude/plugin/skills/handoff/SKILL.md`; note in the module docstring which marker a handoff leaves in transcripts.
- [ ] **Step 2: Write failing tests** on synthetic events: a session with a compaction line after a request with context 280000; a later session whose first prompt names `~/.local/state/agent-board/handoffs/x.md`, reads two files (one also read by the first session), then edits.
- [ ] **Step 3: Run → FAIL.** **Step 4: Implement.** **Step 5: Run → PASS.**
- [ ] **Step 6: Commit** `feat(audit): handoff trace` + attribution trailer.

```json:metadata
{"files": ["tools/audit/handoff_trace.py", "tools/audit/tests/test_handoff_trace.py"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_handoff_trace.py' -v", "acceptanceCriteria": ["compaction detection with context size", "handoff-started session detection and linking", "tokens/seconds/reads to first edit, reread_overlap", "context-at-handoff distribution", "CLI"], "modelTier": "standard"}
```

---

### Task 6: Findings checker and redaction check

**Goal:** Two small checks every report task uses as its Verify: findings format and secret scan.

**Files:**
- Create: `tools/audit/check_findings.py`, `tools/audit/redact_check.sh`, `tools/audit/tests/test_checks.py`

**Acceptance Criteria:**
- [ ] `check_findings.py FILE [--require-heading TEXT ...] [--min-findings N]` prints `OK <n> findings` and exits 0, or prints one line per problem and exits 1
- [ ] A finding block (from `### F-` to the next `### ` or `## `) must have lines starting `Label:`, `Evidence:`, `Confidence:`; Label ∈ {Verified, Measured, Hypothesis}; Evidence not empty and not `none` when Label is Verified or Measured
- [ ] `redact_check.sh FILE...` exits 1 and prints `file:line` for any match, 0 and prints `redact: clean (<n> files)` otherwise
- [ ] Task 1's fixtures pass `redact_check.sh`

**Verify:** `python3 -m unittest discover -s tools/audit/tests -p 'test_checks.py' -v && find tools/audit/tests/fixtures -name '*.jsonl' -exec bash tools/audit/redact_check.sh {} +` → tests OK, then `redact: clean (…)`

**Steps:**

- [ ] **Step 1: Write the failing tests** `tools/audit/tests/test_checks.py`:

```python
import os, subprocess, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__)); AUDIT = os.path.dirname(HERE)

GOOD = """## Findings
### F-sieve-1: Observer scan runs every session
Label: Measured
Evidence: injection_costs.json sources["hook:SessionStart"].total_chars=41210
Component · Root cause · Impact
Confidence: high · Candidate change · How to validate
"""
BAD = """### F-sieve-2: Claim with no evidence
Label: Verified
Evidence: none
"""

def run(*args):
    return subprocess.run(list(args), capture_output=True, text=True)

def tmp(text):
    fd, p = tempfile.mkstemp(suffix=".md"); os.write(fd, text.encode()); os.close(fd); return p

class Checks(unittest.TestCase):
    def test_good_passes(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--require-heading", "Findings")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("OK 1 findings", r.stdout)

    def test_verified_without_evidence_fails(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(BAD))
        self.assertEqual(r.returncode, 1); self.assertIn("F-sieve-2", r.stdout)

    def test_missing_heading_fails(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--require-heading", "Roadmap")
        self.assertEqual(r.returncode, 1)

    def test_min_findings(self):
        r = run(sys.executable, os.path.join(AUDIT, "check_findings.py"), tmp(GOOD), "--min-findings", "2")
        self.assertEqual(r.returncode, 1)

    def test_redact_flags_key(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("token glpat-" + "a" * 20 + "\n"))
        self.assertEqual(r.returncode, 1)

    def test_redact_clean(self):
        r = run("bash", os.path.join(AUDIT, "redact_check.sh"), tmp("nothing here\n"))
        self.assertEqual(r.returncode, 0); self.assertIn("redact: clean (1 files)", r.stdout)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run → FAIL** (files missing).
- [ ] **Step 3: Write `redact_check.sh`:**

```bash
#!/usr/bin/env bash
# usage: redact_check.sh FILE... — fails on secret-shaped strings
set -u
pat='AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{20}|sk-ant-[A-Za-z0-9_-]{10,}|xox[abprs]-[A-Za-z0-9-]{10,}|"private_key"[[:space:]]*:|AIza[0-9A-Za-z_-]{35}|(password|passwd|secret)[[:space:]]*[:=][[:space:]]*[^[:space:]<]{6,}'
[ "$#" -gt 0 ] || { echo "redact: no files given"; exit 2; }
if grep -nEiH -- "$pat" "$@"; then exit 1; fi
echo "redact: clean ($# files)"
```

- [ ] **Step 4: Write `check_findings.py`:**

```python
#!/usr/bin/env python3
"""Validate the runtime-audit findings format. usage: check_findings.py FILE [--require-heading T]... [--min-findings N]"""
import argparse, re, sys

LABELS = {"Verified", "Measured", "Hypothesis"}

def blocks(text):
    out, cur = [], None
    for line in text.splitlines():
        if line.startswith("### F-"):
            cur = [line]; out.append(cur)
        elif line.startswith("### ") or line.startswith("## "):
            cur = None
        elif cur is not None:
            cur.append(line)
    return out

def problems(block):
    title = block[0][4:].split(":")[0]
    fields = {}
    for l in block[1:]:
        m = re.match(r"(Label|Evidence|Confidence):\s*(.*)", l)
        if m: fields[m.group(1)] = m.group(2).strip()
    errs = [f"{title}: missing {k}:" for k in ("Label", "Evidence", "Confidence") if k not in fields]
    label = fields.get("Label", "").split()[0] if fields.get("Label") else ""
    if "Label" in fields and label not in LABELS:
        errs.append(f"{title}: Label {label!r} not in {sorted(LABELS)}")
    if label in ("Verified", "Measured") and fields.get("Evidence", "").lower() in ("", "none", "n/a"):
        errs.append(f"{title}: {label} finding without evidence")
    return errs

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("file")
    ap.add_argument("--require-heading", action="append", default=[])
    ap.add_argument("--min-findings", type=int, default=0)
    a = ap.parse_args()
    text = open(a.file, encoding="utf-8").read()
    bs = blocks(text); errs = [e for b in bs for e in problems(b)]
    heads = [l.lstrip("#").strip() for l in text.splitlines() if l.startswith("#")]
    errs += [f"missing heading containing {h!r}" for h in a.require_heading if not any(h in x for x in heads)]
    if len(bs) < a.min_findings:
        errs.append(f"{len(bs)} findings, need at least {a.min_findings}")
    for e in errs: print(e)
    if errs: return 1
    print(f"OK {len(bs)} findings"); return 0

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the Verify command → tests OK and `redact: clean`.** If a fixture is flagged, fix `capture_fixture.py` redaction and recapture (Task 1 files) rather than editing the fixture by hand.
- [ ] **Step 6: Commit** `feat(audit): findings and redaction checks` + attribution trailer.

```json:metadata
{"files": ["tools/audit/check_findings.py", "tools/audit/redact_check.sh", "tools/audit/tests/test_checks.py"], "verifyCommand": "python3 -m unittest discover -s tools/audit/tests -p 'test_checks.py' -v && find tools/audit/tests/fixtures -name '*.jsonl' -exec bash tools/audit/redact_check.sh {} +", "acceptanceCriteria": ["check_findings OK/exit codes", "block field and label rules", "redact_check exit codes and clean line", "fixtures pass redact_check"], "modelTier": "mechanical"}
```

---

### Task 7: Baseline run over real state

**Goal:** `run_baseline.sh` produces the full metrics set for the agreed scope from the real transcripts.

**Files:**
- Create: `tools/audit/run_baseline.sh`

**Acceptance Criteria:**
- [ ] Writes `audit-out/<YYYY-MM-DD>/{session_metrics,waste_signals,injection_costs,handoff_trace}.json` and `manifest.json` (scope, window, file count, event counts per kind, toolkit git sha)
- [ ] Runs read-only against the real `~/.claude/projects` (aged, multi-session, multi-agent state — the real-state check)
- [ ] Every output parses as JSON; `manifest.json` event counts are all > 0 for `usage`, `tool_use`, `tool_result`
- [ ] The whole test suite still passes

**Verify:** `bash tools/audit/run_baseline.sh && python3 -c "import json,glob,sys; m=json.load(open(sorted(glob.glob('audit-out/*/manifest.json'))[-1])); c=m['event_counts']; print(c); sys.exit(0 if all(c.get(k,0)>0 for k in ('usage','tool_use','tool_result')) else 1)" && python3 -m unittest discover -s tools/audit/tests -p 'test_*.py'` → counts printed, exit 0, tests OK

**Steps:**

- [ ] **Step 1: Write `run_baseline.sh`:**

```bash
#!/usr/bin/env bash
# usage: run_baseline.sh [days] — runs every audit metric over the agreed scope, read-only
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; top="$(git -C "$here" rev-parse --show-toplevel)"
days="${1:-30}"; root="$HOME/.claude/projects"
out="$top/audit-out/$(date +%F)"; mkdir -p "$out"
repos=(--repo /Users/francisco.ruiz/master-gcp-repo --repo /Users/francisco.ruiz/agent-board)
for m in session_metrics waste_signals injection_costs handoff_trace; do
  python3 "$here/$m.py" --root "$root" "${repos[@]}" --days "$days" --out "$out/$m.json"
  echo "wrote $out/$m.json"
done
python3 "$here/transcripts.py" --manifest --root "$root" "${repos[@]}" --days "$days" \
  --sha "$(git -C "$here" rev-parse --short HEAD)" --out "$out/manifest.json"
echo "wrote $out/manifest.json"
```

The manifest comes from `transcripts.py --manifest`. Add that CLI mode to `transcripts.py`: it writes `{"scope": repos, "days": N, "files": <count>, "event_counts": {kind: n}, "toolkit_sha": sha, "generated": iso}`; add one unit test for it in `test_transcripts.py`.

- [ ] **Step 2: Run the Verify command.** Expect a few minutes over ~600 MB. If any metric crashes on real data, fix it under superpowers-extended-cc:systematic-debugging with a new fixture captured from the offending file.
- [ ] **Step 3: Record runtime and counts** in the commit body.
- [ ] **Step 4: Commit** `feat(audit): baseline runner` (`run_baseline.sh`, `transcripts.py`, test) + attribution trailer. `audit-out/` stays uncommitted.

```json:metadata
{"files": ["tools/audit/run_baseline.sh", "tools/audit/transcripts.py", "tools/audit/tests/test_transcripts.py"], "verifyCommand": "bash tools/audit/run_baseline.sh && python3 -c \"import json,glob,sys; m=json.load(open(sorted(glob.glob('audit-out/*/manifest.json'))[-1])); c=m['event_counts']; print(c); sys.exit(0 if all(c.get(k,0)>0 for k in ('usage','tool_use','tool_result')) else 1)\" && python3 -m unittest discover -s tools/audit/tests -p 'test_*.py'", "acceptanceCriteria": ["four metric JSON files + manifest", "read-only run on real aged transcripts", "manifest usage/tool_use/tool_result counts > 0", "full suite passes"], "modelTier": "mechanical"}
```

---

### Task 8: Discovery — atlas (architecture and state)

**Goal:** `docs/superpowers/reports/runtime-audit/atlas.md` maps the current architecture and the source of truth for each kind of state.

**Files:**
- Create: `docs/superpowers/reports/runtime-audit/atlas.<your-name>.md` (the lead promotes it to `atlas.md`)

**Acceptance Criteria:**
- [ ] Sections: `## Components`, `## Diagram`, `## State sources of truth`, `## Implicit state`, `## Findings`
- [ ] Components table covers: board frontend and backend, project switching, tmux session lifecycle, `dev` and `tmux-ctl`, Claude launch, agent spawn/termination, task queue and ideas, handoff, persistent state, logs and telemetry, completion detection; each row cites file:line
- [ ] Diagram is a mermaid block of components and data flow
- [ ] State table has one row each for project, task, agent, terminal/session and usage/telemetry state: where it lives, who writes, who reads, survives tmux loss (yes/no)
- [ ] `## Implicit state` lists every place state lives only in tmux output, conversation history or prompt conventions
- [ ] The usage/telemetry row says whether `board/usage.py` (or other board code) reads subscription quota or limits; if it does, that code is the cited source, otherwise quota is recorded as out of scope
- [ ] Findings in the common format, at least 3; read-only (no edits outside the report file)

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/atlas.md --require-heading Components --require-heading Diagram --require-heading "State sources of truth" --require-heading "Implicit state" --require-heading Findings --min-findings 3 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/atlas.md` → `OK n findings`, `redact: clean (1 files)`

**Constraints:** read the code and `audit-out/<date>/*.json`; open raw transcripts only to check a session a metric points at. Label every claim Verified/Measured/Hypothesis. Commit the report file only: `docs(audit): atlas findings` + attribution trailer.

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/atlas.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/atlas.md --require-heading Components --require-heading Diagram --require-heading \"State sources of truth\" --require-heading \"Implicit state\" --require-heading Findings --min-findings 3 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/atlas.md", "acceptanceCriteria": ["five sections", "components table with file:line", "mermaid diagram", "state table 5 rows incl. survives tmux loss", "implicit state list", "quota source or out-of-scope noted", ">=3 findings, read-only"], "modelTier": "standard"}
```

---

### Task 9: Discovery — sieve (hooks, skills, observer, context cost)

**Goal:** `docs/superpowers/reports/runtime-audit/sieve.md` documents every hook and observer mechanism and the always-on context, with measured costs and overlaps.

**Files:**
- Create: `docs/superpowers/reports/runtime-audit/sieve.<your-name>.md` (promoted to `sieve.md`)

**Acceptance Criteria:**
- [ ] Sections: `## Mechanisms`, `## Always-on context`, `## Overlap matrix`, `## Observer value`, `## Findings`
- [ ] Mechanisms table: one row per hook registered in `~/.claude/settings.json`, each enabled plugin's `hooks.json`, and the repo's `claude/plugin/hooks/hooks.json`, plus task-observer — columns trigger, frequency, implementation (script/model/both), context cost, runtime, purpose, outcome, failure behaviour, overlap. Frequency and context cost come from `injection_costs.json` (cite the key) or say `unmeasured — needs <instrument>`; runtime from a read-only timing probe or `unmeasured`
- [ ] Row count check: the number of table rows ≥ the number of hook entries counted by a command recorded in the report (e.g. a `python3 -c` over the hooks files), so no hook is skipped
- [ ] Always-on context: `first_request_prompt_tokens` median from `injection_costs.json`, and the `static_files` breakdown
- [ ] Overlap matrix: rule × places it is enforced (CLAUDE.md, orchestrator prompt, skill, hook)
- [ ] Observer value: from `~/.task-observer/skill-observations/` — observations logged in the window, how many reached `actioned`, and what the review changed; compared with its measured cost
- [ ] Findings ≥ 4 in the common format; read-only

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/sieve.md --require-heading Mechanisms --require-heading "Always-on context" --require-heading "Overlap matrix" --require-heading "Observer value" --require-heading Findings --min-findings 4 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/sieve.md` → `OK n findings`, `redact: clean (1 files)`

**Constraints:** respect the installed Superpowers behaviour (read how skills load, do not assume). Timing probes run hooks with dummy stdin in a temp dir, never against live state that they would modify; if a hook writes state, mark runtime `unmeasured` instead. Commit the report only: `docs(audit): sieve findings` + attribution trailer.

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/sieve.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/sieve.md --require-heading Mechanisms --require-heading \"Always-on context\" --require-heading \"Overlap matrix\" --require-heading \"Observer value\" --require-heading Findings --min-findings 4 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/sieve.md", "acceptanceCriteria": ["five sections", "mechanisms table with 9 columns, costs cited or unmeasured", "row count >= recorded hook count", "always-on context from measured first-request tokens", "overlap matrix", "observer value vs cost", ">=4 findings, read-only"], "modelTier": "standard"}
```

---

### Task 10: Discovery — relay (routing, lifecycle, handoff, recovery)

**Goal:** `docs/superpowers/reports/runtime-audit/relay.md` judges whether orchestration, routing, parallelism and handoff earn their cost, with one real task traced end to end.

**Files:**
- Create: `docs/superpowers/reports/runtime-audit/relay.<your-name>.md` (promoted to `relay.md`)

**Constraints:** read-only; work from code, `audit-out/<date>/*.json`, and the transcripts of the one traced task. Do not assume the Opus orchestrator is wasteful; judge from evidence. Commit the report only: `docs(audit): relay findings` + attribution trailer.

**Acceptance Criteria:**
- [ ] Sections: `## Task trace`, `## Model routing`, `## Orchestrator cost`, `## Parallelism`, `## Handoff and recovery`, `## Findings`
- [ ] Task trace: one real multi-agent task from the window (session ids named) traced intake → completion across the brief §5.2 items, with where work was duplicated, decisions were expensive, failures went undetected, context was lost
- [ ] Model routing: how tiers are chosen and enforced (cite gate files), whether routed models matched task tiers in the window (from `session_metrics.json` models by agent), whether retries escalate
- [ ] Orchestrator cost: distribution of `orchestrator_share` and what decisions the orchestrator made for it
- [ ] Parallelism: for multi-agent sessions, `cross_agent_duplicate_reads`, `idle_tail_s` and file-overlap evidence; a verdict on when it paid off
- [ ] Handoff and recovery: how the ~300K trigger is measured (hard/warning/estimate; native or custom), context-at-handoff distribution and `reread_overlap` from `handoff_trace.json`, what state is persisted, duplicate-execution and stale-state risks
- [ ] Findings ≥ 5 in the common format

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/relay.md --require-heading "Task trace" --require-heading "Model routing" --require-heading "Orchestrator cost" --require-heading Parallelism --require-heading "Handoff and recovery" --require-heading Findings --min-findings 5 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/relay.md` → `OK n findings`, `redact: clean (1 files)`

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/relay.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/relay.md --require-heading \"Task trace\" --require-heading \"Model routing\" --require-heading \"Orchestrator cost\" --require-heading Parallelism --require-heading \"Handoff and recovery\" --require-heading Findings --min-findings 5 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/relay.md", "acceptanceCriteria": ["six sections", "one real task traced with session ids", "routing tiers vs actual models", "orchestrator_share distribution", "parallelism verdict with metrics", "handoff trigger mechanics and trace stats", ">=5 findings"], "modelTier": "frontier"}
```

---

### Task 11: Synthesis — draft report (lens)

**Goal:** `docs/superpowers/reports/runtime-audit/report.md` is the full draft of the Claude Doc, built only from the three area files and `audit-out/`.

**Files:**
- Create: `docs/superpowers/reports/runtime-audit/report.md`

**Constraints:** do not redo discovery; resolve a conflict between area findings with one targeted read-only probe or present both sides. Never present estimated savings as measured. D4 and D5 appear only as "what the evidence implies" notes. Commit: `docs(audit): draft runtime audit report` + attribution trailer.

**Acceptance Criteria:**
- [ ] Eight sections exactly as the spec's "Component 3" list: `## Summary`, `## Current-state architecture`, `## Baseline measurements`, `## Efficiency audit`, `## Hypotheses`, `## Expanded ideas`, `## Roadmap`, `## Measurement plan`
- [ ] Summary has ≤ 5 lines plus 3–5 next actions, each a concrete engineering task
- [ ] Efficiency audit: findings ranked by expected benefit in the common format, each keeping its source area id (`F-atlas-2` etc.)
- [ ] Hypotheses: H1–H6 each marked confirmed / refuted / unmeasured with evidence
- [ ] Baseline measurements lists what is not observable and the instrument each gap needs
- [ ] Roadmap: phases 1–4, each item with benefit, effort, risk, dependencies, validation, rollback
- [ ] Measurement plan names 8–10 benchmark tasks from real sessions in the window (session ids) with acceptance criteria and risk level

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/report.md --require-heading Summary --require-heading "Current-state architecture" --require-heading "Baseline measurements" --require-heading "Efficiency audit" --require-heading Hypotheses --require-heading "Expanded ideas" --require-heading Roadmap --require-heading "Measurement plan" --min-findings 8 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/report.md` → `OK n findings`, `redact: clean (1 files)`

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/report.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/report.md --require-heading Summary --require-heading \"Current-state architecture\" --require-heading \"Baseline measurements\" --require-heading \"Efficiency audit\" --require-heading Hypotheses --require-heading \"Expanded ideas\" --require-heading Roadmap --require-heading \"Measurement plan\" --min-findings 8 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/report.md", "acceptanceCriteria": ["eight spec sections", "summary + 3-5 concrete next actions", "ranked findings with area ids", "H1-H6 verdicts", "unobservable metrics + instruments", "roadmap phases with 6 attributes", "8-10 benchmark tasks with session ids"], "modelTier": "frontier"}
```

---

### Task 12: Independent evidence review (probe)

**Goal:** `docs/superpowers/reports/runtime-audit/probe-review.md` re-checks the report's evidence independently of its authors.

**Files:**
- Create: `docs/superpowers/reports/runtime-audit/probe-review.md`

**Constraints:** the reviewer did not author Tasks 8–11. Use superpowers-extended-cc:requesting-code-review with requesting-code-review-extras. Re-run evidence yourself: open each cited file:line, re-read each cited metric key from `audit-out/<date>/`, open each cited session. Do not edit `report.md`. Commit: `docs(audit): probe evidence review` + attribution trailer.

**Acceptance Criteria:**
- [ ] Sample of ≥ 10 findings, including every Verified finding in the report's top 5
- [ ] Per sampled finding a `### F-…` block with `Label:` (the label the evidence supports), `Evidence:` (what was re-checked and the observed value), `Confidence:`, and a verdict line `Verdict: holds | relabel <label> | drop`
- [ ] A `## Summary` with counts per verdict
- [ ] An all/none claim (e.g. "every hook is listed") is checked against uncapped output with its count

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/probe-review.md --require-heading Summary --min-findings 10 && grep -c '^Verdict: ' docs/superpowers/reports/runtime-audit/probe-review.md` → `OK n findings` with n ≥ 10, and a Verdict count equal to n

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/probe-review.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/probe-review.md --require-heading Summary --min-findings 10 && grep -c '^Verdict: ' docs/superpowers/reports/runtime-audit/probe-review.md", "acceptanceCriteria": [">=10 sampled incl. all Verified top-5", "per-finding re-check with Verdict line", "summary verdict counts", "all/none claims on uncapped output"], "modelTier": "standard"}
```

---

### Task 13: Apply review and publish the Claude Doc (lens)

**Goal:** The corrected report is published as the Claude Doc "Claude Code Runtime Audit — Baseline 2026-10", and its link is recorded in the repo.

**Files:**
- Modify: `docs/superpowers/reports/runtime-audit/report.md`
- Create: `docs/superpowers/reports/runtime-audit/PUBLISHED.md` (doc link, date, toolkit sha, `audit-out` date)

**Constraints:** load the `anthropic-skills:docs` skill before any Claude Docs call and follow it (skeleton first, then fill sections). Charts use the JSON rows from `audit-out/`, not images. Commit: `docs(audit): publish runtime audit` + attribution trailer.

**Acceptance Criteria:**
- [ ] Every `drop` verdict in `probe-review.md` is removed from `report.md`; every `relabel` is applied (diff shows it)
- [ ] `report.md` still passes the Task 11 Verify
- [ ] The Claude Doc exists with the eight sections, opened for the user, link in `PUBLISHED.md`
- [ ] Redaction check passes on `report.md` immediately before publishing

**Verify:** `python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/report.md --require-heading Summary --require-heading Roadmap --min-findings 8 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/report.md && grep -E 'https://claude\.ai/' docs/superpowers/reports/runtime-audit/PUBLISHED.md` → `OK n findings`, `redact: clean (1 files)`, the doc URL

```json:metadata
{"files": ["docs/superpowers/reports/runtime-audit/report.md", "docs/superpowers/reports/runtime-audit/PUBLISHED.md"], "verifyCommand": "python3 tools/audit/check_findings.py docs/superpowers/reports/runtime-audit/report.md --require-heading Summary --require-heading Roadmap --min-findings 8 && bash tools/audit/redact_check.sh docs/superpowers/reports/runtime-audit/report.md && grep -E 'https://claude\\.ai/' docs/superpowers/reports/runtime-audit/PUBLISHED.md", "acceptanceCriteria": ["drops removed, relabels applied", "report passes Task 11 checks", "Claude Doc with eight sections, link recorded", "redaction clean before publish"], "modelTier": "frontier"}
```

---

## Dependencies

| Task | Blocked by |
| --- | --- |
| 1 | — |
| 2, 3, 4, 5 | 1 |
| 6 | 1 |
| 7 | 2, 3, 4, 5, 6 |
| 8, 9, 10 | 7 |
| 11 | 8, 9, 10 |
| 12 | 11 |
| 13 | 12 |
