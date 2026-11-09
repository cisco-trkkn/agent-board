# Relay gone-cwd: root cause (2026-11-09)

Task 1 of `docs/superpowers/plans/2026-11-09-relay-launch-check.md`. Why the shell that `tmux-ctl relay` respawned in the
lead's `claude` window sat in a deleted directory at 14:24 and 15:05 on 2026-11-09.

**Short answer.** The tmux server process itself had a deleted working directory. tmux 3.8 then starts every new or
respawned pane in that deleted directory and ignores `-c <dir>`. relay.py asked for the right directory; tmux did not
deliver it. The lead's own worktree and Claude Code's stale `activeWorktreeSession` play no part.

## Evidence

Read-only observations of the live machine (the spec's Evidence section is not repeated here).

- The live tmux server (pid 12354, started 12:12:00, `tmux -L agent-board … new-session -A -s main`) has this working
  directory: `lsof -a -p 12354 -d cwd` → `/Users/francisco.ruiz/interiors/.claude/worktrees/home-study`. That directory
  no longer exists (`ls` → "No such file or directory").
- It was removed between 14:11:45 (interiors reflog: `merge home-study: Fast-forward`) and 14:22:30 (mtime of
  `~/interiors/.claude/worktrees`). The first failed relay is 14:24:39. Relays before that removal worked: the interiors
  relay at 13:46:39 has no `cd ~` after its launch line in `~/.zsh_history`.
- The failure is not specific to agent-board. The interiors relay at 15:19:08 failed the same way: pane `%1`, shell pid
  32303 started 15:19:08, its `claude` child only at 15:28:01, and it runs in `~`.
- relay.py asked for the right directory both times. `#{session_path}` is `/Users/francisco.ruiz/agent-board` for
  `agent-board` and `/Users/francisco.ruiz/interiors` for `interiors`, and `#{pane_start_path}` of `%8` and `%1` shows
  those same paths (a probe shows `respawn-pane -c` updates `pane_start_path`).
- Neither old lead was in a gone directory when it relayed. Transcript `cwd` at the relay call: 5592c6a1 was in
  `.claude/worktrees/queue-keep-awake` (it existed until about 15:00), 4474f02d was in `/Users/francisco.ruiz/agent-board`.
- A fingerprint ties the live leads to this cause. Both hand-restarted leads (pids 2532 and 60460) have `OLDPWD` and
  `PWD` both equal to `/Users/francisco.ruiz` in their environment. A shell that had started in the project and then ran
  `cd ~` would export `OLDPWD=<project>` (probed). A shell that started in a deleted directory exports `OLDPWD=.`, and
  the `claude-orchestrator` zsh resets a non-absolute `OLDPWD` to `$PWD` (probed: `env OLDPWD=. zsh -fc 'env'` in `~`
  prints `OLDPWD=/Users/francisco.ruiz`). The reproduction below ends with the same two values.
- The same thing hit a worker window. `~/.zsh_history` has `. …/agents/agent-board-begin-brainstorming-handoff.zsh`,
  then `cd ~`, then the same line again: a `tmux-ctl agent` window (`new-window -c <root>`) whose first start failed.
- Claude Code 2.1.321 prints the message only from its first startup check: `process.cwd()` throws `ENOENT` → "The
  current directory no longer exists (it was deleted or moved). Start Claude Code from an existing directory." →
  `exit(1)`. Nothing else in the binary prints that sentence, so the process really had a deleted cwd.
- How the server came to sit in a worktree: a tmux server keeps the working directory of the command that started it
  (probed: a scratch server started from directory X reports X in `lsof`, and later `new-window -c`/`respawn-pane -c`
  calls do not change it). The live server was started at 12:12:00 by the auto-open line in `~/.zshrc` (line 22). Not
  verified: why that terminal's shell was in `home-study` (it was after the forced restart; a terminal restoring its
  previous directory would explain it).

## Reproduction

Pre-fix code: `git archive 2b70123 board bin tools claude | tar -x -C $S/pre`. `$S` is the session scratchpad, shown as
`<S>` in captured text. Scratch server only: `T=(~/.local/bin/tmux -L repro11 -f /dev/null)`. Claude Code 2.1.321,
tmux 3.8, macOS (Darwin 25.6.0).

Setup, run once:

    mkdir -p $S/cfg $S/state $S/lineage $S/proj && cd $S/proj && git init -q -b main . && echo hi > README.md \
      && git add . && git -c user.name=t -c user.email=t@t commit -qm init \
      && git worktree add -q .claude/worktrees/wt1 -b wt1
    cp ~/.claude.json $S/cfg/.claude.json; cp ~/.claude/settings.json $S/cfg/settings.json
    # in the COPY only: projects[<S>/proj] = the agent-board entry, activeWorktreeSession.worktreePath =
    # <S>/proj/.claude/worktrees/spikeworker and originalCwd = <S>/proj/.claude/worktrees/mod-agent-status (both absent)
    printf 'Reply with the single word ok and stop.\n' > $S/handoff.md

