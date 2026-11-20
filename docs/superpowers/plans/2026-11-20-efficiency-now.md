# Efficiency Now Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The lead hands off at every spec boundary in queue mode with a small fixed-shape doc, the metrics records say how large each context got, a null limits reading says why, and two probes decide E4 and E5.

**Architecture:** One transcript reader, `board/ctxsize.py`, holds the context-size rule; the context guard, the task records and the run records all read through it or through the usage index it agrees with. A stateless PostToolUse hook in the agent-board plugin nudges the lead at a spec boundary, and the orchestrator rules and the handoff skill carry the rule and the boundary doc's shape. A new pure module, `board/metrics_lead.py`, turns the lineage file and the lead transcripts into the four lead fields of a run record.

**Tech Stack:** Python 3 standard library (unittest), bash and zsh hook tests, jq, the Claude Code plugin hooks file.

**Spec:** `docs/superpowers/specs/2026-11-20-efficiency-now-design.md`

## Global Constraints

- Work in the worktree `/Users/francisco.ruiz/agent-board/.claude/worktrees/efficiency-now` on branch `feat/efficiency-now`. Every command in this plan runs from that directory. Never switch the live checkout's branch.
- Commits: conventional with scope (`feat(metrics): …`, `feat(hooks): …`, `docs(notes): …`). `git add` the task's own paths only, `git commit -- <paths>`. End each commit message with the attribution trailer your harness specifies.
- Agent shells are zsh. Quote a word that starts with `=`. Never name a variable `path`.
- A `metrics` command never fails a spec: every new field that cannot be computed is `null` and its name is added to the record's `missing` list. No new code path in `board/metrics.py`, `board/metrics_tasks.py` or `board/metrics_lead.py` may raise out of `cmd_record` or `cmd_start`.
- Nothing private in a record line or a report line: no session ids, no paths, no agent or user names. The new fields hold numbers, lists of numbers, or one of the fixed reason strings below.
- Old records are never rewritten. A reader of `runs.jsonl` or `tasks.jsonl` must accept a record that lacks the new keys.
- `board/ctxsize.py` never raises to its caller and its CLI always exits 0. On a missing, empty or malformed transcript it returns `None` (the CLI prints nothing).
- The nudge hook is read-only and never blocks: it prints either nothing or one `hookSpecificOutput.additionalContext` object, and exits 0 in every case.
- The context guard's threshold (300000), its bands and its two message texts do not change.
- Hook scripts for agent-board sessions live in `claude/plugin/scripts/` and are registered in `claude/plugin/hooks/hooks.json` as `"${CLAUDE_PLUGIN_ROOT}/scripts/<name>.sh" --scoped`; `tools/tests/test_plugin.zsh` enforces that shape. `claude/settings.json` is a mirror of the user's personal `~/.claude/settings.json` and is not edited by this plan.
- Tests that build a usage `Indexer`, call `metrics.build_record` or read taps set `TC_STATE`, `USAGE_ROOT` and `TC_LINEAGE` to temp dirs (the existing `Base` classes do).
- Board suite runs go through `tmux-ctl run -t 900 tests "<cmd> > <file> 2>&1; echo rc=\$? >> <file>"` and the verdict is read from the file. A single test module may run in the Bash tool.
- The fixed limits reason strings: `backfilled run: no tap reading exists for a past window`, `no statusline tap with rate_limits at record time`, `no statusline tap with rate_limits at start`.

### Metric definitions

Every task cites these by name and does not restate them.

- **main-thread turn.** One distinct `requestId` among a transcript's lines with `type == "assistant"`, `isSidechain` false and a `message.usage` object. Several lines share one `requestId` (one per content block; 323 lines for 203 requests in the lead transcript probed on 2026-11-20); they are one turn and the last such line's usage is the turn's usage. A turn's timestamp is that line's `timestamp`.
- **context size** (of a turn). `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the turn's usage. Output tokens are not part of it. `usage.context_tokens(row)` in `board/usage.py` computes the same quantity from a usage-index row (`input + cache_read + cache_write_5m + cache_write_1h`); `board/tests/test_ctxsize.py` proves the two agree on the same line.
- **`context_tokens`** (task record). The context size of the last usage-index row, by `ts`, among the rows `build_task_lines` attributes to the task's implementer (the `mine` rows) that have `sidechain == 0` and `subagent_file == 0`. Scope: the implementer only, never a reviewer; `null` when the task has no such row.
- **lead session** (of a run window `[lo, hi]`). A transcript in the main checkout's transcript directory (`usage.root() / slug_of(main_root)`, top level only) that the project's lineage file names: either as the `old_session_id` of a lineage line with `lo <= ts <= hi`, or as the **successor** of such a line, or as the successor of the newest lineage line with `ts < lo`.
- **successor** (of a lineage line). The top-level transcript, other than the line's own `old_session_id`, whose first 200 lines hold a `type == "user"` line without `agentName` whose message text contains both the basename of the lineage line's `doc` and the phrase `continue from where the previous session left off`. When several match, the one whose first timestamped line is earliest. None matching: no successor.
- **`lead_context_peak`** (run record). The largest context size over the main-thread turns with `lo <= timestamp <= hi` across the run's lead sessions. Scope: the run's own stamped window only. `null`, and listed in `missing`, when no lead session has a turn in the window.
- **`lead_handoffs`** (run record; decided by the lead, 2026-11-20). The number of lineage lines with `prev_end < ts <= hi`, where `prev_end` is the latest `ended_at` among the same batch's other run records that ended before `lo`. Without such a record the lines with `lo <= ts <= hi` are counted. The boundary handoff, which happens after the previous spec's `record` and before this spec's `start`, so belongs to the run that follows it. Scope: handoffs only, never `/compact`. The existing `handoffs` field (lineage lines in `[lo, hi]`) stays as it is.
- **counted handoffs** (of a run). The lineage lines `lead_handoffs` counts, in `ts` order.
- **`post_handoff_tokens`** (run record). A list with one entry per counted handoff: the sum of `input_tokens + cache_read_input_tokens + cache_creation_input_tokens + output_tokens` over the successor's first 10 main-thread turns (fewer when it has fewer). An entry is `null` when the handoff has no successor.
- **`rereads`** (run record). A list with one entry per counted handoff: the number of files in both read sets, the successor's over its first 10 main-thread turns and the previous lead's (`old_session_id`'s transcript) over its whole session. A session's **read set** holds, from the `tool_use` blocks of its main-thread assistant lines: every `Read` block's `input.file_path`; and for every `Bash` block's `input.command`, split into segments at `|`, `||`, `&&`, `;` and newlines and each segment tokenised with `shlex.split` (a segment that does not tokenise is skipped), when the segment's first token has the basename `cat`, `sed`, `head`, `tail` or `grep`, each later token that does not start with `-` and that, joined to the line's `cwd` when relative, is an existing file at record time. Paths are compared after `os.path.normpath`. Known limits, stated wherever a verdict is drawn from it: a `cd` inside the command is not followed, a file deleted since is not counted, and `Grep`/`Glob` tool calls are not reads. An entry is `null` when the successor or the previous lead's transcript is missing.
- **handoff-doc tokens.** The doc's character count divided by 4, rounded down. The budget is 3000. A section starts at a line beginning `## `; the text before the first one is `(top)`.

**User decisions (already made):**
- D1: this spec changes what runs today; the engine and loop spec edits E1-E3 are separate, and E4 and E5 follow this spec's probes.
- D2: "in queue mode, the lead hands off after every finished `Plan & run:` spec (merged, kept, failed or awaiting approval), before the next spec's `writing-plans`, whenever another `Plan & run:` task is pending."
- D3: "context size is recorded for both roles": each task record gets the implementer's context at the task's end, each run record the lead's peak and its handoff count.
- §1a (approved 2026-11-20): the boundary doc's include rule, its fixed four-part shape, the budget of about 3K tokens with a warning that never blocks, and the two measurements `post_handoff_tokens` and `rereads`.

**Planner's assumptions (A1 and A2 are approved; the lead may overrule A3 to A6, each is plan text only):**
- A1 (approved by the lead, 2026-11-20). `lead_handoffs` counts the lineage lines with `prev_end < ts <= ended_at`, and `lead_context_peak` uses the run's own window. The spec's literal "lead sessions in the window, minus one" gives 0 for a boundary handoff, because the order record-then-handoff puts it between two windows, and the spec's gate needs `lead_handoffs >= 1`.
- A2 (approved by the lead, 2026-11-20). The nudge hook is registered only in the plugin's `hooks.json`, with `claude/hooks/spec-boundary-nudge.sh` as a symlink to `claude/plugin/scripts/spec-boundary-nudge.sh`. Nothing is added to `claude/settings.json`: it is not live for agent-board sessions, and registering in both would fire the hook twice.
- A3. `missing_reason` is an object keyed by the missing field (`{"limits": "<reason>"}`), not a bare string, so a second field can carry a reason later. `limits` keeps its `{"start": …, "record": …}` shape; every reader of it already handles nulls inside.
- A4. Task `context_tokens` comes from the usage index rows, not from statusline taps. The taps do carry a context figure (`context_window.current_usage`), but a tap is one file per session, overwritten on every refresh, so it cannot give the figure at the end of an earlier task. Task 0 records this with evidence.
- A5. `ctxsize.context_tokens` reads back from the end of the file until it finds a main-thread turn. The guard's old `tail -n 400` gave up when the last 400 lines held none; the new reader then still finds the older turn. Same number in every other case (checked on a real 8 MB lead transcript: 335235 from both).
- A6. A preliminary reading on 2026-11-20 found all 13 limits-null run records are `backfilled: true` in batch `backfill`, where `build_record` sets limits to null on purpose (`board/metrics.py:705-708`). Task 0 confirms or refutes this with counts before Task 7 writes the reasons.

## File Structure

| File | Responsibility |
|---|---|
| `board/ctxsize.py` (new) | The context-size rule over a transcript: `context_tokens`, `peak`, `turns`, `first_turns_tokens`, `doc_estimate`, and the `last` / `peak` / `doc` CLI |
| `board/metrics_lead.py` (new) | Lead sessions of a run window from the lineage file and the transcript directory; `lead_fields(...)`; read sets for `rereads` |
| `board/metrics_tasks.py` | Task records gain `context_tokens` and `missing` |
| `board/metrics.py` | `build_record` adds the lead fields and `missing_reason`; `cmd_start` adds `missing_reason`; the report prints the Lead lines and the limits reasons |
| `claude/hooks/context-size-guard.sh` | Reads its number from `board/ctxsize.py` |
| `claude/plugin/scripts/spec-boundary-nudge.sh` (new), `claude/hooks/spec-boundary-nudge.sh` (new link) | The spec-boundary nudge hook |
| `claude/plugin/hooks/hooks.json` | Registers the nudge on PostToolUse `TaskUpdate` |
| `claude/orchestrator.md`, `claude/plugin/skills/handoff/SKILL.md` | The boundary rule, the trigger, the include rule, the fixed shape, the budget warning |
| `board/tests/test_ctxsize.py`, `board/tests/test_metrics_lead.py`, `board/tests/test_boundary_rules.py` (new) | Tests |
| `board/tests/fixtures/ctxsize/` (new) | Real trimmed transcript lines and their README |
| `claude/hooks/tests/test-spec-boundary-nudge.sh` (new), `claude/hooks/tests/fixtures/taskupdate-posttooluse.json` (new), `claude/hooks/tests/fixtures/README.md` (new) | Nudge hook tests and the captured payload |
| `docs/superpowers/notes/2026-11-20-limits-gap-cause.md`, `…/<run date>-worker-context-probe.md`, `…/<run date>-code-mode-hooks-probe.md` (new) | The cause note and the two probe notes |
| `docs/superpowers/specs/2026-11-10-pcee-engine-design.md`, `docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md` | E4 and E5 applied or closed |

