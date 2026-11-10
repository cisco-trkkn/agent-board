# Restart recovery and relay root safety

Date: 2026-11-10 · Ideas: 101, 105, 107, 108, 109 in `~/.local/state/agent-board/ideas/agent-board.md`
Related: `docs/superpowers/notes/2026-11-09-relay-gone-cwd.md`, plan `2026-11-09-relay-launch-check`

## Problem

1. **A forced restart loses every project (101).** Nothing brings back the `agent-board` tmux server, the board or the
   project sessions; the user reopens each project and reminds each lead where it was. The only LaunchAgent today is
   the 04:00 worktree sweep.
2. **A tmux server with a deleted cwd breaks every new pane (105).** tmux 3.8 starts new and respawned panes in the
   server's own cwd when that dir is gone, ignoring `-c`. The live server picked up a worktree cwd from the terminal
   that started it (`~/.zshrc` line 22 runs `tmux -L agent-board … new-session -A -s main` from wherever the shell is).
   Nothing warns.
3. **`relay.root_for` silently falls back to `$HOME` (107).** When a session's start path is gone it returns `$HOME`
   (`board/relay.py` `root_for`), pinned by `test_deleted_worktree_session_path_falls_back_to_home`. A relayed or
   restarted lead then starts in `~` without anyone noticing.
4. **Six board tests fail on main (108, 109).** `board/tests/test_orchestrator_path.py` (4) and
   `board/tests/test_restart_orchestrator.py` (2) expect the bare launcher; `relay.launch_line` now types
   `cd -- <root> && <launcher>`.

## Decisions

- Restore is **one click on the board**, not automatic: after a reboot the board offers the projects that were open.
- A restored lead runs **`claude --continue` plus a resume prompt**, keeping its conversation.
- Starting the board at login is an **opt-in LaunchAgent**.

## Design

### 1. Snapshot (`board/restore.py`, new)

- `snapshot(tmux) -> dict`: `{"boot": <kern.boottime seconds>, "saved_at": <epoch>, "restored": false, "projects":
  [{"name", "path", "lead": bool}]}`. One entry per project: the session group when set, else the session name.
  Skip sessions flagged `@tc_bg` or named `*-bg`, and sessions named `_web-*` (board view sessions). `path` is
  `#{session_path}`. `lead` is true when the project's `claude` window runs a claude process (the classifier already
  used by `build_state`).
- `boot_time()`: parse `sysctl -n kern.boottime` (`{ sec = N, usec = M } …`) → N. Linux fallback: `btime` from
  `/proc/stat`. Unreadable → `None`, and restore detection is off (no banner).
- `save(state_dir, snap)`: write `<TC_STATE>/restore/snapshot.json` via `.next` + rename. Never replace an existing
  snapshot with one that has zero projects (a board started on an empty server must not wipe the last good one).
  When the existing snapshot is from an earlier boot and has `restored: false`, do not overwrite it until it is
  restored or dismissed (otherwise the first save after a reboot would erase what is to be restored).
- The board server calls `snapshot` + `save` at most once per 60 s from its existing state-poll path.

### 2. Board at login

`agent-board dash schedule install|uninstall|status`, mirroring `agent-worktrees schedule`
(`bin/agent-worktrees` `cmd_schedule`): writes `~/Library/LaunchAgents/com.user.agent-board-dash.plist` with
`RunAtLoad`, `WorkingDirectory` = `$HOME`, `ProgramArguments` = the absolute `bin/agent-board dash start`, stdout and
stderr to `~/.local/state/tmux-dash/launchd.log`; loads it with `launchctl bootstrap gui/$UID`. Linux: prints that
this is macOS only and exits 2. INSTALL documents it as optional.

### 3. Restore banner and action

- `restore.pending(snap, now_boot, live_projects)`: the snapshot's `boot` is less than `now_boot`, `restored` is false,
  and at least one snapshot project has no live session. Returns the list with, per project, `restorable` (path is a
  dir) or the reason (`folder is gone: <path>`).
- `GET /api/restore` → that list (empty when nothing is pending). The board shows a banner at the top:
  "Restart detected: restore N projects", a checkbox per restorable project (all ticked), unrestorable ones greyed
  with the reason, buttons Restore and Dismiss.
- `POST /api/restore {"projects": [...]}`: for each named project that is restorable and still has no session:
  create the session the way `bin/dev` does (same code path: call `bin/dev <path>` with `TMUX`/`TMUX_PANE` unset).
  `bin/dev` gains two env switches, both unset by default so `dev` behaves as today: `DEV_DETACHED=1` skips its final
  attach/switch-client (lines 31-43; the board has no terminal), and `DEV_NO_LEAD=1` sends nothing to the `claude`
  window (line 21). A `lead: true` project gets
  `DEV_CLAUDE_CMD="<abs claude-orchestrator> --continue <shell-quoted prompt>"`; a `lead: false` project gets
  `DEV_NO_LEAD=1`. Returns per-project `ok` or the error line. Then marks the snapshot `restored: true`.
