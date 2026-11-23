# Night watch: notice a stalled overnight queue

Status: approved by the user on Discord, 2026-11-23 (design parts 1 and 2). Source: the regroup of the ideas inbox,
group C "self-watching", narrowed to the night watch (C-Q1 answer 1).

## Goal

While a queue runs overnight (Queue mode in `claude/orchestrator.md`), notice when it stalls without anyone asking
the user, tell the user on Discord, nudge the lead once, fix the cases that are safe to fix without judgment, and
alert again if nothing changes. Today the board's notifier (`board/notify.py`) already alerts on a lead idle 15 min
with open tasks, an agent stuck in one turn, an agent failing tool calls, high usage and a waiting permission prompt.
It does not notice a dead or silent teammate, a dropped awake hold or a weekly usage pace that will not last the
week, it never nudges the lead, and it never repeats an alert the lead ignored. A queue that stalls at 01:00 is found
at 08:00.

## Decisions (user, Discord, 2026-11-23)

1. **Night watch only** (C-Q1: 1). Spend watch, per-component watchers and architecture scanning are out of scope.
   Guardrails for self-change and finding-to-work stay in the supervised improvement loop spec
   (`2026-11-16-supervised-improvement-loop-design.md` §3, §6); the night watch is one more source of findings for it,
   not part of it.
2. **On a stall: alert + one nudge + safe fixes + re-alert** (C-Q2: 3).
3. **Extend the notifier** (C-Q3: 1): code in the board, deterministic, no LLM, no new process. The Discord bridge
   watches the board's heartbeat.

## 1. When it is on

The watch acts only while queue mode is on: the project's lead task list (the one the board already reads for the
plan view) holds a `pending` or `in_progress` task whose subject starts `Plan & run:` and whose metadata carries
`queue`. This is the queue itself, so a queue that ended normally (its last `Plan & run:` task completed, then
`tmux-ctl awake off`) is not mistaken for a dropped hold. Outside queue mode the notifier behaves exactly as today. The watch runs on every overview the board
already builds (about once a minute) and never on a timer of its own.

## 2. Conditions

New conditions in `board/overview.py` (new record fields) and `board/notify.py` (new kinds), with the existing
latch: an event fires when its condition first appears, not again while it holds, again after it clears and comes
back; one event per kind per project per `RATE_S`.

| Kind | Condition (per project, queue mode) | Key |
| --- | --- | --- |
| `teammate_gone` | a task is `in_progress` with an `owner` whose `✦ <owner>` window does not exist, or whose pane is dead (`#{pane_dead}` = 1) | owner |
| `teammate_silent` | the owner of an `in_progress` task has been at its prompt (agent-status `ready`) for 30 min or more (`SILENT_S = 1800`) | owner |
| `awake_dropped` | queue mode is on and there is no live hold (`$TC_STATE_DIR/awake.json` missing, or its `caffeinatePid` gone) | `awake` |
| `weekly_pace` | the 7-day usage percentage (`usage.plan_limits()["seven_day"]`) is more than 15 points (`PACE_MARGIN = 15`) above the elapsed share of the 7-day window | `seven_day` |

The existing `lead_idle` kind (lead ready 15 min with open tasks) counts as a stall in queue mode as well.

Owner, task status and ownership come from the lead's task list the board already reads for the plan view; window
and pane state from the tmux server the board already queries. A teammate that is busy but hung remains the existing
`stuck` kind and is not duplicated here.

## 3. Actions on a stall

`board/watch.py` takes the notifier's events for a project in queue mode and, per stall:

1. **Alert:** the Discord alert the notifier already sends through `discord_sink`, with the kind's text.
2. **One nudge to the lead** (stall kinds `teammate_gone`, `teammate_silent`, `lead_idle`, `awake_dropped`): one line
   typed into the lead's pane, through tmux-ctl, only while the lead's pane is at its prompt (agent-status `ready`).
   A busy lead is not typed at; the nudge waits for the next overview where the lead is ready, and is sent at most
   once per stall. Lines:
   - `[Watch] teammate <owner> window is gone (task #<id> in progress): respawn it.`
   - `[Watch] teammate <owner> has been idle <n> min with task #<id> in progress: check its report or nudge it.`
   - `[Watch] you have been idle <n> min with <k> open tasks: continue the queue.`
   - `[Watch] the awake hold dropped and I restarted it: <ok | failed: <one line>>.`