---

### Task 0: Limits gap cause and the tap's context figure

**Goal:** A note that states, with counts from the real records and the code lines that produce them, why run records have no limits reading, and whether statusline taps can supply a per-task context figure.

**Files:**
- Create: `docs/superpowers/notes/2026-11-20-limits-gap-cause.md`
- Read only: `docs/superpowers/metrics/runs.jsonl`, `board/metrics.py` (`cmd_start` near line 198, `build_record` near line 705), `board/usage.py` (`tap_entries`, `plan_limits`), the live tap files in `${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}/statusline/`

**Acceptance Criteria:**
- [ ] The note has exactly these five `## ` sections, in this order: `Counts`, `Code path`, `Cause`, `Tap context figure`, `What the fix records`.
- [ ] `Counts` holds a table over every `kind == "run"` record: one row per combination of limits shape (`start` set or null, `record` set or null), `backfilled`, `window` and whether `limits` is in `missing`, with its count; the counts sum to the number of run records, and that total is printed. It also gives the same count for `kind == "start"` records (`limits` set or null).
- [ ] `Code path` cites file:line for each place that writes a null limits value, and says which records each one produced.
- [ ] `Cause` is one paragraph that names the cause and says whether it is inside or outside our code. If any limits-null record is not explained by a cited code path, the note says so and lists those records by `spec` and `at`.
- [ ] `Tap context figure` lists the key paths under `context_window` of one live tap payload (key names and number types only, no session id, no path), says how many tap files exist per session, and concludes which source the task `context_tokens` uses and why (assumption A4 confirmed or refuted).
- [ ] `What the fix records` maps each cause found to one of the three fixed limits reason strings in Global Constraints, or proposes a new string and flags it for the lead.
- [ ] The note contains no session id, no absolute home path and no user name.
- [ ] The implementer's report gives the cause in one line, for the lead's ledger.

**Verify:** `grep -c '^## ' docs/superpowers/notes/2026-11-20-limits-gap-cause.md` → `5`

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-20-limits-gap-cause.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/notes/2026-11-20-limits-gap-cause.md", "acceptanceCriteria": ["note has the five sections Counts, Code path, Cause, Tap context figure, What the fix records", "Counts table sums to the number of run records and covers start records", "Code path cites file:line for every null limits write", "Cause names the cause and whether it is in our code; unexplained records are listed", "Tap context figure lists context_window keys and names the source for task context_tokens", "each cause maps to a fixed reason string or a flagged new one", "no session id, home path or user name in the note", "report gives the cause in one line"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Count the records.** Group the run records and the start records as the Counts criterion says. A starting point (read-only; extend the key as needed):

```bash
python3 - <<'EOF'
import collections, json
rows = [json.loads(l) for l in open('docs/superpowers/metrics/runs.jsonl') if l.strip()]
runs = [r for r in rows if r.get('kind') == 'run']
c = collections.Counter()
for r in runs:
    lim = r.get('limits')
    shape = 'null' if lim is None else json.dumps({k: (None if v is None else 'set') for k, v in lim.items()}, sort_keys=True)
    c[(shape, r.get('backfilled'), r.get('window'), 'limits' in (r.get('missing') or []))] += 1
for k, v in sorted(c.items(), key=str):
    print(v, k)
print('runs', len(runs), 'sum', sum(c.values()))
EOF
```

- [ ] **Step 2: Trace each null to its code line** in `board/metrics.py` (`cmd_start`, `build_record`, the backfill path that passes `backfilled=True`) and in `usage.plan_limits`.
- [ ] **Step 3: Inspect one live tap payload's key paths**, never its values of `session_id`, `transcript_path`, `cwd` or `workspace`:

```bash
sd="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}"; f=$(ls -t "$sd"/statusline/*.json | head -1); jq -c 'del(.session_id,.transcript_path,.cwd,.workspace) | paths(scalars) | map(tostring) | join(".")' "$f"
```

- [ ] **Step 4: Write the note**, run the Verify command, and commit: `git add docs/superpowers/notes/2026-11-20-limits-gap-cause.md` then `git commit -m "docs(notes): limits gap cause and the tap's context figure" -- docs/superpowers/notes/2026-11-20-limits-gap-cause.md`.
- [ ] **Step 5: If the cause is not the one in assumption A6**, or a record is unexplained, say so first in your report and message the lead before Task 7 starts: Task 7's reason strings follow from this note.

---

### Task 1: `board/ctxsize.py`, its fixtures and tests

**Goal:** One module that returns a transcript's last and peak context size, its main-thread turns and a handoff doc's token estimate, tested on real trimmed transcript lines.

**Files:**
- Create: `board/ctxsize.py`
- Create: `board/tests/test_ctxsize.py`
- Create: `board/tests/fixtures/ctxsize/lead.jsonl`, `board/tests/fixtures/ctxsize/README.md`

**Acceptance Criteria:**
- [ ] `context_tokens(path)` returns the context size (Metric definitions) of the last main-thread turn, reading from the end of the file; `peak(path, since=None, until=None)` returns the largest context size over the turns in the window (epoch seconds, inclusive, `None` = open).
- [ ] `turns(path)` returns one dict per main-thread turn in file order, `{"ts": <epoch float or None>, "context": <int>, "total": <context + output_tokens>}`, with lines sharing a `requestId` collapsed to the last one; `first_turns_tokens(path, n=10)` returns the sum of `total` over the first `n` turns, or `None` when there are none.
- [ ] `doc_estimate(path, budget=3000)` returns `(line, over)` as in the code below, or `None` for an unreadable file.
- [ ] A missing file, an empty file, a file of non-JSON lines and a JSON line that is not an object each return `None` (or `[]` for `turns`) and raise nothing. The CLI prints nothing for them and exits 0, and exits 0 with no arguments.
- [ ] The fixture `lead.jsonl` is cut from real transcripts on this machine with `tools/audit/capture_fixture.py` and holds: at least three main-thread turns with different timestamps and different context sizes, one of them spread over two or more lines with the same `requestId`; one real sidechain assistant line with usage whose context size is larger than every main-thread turn's; one assistant line without `message.usage`. The README names each source by its basename, the capture command, the date, and any line that was edited by hand and how.
- [ ] `grep -c '/Users/' board/tests/fixtures/ctxsize/lead.jsonl` prints `0`, and the fixture holds no message text (the capture tool replaces it).
- [ ] The tests cover: the last turn; the sidechain line ignored by `context_tokens`, `peak` and `turns`; the line without usage ignored; `peak` over a window that excludes the largest turn; `peak` with only `since`, only `until`, and a window holding no turn (`None`); the shared-`requestId` lines counted as one turn; `first_turns_tokens` with `n` smaller and larger than the turn count; agreement with the usage index (`usage.context_tokens(usage.row_from_line(d, False))` equals the context size for every main-thread turn line of the fixture); the error cases; the three CLI subcommands through `subprocess` with `python3 -I`; `doc_estimate` under and over the budget, naming the largest section.
- [ ] Expected numbers in the tests are literals read from the fixture (the README lists them), not values recomputed by the code under test.

**Verify:** `python3 -m unittest board.tests.test_ctxsize` → `OK`

