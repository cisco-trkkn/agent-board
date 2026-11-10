# Overnight queue reliability: no stall after shutdown, a hold bound to the queue, real sleeps only

Date: 2026-11-10 · Ideas: 104, 110, 111 in `~/.local/state/agent-board/ideas/agent-board.md`
Related: `docs/superpowers/specs/2026-11-05-queue-keep-awake-design.md` (spec 9), `claude/plugin/skills/handoff/SKILL.md`,
`tools/lib/awake.zsh`, awake probe report `/private/tmp/claude-503/awakeprobe/report.md` (may be gone)

## Problem

1. **Lead stalls after shutdown_requests (110).** A teammate that approves its shutdown just exits; nothing re-invokes
   the lead. A lead that ends its turn "waiting for confirmations" (handoff step 1, teardown before relay) idles
   forever. Seen 2026-11-09 in the interiors overnight queue: session ff88723d idle 22:22–01:43Z (3h20m).
2. **The awake hold dies with one claude process (111).** `awake on` runs `caffeinate -i -s -w <pid>` on the nearest
   claude ancestor of the caller (`tools/lib/awake.zsh` `_aw_claude_pid`). A relay kills that lead (the 01:43Z hold
   died at relay); a non-lead claude that ran `on` binds the hold to itself (21:13:36Z, pid 37993). `_aw_current`
   then deletes `awake.json`; while the wrong owner is alive, the lead's `on` says "already on" and keeps it.
3. **The morning report's Sleep section is noise (104).** `awake sleeps` prints every Sleep, Wake and DarkWake line:
   on this machine's log (2026-11-03 to 2026-11-10) 450 Sleep, 465 Wake and 429 DarkWake lines, of which 17 Sleep
   lines are real (8 Idle Sleep, 8 Clamshell Sleep, 1 Low Power Sleep); the rest are 259 Maintenance Sleep,
   157 Sleep Service Back to Sleep, 17 Notification Wake Back to Sleep.

## Decisions

- Stall fix: **wait in the same turn** (helper + rule) **and a Stop guard** as a backstop.
- Hold: **bind queue-mode holds to the tmux server**, re-point a hold owned by another pid, re-arm at task boundaries.
- Sleeps: **real sleep periods only**, `--all` for the old output.

## Design

### 1. `tmux-ctl wait-gone`

`tmux-ctl wait-gone <name>... [--timeout <s>]` (default 300). Session = the caller's (`$TMUX_PANE`'s session; outside
tmux: usage error 2). Every 2 s list windows; a name is gone when no window is named `✦ <name>`. All gone → print
`wait-gone: all gone`, exit 0. At timeout: `kill-window` each remaining `✦ <name>` window, print
`wait-gone: killed <names> after <s>s`, exit 3. Names are matched exactly (a `✦ ` prefix in the argument is stripped).

### 2. Rules

- `claude/orchestrator.md` (Rules, and "When the task is done, shut the team down"): after sending shutdown_requests,
  run `tmux-ctl wait-gone <names>` in the same turn; never end a turn waiting for shutdown confirmations. Queue mode
  step 1 and the handoff-related lines use `tmux-ctl awake on --queue --lid` instead of `awake on --lid`; queue mode
  step 2 adds: at the start of each `Plan & run:` task, run `tmux-ctl awake status` and, when it is off, `tmux-ctl
  awake on --queue --lid`. "Starting from a handoff": `Queue mode: on` → `tmux-ctl awake on --queue --lid`.
- `claude/plugin/skills/handoff/SKILL.md`: step 1 (checkpoint, then shutdown) ends with `tmux-ctl wait-gone` in the
  same turn; a self-started handoff runs `tmux-ctl handoff-mark` right after writing the doc (step 3); a user-started
  one does not.

### 3. Stop guard

Two scripts in `claude/plugin/scripts/`, registered in `claude/plugin/hooks/hooks.json`:

- `shutdown-record.sh` (PostToolUse, matcher `SendMessage`): when `tool_input.message` is an object with
  `type == "shutdown_request"` (or a JSON string that parses to one), append `tool_input.to` to
  `<TC_STATE>/shutdown-pending/<session_id>` (one name per line, deduped). Nothing else. Fail-open, prints nothing.
