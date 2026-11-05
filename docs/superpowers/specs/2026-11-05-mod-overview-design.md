# Mod: richer overview tab from agent events

Date: 2026-11-05 · Status: approved design, awaiting spec review
Source: ideas file, 2026-11-05 01:21 "use mods to improve the accuracy and capabilities of the overview tab"
(picked in a `regroup`, 2026-11-05).
Depends on: `2026-11-05-mod-agent-status-design.md` (its mod `claude/plugin/mods/agent-status.js`, its status
files and `board/paneclass.py` `mod_states()`). Queued after `2026-11-05-mod-shell-hooks-design.md`.

## Problem

The agent-status mod makes the overview's needs-you and lead status accurate. The overview still cannot say what
each agent is doing, why one needs the user, how long it has been in its state, or that one looks stuck. Mod events
carry all of that.

## User decisions (2026-11-05)

All four additions: what each agent is doing; why it needs you; exact state durations; stuck / failing signals.
Approach: extend the agent-status file (one file and one writer per session), not a second mod or an event log.

## Design

### 1. New fields in `<state dir>/agent-status/<session_id>.json`

Written by `claude/plugin/mods/agent-status.js`, beside its existing `session_id, pane, state, since, updatedAt`:

- `tool`: `{"name", "arg", "startedAt"}` while a tool runs (set when `tool.call` starts, cleared when `next()`
  returns), else `null`. `arg` is short: Bash → the command's first line; Edit / Write / Read / MultiEdit → the file
  path; Agent → its description; anything else → `""`. Always cut to 80 characters.
- `turnStartedAt`: set at `turn.start`, `null` at `turn.complete` and `session.start`.
- `waiting`: `{"kind": "question", "detail": <AskUserQuestion's first question header, else its first question text>}`
  while an AskUserQuestion is open; `{"kind": "permission", "detail": "<tool>: <arg>"}` while a `tool.check` "ask" is
  pending; `null` otherwise. Cleared exactly where `state` leaves `needs-you`.
- `failStreak`: consecutive failed tool calls (a `tool.call` whose `next()` reports an error or throws); a success
  resets it to 0. Starts at 0.
- `lastToolAt`: epoch seconds when the last tool call ended; `null` until one has.

Readers ignore unknown fields; an older file without these fields reads as `null` / 0.

### 2. Overview record (`board/overview.py`)

`paneclass` gains `mod_records(now=None, d=None)` → `{pane: record}` with the same freshness rule as
`mod_states()` (pane matches, known state, `updatedAt` under 45 s); `mod_states()` derives from it, so one listing
serves both.

- `RECORD_KEYS` gains `agents`: one entry per Claude pane of the project,
  `{"window", "pane", "state", "state_s", "tool", "turn_s"}`: `state` is the board status (working / waiting /
  ready); `state_s = now − since`, `turn_s = now − turnStartedAt` (or `null`), `tool` = `"<name>: <arg>"` or `null`.
  A pane without a fresh file gets `state` from the board and `null` for the rest.
- Lead: `lead.idle_s` uses `state_s` when the lead's file is fresh and its state is ready; otherwise today's tmux
  window-activity value.
- `needs_you` entries gain `reason`: `"question: <detail>"` or `"permission: <detail>"` from a fresh file's
  `waiting`, else `null`.
- `alerts` gains, per agent with a fresh file:
  - `{"kind": "failing", "session": <window>, "fail_streak": n}` when `failStreak ≥ failing_streak` (default 3);
  - `{"kind": "stuck", "session": <window>, "turn_s": s}` when busy, `turn_s ≥ stuck_turn_s` (default 1200) and
    `now − lastToolAt ≥ stuck_quiet_s` (default 600, or the whole turn when no tool has ended).
  The three thresholds live in the `usage.thresholds()` config beside the context alerts.

### 3. Page (`board/index.html`, overview tab) and notifier

- Each project card lists one line per agent: `<window> · <state> <duration> · <tool>`
  (e.g. `✦ qrev · busy 12m · Bash: zsh tools/tests/run-all.zsh`); `state_s` formatted as today's idle times.
- Needs-you entries show their reason after the window name.
- `failing` and `stuck` alerts render like the existing context alerts; the notifier (`board/notify.py`) sends them
  as it sends those, once per alert onset.

## Files

- Modify: `claude/plugin/mods/agent-status.js` + its test, `board/paneclass.py`, `board/overview.py`,
  `board/usage.py` (thresholds), `board/notify.py` (if alert kinds are listed there), `board/index.html`.
- Tests: `board/tests/test_paneclass.py`, `board/tests/test_overview*.py`, `claude/plugin/mods/agent-status.test.ts`.

## Testing

- Mod: each new field set, cleared and truncated; `waiting` for both kinds; `failStreak` counts and resets;
  `lastToolAt` set.
- `overview.py`: from fixture status files (one captured from a real mod run, the rest derived): fresh / stale /
  missing file; `idle_s` from `since`; `reason` text; both alerts just below and at each threshold.
- A test board (`TMUX_DASH_PORT=7710`, scratch tmux `-f /dev/null`, temp `TC_STATE`) with one real lead session:
  the card shows the agent line during a Bash call and the reason during an AskUserQuestion.
- Read-only against real state: `GET /api/overview` on the live board (`:7700`) before the merge, checking that the
  current page's fields are unchanged and the new keys are only additions.
- Targeted runs only (those test files, `claude plugin test claude/plugin/mods`); never the full suites.

## Failure

Fails in the queue if the agent-status spec failed (no mod files to read).

## Not in scope

The team band and usage gauges (their own specs); history or charts of agent states.
