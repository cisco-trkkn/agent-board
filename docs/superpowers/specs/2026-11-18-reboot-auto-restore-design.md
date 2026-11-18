# Automatic restore after a forced reboot

Date: 2026-11-18 · Idea: 101 in `~/.local/state/agent-board/ideas/agent-board.md`
Supersedes: §1-3 (snapshot, board at login, restore banner) of `2026-11-10-restart-recovery-design.md`. Its §4 (tmux
server cwd safety) and §5 (`root_for` without the `$HOME` fallback) are unchanged and stay a separate queue item.
Runs after: `feat/discord-ops-bot` is merged (this spec uses `tools/lib/discord.zsh`, `tools/discord_watch.py` and the
bridge in `<project>-bg:discord`, which are not on `main` at 565352b).

## Incident

On Tue 2026-11-17 the org MDM profile (`/Library/Managed Preferences/com.apple.SoftwareUpdate.plist`:
`AutomaticallyInstallMacOSUpdates => true`) installed macOS 26.7.3 at 01:36:11 EST and rebooted at 01:40:52
(`sysctl kern.boottime`). Every process on the `agent-board` tmux server died: board, leads, workers and both Discord
bridges (agent-board bridge log: last line `06:35:47Z`, next `2026-11-18T21:26:54Z`; the interiors bridge left a
zero-byte `bridge-state.json.tmp`). FileVault's authenticated restart logged the user back in and the terminal reopened
`main` (01:43:49), but nothing restarted the projects. The Discord watchdog
(`com.user.agent-board-discord-watch`) only reconnects the MCP server inside a live lead, so with no leads it did
nothing. The Mac idle-slept at 01:45. The stack stayed down ~39 h until the user restarted it by hand.

IT will not grant a deferral or a restart notice, so the fix must recover after the fact, unattended.

## Decisions

- Restore is **fully automatic** at login: no click, no Discord approval.
- The keep-awake hold is **restored exactly as it was** (plain or lid, queue or pid); no hold before means none after.
- A restored lead **resumes its own conversation** by session id (`--resume <sid>`), not `--continue` (several
  conversations share a project folder: the lead's and every teammate's run in the main checkout).
- One LaunchAgent does both jobs: snapshot every 60 s and restore on the first tick of a new boot. It does not need
  the board to be running.

## Design

### 1. Snapshot (`board/restore.py`, new)

`snapshot(tmux, state_dir, now) -> dict`:

```json
{"boot": 1794897652, "saved_at": 1794896100.2, "restored": false,
 "awake": {"lid": false, "queue": true, "project": "agent-board"},
 "projects": [{"name": "agent-board", "path": "/Users/…/agent-board",
               "lead": {"session_id": "5388136e-…", "model": "opus", "discord": true},
               "bridge": true}]}
```

- One entry per project session: the session group when set, else the session name. Skip `*-bg`, sessions flagged
  `@tc_bg`, `_web-*` and `overseer`, and `main`-style sessions with no `claude` window.
- `path` is `#{session_path}`.
- `lead` is `null` unless the `claude` window's pane runs a claude process. Then:
  - `session_id` comes from `paneclass.mod_records()`: the record whose `pane` is that pane id. Missing → `null`.
  - `model` is the `--model` value in the lead's argv (`ps -o args=` of the pane's claude child). Missing → `null`.
  - `discord` is true when that argv carries `--channels plugin:discord@claude-plugins-official`.