- `lead-stop-guard.sh` (Stop): exits 0 at once unless `AGENT_BOARD_LEAD=1` and `$TMUX` is set.
  - Pending teammates: read the session's pending file; drop names with no `✦ <name>` window in the lead's tmux
    session (rewrite the file; delete it when empty). Names left → block.
  - Handoff: `<TC_STATE>/handoff-pending/<session_id>` exists → block.
  - Block = print `{"decision":"block","reason":"<text>"}` with reason
    `teammate(s) <names> still shutting down: run tmux-ctl wait-gone <names>, then continue` and/or
    `a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session <id> (handoff skill step 5)`.
  - Loop cap: `<TC_STATE>/stop-guard/<session_id>` holds `<hash of the block reason> <count>`; the same reason a 4th
    time in a row → allow (exit 0), append a line to `<TC_STATE>/stop-guard.log`, reset the counter. Any allowed stop
    with nothing pending deletes the counter.
- `tmux-ctl handoff-mark [--clear]`: writes or removes `<TC_STATE>/handoff-pending/<CLAUDE_CODE_SESSION_ID>` (needs the
  variable; else error 2). `tmux-ctl relay` removes the old session's marker (`--old-session <id>`) once the relay is
  scheduled.

### 4. Awake hold bound to the queue

In `tools/lib/awake.zsh`:

- `awake on --queue [--lid]`: the watched pid is the tmux server's (`tmux display -p '#{pid}'` on the caller's server,
  via the tmux-ctl tmux wrapper). `awake.json` gains `"queue": true`. `--queue` with `--pid` → usage error 2.
- Re-point: `on` without `--queue` when a live hold exists whose `queue` is not true and whose watched pid is not the
  caller's claude ancestor → kill that caffeinate, start a new hold on the caller (keep `lid`/`watchdogPid` as they
  are), print `awake: on (re-pointed from <old> to <new>)`. `on --queue` over a non-queue hold → re-point to the tmux
  server. `on` (non-queue) over a queue hold → `already on (queue)`, unchanged.
- `status` prints `queue` when the hold is a queue hold.
- The lid watchdog's lead pid (`_aw_lid_on`) for a queue hold is the tmux server pid as well.
- `off` unchanged (ends any hold).

### 5. Real sleeps only

`awake sleeps <since> [--all]`: default output is one line per real sleep period: `<start> – <end> <reason>` (local
`YYYY-MM-DD HH:MM:SS`), end = the next `Wake` line's time (not DarkWake), `…` when none yet. Real = Sleep lines whose
reason is not one of `Maintenance Sleep`, `Sleep Service Back to Sleep`, `Notification Wake Back to Sleep` (a
deny-list, so a new real reason still shows). DarkWake lines are dropped. `--all` prints the current format.
The morning report rule (orchestrator.md Queue mode step 5) is unchanged; it gets the shorter output.

## Error handling

Hooks are fail-open: any error → exit 0 with nothing printed (never block a stop by accident). `wait-gone` with a
window that cannot be killed prints it and still exits 3. `awake on --queue` with no tmux server → `awake: no tmux
server; run on without --queue`, exit 1.

## Testing

- `wait-gone` (zsh, scratch tmux server): two `✦` windows closed after 1 s → exit 0; one that stays → killed at a
  3 s timeout, exit 3; `✦ ` prefix stripped; outside tmux → 2.
- `shutdown-record.sh` with fixture hook JSON: object and string message forms, a plain message ignored, dedupe.
- `lead-stop-guard.sh` with fixture JSON and a scratch tmux server: non-lead → allow; pending name with window →
  block text; window gone → allow and file deleted; handoff marker → block; 4th identical block → allow + log line.
- `handoff-mark` set/clear; `tmux-ctl relay` removes the marker (existing relay test harness).
- awake (existing awake tests' stubs for caffeinate/pmset): `--queue` watches the stub tmux pid and records `queue`;
  re-point from a foreign pid; non-queue `on` over a queue hold keeps it; `--queue --pid` → 2.
- `awake sleeps`: a fixture log with every reason kind → only real periods with their Wake end times; `--all` matches
  the old output.
- hooks.json still passes `claude plugin validate claude/plugin`.

## Out of scope

Delivering a native "teammate exited" event to the lead (needs Claude Code support); changing caffeinate flags; the
lid-hold sudoers setup.
