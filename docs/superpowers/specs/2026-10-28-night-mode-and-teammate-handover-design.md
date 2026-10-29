# Long-running work: night mode and teammate handover

Ideas (francisco_ruiz inbox):
- 2026-10-20: "i need to to make detachment/reattachment easier in tmux for long running night tasks".
- 2026-10-22: "teamates should not be allowed to go over the context budget of 300K. they should find stopping points and handover
  to a new agent just like the orchestrator".

## Problem

- **Overnight runs stop.** The Mac sleeps, or a lead or teammate stops at a question or a permission prompt. Nothing then happens
  until morning.
- **Teammates run until their context is huge.** Quality and cost both degrade as a context grows. Unlike the lead, which hands
  over through the relay, a teammate has no handover.

## Decisions (user, 2026-10-28)

- **C1 pain points:** sleep stops the work, and agents stop for input. Reattaching itself is not the problem.
- **Questions at night:** the lead decides and logs reversible choices, and parks gated tasks until the morning report.
- **Sleep:** keep the Mac awake while work runs, then let it sleep.
- **C2 trigger:** the lead starts the handover, prompted by the board's alert.
- **C2 budget:** per model tier.

## Behaviour

### C1: night mode
- **`tmux-ctl night on | off | status`**, per project. While night mode is on, the session option `@tc_night=1` is set, and the
  board shows a 🌙 marker on the project.
- **Check when turning it on.** It prints a warning for each of these, and turns night mode on regardless:
  - a window already waiting at a permission prompt or a question (the board's existing prompt detection);
  - an agent not in `auto` permission mode;
  - running on battery (`pmset -g batt`), with the note that closing the lid on battery still sleeps the Mac.
- **Staying awake:**
  - night mode starts `caffeinate -i` and records its pid in `$TC_STATE/night-<project>.json`;
  - the board server stops that pid once the project has no open plan task and no running test, or when night mode is
    turned off;
  - it is killed by its recorded pid only.
- **Questions at night:** `claude/orchestrator.md` gains a "Night mode" section, which applies while `@tc_night=1`.
  - **Reversible choices:** the lead makes the reasonable choice, continues, and records `assumed: …` with the task id.
  - **Gates** (destructive steps, merges, pushes, shared-state changes, removing anything, and user-confirm steps that a loaded
    skill names): the lead marks the task `blocked: waiting for user — <question>` and continues with tasks that don't depend
    on it.
  - **Teammates' questions** reach the lead as usual, and the lead applies the same rule.
- **Backstop hook:** `claude/plugin/scripts/night-guard.sh`, PreToolUse(AskUserQuestion). While `@tc_night=1`, it denies the
  question with "Night mode: decide and log it as an assumption, or park the task as blocked; the user reads the morning report."
  - Silent when night mode is off, and with `TC_NIGHT_GUARD=0`.
  - Lets the question through if it hits an error.
- **Morning report:** when night mode is turned off, or the active plan finishes while it's on, the lead writes
  `.superpowers/night/<YYYY-MM-DD>.md` and registers it with `tmux-ctl artifact`. It lists:
  - finished tasks with evidence;
  - every `assumed:` line;
  - blocked tasks and their questions;
  - test runs with their exit codes.

### C2: teammate handover at a per-tier budget
- **Budget:** a new `usage-alerts.json` key, `teammate_context_budget`. Default
  `{"mechanical": 150000, "standard": 300000, "frontier": 300000}`.
  - A model whose window is smaller than its tier's budget is capped at 80% of its window (from `board/prices.json`).
  - The tier comes from the teammate's model, through the routing map (`model-routing.json`, else the defaults
    haiku→mechanical, sonnet→standard, fable/opus→frontier).
- **Alert:** `usage.card_alerts()` gains `teammate_budget` when a live teammate session's context reaches 85% of its budget.
- **Delivery to the lead:** the board queues a line for the lead's pane through the existing CommentQueue, delivered when the
  pane is idle:
  `[Board] Teammate <name> is at <N>K context (<tier> budget <B>K): hand it over.`
  - It's sent once per teammate session.
  - It's sent again if that session is above 100% of its budget ten minutes later.
  - B1's high-context banner tells the user as well.
- **Lead protocol** (`claude/orchestrator.md`, a new "Teammate handover" rule):
  1. Send the teammate `checkpoint now`.
  2. Wait for `checkpoint written`.
  3. Send the shutdown request and wait for the termination notice (the existing replacement rule).
  4. Start a fresh teammate with the same name, role and tier. Its prompt is the teammate rules plus
     `.superpowers/checkpoints/<name>.md`.
  5. Log `handover: <name> at <N>K` in the plan's SDD progress ledger.

  In night mode, the lead runs this without asking.
- **Teammate rule:** "On `checkpoint now`:
  - finish the current step, not the whole task;
  - write `.superpowers/checkpoints/<name>.md` (task, files, progress, next step, assumptions, how to verify), in the same shape
    as the handoff skill's teammate checkpoints;
  - reply `checkpoint written`;
  - never start a new task after it."

## Changes

| File | Change |
|---|---|
| `bin/tmux-ctl` | `night` subcommand: on/off/status, the check when turning it on, the caffeinate start. |
| `board/night.py` (new) | Night state, pid file, the check, stop-caffeinate condition. |
| `board/server.py` | Stop caffeinate when work ends; 🌙 marker; queue the `teammate_budget` line to the lead. |
| `board/usage.py` | `teammate_context_budget` key, tier resolution, `teammate_budget` alert. |
| `claude/plugin/scripts/night-guard.sh` (new), `claude/plugin/hooks/hooks.json`, `plugin.json` | Night backstop hook. |
| `claude/orchestrator.md` | "Night mode" section; "Teammate handover" rule; the new teammate rule on `checkpoint now`. |
| `claude/plugin/skills/handoff/SKILL.md` | Point teammates' checkpoint shape at the same template, so both handovers share it. |
| `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, `README.md` | Night mode, the hook and `TC_NIGHT_GUARD`, the new usage-alerts key, alongside existing entries. |

## Acceptance

- **`board/tests/test_night.py`:**
  - `on` sets the option and records the pid;
  - the check reports a waiting prompt, a non-auto agent and battery power (each from fixtures);
  - caffeinate is stopped when there are no open tasks and no running tests, and on `off`;
  - only the recorded pid is killed;
  - one real `caffeinate -i -t 2` run in a test skipped off macOS.
- **`tools/tests/test_night_guard.zsh`:**
  - denies AskUserQuestion with the night message while `@tc_night=1`;
  - silent when off and with `TC_NIGHT_GUARD=0`;
  - lets the question through on garbage input.
- **`board/tests/test_usage*.py`:**
  - budgets per tier from the routing map;
  - the cap for a small window;
  - the alert at 85%;
  - the default without the key;
  - an invalid key value is reported as a warning.
- **Board queue test:** the handover line is queued once per teammate session, re-queued only when above 100% after 10 minutes,
  and delivered only to an idle lead pane.
- **E2E after merge** (scratch `dev` session, scratch `TC_STATE`):
  - **Night mode:** turning it on starts caffeinate; a lead question during a scratch plan turns into an `assumed:` line or a
    blocked task; the morning report appears in the artifacts panel; caffeinate stops when the plan finishes.
  - **Handover:** a scratch `usage-alerts.json` with a tiny `mechanical` budget sends the handover line to the lead, and the lead
    replaces the teammate under the same name, from its checkpoint.

## Out of scope

- Keeping a lid-closed Mac awake on battery, which needs system power settings.
- A teammate starting its own handover (the user chose the lead).
- Automatic reattach or recovery after a reboot.