### Run 1 (control): server cwd intact. The relay works.

    env -u TMUX -u TMUX_PANE TC_STATE=$S/state TC_LINEAGE=$S/lineage CLAUDE_CONFIG_DIR=$S/cfg AGENT_BOARD_REPO=$S/pre \
      $T new-session -d -s proj -n claude -x 160 -y 45 -c $S/proj
    $T send-keys -t '=proj:claude' "$S/pre/bin/claude-orchestrator --model haiku"; sleep 1; $T send-keys -t '=proj:claude' Enter
    # in the lead, through Claude Code's bash mode (send-keys text, sleep 1, send-keys Enter):
    ! cd .claude/worktrees/wt1 && pwd
    ! git -C $S/proj worktree remove --force $S/proj/.claude/worktrees/wt1; ls $S/proj/.claude/worktrees
    ! $S/pre/bin/tmux-ctl relay $S/handoff.md

Result: `relay-proj.log` says `relayed proj:claude to a fresh orchestrator with <S>/handoff.md`, and the pane shows a
running lead in `<S>/proj` ("Claude Code v2.1.321 · Opus 5.5", the prompt `Read <S>/handoff.md and continue…`). So a lead
in a removed worktree plus the stale `activeWorktreeSession` does not cause the failure. Claude Code had already moved
the lead back to `<S>/proj` on its own once the worktree was gone (`! pwd` printed `<S>/proj`).

### Run 2: the same steps with the server's working directory removed. The relay fails.

    $T kill-server
    git -C $S/proj worktree prune; git -C $S/proj branch -D wt1 -q; git -C $S/proj worktree add -q $S/proj/.claude/worktrees/wt1 -b wt1
    mkdir -p $S/srvcwd2 && cd $S/srvcwd2 && env -u TMUX -u TMUX_PANE TC_STATE=$S/state TC_LINEAGE=$S/lineage \
      CLAUDE_CONFIG_DIR=$S/cfg AGENT_BOARD_REPO=$S/pre $T new-session -d -s proj -n claude -x 150 -y 45 -c $S/proj
    $T send-keys -t '=proj:claude' -l "$S/pre/bin/claude-orchestrator --model haiku"; sleep 1; $T send-keys -t '=proj:claude' Enter
    ! cd .claude/worktrees/wt1 && pwd
    ! git -C $S/proj worktree remove --force $S/proj/.claude/worktrees/wt1; rmdir $S/srvcwd2; ls -d $S/srvcwd2
    ! $S/pre/bin/tmux-ctl relay $S/handoff.md

`lsof -a -p <server pid> -d cwd` → `<S>/srvcwd2`; `ls -d $S/srvcwd2` → "No such file or directory".
`relay-proj.log` (relay.py still reports success):

    relayed proj:claude to a fresh orchestrator with <S>/handoff.md

Pane text after the relay (`capture-pane -p`):

    francisco.ruiz@US5TKNM0JCWGW . % <S>/pre/bin/claude-orchestrator 'Read <S>/handoff.md and continue from where the previous session left off.'
    The current directory no longer exists (it was deleted or moved). Start Claude Code from an existing directory.
    francisco.ruiz@US5TKNM0JCWGW . %

`list-panes`: `cmd=zsh start=<S>/proj cur=<S>/srvcwd2`. tmux reports the requested start path, but the shell is in the
server's deleted directory.

The user's workaround in that state: `respawn-pane -k -c $S/proj`, then `cd ~`, then the bare launcher line. Claude
starts in `/Users/francisco.ruiz`, and its environment has `OLDPWD=/Users/francisco.ruiz` and
`PWD=/Users/francisco.ruiz`, the same as the two live leads.

### Isolating probes (plain shells, no Claude; `/bin/pwd; echo rc=$? PWD=$PWD` typed into the new pane)

| Server cwd | Command | Shell lands in |
|---|---|---|
| intact | `respawn-pane -k -c <proj>`, old pane shell in a deleted dir | `<proj>`, rc=0 |
| intact | `respawn-pane -k -c <proj>`, calling client in a deleted dir | `<proj>`, rc=0 |
| intact | `respawn-pane -k` (no `-c`), old pane shell in a deleted dir | `/Users/francisco.ruiz`, rc=0 |
| deleted | `respawn-pane -k -c <proj>` | deleted dir: `pwd: .: No such file or directory`, rc=1, `PWD=.` |
| deleted | `new-window -d -c <proj>` | deleted dir: same output |
| deleted | `new-window -d -c <proj> "/bin/pwd; …"` (with a command) | deleted dir: same output |
| deleted | `run-shell '/bin/pwd'` | the calling client's cwd, rc=0 (jobs are not affected) |

