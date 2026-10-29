# Overseer: one read-only view across every project

Idea (francisco_ruiz inbox, 2026-10-20): "i spend a lot of time checkin in on the orchestrator of each project. This gets tiring when
there are multiple projects. It would be nice to have a master orchestrator which just allows me to keep tabs. I want it to be a
lightweight agent. A manger's manager. I dont want this manager to add any bureacracy its just so I dont have to switch priject views
just to know whats going on".

This is Group B, part 1 (B1). B2, several orchestrators in one project, has its own spec.

## Problem

The Agent Board shows every project's raw state: windows, runs, tasks, artifacts and "Needs you". To know what each project is
*doing*, what's blocked or what finished, the user still opens each project or asks each lead. Nothing summarises across projects,
nothing answers questions about them, and nothing tells the user when something happens.

## Decisions (user, 2026-10-28)

- **All three:** a per-project summary, asking questions, and notifications.
- **Read-only:** the overseer never messages, redirects or stops a project's agents. The user goes to the project to act.
- **Approach 1:**
  - the digest is built by code (no LLM);
  - notifications are code-driven state changes;
  - a mechanical-tier overseer agent answers questions from the digest.
- **Notifications:** macOS banners and the board tab. They include high context and high usage, reusing the board's usage-alert
  thresholds.
- **Starts automatically** whenever a project has a lead. No button.
- **The board's home page is the overseer view.**

## Behaviour

### Digest
- **`board/overview.py`** builds one record per project from state the board already has:
  - the active plan's title and `done/total` (from `planview`);
  - in-progress tasks, with each owner;
  - "Needs you" items;
  - the last test run: command, exit code, age;
  - the lead's busy/idle state and when it was last active;
  - the last three registered artifacts;
  - the epoch;
  - the project's live usage alerts (`usage.card_alerts()`);
  - its spend today.
- **`GET /api/overview`** returns them as JSON.
- **`tmux-ctl overview [project] [--json]`** prints one compact line per project, or the JSON.

### Notifier
- **What it is:** a thread in `board/server.py`. It compares each new overview with the previous one and emits events.
- **The events:**
  1. a "Needs you" item appears;
  2. a plan finishes (all of its tasks are complete);
  3. a test run ends with a non-zero exit code;
  4. a lead has been idle for 15 minutes or more while its plan has open tasks;
  5. **high context:** a session crosses `context_pct` (default 80). The text names the project, the agent and its percentage;
  6. **high usage:** a session crosses `burn_per_hour` or `session_total`, or the project's spend today crosses `day_total`.
- **Thresholds:** all come from the existing `usage-alerts.json`. `day_total` is a new optional key with no default, so it's off
  until set; the validator accepts it.
- **When an alert fires:** once when it first appears; not again while it stays on; again only after it clears and comes back.
  At most one event of a kind per project every 5 minutes.
- **Delivery:**
  - a macOS banner via `osascript -e 'display notification …'`; a failure is logged and nothing else happens;
  - a board-tab browser notification plus an unread badge in the tab title, fed from the events list in `/api/overview`.
- **Off switch:** `TC_NOTIFY=0` turns notifications off.

### The overseer agent
- **Session:** `overseer`, on agent-board's tmux server, with one window running Claude:
  - model and effort: the mechanical tier (haiku, low effort);
  - system prompt: the new `claude/overseer.md`, not `orchestrator.md`;
  - settings: its own `claude/overseer-settings.json`;
  - no team, no plans, no task-observer.
- **Read-only by permission settings, not by prompt.**
  - Allowed: Read, Grep, Glob, `Bash(tmux-ctl overview*)`, read-only `git log` / `git status` / `git show`.
  - Denied: Write, Edit, NotebookEdit, Agent, SendMessage, `tmux-ctl send|run|tell|agent|keys|relay`, `tmux send-keys`, and any
    other Bash.
- **How it answers:** from `tmux-ctl overview --json` first. If needed, it reads a project's plan file, task list, reports under
  `.superpowers/briefs/` and registered artifacts.
- **Acting:** asked to act, it names the project window to go to and what to say there.
- **Lifecycle:**
  - started by `tmux-ctl`'s session setup whenever a project session with a `claude` window exists and `overseer` doesn't;
  - re-checked by the board server on each overview build, so a crashed or killed overseer is recreated;
  - stopped when the last project session closes, via the existing session-closed hook;
  - idle costs no tokens;
  - `TC_OVERSEER=0` disables it.

### Board home page
- **`/`** serves the overseer view:
  - digest cards for every project, each linking to that project's existing page;
  - the overseer's live terminal through the existing ttyd panel;
  - the notification list.
- The per-project pages keep their current URLs.

## Changes

| File | Change |
|---|---|
| `board/overview.py` (new) | Digest builder. |
| `board/notify.py` (new) | Event diffing, once-per-appearance and rate-limit logic, injected runner for `osascript`. |
| `board/server.py` | `/api/overview`, notifier thread, overseer lifecycle check, home route. |
| `board/usage.py` | Accept and evaluate `day_total`. |
| `board/index.html` | Home view: digest cards, overseer terminal, notifications and badge. |
| `bin/tmux-ctl` | `overview` subcommand; ensure the `overseer` session in session setup. |
| `bin/tmux-session-closed` | Stop `overseer` when no project session remains. |
| `claude/overseer.md`, `claude/overseer-settings.json` (new) | The overseer's prompt and read-only permissions. |
| `docs/ARCHITECTURE.md`, `docs/INSTALL.md`, `README.md` | Overseer, events, `TC_NOTIFY`, `TC_OVERSEER`, `day_total`, the new home page, alongside existing entries. |

## Acceptance

- **`board/tests/test_overview.py`:** a digest from fake tmux and state folders, covering each field, including no plan, no runs and
  no alerts.
- **`board/tests/test_notify.py`:**
  - each of the six events fires once;
  - it doesn't fire again while the condition holds;
  - it fires again after clearing and coming back;
  - the 5-minute rate limit is respected;
  - `TC_NOTIFY=0` sends nothing;
  - the banner text names the project and agent;
  - `osascript` goes through an injected runner, plus one real call in a test skipped off macOS.
- **`board/tests/test_usage*.py`:** `day_total` accepted, evaluated, and off when absent.
- **Overseer lifecycle (zsh, scratch tmux server):**
  - created with the first project session;
  - recreated after `kill-session`;
  - stopped when the last project closes;
  - not created with `TC_OVERSEER=0`.
- **Overseer permissions:** a test loads `overseer-settings.json` and asserts that every write and messaging tool listed above is
  denied, and that `tmux-ctl overview` is allowed.
- **Home route:** `/` serves the overseer view, and project pages still load at their old URLs.
- **E2E (scratch board, two scratch projects, scratch `TC_STATE`):**
  - the overseer appears without being started by hand;
  - making one project need you gives exactly one macOS banner and one board notification;
  - lowering `context_pct` in a scratch alerts file and crossing it gives exactly one high-context banner;
  - the overseer answers "anything need me?" naming the right project, and makes no write tool calls (checked in its transcript).

## Out of scope

- The overseer acting on projects, or relaying messages.
- Notifications other than macOS banners and the board tab (phone, Slack, tmux status line).
- Coordinating several orchestrators in one project: that's B2.
