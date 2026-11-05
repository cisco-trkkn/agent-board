# E2E: agent-status mod, real session (2026-11-05, Claude Code 2.1.318, haiku)

Procedure as run. Every state below is the content of the session's status file next to the `status` of its pane in a
test board's `/api/state`. Epoch seconds are `date +%s` taken in the same snapshot, so they can be compared.

## Setup

- Scratch tmux server `T() { ~/.local/bin/tmux -L agent-status-e2e -f /dev/null "$@"; }`, session `e2e`, one pane `%0`.
- `TMP=$(mktemp -d)`; `T set-environment -g TC_STATE $TMP` before any claude, and `TC_STATE=$TMP` on the claude command line.
- Lead: `TC_STATE=$TMP claude --model haiku --settings <wt>/claude/session-settings.json --plugin-dir <wt>/claude/plugin`
  (the session came up in "auto mode").
- Test board, from the worktree: `TMUX_DASH_PORT=7710 TMUX_DASH_TOKEN=x TMUX_DASH_TMUX_ARGS='-L agent-status-e2e' TC_OVERSEER=0 TC_STATE=$TMP python3 board/server.py`
  (API `http://127.0.0.1:7710/x/api/state`).
- Live dir untouched: `$TMPDIR/tmux-ctl-503/agent-status/*.json` count before = 0, after = 0.
- A prompt typed with `send-keys "text" Enter` in one call was not always submitted; a separate `Enter` after a 1 s pause was.
- Note: zsh `*.json(N)` raised "no matches found" in this agent's shell; `setopt null_glob` and a plain glob worked.

## Transitions

| Moment | status file `state` (since / updatedAt) | `/api/state` pane `status` |
| :- | :- | :- |
| session up, idle | `ready` (since 1793894657, updatedAt 1793894672, `date` 1793894674) | `ready` |
| turn with no tool (story prompt), 3 s in | `busy` (since 1793894758, updatedAt 1793894758, `date` 1793894760) | `working` |
| same turn, 7 s in | `busy` (updatedAt 1793894762, heartbeat) | `working` |
| after that turn | `ready` (since 1793894765, `date` 1793894780) | `ready` |
| AskUserQuestion open | `needs-you` (since 1793894793, `date` 1793894802) | `waiting` |
| same dialog, 15 s later | `needs-you` (updatedAt 1793894807, `date` 1793894818) | `waiting` |
| answered (one Enter), +1.5 s | `busy` (since 1793894823) | `working` |
| answered, +3 s | `ready` (since 1793894826) | `ready` |
| Bash `sleep 20; echo done`, 5 s in | **`needs-you`** (since 1793894705) | **`waiting`** |
| same Bash, ~12 s in (tool still running) | **`needs-you`** (updatedAt 1793894717) | **`waiting`** |
| Bash finished | `busy` (since 1793894727), then `ready` (since 1793894729) | `working`, then `ready` |

No permission dialog was on screen for the Bash call (auto mode): the pane showed the spinner and an empty prompt.

Carried-over checks:

1. `since`/`updatedAt` are epoch seconds: they sit within 2 s of `date +%s` in every snapshot (`$.clock.now()` is ms and `secs()` converts it right).
2. Heartbeat: with no turn running `updatedAt` went 1793894672 to 1793894687 (+15 s); during the open dialog 1793894793 to 1793894807 (+14 s); idle 1793894826 to 1793894837.
3. `/clear`: the old file `a294bc29-….json` was gone at the first snapshot, 3 s later; no file existed for about 25 s; the next heartbeat (since 1793894840, updatedAt 1793894867) wrote `5c778f14-7399-481a-a9ef-e791de91b00f.json`, `ready`, same pane `%0`. The board fell back to pane text (`ready`) in between.

## Exit

`/exit` (after the `/clear`): `ls $TMP/agent-status` printed `total 0` five seconds later, so the real `rm -f` ran; the pane then
showed the shell (`kind: shell`, `status: idle` in `/api/state`).

## Live read-only

Run with the live environment (`TC_STATE` unset), from the worktree:

    $ python3 -c 'import sys; sys.path.insert(0,"board"); import paneclass; print(paneclass.status_dir(), paneclass.mod_states())'
    /var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tmux-ctl-503/agent-status {}
    rc=0

Live dir file count: 0 before the run, 0 after.

## Cleanup

Test board (pid 7453) killed; `tmux -L agent-status-e2e kill-server` then `ls` said `no server running`; `ps` shows no process
with `-L agent-status-e2e`; no `-w` worktree or branch was created. The only `board/server.py` left is the live board (pid 2531,
started Nov 3, listening on :7700), not started by this run.

## Finding

A Bash call that auto mode approves leaves the file at `needs-you` for the whole run of the tool: `tool.check` resolves
`{decision: 'ask'}` (auto mode's own classifier step), the mod sets `needs-you`, and only the `tool.call` `next()` returning (the tool
finished) sets `busy`. The board shows `waiting` for about 22 s of a `sleep 20` with no dialog open. Not fixed here.