The same `respawn-pane -k -c <proj>` on the same server gave `<proj>` before `rmdir` of the server's cwd and the deleted
directory after it. That is the only variable changed.

Not reproduced through a model turn: the scratch `CLAUDE_CONFIG_DIR` is not logged in, so the lead's three shell steps
were typed in Claude Code's `!` bash mode. They run in the same session shell and the same `tmux-ctl relay` →
`run-shell -b` → `relay.py` path.

## Root cause

**tmux 3.8, pane spawn.** When the tmux server process's own working directory has been deleted, a pane created by
`respawn-pane`, `new-window` (and by extension `split-window` and `new-session`) starts in the server's deleted directory
and not in the `-c` directory, while `#{pane_start_path}` still reports the `-c` value. Probe: the "deleted" rows of the
table above. I did not read tmux's source, so the mechanism inside tmux is not named; the behaviour is established by
the before/after probe on one server.

The chain on 2026-11-09:

1. The agent-board tmux server was started at 12:12:00 from a shell whose directory was
   `~/interiors/.claude/worktrees/home-study`, and a tmux server keeps that directory for life.
2. The interiors lead merged `home-study` at 14:11:45 and the worktree was removed by 14:22:30. The server now had a
   deleted cwd.
3. From then on every new pane on that server starts in the deleted directory. `board/relay.py:118`
   (`tmux("respawn-pane", "-k", "-t", pane, "-c", root, check=True)`) passes the correct `root`, tmux does not honour
   it, and `board/relay.py:119-121` (line numbers at 2b70123) type the bare launcher into that shell.
4. Claude Code's startup check fails (`process.cwd()` → `ENOENT`), prints the message and exits 1. relay.py has already
   returned success.

Ruled out, each with a probe above:

- relay's `-c <root>` being wrong (`session_root`/`root_for`, the `_roots` cache): `session_path` and `pane_start_path`
  are the main checkouts.
- The lead's Bash sitting in a removed worktree: Run 1 works; neither real lead was in a gone directory.
- Claude Code's stale `activeWorktreeSession`: present in Run 1, which works. The message comes only from the startup
  `process.cwd()` check.
- `~/.zshrc`, `~/.zprofile` (no `cd`, no `chpwd`; `~/.zshenv` does not exist), and `bin/claude-orchestrator` (no `cd`).
- `~/agent-board` being replaced: its inode dates from 2026-10-16.

## Covered by this plan?

**Tasks 2–3: yes for the relay, no for the cause.**

- Yes: typed into the broken shell of Run 2, `cd -- <S>/proj && <S>/pre/bin/claude-orchestrator --model haiku 'Read …'`
  started Claude with cwd `<S>/proj` (`lsof` on the claude pid). So the launch line of Task 2 lands the new lead in the
  main checkout even on a server in this state, and the start check with retry reports any other startup death. The
  board's restart button uses the same `relay.respawn()`, so it is covered if Task 2 puts the `cd` inside `respawn()`.
- No: the server stays broken until it is restarted, and every other pane it creates still starts in the deleted
  directory. Seen today: the `tmux-ctl agent` worker window (history above). Also exposed: `tmux-ctl new`, the `-bg`
  `tests`/`shell` windows and lanes (`bin/tmux-ctl:73-74`), `bin/tmux-dev-layout:34`, `bin/tmux-overseer:46`.

Extra changes for the lead to queue:

1. **Start the tmux server from a directory that is never removed.** Every place that may start the dedicated server
   should do it from `$HOME` (or `/`) and pass the wanted directory with `-c`: `bin/dev:20`, `bin/tmux-overseer:46`, any
   other caller that can be the first to reach the dedicated server (not audited here), and the user's `~/.zshrc` auto-open line (`( cd ~ && tmux -L agent-board … new-session -A -s
   main -c "$PWD" )`, or simply `cd ~` first). This is the fix for the cause.
2. **`tmux-ctl agent` launch file cds.** Write `cd -- <root> && …` in the launch file (`bin/tmux-ctl`, the `line=`
   assignment in `agent)`), the same repair as Task 2, so a worker does not die at startup or get restarted from `~`
   and create its worktree in the home repo.
3. **Detect it.** A check (board health or `tmux-ctl list`) that the server's cwd exists:
   `lsof -a -p "$(tmux display -p '#{pid}')" -d cwd -Fn` and test the path. Warn with "restart the tmux server".
4. **The running server.** The live `agent-board` server (pid 12354) is in this state now and cannot be repaired in
   place: its cwd is fixed. Until the user restarts it, new panes need the `cd`. Task 4's real relay will pass only
   because of the `cd` in the launch line.
