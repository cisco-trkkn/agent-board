# Efficiency now: spec-boundary handoffs, context size in metrics, the limits gap, two probes

Date: 2026-11-20. Status: design approved by the user on Discord, in two parts (15:03Z and 15:04Z). Source: `docs/superpowers/notes/2026-11-20-efficiency-learnings-for-pcee.md`, items 3-6. Items 1, 2 and 4 (engine part) are edits to the engine and improvement-loop specs (E1-E3, the same date), not part of this spec.

## Problem

From `docs/superpowers/metrics/runs.jsonl` (29 `run` records, 2026-11-20):
- 97.5% of tokens are cache reads, and output is 0.44%.
- The lead is 53.6% of tokens and 58.5% of dollars (median per-run `lead_share` 0.636).
- The lead hands off only when the context guard warns at 300K tokens: 28 handoffs in 29 runs. A lead carrying three specs' context re-reads all of it on every turn of the fourth.
- We can't split the cache-read cost by role or job kind, because no record says how large a context got.
- 13 of 29 runs have no limits reading (`limits` null, `missing: ["limits"]`).

## Decisions (user)

- D1: two pieces. The engine and loop spec edits (E1-E3 now; E4, E5 after this spec's probes) are separate from this spec, which changes what runs today.
- D2: in queue mode, the lead hands off after **every** finished `Plan & run:` spec (merged, kept, failed or awaiting approval), before the next spec's `writing-plans`, whenever another `Plan & run:` task is pending.
- D3: context size is recorded for **both** roles. Each task record gets the implementer's context at the task's end; each run record gets the lead's peak and its handoff count.

## Design

### 1. Spec-boundary handoff (D2)

- `claude/orchestrator.md`, Queue mode step 2 gets one rule. After a `Plan & run:` task is marked completed with its `metadata.outcome`, and every ending step has run (metrics `record` and its commit, the ledger archive), the lead runs `agent-board:handoff` on itself if another `Plan & run:` task is pending. The handoff doc's State of the work names the next spec. The new lead starts that spec with `writing-plans`.
- The same rule goes in the handoff skill's "Your own session" triggers: "a `Plan & run:` spec finished in queue mode, with another pending". It relays without asking, like any self-started handoff.
- **Nudge hook** `claude/hooks/spec-boundary-nudge.sh`:
  - Registered as a PostToolUse hook on the `TaskUpdate` tool in `claude/settings.json` (and the plugin's `hooks.json` if hooks live there for this event).
  - When a `TaskUpdate` sets `status: completed` on a task whose subject starts `Plan & run:`, and the session's task folder still has a pending `Plan & run:` task, it emits additionalContext: `Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task.`
  - It does nothing in every other case, including outside queue mode: no pending `Plan & run:` task means no message.
  - It is read-only and never blocks.
- The order inside the boundary is fixed: outcome, metrics record and commit, then the handoff. The handoff doc records `Queue mode: on` and each queued task's `metadata.queue`, as it does today.

### 2. Context size in metrics (D3)

- **One reader:** `board/ctxsize.py` with:
  - `context_tokens(transcript_path) -> int | None`: the last main-thread assistant turn's `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, the same rule `context-size-guard.sh` uses today.
  - `peak(transcript_path, since=None, until=None) -> int | None`: the maximum of that quantity over the turns in the window.
- `context-size-guard.sh` calls `python3 -I <dir>/board/ctxsize.py last <transcript>` instead of its own `jq` pipeline, so the rule lives in one place. The guard's thresholds, bands and messages are unchanged, and its existing tests stay green.
- **Task records** (`tasks.jsonl`, `board/metrics_tasks.py`) gain `context_tokens`: the implementer's context at the end of its last turn inside the task's window.
  - The agent-to-task join is the one `metrics_tasks` already uses for task tokens (agent name and time window).
  - The transcript comes from the agent's session. If the statusline tap rows already carry a context figure, use that, and record which source was used in the plan's first task.
  - No transcript or figure: `context_tokens: null`, with `context_tokens` added to the record's `missing`.
- **Run records** (`runs.jsonl`, `board/metrics.py` `record`) gain `lead_context_peak` (the peak over the lead's transcripts inside the run window, across handoffs) and `lead_handoffs` (the number of lead sessions in the window, minus one).
- **The report** (`metrics report`) adds one line per spec: `Lead: peak <N>K tokens, <h> handoffs`. The morning report includes it through the existing Metrics section.
- Nothing private goes in a line: no session ids, paths or names, the same rule as today.

### 3. The limits gap

- The first task of the plan finds out why 13 of 29 runs have `limits` null, from the real records and `usage.tap_entries` / `usage.plan_limits` (`board/metrics.py` ~202 and ~707). Its output is a cause stated with evidence, in the plan's ledger and the report.
- The fix follows from the cause. If the cause is outside our code (the tap had no rows in the window, for example because the statusline was not running), the record carries `limits: null` with `missing_reason: "<cause>"` instead of a bare missing. The report prints it.
- Old records are not rewritten.

### 4. Two probes (notes only, nothing changed)

- **Code Mode hooks probe:**
  - Setup: a scratch tmux server (`-f /dev/null`) and a scratch project, with `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1`.
  - Check: do our PreToolUse and PostToolUse hooks fire for a tool call made from Code Mode code? Use the bash-mirror hook and a probe hook that logs every event.
  - Output: `docs/superpowers/notes/<run date>-code-mode-hooks-probe.md`, with the exact setup, the observed events and a go or no-go for E5.
- **Worker context probe:**
  - Setup: one real worker or teammate started the normal way.
  - Check: its `/context` breakdown, and what share MCP tool schemas and connector results take. Read the screen output with `tmux capture-pane`, read-only.
  - Output: `docs/superpowers/notes/<run date>-worker-context-probe.md`, with the numbers and a go or no-go for E4. If MCP schemas are under 5% of a fresh worker's context, E4 is a no-go.

### 5. Last task: apply or close E4 and E5

The plan's last code-free task reads the two probe notes:
- On a go, it applies E4 or E5 to the engine and loop specs as written in the E-revision text.
- On a no-go, it adds a one-line "dropped/blocked: <reason, note path>" under the E item.

## Error handling

- `ctxsize` on a missing, empty or malformed transcript returns None and never raises to the caller. The guard then exits 0 silently, as today.
- The nudge hook, on any parse failure or missing task folder, exits 0 with no output.
- A metrics field the code cannot compute is `null` and listed in `missing`. A `metrics` command never fails a spec, as today.

## Testing

- `board/tests/test_ctxsize.py` runs against real transcript lines copied from this machine and trimmed: one main-thread turn, a sidechain turn that must be ignored, a turn without usage, and a peak over a window. The README in the fixture dir records how they were captured.
- The guard's existing tests run unchanged, plus one test that the guard reads its number from `ctxsize`.
- The nudge hook tests feed it real `TaskUpdate` PostToolUse payloads, captured once from this machine, against a temp task folder:
  - completed `Plan & run:` with another pending → message
  - completed `Plan & run:` with none pending → nothing
  - completed other task → nothing
  - malformed input → nothing, rc 0
- The metrics tests cover `context_tokens`, `lead_context_peak`, `lead_handoffs` and `missing_reason` on temp logs, including a run with two lead sessions.
- **Real-state check (gate):** the next queue boundary after merge. The lead hands off by itself within one turn of marking the `Plan & run:` task completed, and the following run record has `lead_handoffs ≥ 1` and a non-null `lead_context_peak`. The user sees it on Discord. Nothing is asked.

## Out of scope

- The engine itself, the bounce cap and per-kind tool lists (E2, E4: engine spec).
- Any output trimming of `tmux-ctl run` or of tool results.
- Changing the 300K guard threshold.