- `bridge` is true when `<name>-bg` has a `discord` window whose pane runs `node …/discord-bridge/bridge.js`.
- `awake` comes from `$TC_STATE_DIR/awake.json` when `_aw_current` would call it live (caffeinate pid alive). Its
  `lid` and `queue` fields are copied; `project` is the project whose lead pid the hold watches (or, for `queue`, the
  project of the tmux server's first lead). No live hold → `null`.
- `boot_time()`: `sysctl -n kern.boottime` → the `sec` value. Unreadable → `None`: no snapshot is written and no
  restore runs.

`save(state_dir, snap)` writes `<TC_STATE>/restore/snapshot.json` through `.next` + rename, with the two guards from
the 11-10 spec: never replace a snapshot with one that has zero projects, and never replace a snapshot from an earlier
boot whose `restored` is false.

### 2. The tick (`agent-board restore tick`)

`bin/agent-board` gains `restore)` → `python3 board/restore.py "$@"`. `tick` takes a lock
(`<TC_STATE>/restore/tick.lock`, `fcntl.flock`, non-blocking: a second tick exits 0) and then:

1. `TC_RESTORE=0` or `<TC_STATE>/restore/restore.off` → exit 0.
2. Read the snapshot. If it exists, its `boot` is less than `boot_time()` and `restored` is false → **restore** (§3).
3. Else → **snapshot**: build it from the agent-board tmux server (`tc_tmux` resolution, socket `-L agent-board`) and
   save it. No server running → nothing written.

Every tick appends at most one line to `<TC_STATE>/restore/restore.log` (`<ISO> snapshot N projects`, only when the
project list changed; every restore step is logged).

### 3. Restore

In order, each step logged; a failing project never stops the others:

1. **Network**: poll up to 300 s (every 5 s) until `route -n get default` succeeds. Timeout → carry on (claude and the
   bridge retry on their own).
2. **tmux server and board**: `(cd ~ && agent-board dash start)` (starts the server from `$HOME`, so the 11-10 §4
   deleted-cwd problem cannot start here).
3. **Projects**, for each snapshot project with no live session and a `path` that is a directory (a gone folder is
   logged and reported, not created):
   - `bin/dev <path>` with `TMUX`/`TMUX_PANE` unset, `DEV_NO_ATTACH=1` (exists today: create only, no attach), and:
     - lead with `session_id`: `DEV_CLAUDE_CMD="<abs bin/claude-orchestrator> [--model M] [--channels
       plugin:discord@claude-plugins-official] --resume <sid> <quoted RESUME_PROMPT>"`, plus
       `DISCORD_STATE_DIR=$TC_STATE/discord/<name>` when `discord` is true;
     - lead without `session_id`: the same with `--continue` instead of `--resume <sid>`;
     - `lead: null`: `DEV_NO_LEAD=1`.
   - `bin/dev` gains `DEV_NO_LEAD=1` (skip the `send-keys` of the lead command). Unset → `dev` behaves exactly as
     today.
   - Test seam: `TC_RESTORE_ORCH` replaces the absolute `bin/claude-orchestrator` path in the lead command, and
     `TC_RESTORE_CTL` replaces `tmux-ctl` / `agent-board` calls with a stub that logs its argv.
   - `bridge: true` → `tmux-ctl discord bridge start --project <name>`.
   - The overseer is not restored here: `tmux-dev-layout` and the board run `tmux-overseer ensure`.
4. **Keep-awake**: `awake` not null → find the restored lead pane's claude pid for `awake.project` (poll up to 60 s
   for it to appear) and run `tmux-ctl awake on` with `--queue` when `queue` is true, else `--pid <pid>`, plus `--lid`
   when `lid` is true. `tmux-ctl awake` needs `$TMUX` for some paths: the plan checks `awake on` works from launchd
   (no `$TMUX`, `--pid` given) and adds the smallest switch if not.
5. **Report**: for each restored project with `bridge: true`, `tmux-ctl discord send --project <name> -m "<text>"`
   once its bridge is up (poll `bridge.pid` alive up to 120 s). Text: `Mac restarted at HH:MM (boot), restored at
   HH:MM: lead resumed (<sid8>) · bridge · keep-awake <lid|plain|none>` plus one `failed: <step>: <error>` line per
   failure. If `discord send` needs at least one file, the plan adds `-m`-only support (the bridge already posts text).
6. Mark the snapshot `restored: true` with `restored_at` and per-project results, then save.

`RESUME_PROMPT` (constant in `restore.py`): "The Mac was rebooted (forced macOS update) and every teammate and worker
is gone. Check TaskList, git status and git worktree list; respawn the team for unfinished tasks and continue the plan.
If a Plan & run task carries metadata.queue, queue mode is on: the keep-awake hold has already been restored, check it
with tmux-ctl awake status."