```json:metadata
{"files": ["board/ctxsize.py", "board/tests/test_ctxsize.py", "board/tests/fixtures/ctxsize/lead.jsonl", "board/tests/fixtures/ctxsize/README.md"], "verifyCommand": "python3 -m unittest board.tests.test_ctxsize", "acceptanceCriteria": ["context_tokens returns the last main-thread turn's context size; peak the largest in the window", "turns collapses lines sharing a requestId; first_turns_tokens sums total over the first n turns", "doc_estimate returns (line, over) or None", "missing, empty, malformed and non-object input return None or [] and the CLI exits 0", "fixture is real, trimmed, with main-thread turns, a shared requestId, a larger sidechain line and a line without usage; README records the capture", "no /Users/ string and no message text in the fixture", "tests cover every listed case including agreement with usage.context_tokens", "expected numbers are literals from the fixture"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Capture the fixture.** Pick a recent lead transcript (a top-level `*.jsonl` in `~/.claude/projects/-Users-francisco-ruiz-agent-board/` whose assistant lines have no `agentName`) and one subagent transcript (`~/.claude/projects/-Users-francisco-ruiz-agent-board/*/subagents/*.jsonl`; its lines have `isSidechain: true`). Capture each with `python3 tools/audit/capture_fixture.py <src> <scratch dst> --max-lines 400` into your scratchpad, then build `lead.jsonl` from selected lines: the main-thread assistant lines of three or more requests (keep every line of at least one multi-line request), one sidechain assistant line with usage, and one assistant line whose `message.usage` is absent. If no real line lacks usage, copy a real captured assistant line, delete its `message.usage` key, and record that edit in the README. If the sidechain line's context size is not the largest, pick another one that is; do not edit its numbers. Keep the capture tool's `fixture-header` first line.
- [ ] **Step 2: Write the README** with the sources' basenames, the commands, the date, the hand edits, and a table of the fixture's turns: line numbers, `requestId` suffix (last 6 characters), timestamp, context size, total.
- [ ] **Step 3: Write `board/tests/test_ctxsize.py`** for the cases in the Acceptance Criteria, with the expected numbers from the README table. Run it and see it fail on the import of `ctxsize`.

Run: `python3 -m unittest board.tests.test_ctxsize`
Expected: an error naming `ctxsize` (the module does not exist yet).

- [ ] **Step 4: Write `board/ctxsize.py`.** This code was run on 2026-11-20 against the existing guard fixture (352042 from `last` and `peak`) and a real 8 MB lead transcript (335235, the same as the guard's `jq` pipeline; 0.04 s). Add `turns` and `first_turns_tokens` to it as the criteria define them, and keep `peak` and `context_tokens` as they are:

```python
#!/usr/bin/env python3
"""ctxsize: the one reader of a transcript's context size.

Context size of a turn = input_tokens + cache_read_input_tokens + cache_creation_input_tokens of a main-thread
(isSidechain false) assistant line with usage. Lines sharing a requestId are one turn; the last line wins.
CLI: ctxsize.py last <transcript> | peak <transcript> [--since ISO] [--until ISO] | doc <handoff doc>. Prints the number
(or the doc line), or nothing; always exits 0."""
import json
import sys
from datetime import datetime

BLOCK = 1 << 20


def _size(d):
    """Context size of one parsed line, or None when it is not a main-thread assistant turn with usage."""
    if not isinstance(d, dict) or d.get("type") != "assistant" or d.get("isSidechain"):
        return None
    u = (d.get("message") or {}).get("usage") if isinstance(d.get("message"), dict) else None
    if not isinstance(u, dict):
        return None
    try:
        return sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    except (TypeError, ValueError):
        return None


def _parse(raw):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        return None


def _epoch(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def context_tokens(transcript_path):
    """Context size at the last main-thread assistant turn, or None. Reads the file from its end, a block at a time."""
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, 2)
            pos, tail = f.tell(), b""
            while pos > 0:
                step = min(BLOCK, pos)
                pos -= step
                f.seek(pos)
                lines = (f.read(step) + tail).split(b"\n")
                tail = lines[0] if pos > 0 else b""
                for raw in reversed(lines[1:] if pos > 0 else lines):
                    if b'"assistant"' in raw:
                        n = _size(_parse(raw))
                        if n is not None:
                            return n
    except OSError:
        return None
    return None


def peak(transcript_path, since=None, until=None):
    """Largest context size over the main-thread assistant turns with since <= timestamp <= until (epoch seconds;
    None = open), or None when no turn is in the window."""
    best = None
    try:
        with open(transcript_path, "rb") as f:
            for raw in f:
                if b'"assistant"' not in raw:
                    continue
                d = _parse(raw)
                n = _size(d)
                if n is None:
                    continue
                if since is not None or until is not None:
                    ts = _epoch(d.get("timestamp"))
                    if ts is None or (since is not None and ts < since) or (until is not None and ts > until):
                        continue
                if best is None or n > best:
                    best = n
    except OSError:
        return None
    return best


DOC_BUDGET = 3000


def doc_estimate(path, budget=DOC_BUDGET):
    """(line, over) for a handoff doc: tokens = characters / 4; a section starts at a line beginning "## " and the text
    before the first one is "(top)". None when the file cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    sections, name = {}, "(top)"
    for line in text.splitlines(keepends=True):
        if line.startswith("## "):
            name = line[3:].strip() or "(untitled)"
        sections[name] = sections.get(name, 0) + len(line)
    total = len(text) // 4
    over = total > budget
    line = f"handoff doc: {total} tokens (budget {budget}): {'over' if over else 'ok'}"
    if over and sections:
        big = max(sections, key=sections.get)
        line += f"; largest section: {big} ({sections[big] // 4} tokens)"
    return line, over


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    try:
        if len(a) == 2 and a[0] == "last":
            n = context_tokens(a[1])
        elif len(a) >= 2 and a[0] == "peak":
            opt = dict(zip(a[2::2], a[3::2]))
            n = peak(a[1], _epoch(opt.get("--since")) if "--since" in opt else None,
                     _epoch(opt.get("--until")) if "--until" in opt else None)
        elif len(a) == 2 and a[0] == "doc":
            got = doc_estimate(a[1])
            if got:
                print(got[0])
            return 0
        else:
            n = None
    except Exception:
        n = None
    if n is not None:
        print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests until green**, then name the mutations in your report by running each once: make `_size` ignore `isSidechain` (the sidechain tests must fail); drop the `requestId` collapse in `turns` (the shared-`requestId` test must fail); make `peak` ignore `until` (the window test must fail). Restore the code after each.
- [ ] **Step 6: Commit.** `git add board/ctxsize.py board/tests/test_ctxsize.py board/tests/fixtures/ctxsize` then `git commit -m "feat(metrics): ctxsize, one reader of a transcript's context size" -- board/ctxsize.py board/tests/test_ctxsize.py board/tests/fixtures/ctxsize`.

---

### Task 2: The context guard reads its number from ctxsize

**Goal:** `context-size-guard.sh` gets its token count from `board/ctxsize.py` and its `jq` pipeline is gone, with thresholds, bands and messages unchanged.

**Files:**
- Modify: `claude/hooks/context-size-guard.sh` (the block from the comment `# Context size = everything sent as input…` through the line `[ -n "$tokens" ] || exit 0`)
- Modify: `claude/hooks/tests/test-context-size-guard.sh` (new checks before the comment `# real-state replay of session 48822fd2 (read-only)`)

**Acceptance Criteria:**
- [ ] The guard calls `python3 -I <reader> last <transcript>`, where `<reader>` is `$CLAUDE_CTXSIZE_PY` when set, else `board/ctxsize.py` two directories above the guard's real path (`realpath "$0"`: the live guard is reached through the link `~/.claude/hooks/context-size-guard.sh`).
- [ ] An empty or non-numeric reader output makes the guard exit 0 with no output.
- [ ] Every existing check in `test-context-size-guard.sh` passes unchanged (33 on 2026-11-20, with the real-transcript replay skipped when that transcript is gone), plus the two new ones: 35 passed, 0 failed.
- [ ] The strings `300000`, `50000` and both message texts in the guard are byte-identical to before: `git diff claude/hooks/context-size-guard.sh` shows changes only inside the block named in Files.
- [ ] Real-state check, read-only: with a real lead transcript `T` from `~/.claude/projects/-Users-francisco-ruiz-agent-board/`, `python3 -I board/ctxsize.py last "$T"` prints the same number as the old pipeline `tail -n 400 "$T" | jq -c 'select(.type == "assistant" and (.isSidechain | not) and .message.usage != null) | .message.usage | (.input_tokens // 0) + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)' | tail -n 1`. Report both numbers.

**Verify:** `bash claude/hooks/tests/test-context-size-guard.sh` → last line `passed=35 failed=0` (`passed=38` when the real 48822fd2 transcript exists)

```json:metadata
{"files": ["claude/hooks/context-size-guard.sh", "claude/hooks/tests/test-context-size-guard.sh"], "verifyCommand": "bash claude/hooks/tests/test-context-size-guard.sh", "acceptanceCriteria": ["guard calls python3 -I <reader> last <transcript>, reader from CLAUDE_CTXSIZE_PY or board/ctxsize.py beside the guard's real path", "empty or non-numeric reader output: exit 0, no output", "all existing checks pass plus two new ones: 35 passed, 0 failed", "thresholds, bands and message texts unchanged", "real-state: ctxsize last equals the old jq pipeline on a real lead transcript"], "modelTier": "mechanical"}
```

**Steps:**

- [ ] **Step 1: Add the two failing checks.** In `claude/hooks/tests/test-context-size-guard.sh`, insert these lines directly above the comment line `# real-state replay of session 48822fd2 (read-only)`:

```bash
# the number comes from board/ctxsize.py: a stub reader's figure is the one reported, and a silent reader keeps the guard silent
printf '#!/usr/bin/env python3\nprint(999000)\n' > "$T/stub.py"
o=$(CLAUDE_CTXSIZE_PY="$T/stub.py" run UserPromptSubmit s10 "$FX")
check "guard reads its number from ctxsize (stub says 999K)" "$(sm "$o" '.systemMessage' | grep -c '999K')" "1"
printf '#!/usr/bin/env python3\n' > "$T/empty.py"
check "reader prints nothing -> guard silent" "$(CLAUDE_CTXSIZE_PY="$T/empty.py" run UserPromptSubmit s11 "$FX" | wc -c | tr -d ' ')" "0"
```

- [ ] **Step 2: Run the test and see the two new checks fail.**

Run: `bash claude/hooks/tests/test-context-size-guard.sh`
Expected: `FAIL guard reads its number from ctxsize (stub says 999K): expected '1', got '0'` and `FAIL reader prints nothing -> guard silent`, last line `passed=33 failed=2`. (This run was made on 2026-11-20 against the unchanged guard.) These two checks are the mutation test of this task: putting the `jq` pipeline back makes exactly them fail.

- [ ] **Step 3: Replace the block in the guard.** In `claude/hooks/context-size-guard.sh`, delete everything from the comment line `# Context size = everything sent as input on the latest main-thread assistant turn.` through the line `[ -n "$tokens" ] || exit 0` (both included) and put this in its place:

```bash
# Context size = everything sent as input on the latest main-thread assistant turn. board/ctxsize.py holds the rule;
# CLAUDE_CTXSIZE_PY points at another reader (tests). This file is reached through a symlink, hence realpath.
self=$(realpath "$0" 2>/dev/null || printf '%s' "$0")
reader="${CLAUDE_CTXSIZE_PY:-$(dirname "$self")/../../board/ctxsize.py}"
tokens=$(python3 -I "$reader" last "$transcript" 2>/dev/null)
case "$tokens" in ''|*[!0-9]*) exit 0 ;; esac
```

The next line of the file stays `sdir="${CLAUDE_CONTEXT_GUARD_STATE:-$HOME/.local/state/agent-board/context-guard}"`.

- [ ] **Step 4: Run the test.**

Run: `bash claude/hooks/tests/test-context-size-guard.sh`
Expected: last line `passed=35 failed=0`.

- [ ] **Step 5: Run the real-state comparison** from the Acceptance Criteria on one real lead transcript and put both numbers in your report.
- [ ] **Step 6: Commit.** `git add claude/hooks/context-size-guard.sh claude/hooks/tests/test-context-size-guard.sh` then `git commit -m "refactor(hooks): the context guard reads its number from ctxsize" -- claude/hooks/context-size-guard.sh claude/hooks/tests/test-context-size-guard.sh`.

---

### Task 3: The spec-boundary nudge hook

**Goal:** A PostToolUse hook on `TaskUpdate` that tells the lead to hand off when a `Plan & run:` task is completed and another is pending, tested on a real captured payload and registered in the plugin.

**Files:**
- Create: `claude/plugin/scripts/spec-boundary-nudge.sh` (mode 755)
- Create: `claude/hooks/spec-boundary-nudge.sh` (a symlink to `../plugin/scripts/spec-boundary-nudge.sh`)
- Create: `claude/hooks/tests/test-spec-boundary-nudge.sh`
- Create: `claude/hooks/tests/fixtures/taskupdate-posttooluse.json`, `claude/hooks/tests/fixtures/README.md`
- Modify: `claude/plugin/hooks/hooks.json` (PostToolUse list)
- Modify: `tools/tests/test_plugin.zsh` (two checks after the line that starts `check "legacy hook paths are symlinks into the plugin"`)

**Acceptance Criteria:**
- [ ] Spec §1, quoted: "When a `TaskUpdate` sets `status: completed` on a task whose subject starts `Plan & run:`, and the session's task folder still has a pending `Plan & run:` task, it emits additionalContext: `Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task.`" The output is exactly `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "<that sentence>"}}`.
- [ ] "It does nothing in every other case": a completed task with another subject, a `Plan & run:` task set to a status other than `completed`, no pending `Plan & run:` task, a missing task folder, a broken task file and malformed input all print nothing and exit 0. The completed task's own file never counts as the pending one.
- [ ] The task folder is `${SPEC_NUDGE_TASKS_DIR:-$HOME/.claude/tasks}/session-<first 8 characters of session_id>/`; the hook opens files only for reading and writes nothing anywhere.
- [ ] Delivery semantics: the hook is stateless, so two concurrent deliveries, a repeated delivery and deliveries out of order each print the same advice or nothing; the test's "read-only" check proves it leaves no state. Nothing depends on order.
- [ ] `taskupdate-posttooluse.json` is a real PostToolUse payload of a `TaskUpdate` call captured on this machine, with only `session_id`, `transcript_path` and `cwd` replaced by placeholders; `fixtures/README.md` says how it was captured (the commands, the Claude Code version, the date) and lists the payload's top-level keys and the keys of `tool_input`.
- [ ] The field names the hook reads (`tool_name`, `tool_input.taskId`, `tool_input.status`, `session_id`) are the ones in the captured payload. If the capture shows other names, change the hook and the test to the real names and say so in the report.
- [ ] `claude/plugin/hooks/hooks.json` has one new PostToolUse entry: matcher `TaskUpdate`, command `"${CLAUDE_PLUGIN_ROOT}/scripts/spec-boundary-nudge.sh" --scoped`, timeout 5, not async. `claude/settings.json` is unchanged.
- [ ] `bash claude/hooks/tests/test-spec-boundary-nudge.sh` ends `passed=14 failed=0`, and `zsh tools/tests/test_plugin.zsh` ends `ALL PASS` (or its headless probe skips as it does on `main`).
- [ ] Real-state check, read-only: fed the fixture payload with `session_id` set to the lead's current session id prefix and `taskId` set to a completed `Plan & run:` task of the lead's real folder `~/.claude/tasks/session-<id8>/` (no `SPEC_NUDGE_TASKS_DIR`), the hook prints the message while that folder has a pending `Plan & run:` task; `ls -la` of the folder before and after shows no change. Report the output.

**Verify:** `bash claude/hooks/tests/test-spec-boundary-nudge.sh` → last line `passed=14 failed=0`

```json:metadata
{"files": ["claude/plugin/scripts/spec-boundary-nudge.sh", "claude/hooks/spec-boundary-nudge.sh", "claude/hooks/tests/test-spec-boundary-nudge.sh", "claude/hooks/tests/fixtures/taskupdate-posttooluse.json", "claude/hooks/tests/fixtures/README.md", "claude/plugin/hooks/hooks.json", "tools/tests/test_plugin.zsh"], "verifyCommand": "bash claude/hooks/tests/test-spec-boundary-nudge.sh", "acceptanceCriteria": ["completed Plan & run with another pending: exactly the spec's additionalContext sentence", "every other case prints nothing and exits 0; the completed task's own file never counts as pending", "task folder from SPEC_NUDGE_TASKS_DIR or ~/.claude/tasks, session-<id8>; read-only", "stateless: concurrent, repeated and out-of-order deliveries are harmless", "fixture is a real captured TaskUpdate PostToolUse payload; README says how", "hook reads the field names the capture shows", "one hooks.json entry: PostToolUse TaskUpdate, --scoped, timeout 5, not async; claude/settings.json unchanged", "hook test 14 passed 0 failed; test_plugin.zsh ALL PASS", "real-state read-only run against the lead's real task folder prints the message and changes nothing"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Capture a real payload.** In a scratch project directory under your scratchpad (never this repo), write `.claude/settings.json` with one PostToolUse hook, matcher `TaskUpdate`, command `cat >> <scratch>/payload.jsonl` (the hook's stdin is the payload). Start Claude Code there and have it create a task and set it to `completed` with the task tools. Headless first: `claude -p "Use TaskCreate to create one task titled 'Plan & run: probe', then use TaskUpdate to set it to completed. Do nothing else." --allowedTools TaskCreate,TaskUpdate` from the scratch directory. If the headless run has no task tools, run an interactive session on a scratch tmux server instead (`~/.local/bin/tmux -L <short sock> -f /dev/null new-session -d -s probe -c <scratch>`, then `send-keys` the same prompt to `claude`; kill that server by its socket afterwards and check with `ps` that nothing of it is left). Keep one line whose `tool_input.status` is `completed`, replace `session_id`, `transcript_path` and `cwd` with `abcdef12-0000-4000-8000-000000000000`, `/home/u/t.jsonl` and `/home/u/p`, pretty-print nothing (one JSON object on one line), and save it as the fixture. If neither way yields a payload, stop and message the lead; do not hand-write the fixture. The expected shape, from a real transcript's `TaskUpdate` call on 2026-11-20 (`tool_use.input` was `{"taskId": "53", "status": "in_progress"}` and the result `{"success": true, "taskId": "53", "updatedFields": ["status"], "statusChange": {"from": "pending", "to": "in_progress"}}`):

```json
{"session_id": "abcdef12-0000-4000-8000-000000000000", "transcript_path": "/home/u/t.jsonl", "cwd": "/home/u/p", "hook_event_name": "PostToolUse", "tool_name": "TaskUpdate", "tool_input": {"taskId": "1", "status": "completed"}, "tool_response": {"success": true, "taskId": "1", "updatedFields": ["status"], "statusChange": {"from": "in_progress", "to": "completed"}}}
```

- [ ] **Step 2: Write `claude/hooks/tests/fixtures/README.md`** (how the payload was captured, its keys).
- [ ] **Step 3: Write the test** `claude/hooks/tests/test-spec-boundary-nudge.sh`:

```bash
#!/bin/bash
# Test for claude/hooks/spec-boundary-nudge.sh (a link to claude/plugin/scripts/spec-boundary-nudge.sh).
# fixtures/taskupdate-posttooluse.json is a real PostToolUse payload of a TaskUpdate call (fixtures/README.md says how it
# was captured); each case swaps in its own session_id, taskId and status with jq and points the hook at a temp task folder.
set -u
H="${HOOK:-$(cd "$(dirname "$0")/.." && pwd)/spec-boundary-nudge.sh}"
FX="$(cd "$(dirname "$0")" && pwd)/fixtures/taskupdate-posttooluse.json"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
SID="abcdef12-0000-4000-8000-000000000000"; D="$T/tasks/session-abcdef12"; mkdir -p "$D"
MSG="Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task."
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
mk() { jq -n --arg i "$1" --arg s "$2" --arg st "$3" '{id:$i, subject:$s, status:$st, blocks:[], blockedBy:[]}' > "$D/$1.json"; }
run() { # taskId status [tasks root] -> hook stdout
  jq --arg s "$SID" --arg i "$1" --arg st "$2" '.session_id=$s | .tool_input.taskId=$i | .tool_input.status=$st' "$FX" \
    | SPEC_NUDGE_TASKS_DIR="${3:-$T/tasks}" "$H" --scoped 2>>"$T/err"
}
before=$(ls -A "$D" | wc -l | tr -d ' ')

check "fixture is a TaskUpdate PostToolUse payload" "$(jq -r '.hook_event_name + " " + .tool_name' "$FX")" "PostToolUse TaskUpdate"
mk 55 "Plan & run: docs/superpowers/specs/a.md" completed
mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
mk 60 "Task 1: something else" completed
o=$(run 55 completed)
check "completed Plan & run, another pending: message" "$(printf '%s' "$o" | jq -r '.hookSpecificOutput.additionalContext')" "$MSG"
check "completed Plan & run, another pending: event name" "$(printf '%s' "$o" | jq -r '.hookSpecificOutput.hookEventName')" "PostToolUse"
check "completed Plan & run, another pending: never blocks" "$(printf '%s' "$o" | jq -r 'has("decision")')" "false"
check "completed other task: nothing" "$(run 60 completed | wc -c | tr -d ' ')" "0"
check "Plan & run set to in_progress: nothing" "$(run 55 in_progress | wc -c | tr -d ' ')" "0"
mk 61 "Task 2: pending but not a spec" pending
mk 18 "Plan & run: docs/superpowers/specs/b.md" in_progress
check "completed Plan & run, none pending: nothing" "$(run 55 completed | wc -c | tr -d ' ')" "0"
mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
check "the completed task itself still pending on disk does not count" "$(mk 55 'Plan & run: docs/superpowers/specs/a.md' pending; mk 18 'Plan & run: docs/superpowers/specs/b.md' completed; run 55 completed | wc -c | tr -d ' ')" "0"
o=$(printf 'not json' | SPEC_NUDGE_TASKS_DIR="$T/tasks" "$H" --scoped 2>>"$T/err"); rc=$?
check "malformed input: nothing" "$(printf '%s' "$o" | wc -c | tr -d ' ')" "0"
check "malformed input: rc 0" "$rc" "0"
o=$(run 55 completed "$T/no-such-root"); rc=$?
check "missing task folder: nothing, rc 0" "$(printf '%s' "$o" | wc -c | tr -d ' ') $rc" "0 0"
printf '{broken' > "$D/99.json"
mk 55 "Plan & run: docs/superpowers/specs/a.md" completed; mk 18 "Plan & run: docs/superpowers/specs/b.md" pending
check "a broken task file is skipped, message still sent" "$(run 55 completed | jq -r '.hookSpecificOutput.additionalContext')" "$MSG"
rm -f "$D/99.json"
check "read-only: task folder file count unchanged" "$(ls -A "$D" | wc -l | tr -d ' ')" "$((before + 4))"
check "stderr empty" "$(wc -c < "$T/err" | tr -d ' ')" "0"
echo "passed=$pass failed=$fail"
[ "$fail" -eq 0 ]
```

- [ ] **Step 4: Run it and see it fail** because the hook does not exist.

Run: `bash claude/hooks/tests/test-spec-boundary-nudge.sh`
Expected: `FAIL` lines for the message checks (the hook path is missing), last line with `failed=` above 0.

- [ ] **Step 5: Write the hook** `claude/plugin/scripts/spec-boundary-nudge.sh`, `chmod +x` it, and create the link: `ln -s ../plugin/scripts/spec-boundary-nudge.sh claude/hooks/spec-boundary-nudge.sh`. It follows `claude/plugin/scripts/shutdown-record.sh` (stdin to an inline `python3 -I`, fail-open). The differences from that script that change behaviour: this hook writes no file and takes no lock (shutdown-record appends under `flock`), it prints a `hookSpecificOutput` object (shutdown-record prints nothing), and it reads `~/.claude/tasks`, not `TC_STATE`.

```bash
#!/usr/bin/env bash
# PostToolUse(TaskUpdate): at a spec boundary in queue mode, tell the lead to hand off before the next spec
# (docs/superpowers/specs/2026-11-20-efficiency-now-design.md §1). It speaks only when the update sets status
# "completed" on a task whose subject starts "Plan & run:" and the session's task folder
# (${SPEC_NUDGE_TASKS_DIR:-~/.claude/tasks}/session-<first 8 of session_id>/) still holds a pending "Plan & run:" task.
# Read-only, never blocks. Fail-open: any error, a missing folder or a malformed payload exits 0 with nothing printed.
# Delivery: stateless, so a repeated or concurrent delivery prints the same advice again; order does not matter.
# --scoped (the plugin registration) is accepted and changes nothing.
input=$(cat) || exit 0
printf '%s' "$input" | python3 -I -c 'import glob, json, os, re, sys
PREFIX = "Plan & run:"
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "TaskUpdate" or not isinstance(ti, dict) or ti.get("status") != "completed":
        sys.exit(0)
    sid, tid = d.get("session_id"), str(ti.get("taskId") or "")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
        sys.exit(0)
    root = os.environ.get("SPEC_NUDGE_TASKS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "tasks")
    folder = os.path.join(root, "session-" + sid[:8])

    def task(path):
        try:
            with open(path) as f:
                t = json.load(f)
            return t if isinstance(t, dict) else {}
        except (OSError, ValueError):
            return {}
    if not str(task(os.path.join(folder, tid + ".json")).get("subject") or "").startswith(PREFIX):
        sys.exit(0)
    pending = False
    for p in glob.glob(os.path.join(folder, "*.json")):
        t = task(p)
        if str(t.get("id")) != tid and t.get("status") == "pending" and str(t.get("subject") or "").startswith(PREFIX):
            pending = True
            break
    if pending:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
              "Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task."}}))
except Exception:
    pass
' 2>/dev/null
exit 0
```

- [ ] **Step 6: Run the test.** Expected last line: `passed=14 failed=0`. This code and test were run together on 2026-11-20 with that result.
- [ ] **Step 7: Run each mutation once and report the failing check**, restoring the hook after each (results from the 2026-11-20 run):
  - `if pending:` → `if True:` makes `completed Plan & run, none pending: nothing` fail.
  - the completed task's subject test → `if False:` makes `completed other task: nothing` fail.
  - removing ` or ti.get("status") != "completed"` makes `Plan & run set to in_progress: nothing` fail.
  - removing `str(t.get("id")) != tid and ` makes `the completed task itself still pending on disk does not count` fail.
- [ ] **Step 8: Register it.** In `claude/plugin/hooks/hooks.json`, add this entry to the `PostToolUse` array, directly after the `SendMessage` entry:

```json
      {
        "matcher": "TaskUpdate",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/spec-boundary-nudge.sh\" --scoped", "timeout": 5 }
        ]
      },
```

- [ ] **Step 9: Add the registration checks** to `tools/tests/test_plugin.zsh`, directly after the line that starts `check "legacy hook paths are symlinks into the plugin"`:

```zsh
check "hooks.json registers spec-boundary-nudge on PostToolUse TaskUpdate, --scoped, timeout 5, not async" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PostToolUse"]
hit = [(e.get("matcher"), h) for e in d for h in e["hooks"] if h["command"].endswith("/scripts/spec-boundary-nudge.sh\" --scoped")]
assert len(hit) == 1 and hit[0][0] == "TaskUpdate" and hit[0][1].get("timeout") == 5 and not hit[0][1].get("async"), hit
PY
check "spec-boundary-nudge.sh is executable and claude/hooks links to it" zsh -c '[[ -x $1/claude/plugin/scripts/spec-boundary-nudge.sh && -L $1/claude/hooks/spec-boundary-nudge.sh && $(readlink $1/claude/hooks/spec-boundary-nudge.sh) == ../plugin/scripts/spec-boundary-nudge.sh ]]' _ "$R"
```

Both checks were run on 2026-11-20 against a patched copy of `hooks.json` (both `ok`) and against the unpatched file (both `FAIL`).

- [ ] **Step 10: Run** `zsh tools/tests/test_plugin.zsh` and read its last line (`ALL PASS`; on a failure it prints `N FAILED`).
- [ ] **Step 11: Run the real-state check** from the Acceptance Criteria and put the output in your report.
- [ ] **Step 12: Commit** the seven paths in Files with `feat(hooks): spec-boundary nudge on TaskUpdate`.

---

### Task 4: Boundary rule in orchestrator.md and handoff skill

**Goal:** `claude/orchestrator.md` and the handoff skill tell the lead to hand off at every spec boundary in queue mode, and the skill defines what the boundary doc carries, its fixed shape and its budget warning.

**Files:**
- Modify: `claude/orchestrator.md` (Queue mode steps 2 and 4; "Handing off on your own")
- Modify: `claude/plugin/skills/handoff/SKILL.md` (section 2 "Write the handoff doc", section 4 "Ask before switching")
- Create: `board/tests/test_boundary_rules.py`

**Acceptance Criteria:**
- [ ] Use the `writing-for-agents` skill for both documents.
- [ ] `claude/orchestrator.md`, Queue mode step 2, gains the rule from spec §1: after a `Plan & run:` task is marked completed with its `metadata.outcome` and every ending step has run (the metrics `record` and its commit, the ledger archive), the lead runs `agent-board:handoff` on itself if another `Plan & run:` task is pending; the doc's State of the work names the next spec; the new lead starts that spec with `writing-plans`. The fixed order is stated: outcome, metrics record and commit, then the handoff. It applies to every outcome: merged, mr, kept, failed, awaiting merge approval.
- [ ] `claude/orchestrator.md` "Handing off on your own", **Your own session**, lists the boundary as a case where the handoff is required, not a judgment call, and says the hook message `Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task.` is that trigger.
- [ ] The existing "Not now" cases still win: the rule text says the boundary handoff waits while one of them holds (for example a merge in progress) and runs at the first turn after.
- [ ] The handoff skill's step 4 names the trigger in its definition of self-started, in the spec's words: "a `Plan & run:` spec finished in queue mode, with another pending", and says it relays without asking.
- [ ] The handoff skill gains a section for the boundary doc that holds, each stated once:
  - the cost rule (a doc line and a lookup result both stay in the next lead's context and are re-read every turn, so compare the fact's size with the size of what the next lead would read to rediscover it);
  - the include rule's four parts (include a fact the next spec needs when recovering it takes a much bigger read or several tool calls; give a pointer when one named file or command answers exactly that; never include finished history; durable knowledge goes to the shared context file with `tmux-ctl context add` before the handoff);
  - the fixed shape as four `## ` sections in this order, `Queue state`, `Live state`, `Carried over`, `Pointers`, with the content the spec lists for each (Queue state: the next spec's path, every queued task's `metadata.queue`, the batch id; Live state: keep-awake, uncommitted files and why, open worktrees and leftovers, user gates waiting; Carried over: rulings and open user decisions that affect later specs, one line each with a pointer; Pointers: the spec to start from, the last report, the archived ledger);
  - that the boundary doc still starts with the `Project:` line, keeps `Queue mode: on` and the `Awake:` line inside Queue state, keeps the Previous session line, and has no Team section;
  - that mid-spec handoffs (the context guard, a live team, a ledger mid-loop) keep the fuller format with the Team section.
- [ ] The skill tells the lead to run, after writing any handoff doc, `python3 -I "$(dirname "$(realpath "$(command -v tmux-ctl)")")/../board/ctxsize.py" doc <doc>` and, when the line says `over`, to trim the section it names once and go on. The text says the warning never blocks the handoff and applies to boundary docs only.
- [ ] `board/tests/test_boundary_rules.py` asserts, by reading the two files: the hook sentence appears verbatim in `claude/orchestrator.md`; the four section names appear in the skill in the fixed order; the skill contains the trigger phrase, the `ctxsize.py" doc` command and the words `never blocks`; and `ctxsize.doc_estimate` on a temp doc built with the four sections and 13000 characters under `Carried over` returns a line containing `over; largest section: Carried over`.
- [ ] Nothing else in either document changes meaning: the Teammate mode, the relay steps and Queue mode steps 1, 3 and 5 are untouched (`git diff --stat` shows only these two files and the test).

**Verify:** `python3 -m unittest board.tests.test_boundary_rules` → `OK`

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/handoff/SKILL.md", "board/tests/test_boundary_rules.py"], "verifyCommand": "python3 -m unittest board.tests.test_boundary_rules", "acceptanceCriteria": ["writing-for-agents used", "orchestrator Queue mode step 2 has the boundary rule with the fixed order and every outcome", "Handing off on your own lists the boundary as required and names the hook message", "the Not now cases still win", "handoff skill names the trigger as self-started, relays without asking", "skill has the cost rule, the include rule, the four-section fixed shape and the mid-spec exception", "skill runs ctxsize.py doc and trims once; the warning never blocks", "test_boundary_rules asserts the texts and the doc estimate", "no other meaning changes"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Write `board/tests/test_boundary_rules.py`** from the criterion above (paths relative to the repo root found from `__file__`; it imports `ctxsize` the way `board/tests/test_ctxsize.py` does). Run it and see the text assertions fail.
- [ ] **Step 2: Edit `claude/orchestrator.md`.** Put the boundary rule at the end of Queue mode step 2, after the sentence "Measurement never fails a spec: …". Rewrite step 4 to point at it: handoffs during the queue relay without asking, one happens at every spec boundary (step 2), and the boundary doc uses the handoff skill's boundary shape.
- [ ] **Step 3: Edit the handoff skill.** Add the boundary section inside "## 2. Write the handoff doc", after the bullet list of doc parts and before "Redact secrets and personal data.", under a `### At a spec boundary (queue mode)` heading. Add the budget check after the paragraph "Find the previous session id." block, before "Register it". Add the trigger to step 4's definition of self-started.
- [ ] **Step 4: Check the command the skill gives** resolves on this machine: `python3 -I "$(dirname "$(realpath "$(command -v tmux-ctl)")")/../board/ctxsize.py" doc "$(ls -t ~/.local/state/agent-board/handoffs/*.md | head -1)"` prints one `handoff doc: <n> tokens (budget 3000): ok|over…` line (read-only; on 2026-11-20 the newest doc gave 2137 tokens, ok). In this worktree `tmux-ctl` resolves to the main checkout, where `board/ctxsize.py` exists only after the merge: before the merge run the same check with `board/ctxsize.py` from this worktree, and say so in the report.
- [ ] **Step 5: Run the test until green and commit** the three paths with `feat(handoff): hand off at every spec boundary, with a fixed-shape doc and a budget warning`.

---

### Task 5: Task records gain `context_tokens`

**Goal:** Each line `build_task_lines` returns carries the implementer's context size at the end of the task, or `null` with the field named in a new `missing` list.

**Files:**
- Modify: `board/metrics_tasks.py` (`KEYS` near line 22, `build_task_lines` near lines 216-245)
- Modify: `board/tests/test_metrics_tasks.py` (`row` helper near line 115, `test_keys_exact` near line 287, new tests in `TestBuild`)
- Read: `docs/superpowers/notes/2026-11-20-limits-gap-cause.md` section `Tap context figure` (the source decision)

**Acceptance Criteria:**
- [ ] Every task line has `context_tokens` as Metric definitions defines it, and `missing`: a list that holds `"context_tokens"` when the value is `null` and is `[]` otherwise.
- [ ] Rows with `sidechain == 1` or `subagent_file == 1` never supply the value, even when they are the task's latest rows.
- [ ] A reviewer's rows never supply it.
- [ ] `KEYS` in `board/metrics_tasks.py` and `test_keys_exact` list the two new keys.
- [ ] New tests in `board/tests/test_metrics_tasks.py`: the last main-thread row by `ts` wins over an earlier larger one (the value is the end-of-task size, not the peak); a later sidechain row is skipped; a task with no rows has `null` and `missing == ["context_tokens"]`; two tasks sharing one owner each get their own last row.
- [ ] Each new guard test names its mutation in your report, run once: taking `max` over the rows makes the "last wins" test fail; dropping the sidechain filter makes the sidechain test fail.
- [ ] `board/tests/test_metrics_tasks_log.py` and the other readers of `tasks.jsonl` still pass: `grep -rn "tasks.jsonl\|read_tasks" board/*.py` is checked for any reader that assumes the old key set, and each hit is listed in the report as "accepts new keys".
- [ ] If Task 0's note refuted assumption A4 (the tap is a usable per-task source), stop and message the lead before writing code.

**Verify:** `python3 -m unittest board.tests.test_metrics_tasks board.tests.test_metrics_tasks_log` → `OK`

```json:metadata
{"files": ["board/metrics_tasks.py", "board/tests/test_metrics_tasks.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_tasks board.tests.test_metrics_tasks_log", "acceptanceCriteria": ["every task line has context_tokens and a missing list", "sidechain and subagent-file rows never supply the value", "reviewer rows never supply it", "KEYS and test_keys_exact list the new keys", "tests: last row wins over a larger earlier one, sidechain skipped, no rows is null and missing, shared owner split per task", "mutations named and run once", "every reader of tasks.jsonl accepts the new keys", "stop and ask if Task 0 refuted A4"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Extend the test helper** `row(...)` in `board/tests/test_metrics_tasks.py` with keyword arguments for `inp`, `cr`, `cw5`, `cw1`, `side` and `sub` (defaults 0), mapped to the row's `input`, `cache_read`, `cache_write_5m`, `cache_write_1h`, `sidechain` and `subagent_file`. Write the four new tests and update `test_keys_exact`. Run and see them fail on the missing key.
- [ ] **Step 2: Implement** in `build_task_lines`: from `rs` (the task's `mine` rows) keep those with no `sidechain` and no `subagent_file`, take the one with the largest `ts`, and set `context_tokens` to `usage.context_tokens(that row)`; otherwise `None` and `missing = ["context_tokens"]`.
- [ ] **Step 3: Run the Verify command until green, run the two mutations, commit** both paths with `feat(metrics): task records carry the implementer's context size`.

---

### Task 6: `board/metrics_lead.py`: the lead fields

**Goal:** A pure module that turns a transcript directory, a lineage file and a run window into the run record's four lead fields, exactly as Metric definitions defines them.

**Files:**
- Create: `board/metrics_lead.py`
- Create: `board/tests/test_metrics_lead.py`
- Read: `board/ctxsize.py` (`peak`, `turns`, `first_turns_tokens`), `board/metrics.py` `count_handoffs` (the lineage line shape: `{"ts", "old_session_id", "doc", "pane"}`)

**Acceptance Criteria:**
- [ ] `lead_fields(tdir, lineage_file, lo, hi, prev_end=None)` returns `{"lead_context_peak": int | None, "lead_handoffs": int, "post_handoff_tokens": [int | None, …], "rereads": [int | None, …], "missing": [names]}`. `tdir` and `lineage_file` are paths; `lo`, `hi`, `prev_end` are epoch seconds. It imports `ctxsize` and the standard library only (no import of `metrics`, which would be circular).
- [ ] Lead session, successor, `lead_context_peak`, `lead_handoffs`, counted handoffs, `post_handoff_tokens` and `rereads` follow Metric definitions word for word, including the read-set rule for `Bash` commands.
- [ ] `missing` holds `"lead_context_peak"` when the peak is `None`, and `"post_handoff_tokens"` / `"rereads"` when the matching list has a `null` entry. A missing lineage file gives `lead_handoffs == 0`, empty lists and a `None` peak. A missing `tdir` gives a `None` peak and `null` list entries.
- [ ] It never raises: a malformed lineage line, an unreadable transcript and a `Bash` command that does not tokenise are skipped. One test passes a directory holding a binary file named `x.jsonl` and a lineage file with a broken line and gets a dict back.
- [ ] The returned dict holds no session id, no path and no file name: a test dumps it to JSON and asserts the temp dir's path, every session id used and every file name read are absent.
- [ ] Tests build temp transcripts and a temp lineage file (helpers in the test file write assistant lines with `requestId`, `timestamp`, `isSidechain`, `cwd`, `message.usage` and `tool_use` blocks, and a first user line `Read <doc> and continue from where the previous session left off.`). Cases:
  - a run with two lead sessions and one handoff inside the window: peak is the larger of the two sessions' in-window peaks, `lead_handoffs == 1`;
  - a turn outside `[lo, hi]` with the largest context is not the peak;
  - the boundary handoff: one lineage line between `prev_end` and `lo` → `lead_handoffs == 1` and its successor's numbers are in the lists; two lines between `prev_end` and `lo` plus one inside the window → `3`; the same single line with `prev_end=None`, and with `prev_end` later than the line → `0`, empty lists; a line at exactly `prev_end` is not counted and a line at exactly `hi` is;
  - no lineage line in the window and none before it → peak `None`, in `missing`;
  - a teammate transcript in `tdir` that quotes the doc's name in a user line carrying `agentName` is not the successor; a user line that names the doc without the relay phrase is not the successor;
  - `post_handoff_tokens` with a successor of 12 turns sums the first 10 only, and of 3 turns sums 3;
  - `rereads`: `Read` blocks and `Bash` reads (`cat a | head`, `sed -n 1,5p b`, `grep -n x c d`, `cd z && tail e`) against real temp files; a path read by both sessions through different tools (one `Read`, one `cat`) counts once; a relative path is joined to the line's `cwd`; a `grep` pattern that is not a file does not count; a file read by the successor only after its 10th turn does not count; a file that no longer exists does not count; a sidechain line's reads do not count;
  - a handoff whose successor is absent gives `null` in both lists and both names in `missing`.
- [ ] Each guard or absence test names its mutation in your report, run once. At least: counting reads beyond the 10th turn makes the "after its 10th turn" test fail; dropping the `agentName` test in the successor rule makes the teammate test fail; widening the peak to ignore `hi` makes the "outside the window" test fail; counting from `lo` when `prev_end` is given makes the boundary test fail, and counting lines before `lo` when `prev_end` is `None` makes the `prev_end=None` case fail.
- [ ] Real-state check, read-only: one run of `lead_fields` against this machine's real lineage file (`~/.local/state/agent-board/lineage/agent-board.jsonl`) and transcript directory for the window of the newest stamped run record in `docs/superpowers/metrics/runs.jsonl`, with `prev_end` from the previous run record of its batch. Report the returned dict (numbers only), and the same run for a window on an earlier day (a lineage file that spans days). On 2026-11-20 the last six lineage lines had successors by this rule in four of four probed cases with the first 200 lines read.

**Verify:** `python3 -m unittest board.tests.test_metrics_lead` → `OK`

```json:metadata
{"files": ["board/metrics_lead.py", "board/tests/test_metrics_lead.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_lead", "acceptanceCriteria": ["lead_fields returns the four fields and missing; imports ctxsize and stdlib only", "every field follows Metric definitions word for word", "missing names each null field; missing lineage file or tdir handled", "never raises on malformed input", "no session id, path or file name in the returned dict", "tests cover two lead sessions, window bounds, the boundary handoff and prev_end, no lineage, the successor rule's exclusions, 10-turn limits, the read-set rule, an absent successor", "mutations named and run once", "real-state read-only run against the real lineage and transcripts, on two days"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Write the test helpers and the tests** for the cases above. Use `os.utime` where a test needs an old file. Run and see the import fail.
- [ ] **Step 2: Implement** `board/metrics_lead.py` with these functions, each small enough to test alone:
  - `lineage(lineage_file)` → the valid lines as dicts, sorted by `ts`.
  - `successor(tdir, line)` → a path or `None` (Metric definitions: successor).
  - `read_set(transcript, first_turns=None)` → a set of normalised paths (Metric definitions: read set); `first_turns` limits it to the `tool_use` blocks of the first N distinct `requestId`s among main-thread assistant lines.
  - `lead_fields(tdir, lineage_file, lo, hi, prev_end=None)`.
- [ ] **Step 3: Run until green, run the mutations, run the real-state check** (a short `python3 -I -c` from the repo root with `sys.path.insert(0, "board")`; print only the returned dict).
- [ ] **Step 4: Commit** both paths with `feat(metrics): lead context peak, handoffs, post-handoff tokens and re-reads from the lineage`.

---

### Task 7: Run records, `missing_reason`, report lines

**Goal:** `metrics record` writes the four lead fields and a reason for a null limits reading, `metrics start` writes the reason too, and `metrics report` prints one Lead line per spec and each limits reason.

**Files:**
- Modify: `board/metrics.py` (`cmd_start` near line 198; `build_record` near lines 699-719; `report_text` near lines 1026-1034)
- Modify: `board/tests/test_metrics_record_usage.py`, `board/tests/test_metrics_report.py`
- Read: `docs/superpowers/notes/2026-11-20-limits-gap-cause.md` (the causes and their reason strings), `board/metrics_lead.py`

**Acceptance Criteria:**
- [ ] `build_record` adds `lead_context_peak`, `lead_handoffs`, `post_handoff_tokens` and `rereads` from `metrics_lead.lead_fields(usage.root() / slug_of(root), tc_env.lineage_dir() / f"{project}.jsonl", lo, hi, prev_end)` and extends the record's `missing` with the names it returns. `prev_end` follows Metric definitions (`lead_handoffs`): the latest `ended_at` before `lo` among the same batch's other run records, from `last_runs(lines)`; `None` when there is none.
- [ ] A failure inside `lead_fields` or its import never fails the record: the four fields are then `null`, `null`, `[]`, `[]`, all four names are in `missing`, and one line `metrics: record: lead fields skipped: <clean reason>` goes to stderr. A test patches `metrics_lead.lead_fields` to raise and asserts the record is still built.
- [ ] `missing_reason` (assumption A3): when `limits` is in `missing`, the record has `missing_reason: {"limits": "<one of the fixed limits reason strings>"}`: the backfilled string for a backfilled run, the record-time string when `plan_limits` returned nothing. `cmd_start` writes `missing_reason: {"limits": "no statusline tap with rate_limits at start"}` beside its existing `missing`. A record with a limits reading has no `missing_reason` key. If Task 0's note found a further cause, it gets the string that note names.
- [ ] `limits` keeps its shape (`{"start": …, "record": …}` on a run record, an object or `null` on a start record).
- [ ] The report prints, directly after the two `Limits at …` lines: one line per run record that has the key `lead_context_peak`, sorted by spec, `<spec>: Lead: peak <N>K tokens, <h> handoffs` with `<N>` the peak divided by 1000 and rounded down, or `-` for a `null` peak; when `lead_handoffs > 0` and `rereads` has at least one number, the suffix `, <r> re-reads after handoff` with `<r>` the sum of the non-null entries. A run record without the key (an old record) prints no Lead line.
- [ ] Directly after the Lead lines the report prints one line `Re-reads count files read with Read, cat, sed, head, tail or grep in the new lead's first 10 turns that the previous lead also read; Grep and Glob calls are not counted.` when at least one Lead line has the re-reads suffix (the scope stated next to the figure), and no such line otherwise.
- [ ] The report prints `Limits missing: <spec>: <reason>` for every run record of the batch that has `missing_reason.limits`, and `Limits missing: start <spec>: <reason>` for start lines that have it. None: no such line.
- [ ] Tests in `board/tests/test_metrics_record_usage.py`: a run with two lead sessions (a temp lineage line inside the window and two temp transcripts under `self.proj / slug`) gives the expected peak and `lead_handoffs == 1`; no lineage file gives a `null` peak in `missing` and `lead_handoffs == 0`; the boundary handoff (a lineage line between the batch's previous run record's `ended_at` and this run's start) is counted, and is not counted without a previous run record in the batch; `missing_reason` on a record without taps, on a backfilled record (`backfilled=True`) and absent on a record with a tap reading; the record's JSON holds no temp path and no session id (extend the existing `assertNotIn("Users", …)` style check with the session ids used).
- [ ] Tests in `board/tests/test_metrics_report.py`: the Lead line with a peak and no handoffs; with handoffs and re-reads (the suffix and the scope line); with a `null` peak (`peak -`); no Lead line for a record without the key; the two `Limits missing:` forms.
- [ ] `board/tests/test_metrics_backfill.py`, `board/tests/test_metrics_backfill_privacy.py`, `board/tests/test_metrics_log.py`, `board/tests/test_metrics_analyze.py`, `board/tests/test_metrics_recommend.py` and `board/tests/test_metrics_weekly.py` pass; a test of theirs that compares a record's exact key set is updated for the new keys, and each such change is listed in the report.
- [ ] Each figure the report prints resolves to a path in the run record: the report lists `lead_context_peak`, `lead_handoffs` and `rereads` as the sources of the Lead line, and a test asserts the printed numbers equal those fields of the record it wrote.
- [ ] Real-state check, read-only: `python3 -I board/metrics.py --repo . report 2026-11-11-1 > <scratch file>` on this worktree's real `runs.jsonl` exits 0 and prints no Lead line for the old records and one `Limits missing:` line per record that would have a reason (old records have none: zero lines), and the output's other lines are identical to the same command run from `main` (`diff` shows no change). Report the diff result.

**Verify:** `python3 -m unittest board.tests.test_metrics_record_usage board.tests.test_metrics_report board.tests.test_metrics_backfill board.tests.test_metrics_backfill_privacy board.tests.test_metrics_log` → `OK`

```json:metadata
{"files": ["board/metrics.py", "board/tests/test_metrics_record_usage.py", "board/tests/test_metrics_report.py"], "verifyCommand": "python3 -m unittest board.tests.test_metrics_record_usage board.tests.test_metrics_report board.tests.test_metrics_backfill board.tests.test_metrics_backfill_privacy board.tests.test_metrics_log", "acceptanceCriteria": ["build_record adds the four lead fields from metrics_lead.lead_fields with prev_end from the batch's previous run", "a failure in lead_fields never fails the record", "missing_reason.limits on run and start records uses the fixed strings; absent when limits were read", "limits keeps its shape", "report prints one Lead line per run record with the key, with the re-reads suffix when it applies", "the re-reads scope line is printed beside the figure", "report prints the Limits missing lines", "record tests cover two lead sessions, no lineage, the boundary handoff, missing_reason, privacy", "report tests cover every Lead line form and both Limits missing forms", "the other metrics test modules pass; key-set changes listed", "each printed figure resolves to a record field, asserted by a test", "real-state read-only report run on the real runs.jsonl diffs clean against main"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Read Task 0's note.** If its cause differs from assumption A6, use its reason strings and tell the lead in your report.
- [ ] **Step 2: Write the record tests**, run them, see them fail on the missing keys.
- [ ] **Step 3: Implement the record half** in `build_record` and `cmd_start`. Import `metrics_lead` at the top of `board/metrics.py` beside `metrics_tasks`. Wrap the `lead_fields` call as the second criterion says.
- [ ] **Step 4: Write the report tests**, see them fail, implement the report lines in `report_text`.
- [ ] **Step 5: Run the Verify command**, then `python3 -m unittest board.tests.test_metrics_analyze board.tests.test_metrics_recommend board.tests.test_metrics_weekly board.tests.test_metrics_tasks_log`.
- [ ] **Step 6: Run the real-state check** and commit the three paths with `feat(metrics): run records carry the lead's context peak, handoffs and re-reads; a null limits reading says why`.

---

### Task 8: Worker context probe (note only)

**Goal:** A note with a real teammate's `/context` breakdown and the share MCP tool schemas and connector results take, ending in a go or no-go for E4.

**Files:**
- Create: `docs/superpowers/notes/<run date>-worker-context-probe.md` (`<run date>` is the UTC date the probe ran, `date -u +%Y-%m-%d`)

**Acceptance Criteria:**
- [ ] The probe uses one real teammate started the normal way by the lead (the Agent tool with a team name, in this project's `dev` session), fresh, before it has done any work. The implementer of this task asks the lead to start it and to send it `/context`, or to name an existing fresh teammate window; the implementer does not start agents itself.
- [ ] The screen is read with `tmux-ctl read "✦ <name>" 200` or `tmux capture-pane -p -t <pane>`, read-only. Nothing is typed into the teammate's window by the implementer.
- [ ] The note has exactly these four `## ` sections, in this order: `Setup`, `Breakdown`, `MCP share`, `Verdict for E4`.
- [ ] `Setup` gives the Claude Code version, the model, the teammate's tier, how it was started, and the exact read command.
- [ ] `Breakdown` is a table with one row per category `/context` prints (system prompt, system tools, MCP tools, custom agents, memory files, skills, messages, free space, and any other it prints), with tokens and percentage of the context window, copied from the screen. It also gives each category as a share of the used context (tokens divided by the sum of the non-free rows).
- [ ] `MCP share` gives MCP tool schemas as a percentage of the fresh worker's used context, lists the MCP servers and their token counts as `/context` shows them, and says what connector results add when the capture shows any.
- [ ] `Verdict for E4` is one line starting `go:` or `no-go:`. The rule, quoted from the spec: "If MCP schemas are under 5% of a fresh worker's context, E4 is a no-go." The line names the figure it rests on and that its scope is one fresh teammate of one tier on one day.
- [ ] The note holds no session id and no absolute home path.
- [ ] Nothing in the repo other than this note changes.

**Verify:** `grep -c '^## ' docs/superpowers/notes/*-worker-context-probe.md` → `4`

```json:metadata
{"files": ["docs/superpowers/notes/<run date>-worker-context-probe.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/notes/*-worker-context-probe.md", "acceptanceCriteria": ["one real fresh teammate started the normal way by the lead", "screen read with tmux-ctl read or capture-pane, read-only", "note has the four sections Setup, Breakdown, MCP share, Verdict for E4", "Setup gives version, model, tier, start method, read command", "Breakdown has one row per /context category with tokens, percent of window and share of used context", "MCP share gives the schemas' percentage of used context and the servers", "Verdict is one go: or no-go: line by the 5% rule, with its figure and scope", "no session id or home path", "only the note changes"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Message the lead**: ask for one fresh standard-tier teammate named `ctx-probe` with the brief "Wait for instructions; do nothing", and for `/context` to be sent to its window (`tmux-ctl send "✦ ctx-probe" "/context"` from the lead). Wait for the lead's reply naming the window.
- [ ] **Step 2: Read the window** (`tmux-ctl read "✦ ctx-probe" 200`), copy the breakdown, and tell the lead the teammate can be shut down.
- [ ] **Step 3: Write the note**, run the Verify command, commit the note with `docs(notes): worker context probe`.

---

### Task 9: Code Mode hooks probe (note only)

**Goal:** A note that says, from an observed run on a scratch tmux server, whether PreToolUse and PostToolUse hooks fire for tool calls made from Code Mode code, ending in a go or no-go for E5.

**Files:**
- Create: `docs/superpowers/notes/<run date>-code-mode-hooks-probe.md` (`<run date>` is the UTC date the probe ran)

**Acceptance Criteria:**
- [ ] The probe runs in a scratch project directory under the implementer's scratchpad, in a Claude session started on a scratch tmux server with `~/.local/bin/tmux -L <short socket name> -f /dev/null …` and `TMUX=` cleared for every probe command, with `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` in that session's environment. The socket name is short (a long `TMUX_TMPDIR` path fails with "File name too long").
- [ ] The scratch project's `.claude/settings.json` registers two hooks: a probe hook on PreToolUse and PostToolUse with no matcher that appends `hook_event_name`, `tool_name` and a timestamp of each event to a log file in the scratch directory, and this repo's `claude/plugin/scripts/bash-mirror.sh` on PostToolUse `Bash` with `TC_STATE` pointed at a scratch directory (so the real board's feed is untouched).
- [ ] Two runs with the same prompt, one that makes Claude run a shell command and read a file: a control run without the variable and a run with it. The note says for each run which tool calls were made and which hook events were logged for them, from the log file and the bash-mirror output file.
- [ ] If Code Mode cannot be confirmed active in the second run (the session shows no sign of it, or the variable is not recognised by this version), the note says so with the evidence, and the verdict is `no-go: Code Mode could not be exercised`.
- [ ] The note has exactly these four `## ` sections, in this order: `Setup`, `Observed events`, `What fires and what does not`, `Verdict for E5`.
- [ ] `Setup` gives the Claude Code version, every command run (the tmux server start, the settings file's content, the prompts), so the probe can be repeated.
- [ ] `Observed events` is a table: run (control or Code Mode), tool call, PreToolUse logged (yes or no), PostToolUse logged (yes or no), bash-mirror line written (yes or no).
- [ ] `Verdict for E5` is one line starting `go:` or `no-go:`. Go requires that both PreToolUse and PostToolUse fired for every tool call made from Code Mode code in the run, the rule the loop spec gives: "only if the Code Mode hooks probe returns a go (our PreToolUse and PostToolUse gates fire under it".
- [ ] Cleanup: the scratch tmux server is killed by its socket (`tmux -L <sock> kill-server`), `ps` shows no process of it left, and no `pkill` or `killall` is used. The note holds no session id and no absolute home path. Nothing in the repo other than this note changes, and the real tmux server and `~/.claude` are untouched.

**Verify:** `grep -c '^## ' docs/superpowers/notes/*-code-mode-hooks-probe.md` → `4`

```json:metadata
{"files": ["docs/superpowers/notes/<run date>-code-mode-hooks-probe.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/notes/*-code-mode-hooks-probe.md", "acceptanceCriteria": ["scratch project and scratch tmux server started with -f /dev/null, TMUX cleared, CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1", "probe hook on PreToolUse and PostToolUse plus bash-mirror with TC_STATE in scratch", "a control run and a Code Mode run with the same prompt, events reported for each", "Code Mode not confirmable gives no-go with evidence", "note has the four sections Setup, Observed events, What fires and what does not, Verdict for E5", "Setup lists every command", "Observed events table per tool call", "Verdict is one go: or no-go: line by the both-hooks rule", "scratch server killed by socket and checked; no session id or home path; only the note changes"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Build the scratch project** and its `.claude/settings.json` with the two hooks. The probe hook's command can be `jq -c '{e: .hook_event_name, t: .tool_name, at: now}' >> <scratch>/events.jsonl`.
- [ ] **Step 2: Start the scratch server** and run the control prompt, then the Code Mode prompt in a second window whose environment has the variable (`tmux -L <sock> new-window -e CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 -c <scratch> …`). Read each window with `tmux -L <sock> capture-pane -p -t <target>`. Give a permission prompt in the scratch session the answer it needs with `send-keys`; it is your own scratch session.
- [ ] **Step 3: Read `events.jsonl`** and the bash-mirror file under the scratch `TC_STATE`, fill the table, write the note.
- [ ] **Step 4: Clean up** (kill the server by socket, `ps` check), run the Verify command, commit the note with `docs(notes): Code Mode hooks probe`.

---

### Task 10: Apply or close E4 and E5

**Goal:** The engine spec's E4 item and the loop spec's E5 item each say `Applied`, `Dropped` or `Blocked` with the probe note's path, and on a go the pending paragraph becomes the rule.

**Files:**
- Modify: `docs/superpowers/specs/2026-11-10-pcee-engine-design.md` (the `- **E4.**` bullet near line 68; the paragraph starting `Pending (E4, 2026-11-20):` near line 221)
- Modify: `docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md` (the `- **E5.**` bullet near line 84; the bullet starting `- Pending (E5, 2026-11-20):` near line 167)
- Read: `docs/superpowers/notes/*-worker-context-probe.md`, `docs/superpowers/notes/*-code-mode-hooks-probe.md`

**Acceptance Criteria:**
- [ ] No code changes: `git diff --stat` for this task shows the two spec files only.
- [ ] E4, when the worker-context note's verdict line starts `go:`: the bullet becomes `- **E4.** Applied (<note path>): each job kind has a tools/mcp list, allow-all by default (section 3, step 2).` and the paragraph `Pending (E4, 2026-11-20): … Not built until then.` is replaced by the rule itself, marked `(E4, 2026-11-20)`: a per-kind `tools`/`mcp` column on the job table, allow-all by default, with the probe's figure and the note's path. The words "Pending" and "Not built until then" are gone from that paragraph.
- [ ] E4, when the verdict starts `no-go:`: the bullet becomes `- **E4.** Dropped: <the verdict's reason> (<note path>).` (or `Blocked:` when the note says the probe could not be run), the pending paragraph is replaced by one line `Dropped (E4, 2026-11-20): <reason> (<note path>).` (or `Blocked …`), and nothing else in the section changes.
- [ ] E5 follows the same two forms in the loop spec: on `go:`, `- **E5.** Applied (<note path>): …` and the pending bullet becomes the rule (`CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` is a trial variant for mechanical-tier implementers), marked `(E5, 2026-11-20)`; on `no-go:`, `- **E5.** Dropped: <reason> (<note path>).` or `Blocked: …`, and the pending bullet becomes the one-line `Dropped (E5, 2026-11-20): …` or `Blocked …`.
- [ ] Each reason is the probe note's own verdict text, not a new judgment, and each note path is the real file name.
- [ ] If a probe note is missing or has no verdict line, that item is `Blocked: probe not run` with the reason from the lead's ledger; ask the lead for the reason.

**Verify:** `grep -h -c -E '^- \*\*E[45]\.\*\* (Applied|Dropped|Blocked)' docs/superpowers/specs/2026-11-10-pcee-engine-design.md docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md` → `1` and `1`

```json:metadata
{"files": ["docs/superpowers/specs/2026-11-10-pcee-engine-design.md", "docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md"], "verifyCommand": "grep -h -c -E '^- \\*\\*E[45]\\.\\*\\* (Applied|Dropped|Blocked)' docs/superpowers/specs/2026-11-10-pcee-engine-design.md docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md", "acceptanceCriteria": ["only the two spec files change", "E4 on go: bullet says Applied with the note path and the pending paragraph becomes the rule", "E4 on no-go: bullet says Dropped or Blocked with reason and note path; pending paragraph becomes one line", "E5 follows the same two forms in the loop spec", "each reason is the note's verdict text and each path is real", "a missing note or verdict gives Blocked: probe not run after asking the lead"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Read both notes' verdict lines**: `grep -h -A2 '^## Verdict' docs/superpowers/notes/*-worker-context-probe.md docs/superpowers/notes/*-code-mode-hooks-probe.md`.
- [ ] **Step 2: Edit the engine spec** for E4 and the loop spec for E5 as the criteria say.
- [ ] **Step 3: Run the Verify command** (two lines, each `1`), check `grep -c 'Not built until then' <each spec>` is `0` for an item that was applied or dropped, and commit both files with `docs(spec): E4 and E5 applied or closed from the probe notes`.

---

### Task 11: Full suite and read-only real-state checks

**Goal:** Every suite passes on the branch with all tasks in, and three read-only runs against this machine's real state show the reader, the hook and the report working on it.

**Files:**
- No file changes expected. A fix for a failure goes through `superpowers-extended-cc:systematic-debugging` and is committed on its own, naming the task whose code it fixes.

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` ends with its verdict line and exit code 0 or 4 (4 = every job passed, over the 300 s budget, accepted on this machine). The verdict is the runner's own summary line plus the exit code, read from a file the command wrote; never from a `tail` of the pane.
- [ ] `python3 -m unittest discover -s board/tests` reports `OK` in its `Ran N tests` block.
- [ ] `for t in claude/hooks/tests/test-*.sh; do bash "$t" || echo "FAIL $t"; done` prints no line starting `FAIL ` (count them uncapped: `grep -c '^FAIL '` is `0`), and the count of test files run is printed (it includes `test-spec-boundary-nudge.sh`).
- [ ] In `tools/discord-bridge`, `npm test` passes (`npm ci` first in a fresh worktree); `all.zsh` does not run it.
- [ ] Real state 1, read-only: for the three newest top-level transcripts in `~/.claude/projects/-Users-francisco-ruiz-agent-board/`, `python3 -I board/ctxsize.py last <t>` and `peak <t>` each print a number or nothing, exit 0, and `peak >= last` whenever both print. Report the numbers without the file names.
- [ ] Real state 2, read-only: the nudge hook, fed the fixture payload with the lead's real session id prefix and a completed `Plan & run:` task id from `~/.claude/tasks/session-<id8>/`, prints the message while a pending `Plan & run:` task exists there. `ls -la` of that folder is unchanged.
- [ ] Real state 3, read-only: `python3 -I board/metrics.py --repo . report 2026-11-11-1` exits 0 on the real `runs.jsonl` (a log that spans many days and 30 run records) and its output, compared with the same command from `main`, differs in no line.
- [ ] `git status --short` shows nothing but the files this plan lists, and `git diff main --stat -- claude/settings.json` is empty.

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?` → the runner's verdict line, then `rc=0` or `rc=4`

```json:metadata
{"files": [], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh verdict line with rc 0 or 4, read from a file", "board unittest discover OK", "claude/hooks shell tests: zero FAIL lines, file count printed", "discord-bridge npm test passes", "real state 1: ctxsize last and peak on three real transcripts, peak >= last", "real state 2: nudge hook against the lead's real task folder, folder unchanged", "real state 3: metrics report on the real runs.jsonl diffs clean against main", "git status shows only planned files; claude/settings.json unchanged"], "modelTier": "standard"}
```

**Steps:**

- [ ] **Step 1: Run the full suite** through `tmux-ctl run -t 1500 tests "zsh tools/tests/all.zsh > <scratch>/all.log 2>&1; echo rc=\$? >> <scratch>/all.log"` and read `<scratch>/all.log`'s verdict line and `rc=` line.
- [ ] **Step 2: Run the board suite** the same way with `python3 -m unittest discover -s board/tests`, and read the `Ran N tests` block from its file. Do not edit a `board/*.py` file while it runs.
- [ ] **Step 3: Run the hook tests** and count `FAIL ` lines uncapped. Run `npm ci` and `npm test` in `tools/discord-bridge`.
- [ ] **Step 4: Run the three real-state checks** and put their outputs in the report.
- [ ] **Step 5: Report** each verdict with the command and the line it came from.

---

### Task 12: User gate: next queue boundary after merge

**Goal:** At the first queue boundary after this branch is merged (queue task #18 is next), the lineage file shows a handoff the lead started within one turn of marking the `Plan & run:` task completed, and the run record written for the following spec has `lead_handoffs >= 1` and a non-null `lead_context_peak`, checked with the `jq` command below on `docs/superpowers/metrics/runs.jsonl`.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:**
- Read only: `docs/superpowers/metrics/runs.jsonl` on `main`, `~/.local/state/agent-board/lineage/agent-board.jsonl`, the previous lead's transcript

**Acceptance Criteria:**
- [ ] This task is not run inside this plan's execution. It stays open until the next `Plan & run:` spec after the merge has finished and been recorded, and it is checked then by the lead that is running at that time.
- [ ] The lead handed off by itself: in the previous lead's transcript, the `TaskUpdate` that set the `Plan & run:` task to `completed` is followed, within one main-thread turn, by the Skill call `agent-board:handoff`, with no user message between them. The lineage file has a line whose `ts` is after that `TaskUpdate`'s timestamp and before the next spec's `started_at`.
- [ ] The nudge fired: the previous lead's transcript holds the text `Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task.` after that `TaskUpdate`.
- [ ] The run record of the spec that followed the boundary has `lead_handoffs >= 1` and a non-null `lead_context_peak`: the Verify command prints `true`.
- [ ] The boundary doc has the four sections `Queue state`, `Live state`, `Carried over`, `Pointers`, and `python3 -I board/ctxsize.py doc <doc>` prints its token count; the count and the record's `post_handoff_tokens` and `rereads` are reported to the user.
- [ ] The user sees the handoff on Discord (the lead's usual handoff line). Nothing is asked of the user.
- [ ] A criterion that fails is reported to the user with the captured output; the gate is not closed.

**Verify:** `jq -s -e '[.[]|select(.kind=="run")]|last|(.lead_handoffs>=1 and .lead_context_peak!=null)' docs/superpowers/metrics/runs.jsonl` → `true`

```json:metadata
{"files": [], "verifyCommand": "jq -s -e '[.[]|select(.kind==\"run\")]|last|(.lead_handoffs>=1 and .lead_context_peak!=null)' docs/superpowers/metrics/runs.jsonl", "acceptanceCriteria": ["not run inside this plan; checked at the next spec boundary after merge (#18 is next)", "the lead ran agent-board:handoff within one main-thread turn of the completing TaskUpdate, with a lineage line between that update and the next spec's start", "the nudge text is in the previous lead's transcript after that TaskUpdate", "the following run record has lead_handoffs >= 1 and a non-null lead_context_peak (the jq command prints true)", "the boundary doc has the four sections and its token count, post_handoff_tokens and rereads are reported", "the user sees the handoff on Discord and is asked nothing", "a failed criterion is reported with output and the gate stays open"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```

**Steps:**

- [ ] **Step 1: After the next spec is recorded**, run the Verify command on `main`. On 2026-11-20, before any of this plan's code, it printed `false` (exit 1) on the real log, so it cannot pass by accident.
- [ ] **Step 2: Check the transcript and lineage criteria** with read-only commands, capture their output, and report to the user.