- `POST /api/restore/dismiss` marks it `restored: true` without starting anything.
- The resume prompt (one line, constant in `restore.py`): "The machine restarted and every teammate and worker is
  gone. Check TaskList, git status and git worktree list; respawn the team for unfinished tasks and continue the
  plan. If any Plan & run task carries metadata.queue, queue mode is on: run tmux-ctl awake on --lid first."
- Both POSTs need the board token like every other mutating endpoint.

### 4. tmux server cwd safety

- Prevention: `bin/dev` and `bin/tmux-dash` start the tmux server from `$HOME`: every place that may create the
  server (`new-session`) runs in a subshell with `cd ~` first. INSTALL's auto-attach snippet becomes
  `(cd ~ && tmux -L agent-board -f … new-session -A -s main)`. The user's own `~/.zshrc` line 22 is not edited by the
  plan; the plan's last task tells the user the one-line change (user gate).
- Detection: `tmux_server_cwd(tmux)` in `board/restore.py`: the server pid from `display -p '#{pid}'`, then
  `lsof -a -p <pid> -d cwd -Fn` → the `n` line. Gone (not a dir) → warning
  `tmux server cwd is gone (<path>): new panes start there; restart the tmux server (agent-board dash stop, then
  start)`. Shown by the board in the same banner area (from `build_state`, checked at most every 60 s) and printed by
  `tmux-ctl list` as the first line (`tmux-ctl` does its own `lsof`). `lsof` missing or failing → no warning.

### 5. `root_for` without the silent `$HOME` fallback

- `root_for(start_path)`:
  - start_path is a dir → unchanged behaviour (cached main checkout).
  - start_path is set but gone → walk up its parents to the nearest existing dir `p` (stop before `/`). If
    `_git_root(p)` is a repo whose toplevel is not `$HOME`, return that main checkout (a removed
    `<repo>/.claude/worktrees/x` resolves to `<repo>`). Else return `None`.
  - start_path empty → `None`.
- Callers: `build_state` (both places) shows `relay.root_for(p) or p` (display only). `session_root`, relay and
  `restart_orchestrator` treat `None` as an error: no respawn, the error `project folder is gone: <start_path>` is
  returned to the caller (board toast / `tmux-ctl relay` stderr, exit 1).
- Tests: `test_deleted_worktree_session_path_falls_back_to_home` becomes two tests: removed worktree → main checkout;
  gone non-git path → `None` and relay refuses with the message.
- `test_orchestrator_path.py` and `test_restart_orchestrator.py`: expected launch text becomes
  `relay.launch_line(root, prompt)` output (`cd -- <root> && <launcher> [prompt]`), asserted against the function, not
  a copied string.

## Error handling

Snapshot, boot-time and lsof failures disable their feature silently (no banner, no warning); they never break the
board's state poll. A restore of one project that fails does not stop the others; each result is shown in the banner.

## Testing

- `board/tests/test_restore.py`: snapshot from a fake tmux listing (skips `-bg`, `@tc_bg`, `_web-*`; group name wins;
  `lead` flag); save keeps the last good snapshot on zero projects and keeps an unrestored earlier-boot snapshot;
  `boot_time` parses the macOS format; `pending` with older/same boot, restored flag, all-live, gone folder; POST
  restore builds the `bin/dev` call with the env (stub runner) for lead and non-lead projects and marks restored;
  dismiss; token required; resume prompt contains `TaskList` and `awake on --lid`.
- `tmux_server_cwd` with a stub runner: gone path → warning text; existing → none; lsof failure → none.
- root_for cases above; the six fixed tests pass; full `python3 -m unittest discover -s board/tests` green.
- zsh (`tools/tests/`, scratch tmux server): `dev` started from a temp dir that is then deleted leaves the server cwd
  at `$HOME`; `tmux-ctl list` prints the warning when a scratch server is started from a dir that is then removed.
- `agent-board dash schedule install` with a temp `HOME` writes the plist with the right keys (no `launchctl` call
  under test: stub).
- User gate (manual e2e): two projects open, reboot, open the board, Restore; both leads resume their conversations
  with the prompt.

## Out of scope

Automatic restore without a click; restoring teammate/worker windows; restoring windows other than the dev layout;
saving more than the latest snapshot.