3. **Safe fix**, only for `awake_dropped`: run `tmux-ctl awake on --queue --lid` once per stall, and report the
   result in the alert and the nudge. No other fix is automatic. Only the lead can spawn teammates, so the dead
   teammate's fix is the nudge.
4. **Re-alert:** if the same stall (project, kind, key) still holds 15 min (`REALERT_S = 900`) after its first alert,
   one second Discord alert: `<project>: <kind text> — lead did not react (15 min)`. Then nothing more until the
   condition clears.

`weekly_pace` is alert only: no nudge, no fix, no re-alert.

State lives in `$TC_STATE_DIR/watch.json`: per open stall `first_at`, `nudged_at`,
`fixed_at`, `realerted_at`. A cleared stall is removed. A board restart reads the file, so a stall is not
nudged twice.

## 4. Lead side

`claude/orchestrator.md` gets a short `[Watch]` paragraph next to the `[Board]` line: a line starting `[Watch]` came
from the board's night watch, not the user; the lead acts on it (respawns the named teammate per "Replacing a
stalled teammate", reads the teammate's report, continues the queue) and does not reply to it. The text stays one
line per step (the Queue mode step-line tests: see `tools/tests/test_plugin.zsh`).

## 5. Board down

`board/watch.py` writes `$TC_STATE_DIR/watch/heartbeat` on every overview: `{"at": <ISO>, "queue": [<projects in queue mode>]}`. The Discord bridge
(`tools/discord-bridge/bridge.js`, a separate node process) checks it each minute while its project was in queue mode in the last heartbeat it read. If the heartbeat is more than 5 min old it posts once:
`⚠️ <project>: board down, night watch off (last heartbeat <time>)`, and once when the heartbeat is fresh again:
`<project>: board back, night watch on`.

## 6. Parts

- `board/overview.py`: per-project fields for owned in-progress tasks (owner, task id, window present, pane dead,
  owner ready since), queue mode and the awake hold (live or not) and the weekly pace (used %, elapsed %). Added to
  `RECORD_KEYS`.
- `board/notify.py`: the four kinds and their texts in `conditions()`; `KINDS` extended.
- `board/watch.py` (new): queue-mode gate, nudge, awake fix, re-alert, heartbeat, `watch.json`. Clock, tmux-ctl
  runner and sinks injected, as `Notifier` does.
- `board/server.py`: call the watch after the notifier on each overview.
- `tools/discord-bridge/bridge.js` (or a new `lib/` module): the heartbeat check.
- `claude/orchestrator.md`: the `[Watch]` paragraph.
- `docs/ARCHITECTURE.md`: a short "Night watch" section.

## 7. Testing

- Unit (`board/tests/test_watch.py`, extensions to the notify and overview tests): fixed overview records and a fake
  clock for each condition appearing, holding and clearing; queue mode off → no watch action; one nudge per stall,
  only to a ready lead; the awake fix runs once and reports ok or failed; the re-alert fires once at 15 min and not
  for `weekly_pace`; `watch.json` survives a restart without a second nudge.
- E2E on a scratch tmux server (`-f /dev/null`, `tools/tests/lib.zsh`): a fake lead pane at a prompt, a `✦ fake`
  teammate window owning an in-progress task in a temp task list that also holds a pending `Plan & run:` task with
  `queue` metadata; kill the teammate pane; check the Discord feed line, the `[Watch] teammate fake …` line in the lead pane and, with the clock seam moved
  15 min, the re-alert.
- Bridge (`tools/discord-bridge/test/`): stale heartbeat in queue mode → one down post; fresh again → one back post;
  queue mode off → nothing.
- Isolation: every test sets `TC_STATE` to a temp dir; the leak check compares the real
  `~/.local/state/agent-board/watch*` before and after.

## Out of scope

Spend watch, per-component watchers, architecture scanning (C ideas parked in this spec's favour); automatic
teammate respawn by the board; any LLM judgment in the watch; acting outside queue mode.
