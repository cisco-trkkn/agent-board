---
name: "tmux-orchestrator"
description: Drive the other windows of the current tmux session with tmux-ctl, such as running tests in the "tests" window, reading the "shell" window, or starting and checking worker Claude agents in their own worktrees. Use it when running inside tmux ($TMUX is set), especially in a `dev` session with claude/shell/tests windows, or when the user asks to run something "in the tests/shell window", watch a window, or coordinate several agents.
---

# tmux-orchestrator

`tmux-ctl` (on PATH in agent-board sessions) controls the windows of the tmux session you're running in.
Output stays visible to the user in those windows. Run `tmux-ctl help` for usage.

## Windows

| Window | Use |
| --- | --- |
| `claude` | the team lead |
| `✦ <name>` | one per teammate while the team runs |
| `<project>-bg` (hidden session) | the agents' `tests` and `shell` windows and their lanes, driven only through `tmux-ctl` |

The user watches agent runs in the Agent Board's Activity drawer and plans, specs, handoffs and reports in its artifacts panel.

## Commands

| Command | Does |
| --- | --- |
| `tmux-ctl list` | Windows: index, name, `idle`/`busy`, `needs-user`, worker flag, cwd |
| `tmux-ctl read <win> [lines]` | Last N lines of a window's main pane (default 60) |
| `tmux-ctl read <win> watch [lines]` | Last N lines of a window's watch pane (from `.dev/windows`) |
| `tmux-ctl feed [win] [lines]` | Tail of the feed log (Bash calls mirrored by the hook), for one window or both (default 80 lines) |
| `tmux-ctl run [-t secs] [-C dir] <win> "<cmd>"` | Type the command into an idle shell window, wait (default 600s), print its output and `[exit N]`; exits with the command's code. Busy window: uses lane `<win>·<you>`. Runs in `-C dir` (default: your git top level) |
| `tmux-ctl send [-C dir] <win> "<cmd>"` | Type and press Enter without waiting, e.g. a watcher or dev server. Same lane and `-C` rules as `run` |
| `tmux-ctl keys <win> C-c` | Raw keys, e.g. stop something you started. Not allowed on worker windows |
| `tmux-ctl new <win> [dir]` | Open another shell window |
| `tmux-ctl agent <name> [--force] "<task>"` or `--brief FILE` | Start a worker Claude: new window plus `claude -w <name>` (worktree `.claude/worktrees/<name>`, branch `claude/<name>`) |
| `tmux-ctl tell <agent> "<msg>"` | Send a follow-up message to a worker. Refused while it is waiting on the user |
| `tmux-ctl agents` | Each worker's state (working / WAITING ON USER / exited) and last lines |
| `tmux-ctl artifact <path>` | Show a file in the board's artifacts panel |
| `tmux-ctl idea "<text>"` | File an idea for later |
| `tmux-ctl relay <doc>` | Used only by `/handoff`, and only the lead (the session's `claude` window) can run it: from any other window it refuses and prints the manual start command, which you give to the user |

## How to use it

1. Start with `tmux-ctl list` to see what exists and what's busy.
2. Run test suites and long builds with `tmux-ctl run tests "<cmd>"`: it runs in the hidden session `<project>-bg` (a lane window `tests·<you>` if `tests` is busy), in your own worktree (`-C <dir>` to override), and the user sees every run in the Agent Board's Activity drawer. Use `-t` for long suites (`-t 1800`). Use your Bash tool for everything else. Type only into windows you started, through `tmux-ctl`.
3. Exit 124 means it is still running after the timeout. `read` the window later; don't re-run it.
4. A `busy` error means something else is running there. Read it and wait, or ask the user. Don't
   interrupt what you didn't start.

## Feeds and lanes

- **Feeds:** logs written by the Bash mirror hook, one per window, at `$STATE/feed-<session>-<win>.log`, where `STATE` is `${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}`. Read them with `tmux-ctl feed [win] [lines]`. The Agent Board no longer shows them; there are no feed panes. Each entry starts with a header line `── HH:MM:SS · <agent> · <cwd> · exit N · @<epoch>`, then `$ <command>` and the output tail; the `· @<epoch>` suffix (seconds since 1970) orders entries across days and is absent from older entries.
- **Watch pane (optional):** a `.dev/windows` file in the repo can still start a watcher pane in `<project>-bg:tests`, marked `@tc_role watch`. Read it with `tmux-ctl read <win> watch`. Format: one `window: command` per line, `#` for comments. Example:
  ```
  # .dev/windows
  tests: ptw -- -q
  ```
- **Lanes:** `run` and `send` need an idle target window. If the main pane is busy, they use a lane window `<win>·<caller>` (for example `tests·implementer`; the caller is your window name without `✦ `) created in `<project>-bg`. Lane windows are tagged `@tc_lane` and reaped after 15 minutes idle.
- **`-C <dir>`:** `run` and `send` run the command as `( cd <dir> || exit 2; <cmd> )`. The default is your git top level, so a teammate or worker runs in its own worktree.

## Worker agents vs. agent teams

- **Agent team (default for in-conversation work):** each teammate in its own `✦ <name>` window,
  coordinated by you, shut down when done. Don't drive teammate windows with `tmux-ctl`; message
  teammates through the team.
- **Worker agents (`tmux-ctl agent`):** for long, independent tasks that should keep running in their own
  worktree and window after this conversation ends.
  Worker tasks are repo-scoped (worktree-isolated): user-config work (`~/.claude`, settings, hooks,
  plugins, LaunchAgents, dotfiles) runs in the main session, never in a worker; `agent` warns when a
  task names such paths. A worker starts with none of your context, so the brief needs a goal, a scope
  and a done-criterion: `agent` refuses a brief under ~8 words, so pass longer text or `--brief FILE`
  (contents sent verbatim); `--force` skips both checks.

## Rules

- Never answer a worker's or teammate's permission prompt or question. `tell` refuses while a worker
  waits on the user. Tell the user which window needs them instead.
- Workers commit on their own branches. Don't merge or delete them unless asked. Merged agent worktrees are removed automatically
  (after a merge, on a worker shutdown, and daily at 04:00); stale unmerged ones are flagged on the board and in `Ctrl-a W` for the user to remove.
