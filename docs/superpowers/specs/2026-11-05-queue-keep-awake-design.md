# Queue mode keeps the Mac awake

Date: 2026-11-05 · Status: approved design · Source: ideas inbox (interiors lead's report)

## Problem

An overnight queue runs only while the Mac is awake. On 2026-11-05 the interiors queue (3 specs) stalled for about 8 h: the Mac entered Deep Idle sleep at 03:15 on AC power (`pmset -g log`: "Sleep … Deep Idle … Using AC"). That paused the lead and every teammate until a key press at 11:00. Nothing in Queue mode holds a power assertion, and the morning report cannot say that the night was lost to sleep.

## Goal

- While a queue runs, the Mac does not idle-sleep.
- A handed-off lead keeps that hold in place.
- The morning report lists every sleep that happened during the run, including the ones `caffeinate` cannot stop (a closed lid, a battery running out).

## Non-goals

- Board UI for the awake state.
- Inferring stalls from gaps between ledger entries. `pmset -g log` records the real sleep events, so the report lists those instead.
- Linux and other platforms. The helper says it is unsupported and exits 0.

## Design

### 1. `tmux-ctl awake` (new subcommand in `bin/tmux-ctl`)

| Command | Behaviour |
| --- | --- |
| `awake on [--pid N]` | Holds `caffeinate -i -s -w <pid>`. `<pid>` defaults to the nearest ancestor of the calling shell whose command name contains `claude`; without one and without `--pid`, it fails with `awake: no claude ancestor; pass --pid`. Writes `$TC_STATE_DIR/awake.json` = `{"pid": <watched pid>, "caffeinatePid": <pid>, "since": "<ISO UTC>"}`. If the file names a caffeinate that is still alive (same pid, command `caffeinate`), it does nothing and prints `awake: already on (pid <caffeinatePid>, since <since>)`. A dead or reused pid is replaced. On battery (`pmset -g batt` says `Battery Power`) it also prints `awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night`. Prints `awake: on (pid <caffeinatePid>, watching <pid>)`. |
| `awake off` | Kills the recorded caffeinate only if that pid is still a `caffeinate` process, then removes the file. Prints `awake: off`. With no file, it prints `awake: off` and exits 0. |
| `awake status` | Prints `on (pid …, watching …, since …)` or `off`, plus the power-source line from `pmset -g batt` (source and %). Removes a file whose caffeinate is dead and reports `off`. |
| `awake sleeps <since>` | `<since>` is an ISO time (`2026-11-05T06:05:39Z` or local `2026-11-05 01:05`). Prints the `pmset -g log` lines of type `Sleep`, `Wake` and `DarkWake` at or after that time, one per line as `<local time> <type> <reason>`. `<reason>` is the quoted cause (`Idle Sleep`, `Clamshell Sleep`, `Maintenance Sleep`, …) or the wake reason. It prints nothing when there were none, and always exits 0. |

- **Unsupported platform:** without `caffeinate` or `pmset` on PATH, every subcommand prints `awake: unsupported here` and exits 0, so rule text can call it unconditionally.
- **Why `-i -s`:** `-i` blocks idle sleep on AC and on battery. `-s` blocks system sleep on AC only. Neither keeps a closed lid awake without an external display. `-w <lead pid>` ends the hold when the lead exits, so a crashed or replaced lead never leaves the Mac held awake.

### 2. Rules

- **`claude/orchestrator.md` Queue mode, step 1** (after the answers are written to the tasks): run `tmux-ctl awake on`. If it printed the battery warning, tell the user in one line. That is a notice, not a question, so the "ask once" rule is unchanged.
- **Step 5, morning report:** run `tmux-ctl awake sleeps <run start>`, using the earliest `answeredAt`. Add a **Sleep** section listing its lines, or `none`. Then run `tmux-ctl awake off`.
- **Handoff skill (`claude/plugin/skills/handoff/SKILL.md`), State of the work in queue mode:** add an `Awake: on since <since>` line from `tmux-ctl awake status`. The orchestrator's "Starting from a handoff" step runs `tmux-ctl awake on` when the doc says `Queue mode: on`. The old lead's caffeinate dies with the old lead (`-w`), so the new lead re-arms the hold.

### 3. Tests

- `tools/tests/test_ctl_awake.zsh`, added to `run-all.zsh`, on the scratch tmux harness (`lib.zsh`, temp `TC_STATE`).
- `caffeinate` and `pmset` are stubbed by scripts on PATH. The stubs serve fixture output captured from this machine (`pmset -g batt` on AC and on battery; a `pmset -g log` excerpt with `Sleep`/`Wake`/`DarkWake` lines), stored under `tools/tests/fixtures/awake/` with the capture command in a README line.
- Cases:
  - `on` twice leaves one process and prints `already on`;
  - `on` with a dead recorded pid starts a new one;
  - `off` kills only a pid that is still `caffeinate` (a reused pid is left alone);
  - `status` cleans a stale file;
  - the battery warning shows on the battery fixture and not on the AC one;
  - `sleeps` filters by time and keeps the reason;
  - no `claude` ancestor and no `--pid` fails with the message;
  - with `caffeinate` absent from PATH, every subcommand prints `unsupported here` and exits 0.
- One real run with no stubs: `awake on --pid $$`, then `pmset -g assertions` shows the caffeinate's `PreventUserIdleSystemSleep`, then `awake off`, then the assertion is gone. Its output is pasted in the plan's verification task.

## Acceptance

- During a queue run, `pmset -g assertions` shows a caffeinate assertion owned by the lead's hold.
- After a handoff, the new lead holds one again.
- The morning report has a Sleep section.
- After the report, no caffeinate started by `awake` remains.
