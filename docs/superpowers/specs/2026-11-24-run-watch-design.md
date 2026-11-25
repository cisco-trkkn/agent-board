# Run watch: auto-armed handoff guard, overdue runs killed, teammate-hooks test scrub

Status: approved by the user on Discord, 2026-11-24 (A-Q1 option 1, design "Ok"). Source: the regroup of the ideas
inbox, 2026-11-24, group A "queue reliability" (ideas 2026-11-24 01:42, 09:57, 10:00, 2026-11-23 18:41).

## Decisions (user, Discord, 2026-11-24)

1. One spec, three parts (a, b, c); each has its own tests.
2. Hung runs: the night watch detects and acts (option 1), not a worker.md rule alone.
3. The handoff guard arms itself when a lead writes a handoff doc.

Depends on `docs/superpowers/specs/2026-11-23-night-watch-design.md` (hard): part b extends `board/watch.py`,
`board/overview.py` and `board/notify.py` as that spec builds them, and acts only in queue mode as it defines it (§1).

## a. Auto-armed handoff guard

Seen 2026-11-24 01:42: the lead wrote a boundary handoff doc and ended its turn without `tmux-ctl handoff-mark` and
without `tmux-ctl relay`; it sat idle 17 min. The Stop guard (`claude/plugin/scripts/lead-stop-guard.sh`, mark
`$STATE/handoff-pending/<session id>`) exists but arms only when the skill runs `handoff-mark`.

- New PostToolUse hook `claude/plugin/scripts/handoff-arm.sh`, matcher `Write|Edit|MultiEdit`, registered in
  `claude/plugin/hooks/hooks.json` (not async: the mark must exist before the turn can end).
- It acts only when `AGENT_BOARD_LEAD=1`, the session id matches `^[A-Za-z0-9_-]+$`, and the tool's `file_path`
  resolves under the handoffs dir (`${TC_HANDOFFS_DIR:-~/.local/state/agent-board/handoffs}`, or the older
  `~/.claude/handoffs/`) with a `.md` extension. Then it creates the same mark file `handoff-mark` creates. Anything
  else: exit 0, no output.
- `tmux-ctl relay` clears the mark as today. The handoff skill's **Not yet** path runs `tmux-ctl handoff-mark --clear`
  before it ends (`claude/plugin/skills/handoff/SKILL.md`), and so does calling a handoff off. The explicit
  `handoff-mark` step stays (harmless when the hook already armed it).
- A teammate (`AGENT_BOARD_LEAD` unset) writing into the handoffs dir arms nothing.

Tests (`claude/hooks/tests/` style or `tools/tests/`, temp `TC_STATE`): lead Write of a handoffs `.md` → mark exists;
same for Edit; a non-lead → no mark; a path outside the dir, or a non-`.md` → no mark; a bad session id → no mark;
the Stop guard then blocks; `relay` (or `--clear`) → the guard lets the stop through. Leak check: the real
`~/.local/state/agent-board/handoff-pending/` is unchanged.

## b. Overdue runs (night-watch kind `run_overdue`)

Seen 2026-11-24: engine part 2 Task 5's `npm test` hung 6h25m while its teammate and the lead waited.

**Caps.** `docs/superpowers/run-caps.json`:

```json
{"default_s": 900,
 "caps": [
   {"match": "node --test", "cap_s": 360},
   {"match": "npm test", "cap_s": 360},
   {"match": "unittest discover -s board/tests", "cap_s": 1080},
   {"match": "tools/tests/all.zsh", "cap_s": 1620},
   {"match": "tools/tests/run-all.zsh", "cap_s": 1620}]}
```

`match` is a plain substring of the process command line; the first match wins; no match → `default_s`. A missing or
unparsable file → the defaults above, built into `board/watch.py`, and one log line.

**What is watched.** In queue mode only (night-watch §1), every pane of a `✦ <name>` window: the descendants of the
pane's process (`ps -ax -o pid,ppid,etime,time,command`, one call per overview), excluding the `claude` process itself
and shells whose only child is watched. For each descendant whose elapsed time is past its cap:

| State | Action |
| --- | --- |
| first seen past cap | Discord alert `<project>: <name> run past cap: <cmd, 80 chars> (<n> min, cap <c> min)`; record its CPU time |
| CPU time rose since the previous overview | nothing more ("slow but moving"); keep recording |
| CPU time unchanged (same PID set) on 2 overviews in a row and for at least 120 s | `kill <pid>` (TERM, then KILL after 10 s if alive), by PID only, never a pattern; type into the teammate's pane, only while it is at its prompt or busy waiting on that command: `[Watch] killed <cmd> after <n> min, no progress: report to the lead`; nudge the lead (night-watch §3 rules: once, only when ready): `[Watch] killed <name>'s <cmd> after <n> min, no progress: read its report.` |

One kill per PID. A PID that is gone before the kill → the stall clears. State in `$TC_STATE_DIR/watch.json` beside the
night watch's (`run_overdue` entries keyed `<window>:<pid>`: `first_at`, `cpu`, `flat_count`, `flat_since`, `killed_at`). A board
restart reads it, so a PID is not alerted or killed twice.

**Morning report.** Each kill is one `watch_kill` line appended to `$TC_STATE_DIR/watch/kills.jsonl`
(`{"at","project","window","pid","cmd","elapsed_s","cap_s"}`); the lead's morning report (Queue mode step 5) lists that
night's lines under **Seen** (`claude/orchestrator.md`: one more continuation line, not a new step line, per the
step-line tests in `tools/tests/test_plugin.zsh`).

**Seams.** `ps` runner, kill function, clock and tmux-ctl runner are injected, as `Notifier` and the night watch's
`watch.py` do.

Tests (`board/tests/test_watch_runs.py`): fixed `ps` outputs and a fake clock: under cap → nothing; past cap → one
alert; CPU rising → no kill; flat twice and 120 s → one kill of that PID, one teammate line, one lead nudge; a second overview →
no second kill; queue mode off → nothing; a caps file with a match → its cap; missing caps file → defaults; restart
from `watch.json` → no repeat. E2E on a scratch tmux server (`-f /dev/null`): a `✦ fake` window running
`perl -e 'sleep 9999'` with a 1 s cap via a temp caps file and the clock seam, queue-mode task list as in night-watch
§7: the process is gone, the pane shows the `[Watch] killed` line, `kills.jsonl` has one line. Leak check on the real
`watch*` files.

## c. test_teammate_hooks.zsh scrub

`tools/tests/test_teammate_hooks.zsh` fails (3 FAILs) whenever `AGENT_BOARD_LEAD` is set in the calling shell. The
test unsets `AGENT_BOARD_LEAD` (and `AGENT_BOARD_TEAMMATE` if it reads it) for every case that does not set it on
purpose. Test: run it with `AGENT_BOARD_LEAD=1` exported → ALL PASS; without → ALL PASS. Then remove the shared-context
gotcha that says to run it with `env -u AGENT_BOARD_LEAD`.

## Parts

- `claude/plugin/scripts/handoff-arm.sh` (new), `claude/plugin/hooks/hooks.json`, `claude/plugin/skills/handoff/SKILL.md`.
- `board/watch.py`, `board/overview.py` (per-pane process sample), `board/notify.py` (`run_overdue` kind and text).
- `docs/superpowers/run-caps.json` (new).
- `claude/orchestrator.md`: the `[Watch] killed` line meaning (beside night-watch's `[Watch]` paragraph) and the
  Seen line in step 5.
- `tools/tests/test_teammate_hooks.zsh`.
- `docs/ARCHITECTURE.md`: a few lines under the Night watch section.

## Out of scope

Killing anything outside queue mode or outside a `✦` pane; killing by pattern; restarting a killed run; per-test
timeouts inside the suites themselves; LLM judgment of progress.
