# Retire-plan-window: real-state check of the re-layout

Checked 2026-10-29 01:46 EDT against the live tmux server (the user's default socket, `$TMUX=/private/tmp/tmux-503/default,…`), read-only, using the head `c4a98ce` version of `bin/tmux-dev-layout`.

## Live windows

Command, run on the live server:

    tmux list-panes -a -F '#{session_name}:#{window_name} | #{pane_start_command}'

Output (29 lines; the long `claude` agent start commands are shortened to `…`, only their leading `cd` and `--agent-name` kept):

```
_web-47416:claude | 
_web-47416:✦ rev | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/retire-plan-window && env CLAUDECODE=1 … --agent-name rev …"
_web-47416:✦ realstate | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/retire-plan-window && env CLAUDECODE=1 … --agent-name realstate …"
_web-47416:plan | "/Users/francisco.ruiz/agent-board/bin/tmux-plan agent-board /Users/francisco.ruiz/agent-board"
agent-board:claude | 
agent-board:✦ rev | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/retire-plan-window && env CLAUDECODE=1 … --agent-name rev …"
agent-board:✦ realstate | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/retire-plan-window && env CLAUDECODE=1 … --agent-name realstate …"
agent-board:plan | "/Users/francisco.ruiz/agent-board/bin/tmux-plan agent-board /Users/francisco.ruiz/agent-board"
agent-board-bg:tests | 
agent-board-bg:shell | 
francisco_ruiz:claude | 
francisco_ruiz:✦ ctx-rev | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/shared-project-context && env CLAUDECODE=1 … --agent-name ctx-rev …"
francisco_ruiz:✦ ctx-impl | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/shared-project-context && env CLAUDECODE=1 … --agent-name ctx-impl …"
francisco_ruiz:✦ ctx-final | "cd /Users/francisco.ruiz/agent-board/.claude/worktrees/shared-project-context && env CLAUDECODE=1 … --agent-name ctx-final …"
francisco_ruiz:plan | "/Users/francisco.ruiz/agent-board/bin/tmux-plan francisco_ruiz /Users/francisco.ruiz"
francisco_ruiz-bg:tests | 
francisco_ruiz-bg:shell | 
interiors:claude | 
interiors:✦ fixer | "cd /Users/francisco.ruiz/interiors && env CLAUDECODE=1 … --agent-name fixer …"
interiors-bg:tests | 
interiors-bg:shell | 
master-gcp-repo:claude | 
master-gcp-repo:ReFaCtOr | 
master-gcp-repo-bg:tests | 
master-gcp-repo-bg:tests | "zsh -lc … (watch loop)"
master-gcp-repo-bg:shell | 
master-gcp-repo-bg:shell | "zsh -lc … (watch loop)"
x-dev-notgit-bg:tests | 
x-dev-notgit-bg:shell | 
```

Window group facts (from `tmux list-windows -a -F '#{session_name}:#{window_name} grp=#{session_group} panes=#{window_panes}'`):

    _web-47416:plan grp=agent-board panes=1
    agent-board:plan grp=agent-board panes=1
    francisco_ruiz:plan grp=francisco_ruiz panes=1

`_web-47416` is a group view of the real session `agent-board`; both list the same `plan` window.

## Counts

Each from `grep -c` over the saved, unshortened output above (every `plan` window has one pane, so pane lines equal window lines):

| # | What | Command | Result |
|---|------|---------|--------|
| 1 | windows named `plan` | `grep -c '^[^|]*:plan | ' live.txt` | 3 |
| 2 | of those, start command contains `tmux-plan` | `grep '^[^|]*:plan | ' live.txt \| grep -c 'tmux-plan'` | 3 |
| 3 | NOT named `plan`, start command contains `tmux-plan` | `grep -v '^[^|]*:plan | ' live.txt \| grep -c 'tmux-plan'` | 0 |

Count 3 is 0, so the new close condition (window named `plan` and start command contains `tmux-plan`) matches every real `plan` window and nothing else. The 3 lines are 2 distinct windows: `agent-board:plan` and `_web-47416:plan` are one window seen through two grouped sessions; `francisco_ruiz:plan` is the other.

Per-session duplicates (the layout targets `=sess:plan`, ambiguous if a session has two or more). Re-checked later on the live server, read-only:

    tmux list-windows -a -F '#{session_name} #{window_name}' | awk '$2=="plan"' | sort | uniq -c
          1 agent-board plan
          1 francisco_ruiz plan

Sessions with two or more `plan` windows: 0. (The group view `_web-47416` had closed by this second check, so it no longer lists; it showed 1 in the first check.)

A `dev` re-run would clean the real sessions `agent-board` and `francisco_ruiz` (it is run on the real session; `dev` derives the group key from `#{session_group}`). It would not be run on `_web-47416`: a group view shares the window, so closing it in the real session removes it from the view too (next section). `interiors` and `master-gcp-repo` have no `plan` window and would be untouched.

Correction (final review, 2026-10-29): the install runs in dedicated mode, so `dev` lays out sessions on the `-L agent-board` server, not the default server checked above. A read-only check of `-L agent-board` found the same two `plan` windows with the same `tmux-plan` start command, and no other window among its 8 panes with `tmux-plan` in its start command, so the close condition holds there too. The two `plan` windows on the default server are not reached by `dev`; close them by hand with `tmux kill-window -t '=agent-board:plan'` and `tmux kill-window -t '=francisco_ruiz:plan'`.

## Group-view probe

Scratch server, never the live one: `~/.local/bin/tmux -L rps-probe-61512 -f /dev/null …`. The layout reads its server from `TMUX_DASH_TMUX_ARGS` (first match in `bin/_tc_bins.zsh`), so it was run as `env -u TMUX TMUX_DASH_TMUX_ARGS="-L rps-probe-61512" zsh bin/tmux-dev-layout dev1 <scratch dir>`: it could only reach the scratch server.

Setup: real session `dev1` with windows `claude` and `plan` (started with `sh -c 'sleep 600; : tmux-plan'`), and `new-session -d -s dev1_web -t dev1` for the grouped view.

Before the layout (`list-windows -a`, start command shown, which contains `tmux-plan`):

    dev1:claude grp=dev1 start=
    dev1:plan grp=dev1 start="sh -c 'sleep 600; : tmux-plan'"
    dev1_web:claude grp=dev1 start=
    dev1_web:plan grp=dev1 start="sh -c 'sleep 600; : tmux-plan'"

Layout run on the real session `dev1`: exit code 0. After (`list-windows -a`):

    dev1:claude grp=dev1
    dev1-bg:tests grp=
    dev1-bg:shell grp=
    dev1_web:claude grp=dev1

The `plan` window is gone from both `dev1` and the group view `dev1_web`. (`dev1-bg` is the hidden agent session the layout creates.)

Cleanup: `kill-server` on the scratch socket; afterwards `list-sessions` printed `no server running on /private/tmp/tmux-503/rps-probe-61512`, the stale socket file was removed (`ls /private/tmp/tmux-503/ | grep -c rps` → 0), and no `sleep 600` process remained (`ps` count 0). The live server still lists 3 `plan` pane lines, unchanged.

## Commands run

Against the live server, only these read-only commands:

- `tmux list-panes -a -F '#{session_name}:#{window_name} | #{pane_start_command}'`
- `tmux list-windows -a -F '#{session_name}:#{window_name} grp=#{session_group} panes=#{window_panes}'` (also once with `'#{session_name} grp=#{session_group}'`)
- `tmux list-windows -a -F '#{session_name} #{window_name}'` piped to `awk`/`sort`/`uniq -c` (per-session plan count)
- `tmux list-windows -a -F '#{session_name}:#{window_name}'` (final check that 3 `plan` lines remain)

No `bin/tmux-dev-layout`, `dev`, or any write command (`new-*`, `kill-*`, `move-*`, `set-*`, `send-keys`) was run against the live server. Everything that writes ran on the scratch server `-L rps-probe-61512`.
