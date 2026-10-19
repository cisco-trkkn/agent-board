# Installing agent-board

This guide sets up the tmux `dev` toolkit, the Agent Board web UI and the Claude Code rules and hooks on a new machine. It takes about 15 minutes.

There is no installer yet. Installing means cloning the repo, symlinking its files into the live paths and adding a few lines to `~/.tmux.conf` and `~/.claude/settings.json`. The refactors that would turn this into one command are planned in [`docs/superpowers/plans/2026-10-19-installability-refactors.md`](superpowers/plans/2026-10-19-installability-refactors.md). They have not been applied yet.

> **Platform:** developed and tested on macOS (zsh, BSD userland). Linux should mostly work. The known macOS-only pieces are `open` in `tmux-dash` and `pbcopy` in the tmux.conf snippet; see [Linux notes](#linux-notes).

## 1. Prerequisites

| Tool | Tested version | Used by | Notes |
| --- | --- | --- | --- |
| zsh | 5.9 | every `bin/` script | must be at `/usr/bin/env zsh` |
| tmux | 3.8 | everything | **must be reachable at `~/.local/bin/tmux`** (see below) |
| ttyd | 1.7.7 | the board's live terminals | **must be at `~/.local/bin/ttyd`** |
| fzf | 0.74 | `tmux-jump`, `tmux-agent-cleanup` | expected at `~/.local/bin/fzf` (`FZF_BIN` overrides it for cleanup) |
| python3 | 3.11+ (tested 3.14) | board server, hooks | standard library only, no pip packages |
| jq | 1.7 | `tmux-ctl run` (run records) | anywhere on `PATH` |
| git | 2.40+ | worktrees, board | worktrees need `git worktree` with `--porcelain` |
| Claude Code | 2.1.300+ | lead, teammates, workers | `claude` on `PATH`; agent teams enabled (step 5) |
| superpowers-extended-cc plugin | 6.5+ | the skills the rules invoke | optional, but the lead/worker rules assume it |

The scripts call tmux, ttyd and fzf by **absolute path** under `~/.local/bin`, not through `PATH`. If you installed them with Homebrew, add symlinks:

```zsh
mkdir -p ~/.local/bin
ln -s "$(command -v tmux)" ~/.local/bin/tmux
ln -s "$(command -v ttyd)" ~/.local/bin/ttyd
ln -s "$(command -v fzf)"  ~/.local/bin/fzf
```

Homebrew install, if you need the tools: `brew install tmux ttyd fzf jq`.

Make sure `~/.local/bin` is on your `PATH` (`dev`, `tmux-ctl`, `claude-orchestrator` are called by name):

```zsh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
```

## 2. Clone

Clone to `~/agent-board`. Other paths work, but then substitute your path everywhere below.

```zsh
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
```

**The checked-out branch is what runs.** Every live path below is a symlink into this checkout, so switching branches in `~/agent-board` changes the tools in every tmux session immediately. Do feature work in worktrees (`.claude/worktrees/…`) and keep `~/agent-board` on `main`.

## 3. Symlink into the live paths

Before linking, look at what is already there. If a real file exists at a target, back it up first (`mv F F.bak-$(date +%Y%m%d)`). `ln -sfn` replaces a symlink but not a directory.

```zsh
REPO=~/agent-board
mkdir -p ~/.local/bin ~/.local/share ~/.claude/hooks

# commands
for f in "$REPO"/bin/*; do ln -sfn "$f" ~/.local/bin/"${f:t}"; done

# board app and test tools
ln -sfn "$REPO/board" ~/.local/share/tmux-dash
ln -sfn "$REPO/tools" ~/.local/share/tmux-tools

# Claude rules and hooks
ln -sfn "$REPO/claude/orchestrator.md" ~/.claude/orchestrator.md
ln -sfn "$REPO/claude/worker.md"       ~/.claude/worker.md
for f in "$REPO"/claude/hooks/*; do ln -sfn "$f" ~/.claude/hooks/"${f:t}"; done
```

| Repo path | Live path | What reads it |
| --- | --- | --- |
| `bin/<script>` | `~/.local/bin/<script>` | you, tmux key bindings, other scripts |
| `board/` | `~/.local/share/tmux-dash` | `tmux-dash` (runs `server.py`), `tmux-ctl idea`/`relay` |
| `tools/` | `~/.local/share/tmux-tools` | test runner only |
| `claude/orchestrator.md` | `~/.claude/orchestrator.md` | `claude-orchestrator` (`--append-system-prompt-file`) |
| `claude/worker.md` | `~/.claude/worker.md` | `tmux-ctl agent` (`--append-system-prompt-file`) |
| `claude/hooks/*.sh` | `~/.claude/hooks/*.sh` | Claude Code hooks (step 5), `tmux-ctl artifact` |

## 4. tmux configuration

Add this block to `~/.tmux.conf`. The two `set-hook` lines are required; the key bindings are recommended. The full author config (Catppuccin theme, menu, resurrect) is not in the repo; only the parts the toolkit depends on are listed here.

```tmux
# --- agent-board: required ---
# Each agent-team teammate gets its own window "✦ name" instead of a split pane
set-hook -g after-split-window 'run-shell -b "~/.local/bin/tmux-teammate-window"'
# Per-project state (artifacts, runs, feeds, lineage) is deleted when the project's session ends
set-hook -g session-closed 'run-shell -b "~/.local/bin/tmux-session-closed #{q:hook_session_name}"'
# A waiting Claude rings the bell: the window tab turns red and the board shows "Needs you"
set -g monitor-bell on
set -g bell-action other

# Claude Code: Shift+Enter newlines, notifications passthrough
set -g allow-passthrough on
set -s extended-keys on
set -as terminal-features 'xterm*:extkeys'

# --- agent-board: recommended key bindings (prefix shown as Ctrl-a) ---
# Ctrl-a D : open (or switch to) the dev session for this folder
bind D run-shell -b "DEV_CLIENT='#{client_name}' ~/.local/bin/dev '#{pane_current_path}'"
# Ctrl-a f : fuzzy-jump to any window in any session
bind f run-shell -b "~/.local/bin/tmux display-popup -c '#{client_name}' -E -w 70% -h 50% -T ' jump to window ' \"~/.local/bin/tmux-jump '#{client_name}'\""
# Ctrl-a W : pick finished agent worktrees to remove (never forces)
bind W display-popup -E -w 90% -h 60% -d "#{pane_current_path}" -T " clean up agent worktrees " "~/.local/bin/tmux-agent-cleanup"
# Ctrl-a A : a named Claude in its own worktree;  Ctrl-a C : plain Claude here
bind A command-prompt -p "New Claude agent name:" { new-window -n "%1" -c "#{pane_current_path}" ; send-keys "claude -w '%1' -n '%1'" Enter }
bind C { new-window -n claude -c "#{pane_current_path}" ; send-keys "claude" Enter }
```

Reload with `tmux source-file ~/.tmux.conf`.

**If you use tmux-resurrect + continuum:** a restore re-runs `claude --continue` in windows that ran Claude. Scratch tmux servers (tests, experiments) must start with `-f /dev/null` so they don't restore your sessions; the test harness already does this.

## 5. Claude Code configuration

Merge these keys into `~/.claude/settings.json`. Keep any hooks you already have; Claude Code runs every matching hook.

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "teammateMode": "auto",
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/kill-guard.sh", "timeout": 10 }] }
    ],
    "PostToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/bash-mirror.sh", "timeout": 5, "async": true }] },
      { "matcher": "Write|Edit|MultiEdit|Artifact",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/artifact-register.sh", "timeout": 5, "async": true }] }
    ],
    "PostToolUseFailure": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "~/.claude/hooks/bash-mirror.sh", "timeout": 5, "async": true }] }
    ]
  }
}
```

| Hook | What breaks without it |
| --- | --- |
| `kill-guard.sh` | nothing visible, but an agent's `pkill -f <pattern>` can kill the lead and its whole team |
| `bash-mirror.sh` | the board's Activity drawer shows no command feed |
| `artifact-register.sh` | the board's artifacts panel stays empty (plans, specs, handoffs, reports) |

Optional, only with the superpowers-extended-cc plugin's user-gate feature:

```json
"Stop": [{ "hooks": [
  { "type": "command", "command": "bash ~/agent-board/claude/hooks/superpowers-hook.sh stop-revalidate-user-gates.sh" },
  { "type": "command", "command": "bash ~/agent-board/claude/hooks/superpowers-hook.sh stop-wait-guard.sh" } ] }],