### 4. LaunchAgent (`agent-board restore schedule install|status|uninstall`)

Mirrors `agent-worktrees schedule` (`bin/agent-worktrees` `cmd_schedule`): writes
`~/Library/LaunchAgents/com.user.agent-board-restore.plist` with `RunAtLoad` true, `StartInterval` 60,
`WorkingDirectory` `$HOME`, `ProgramArguments` = absolute `bin/agent-board restore tick`, `EnvironmentVariables.PATH`
as in the discord-watch plist (`~/.local/bin:/opt/homebrew/bin:~/.bun/bin:/usr/bin:/bin`), stdout/stderr to
`<TC_STATE>/restore/launchd.log`; then `launchctl bootstrap gui/$UID`. `status` prints loaded/not loaded and the
snapshot's age, boot and project names. `uninstall` boots out and removes the plist. Linux: prints macOS only, exit 2.
`docs/INSTALL.md` documents it as recommended, and the plan's last task installs it on this Mac (user gate).

## Error handling

- Snapshot failures (tmux down, ps or agent-status unreadable) skip that field or that tick; they never raise out of
  `tick`.
- `boot_time()` unreadable → no snapshot and no restore.
- A restore step that fails is logged, reported to Discord and recorded in `results`; the snapshot is still marked
  restored, so a broken project does not loop every 60 s. `agent-board restore again` clears `restored` for a manual
  retry.
- A project session that already exists (the user got there first) is left alone and reported as `already open`.

## Known limit

Restore needs a logged-in GUI session. The MDM update path uses FileVault's authenticated restart, which logs the user
in. A panic or power loss stops at the FileVault login screen; restore runs as soon as the user logs in.

## Testing

- `board/tests/test_restore.py` (stub tmux, ps, agent-status dir, sysctl, runner):
  - snapshot: skips `-bg`, `@tc_bg`, `_web-*`, `overseer`; group name wins; lead with and without an agent-status
    record; `--model` and discord channel parsed from argv; bridge detection; awake fields from a live and a dead
    `awake.json`.
  - save guards: zero projects keeps the old one; an unrestored earlier-boot snapshot is kept.
  - `boot_time` parses `{ sec = 1794897652, usec = 269307 } Tue Nov 17 01:40:52 2026`.
  - tick: same boot → snapshot; newer boot + unrestored → restore; `TC_RESTORE=0` and `restore.off` → nothing; lock
    held → exit 0.
  - restore plan: exact `bin/dev` env for resume / continue / no-lead, `DISCORD_STATE_DIR` only for discord leads,
    bridge start only for `bridge: true`, gone folder reported, live session left alone, awake args for each of
    plain/lid/queue, Discord text includes failures, snapshot marked restored after a failure.
  - `RESUME_PROMPT` mentions TaskList and `awake status`.
- `tools/tests/` (zsh, scratch tmux server, `-f /dev/null`): `DEV_NO_ATTACH=1 DEV_NO_LEAD=1 dev <tmpdir>` creates the
  session and sends no keys; with only `DEV_NO_ATTACH` the `DEV_CLAUDE_CMD` line is typed.
  End-to-end: a snapshot with a faked older `boot` and `TC_RESTORE_ORCH` / `TC_RESTORE_CTL` stubs recreates two project sessions on the
  scratch server with the expected lead command lines.
- `restore schedule install` with a temp `HOME` writes the plist keys above (launchctl stubbed).
- User gate (real reboot): two projects open, one with a Discord lead and bridge, a queue hold on; `sudo shutdown -r
  now`; after login, without touching anything: both sessions exist, the leads show their old conversations, the
  bridge posts the restart line, `tmux-ctl awake status` shows the hold, and `pmset -g log` shows no Idle Sleep in
  the 10 minutes after login.

## Out of scope

Restoring teammate and worker windows (the lead respawns them from the resume prompt); a pre-reboot checkpoint (macOS
gives no usable warning under this MDM policy); approval before restore; keeping more than the latest snapshot; the
11-10 §4-5 items.
