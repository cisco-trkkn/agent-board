# Installing agent-board

This guide installs the tmux `dev` toolkit, the Agent Board web UI and the Claude Code rules and hooks **without changing how your existing Claude Code setup behaves**. Your own `claude` sessions, `~/.claude/settings.json`, skills and agents stay as they are. agent-board's settings and hooks apply only to the Claude sessions agent-board starts. Expect about 15 minutes.

There is no installer yet. Installing means cloning the repo, linking a few files and writing two small config files of your own. A few parts can't be fully scoped to agent-board without code changes; they are listed in [Known gaps](#known-gaps-in-the-scoped-install) and planned in [`docs/superpowers/plans/2026-10-19-installability-refactors.md`](superpowers/plans/2026-10-19-installability-refactors.md). That plan has not been applied.

> **Shell:** every snippet is zsh (the macOS default shell). Run them in zsh, not bash.
>
> **Platform:** developed and tested on macOS. For Linux, see [Linux notes](#linux-notes).

## What this install changes on your machine

| Location | Change | Effect on your other Claude Code / tmux use |
| --- | --- | --- |
| `~/.claude/settings.json` | **none** | none |
| `~/.claude/skills/`, `~/.claude/agents/` | **none** | none |
| `~/.zshrc` | one `PATH` line, only if `~/.local/bin` isn't on your `PATH` already | `~/.local/bin` goes first on `PATH` in every new shell. Skip it and add the folder yourself if you'd rather it go last |
| `~/.local/bin/{tmux,ttyd,fzf}` | symlinks to your own installed binaries, only where missing | none: they point to the same binaries |
| `~/.local/bin/` | symlinks: `dev`, `tmux-ctl`, `tmux-dash`, … and a `claude-orchestrator` wrapper | none. These are new command names, and step 3 checks for clashes first |
| `~/.local/share/tmux-dash`, `~/.local/share/tmux-tools` | symlinks into the repo | none |
| `~/.claude/orchestrator.md`, `~/.claude/worker.md`, `~/.claude/hooks/{artifact-register,bash-mirror,kill-guard,superpowers-hook}.sh` | symlinks into the repo (and `~/.claude/hooks/` itself if missing) | none. Claude Code never reads these on its own; only agent-board's launchers and its settings file do |
| `~/.config/agent-board/` | new: `claude-settings.json`, `tmux.conf` | none. Only agent-board sessions load them |
| `~/.tmux.conf` | one `source-file` line | tmux-wide; see [step 5](#5-tmux) for exactly what it changes |
| your running tmux server | the two agent-board hooks, loaded once in step 5 | the same as the `~/.tmux.conf` row |
| `~/.claude/ideas/`, `~/.claude/handoffs/` | created on first use | none |
| `~/.claude/projects/` (your transcripts) | **read only**, by the board's Usage tab | none: nothing is written there |
| `~/.claude/usage-alerts.json` | not created; the board reads it if you add it | none: only the board reads it |

> **Followed an earlier version of this guide, or copied the author's setup?** If `~/.claude/settings.json` already registers `bash-mirror.sh`, `artifact-register.sh` or `kill-guard.sh`, remove those entries first. Otherwise they run twice in agent-board sessions, and they still run in all your other sessions.

## 1. Prerequisites

Versions are the ones tested. Older versions may work, but only Python 3.9 has been checked.

| Tool | Tested | Used by | Notes |
| --- | --- | --- | --- |
| zsh | 5.9 | every `bin/` script | on `PATH` |
| tmux | 3.8 | everything | **called as `~/.local/bin/tmux`** (step 2). The optional key bindings in step 5 need 3.2+ |
| ttyd | 1.7.7 | the board's live terminals | **called as `~/.local/bin/ttyd`** |
| fzf | 0.74 | `tmux-jump`, `tmux-agent-cleanup` | called as `~/.local/bin/fzf` (`FZF_BIN` overrides it for cleanup) |
| python3 | 3.9.6, 3.14 | board server, hooks | standard library only. The macOS Command Line Tools `python3` (3.9) passes the board suite |
| jq | 1.7.1 | `tmux-ctl run` (run records) | on `PATH`; recent macOS ships `/usr/bin/jq` |
| git | 2.4x | worktrees, board | needs `rev-parse --path-format` (git 2.31+) |
| Claude Code | 2.1.303 | lead, teammates, workers | `claude` on `PATH`, logged in; needs `--settings` and agent teams |
| superpowers-extended-cc plugin | 6.5.3 | the skills the rules invoke | optional; without it the lead still runs, but the skill names in its rules point at nothing |

```zsh
brew install tmux ttyd fzf jq
```

## 2. Point `~/.local/bin` at your tools

The scripts call tmux, ttyd and fzf by absolute path under `~/.local/bin`. Link your installed copies there; nothing changes if links already exist:

```zsh
mkdir -p ~/.local/bin
for t in tmux ttyd fzf; do
  [[ -e ~/.local/bin/$t ]] || ln -s "$(command -v $t)" ~/.local/bin/$t
done
```

These link to the same binaries already on your `PATH`, so your own `tmux` keeps working as before.

Put `~/.local/bin` on your `PATH` if it isn't already, and reload:

```zsh
[[ ":$PATH:" == *":$HOME/.local/bin:"* ]] || printf '\n%s\n' 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

agent-board types `claude-orchestrator` and `tmux-ctl` into tmux panes, which resolve them through **the pane shell's `PATH`**. If tmux's `default-shell` is bash or fish, put `~/.local/bin` on `PATH` in that shell's profile too.

## 3. Clone and link

The repo is private. Authenticate first (`gh auth login`, or use the SSH URL `git@github.com:cisco-trkkn/agent-board.git`).

```zsh
git clone https://github.com/cisco-trkkn/agent-board.git ~/agent-board
```

Other paths work, but substitute yours everywhere below. **The checked-out branch is what runs**: every link points into this checkout, so keep `~/agent-board` on `main` and do your own changes in a worktree.

**Check for clashes first.** This prints any target that already exists and is not already a link into the repo. If it prints anything, stop and decide what to do about that file; `ln -sfn` below would silently replace a file, and would put a link *inside* an existing directory:

```zsh
REPO=~/agent-board
targets=(~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.claude/orchestrator.md ~/.claude/worker.md)
for f in "$REPO"/bin/*; do targets+=(~/.local/bin/${f:t}); done
for f in "$REPO"/claude/hooks/*; do targets+=(~/.claude/hooks/${f:t}); done
for t in $targets; do
  [[ -e $t || -L $t ]] && [[ "$(readlink $t)" != "$REPO"/* ]] && print "EXISTS: $t"
done
```

On a re-run, `EXISTS: ~/.local/bin/claude-orchestrator` is expected once that path holds the step 4 wrapper.

`dev` is the name most likely to clash. The board calls `~/.local/bin/dev` by that exact path, so it has to be this one.

Then link:

```zsh
REPO=~/agent-board
mkdir -p ~/.local/bin ~/.local/share ~/.claude/hooks

# commands (claude-orchestrator gets a wrapper in step 4 instead)
for f in "$REPO"/bin/*; do
  [[ ${f:t} == claude-orchestrator ]] && continue
  ln -sfn "$f" ~/.local/bin/${f:t}
done

# board app and test tools
ln -sfn "$REPO/board" ~/.local/share/tmux-dash
ln -sfn "$REPO/tools" ~/.local/share/tmux-tools

# rules and hook scripts: inert files, read only by agent-board's launchers and settings
ln -sfn "$REPO/claude/orchestrator.md" ~/.claude/orchestrator.md
ln -sfn "$REPO/claude/worker.md"       ~/.claude/worker.md
for f in "$REPO"/claude/hooks/*; do ln -sfn "$f" ~/.claude/hooks/${f:t}; done
```

## 4. Claude Code settings for agent-board sessions only

agent-board's lead needs agent teams, `teammateMode`, and three hooks. Instead of adding them to `~/.claude/settings.json`, put them in a separate file and pass it with `claude --settings`, so they load **only** for the sessions agent-board starts.

```zsh
mkdir -p ~/.config/agent-board
cat > ~/.config/agent-board/claude-settings.json <<'EOF'
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1",
    "AGENT_BOARD": "1"
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
EOF
```

`--settings` is additive: your own `~/.claude/settings.json`, project settings, plugins and hooks still load in agent-board sessions too. Claude Code starts teammates with the lead's settings `env` on their command line (seen for `~/.claude/settings.json`; expected, not yet verified, for `--settings`). `AGENT_BOARD=1` is a marker the scripts don't read yet; the plan uses it to gate the hooks.

Now make every agent-board lead start with that file. `dev`, the board's Restart orchestrator and the `/handoff` relay all start the lead by typing `claude-orchestrator`, so a wrapper with that name covers all three:

```zsh
REPO=~/agent-board
# remove any old link first: writing through a link into the repo would overwrite the repo's own launcher
[[ -L ~/.local/bin/claude-orchestrator ]] && rm ~/.local/bin/claude-orchestrator
cat > ~/.local/bin/claude-orchestrator <<EOF
#!/usr/bin/env zsh
# agent-board lead: repo launcher + agent-board-only settings
exec ${REPO}/bin/claude-orchestrator --settings \$HOME/.config/agent-board/claude-settings.json "\$@"
EOF
chmod +x ~/.local/bin/claude-orchestrator
cat ~/.local/bin/claude-orchestrator      # check: the exec line names your repo path
```

What each hook does for the lead:

| Hook | Without it |
| --- | --- |
| `kill-guard.sh` | an agent's `pkill -f <pattern>` can kill the lead and its whole team |
| `bash-mirror.sh` | `tmux-ctl feed` (the log of agents' Bash calls) stays empty. The board no longer shows this feed |
| `artifact-register.sh` | plans, specs and handoffs don't appear in the artifacts panel automatically (`tmux-ctl artifact <path>` still works) |

### Skills and agent types the rules mention

`claude/orchestrator.md` and `claude/worker.md` name skills and agent types. Install **none** of them globally for agent-board's sake:

| Referenced as | Status in the scoped install |
| --- | --- |
| `superpowers-extended-cc:*` skills | used if you already have the plugin; otherwise the lead works without them |
| `tmux-orchestrator` skill | not needed: `tmux-ctl help` and the rules carry the same commands |
| `handoff` skill (`/handoff`) | not available yet (plan Task 3 ships it as a session-only plugin) |
| `effort-low` / `-medium` / `-high` agent types | not available yet (same plan task). If your superpowers routing enforces effort, the lead may need to dispatch `general-purpose` instead |
| `task-observer`, `gitlab-ci-loop` | the author's personal skills; ignored when absent |

## 5. tmux

agent-board needs two tmux hooks. A tmux hook is server-wide, so this is the one change that reaches outside agent-board.

First check whether you already use these hooks:

```zsh
tmux show-hooks -g 2>/dev/null | grep -E '^(after-split-window|session-closed)'
```

If that prints nothing, use the file below as is. If it prints a hook of yours, change that line's `set-hook -g` to `set-hook -ga`, so agent-board's hook is added next to yours instead of replacing it.

```zsh
cat > ~/.config/agent-board/tmux.conf <<'EOF'
# agent-board: each agent-team teammate gets its own window "✦ name" instead of a split pane
set-hook -g after-split-window 'run-shell -b "~/.local/bin/tmux-teammate-window"'
# agent-board: delete a project's agent-board state files when its session closes
set-hook -g session-closed 'run-shell -b "~/.local/bin/tmux-session-closed #{q:hook_session_name}"'
EOF
grep -qF 'agent-board/tmux.conf' ~/.tmux.conf 2>/dev/null || printf '\n%s\n' 'source-file ~/.config/agent-board/tmux.conf' >> ~/.tmux.conf
# load just these two hooks into the running server (re-sourcing all of ~/.tmux.conf could repeat your own bindings and plugins)
tmux source-file ~/.config/agent-board/tmux.conf 2>/dev/null || true
```

Effect on your other tmux use:

- **`after-split-window`** checks new split panes, and acts only on a pane whose command is a Claude agent-team teammate (`--agent-name …`, or older Claude's `cat` placeholder). If you also use agent teams in tmux outside agent-board, those teammates get their own windows too. Ordinary splits are untouched.
- **`session-closed`** deletes only files named after the closed session in agent-board's state directory (`$TMPDIR/tmux-ctl-$UID/`).

Optional, tmux-wide, only if you want them:

```tmux
# A waiting Claude rings the bell → red window tab (the board's "Needs you" works without this)
set -g monitor-bell on
set -g bell-action other
# Key bindings: pick keys that are free in your config
bind D run-shell -b "DEV_CLIENT='#{client_name}' ~/.local/bin/dev '#{pane_current_path}'"
bind f run-shell -b "~/.local/bin/tmux display-popup -c '#{client_name}' -E -w 70% -h 50% -T ' jump to window ' \"~/.local/bin/tmux-jump '#{client_name}'\""
bind W display-popup -E -w 90% -h 60% -d "#{pane_current_path}" -T " clean up agent worktrees " "~/.local/bin/tmux-agent-cleanup"
```

If you use tmux-resurrect with continuum, scratch tmux servers you start yourself should use `-f /dev/null` so they don't restore your sessions. The test harness already does this.

## 6. Verify

**agent-board works:**

```zsh
cd ~/agent-board
python3 -m unittest discover -s board/tests      # expect: Ran 211 tests … OK
zsh tools/tests/run-all.zsh                      # expect: ALL PASS after each of 17 ### test_*.zsh
```

Both suites are safe next to live sessions. The zsh tests start their own tmux server on a private socket with `-f /dev/null` and a temporary state directory.

```zsh
dev ~/some/git/repo        # session "repo": windows claude (the lead) and shell
tmux-dash                  # starts the board, opens http://127.0.0.1:7700/<token>/
```

On first start in a folder, Claude may ask you to trust it; accept it in the `claude` window. Teammates spawned in an untrusted folder die silently at that prompt.

**Your own setup is untouched:**

```zsh
grep -sc 'agent-board\|bash-mirror\|kill-guard\|artifact-register' ~/.claude/settings.json   # expect 0 (or no output: no file)
```

In a plain `claude` session started outside agent-board, `/hooks` lists none of the three agent-board hooks. In the agent-board lead, `/hooks` lists them.

## Known gaps in the scoped install

These need code changes (planned in the [installability plan](superpowers/plans/2026-10-19-installability-refactors.md), not applied):

| Gap | Effect today | Plan task |
| --- | --- | --- |
| Workers (`tmux-ctl agent`) start as `claude -w …` without `--settings` | worker Bash calls are not mirrored to `tmux-ctl feed`, worker files are not auto-registered as artifacts, and kill-guard does not protect workers. `tmux-ctl run` records still appear | 2 |
| Teammates: Claude Code passes the lead's `env` to teammates, but whether it passes `--settings` hooks is unverified | if not, `tmux-ctl feed` shows no teammate commands, teammate plans aren't auto-registered, and kill-guard doesn't protect teammates | 1 |
| The wrapper is found through the pane shell's `PATH`; `DEV_CLAUDE_CMD` bypasses it | a pane whose shell lacks `~/.local/bin` runs no lead, and a custom `DEV_CLAUDE_CMD` must pass `--settings` itself ([CUSTOMIZATION §3](CUSTOMIZATION.md#3-lead-and-worker-behaviour)) | 2 |
| `/handoff`, `tmux-orchestrator`, `effort-*` live outside the repo | not available in the scoped install | 3 |
| tmux hooks are server-wide | see step 5 | 4 |
| Commands are linked into `~/.local/bin` by fixed names | `dev` may clash with an existing command | 5 |

## Upgrading

```zsh
cd ~/agent-board && git pull
tmux-dash stop && tmux-dash start     # only needed when board/ changed
```

Scripts and rules take effect on their next run. A new script in `bin/` needs its link (re-run the link loop in step 3).

## Uninstalling

```zsh
tmux-dash stop
for f in ~/agent-board/bin/*; do [[ "$(readlink ~/.local/bin/${f:t})" == ~/agent-board/* ]] && rm ~/.local/bin/${f:t}; done
rm -f ~/.local/bin/claude-orchestrator      # the wrapper from step 4
for t in ~/.local/share/tmux-dash ~/.local/share/tmux-tools ~/.claude/orchestrator.md ~/.claude/worker.md; do
  [[ "$(readlink $t)" == ~/agent-board/* ]] && rm $t
done
for f in ~/agent-board/claude/hooks/*; do [[ "$(readlink ~/.claude/hooks/${f:t})" == ~/agent-board/* ]] && rm ~/.claude/hooks/${f:t}; done
sed -i '' '/agent-board\/tmux.conf/d' ~/.tmux.conf
mv ~/.config/agent-board ~/.config/agent-board.bak-$(date +%Y%m%d)   # keeps your settings edits; delete when sure
```

The running tmux server keeps the two hooks until it restarts. To drop them now: `tmux set-hook -gu after-split-window; tmux set-hook -gu session-closed`. That also clears any hook of your own on those events, so re-source your config afterwards.

The `~/.local/bin/{tmux,ttyd,fzf}` links from step 2 are harmless to keep. State lives in `~/.local/state/tmux-dash/` (board token, pids, logs) and `${TMPDIR}/tmux-ctl-$UID/` (runtime state). Your ideas are in `~/.claude/ideas/`; keep that folder if you want them.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `tmux-dash: failed to start — see ~/.local/state/tmux-dash/*.log` | `ttyd` missing at `~/.local/bin/ttyd`, or port 7700/7701 taken. Read `ttyd.log` / `server.log`; change ports with `TMUX_DASH_PORT` / `TMUX_DASH_TTYD_PORT`. |
| Board loads but terminals are blank | ttyd not running (`tmux-dash status`), or the board and ttyd look at different tmux servers. `TMUX_DASH_TMUX_ARGS` must be the same for both; `tmux-dash` passes it to both. |
| `tmux-ctl: not inside tmux` | `tmux-ctl` only works from a pane inside tmux. |
| `tmux-ctl run` fails with `jq: command not found` | install jq. |
| Teammates open as split panes, not `✦ name` windows | the `after-split-window` hook is not loaded: check `tmux show-hooks -g`, then re-source `~/.tmux.conf`. |
| A teammate window dies right after it spawns | the folder isn't trusted yet. Run `claude` there once and accept the trust prompt. |
| The lead has no agent team, or `/hooks` shows no agent-board hooks | the lead was started by the repo's `claude-orchestrator` instead of the wrapper. `command -v claude-orchestrator` must print `~/.local/bin/claude-orchestrator`, and that file must be the wrapper from step 4, not a link. |
| `tmux-ctl feed` is empty | the lead lacks the settings file (row above), or the commands came from a worker (known gap). |
| Usage tab says it is indexing, or shows $0 | the first pass over `~/.claude/projects` takes a while on a large history; costs appear as it proceeds. A model missing from `board/prices.json` shows as *unpriced*. |
| `claude-orchestrator: ~/.claude/orchestrator.md missing, starting plain claude` | the link from step 3 is missing. |

## Linux notes

Untested. Known differences:

- `tmux-dash` with no argument calls macOS `open`. Run `tmux-dash start` and open the printed URL.
- The uninstall `sed -i ''` is BSD syntax; on GNU sed use `sed -i`.
- `${TMPDIR}` is usually unset on Linux, so runtime state goes to `/tmp/tmux-ctl-$UID/`.

## Appendix: the author's original global setup

The author's machine registers the hooks, `env` and `teammateMode` in `~/.claude/settings.json`, and keeps the skills in `~/.claude/skills/`. All of these then apply to **every** Claude Code session. Don't copy that setup onto a machine where you use Claude Code for other work. The scoped install above replaces it, and the plan's install script will migrate a global install to the scoped one (Task 6).