"PostToolUse": [{ "matcher": "TaskUpdate", "hooks": [
  { "type": "command", "command": "bash ~/agent-board/claude/hooks/superpowers-hook.sh post-task-complete-revalidate.sh" } ] }]
```

### Skills and agent definitions the rules refer to

`claude/orchestrator.md` and `claude/worker.md` name skills and agent types that are **not in this repo yet** (see the refactor plan, Task 3). Without them the lead still works but some instructions point at nothing:

| Referenced as | Purpose | Where it lives today |
| --- | --- | --- |
| `superpowers-extended-cc:*` skills | brainstorming, plans, TDD, review, verification | the superpowers-extended-cc plugin (install from its marketplace) |
| `tmux-orchestrator` skill | full `tmux-ctl` reference for agents | author's `~/.claude/skills/tmux-orchestrator/` |
| `handoff` skill (`/handoff`) | checkpoint the team, write a handoff doc, `tmux-ctl relay` | author's `~/.claude/skills/handoff/` |
| `effort-low` / `effort-medium` / `effort-high` agents | effort-pinned subagent types for model routing | author's `~/.claude/agents/`; the plugin's `/onboard` can generate them |
| `task-observer`, `gitlab-ci-loop` | author's personal workflow skills | not needed; delete those rows from `orchestrator.md` in your copy |

## 6. Verify the install

```zsh
cd ~/agent-board
python3 -m unittest discover -s board/tests      # expect: Ran 134 tests … OK
zsh tools/tests/run-all.zsh                      # expect: ALL PASS after every ### test_*.zsh
```

Both suites are safe to run on a machine with live sessions: the zsh tests start their own tmux server on a private socket with `-f /dev/null` and a temporary `TC_STATE`.

Then try the real thing:

```zsh
dev ~/some/git/repo        # opens session "repo": windows claude (the lead) and shell
tmux-dash                  # starts the board and opens http://127.0.0.1:7700/<token>/
```

In the `claude` window the lead starts with the orchestrator rules. In the board you should see the project card, its windows and the live terminal.

## Upgrading

```zsh
cd ~/agent-board && git pull
tmux-dash stop && tmux-dash start     # only needed when board/ changed
```

Scripts and rules take effect on their next run; nothing else needs restarting. A new script in `bin/` needs its symlink (re-run the `bin` loop in step 3).

## Uninstalling

```zsh
tmux-dash stop
for f in ~/agent-board/bin/*; do [[ -L ~/.local/bin/${f:t} ]] && rm ~/.local/bin/${f:t}; done
rm ~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.claude/orchestrator.md ~/.claude/worker.md
for f in ~/agent-board/claude/hooks/*; do [[ -L ~/.claude/hooks/${f:t} ]] && rm ~/.claude/hooks/${f:t}; done
```

Then remove the block from `~/.tmux.conf` and the hook entries from `~/.claude/settings.json`. State lives in `~/.local/state/tmux-dash/` (board token, pids, logs), `${TMPDIR}/tmux-ctl-$UID/` (per-project runtime state) and `~/.claude/ideas/` (your ideas; keep it if you want them).

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `tmux-dash: failed to start — see ~/.local/state/tmux-dash/*.log` | `ttyd` missing at `~/.local/bin/ttyd`, or port 7700/7701 taken. Check `ttyd.log` / `server.log`; change ports with `TMUX_DASH_PORT` / `TMUX_DASH_TTYD_PORT`. |
| Board loads but terminals are blank | ttyd not running (`tmux-dash status`), or the board and ttyd use different tmux servers. Set `TMUX_DASH_TMUX_ARGS` the same for both (it is passed through by `tmux-dash`). |
| `tmux-ctl: not inside tmux` | `tmux-ctl` only works from a pane inside a tmux session. |
| `tmux-ctl run` fails with `jq: command not found` | install jq. |
| Teammates open as split panes, not `✦ name` windows | the `after-split-window` hook is missing from `~/.tmux.conf`, or tmux was not reloaded. |
| A teammate window is dead right after spawning | the folder is not trusted by Claude Code yet. Open `claude` there once and accept the trust prompt. |
| Activity drawer has runs but no command feed | `bash-mirror.sh` hook not registered (step 5). |
| Artifacts panel is empty | `artifact-register.sh` hook not registered, or the file is not under `docs/superpowers/{plans,specs}/`, `~/.claude/handoffs/` or a scratchpad report. Register by hand: `tmux-ctl artifact <path>`. |
| `claude-orchestrator: ~/.claude/orchestrator.md missing, starting plain claude` | the symlink from step 3 is missing. |

## Linux notes

Not tested, but these are the known differences:

- `tmux-dash` (no argument) calls macOS `open` to launch the browser. Use `tmux-dash start` and open the printed URL, or alias `open` to `xdg-open`.
- The tmux copy binding in the author config uses `pbcopy`; use `wl-copy` or `xclip`.
- `tmux-teammate-window` reads a pane's processes with `ps -t <tty>`; procps accepts the same form.
- `${TMPDIR:-/tmp}` is usually unset on Linux, so runtime state goes to `/tmp/tmux-ctl-$UID/`.
