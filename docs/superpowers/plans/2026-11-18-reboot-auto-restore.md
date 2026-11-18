# Reboot auto-restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a forced reboot, a LaunchAgent restores every agent-board project (tmux session, lead resumed by session id, Discord bridge, keep-awake hold) without the user touching anything, and reports it on Discord.

**Architecture:** `board/restore.py` snapshots the agent-board tmux server every 60 s (one LaunchAgent tick) into a durable JSON file; the first tick of a new boot replays it through `bin/dev` (new `DEV_NO_LEAD`), `tmux-ctl discord bridge start`, `tmux-ctl awake on` and `tmux-ctl discord send -m` (new: text without files). `board/restore_schedule.py` installs the LaunchAgent, mirroring `worktree_safety.schedule_*`.

**Tech Stack:** Python 3 stdlib (unittest), zsh, tmux, launchd.

**Spec:** `docs/superpowers/specs/2026-11-18-reboot-auto-restore-design.md`

## Global Constraints

- Every behaviour in the spec's §1-4, Error handling and Testing sections is binding unless a Ruling below changes it.
- **Ruling R1 (state dir):** the restore dir is `tc_env.agent_base() / "restore"` (`$TC_STATE`, else `~/.local/state/agent-board`, so `~/.local/state/agent-board/restore/`), NOT `tc_env.state_dir()`: that default is `$TMPDIR/tmux-ctl-<uid>`, which macOS clears on reboot, so a snapshot there would be gone exactly when it is needed. With `TC_STATE` set (tests) both rules give `$TC_STATE`. `awake.json` is still read from `tc_env.state_dir()` (where `tools/lib/awake.zsh` writes it), only while snapshotting.
- **Ruling R2 (Discord env):** the restored lead command does NOT set `DISCORD_STATE_DIR`: `bin/claude-orchestrator:34` unsets it and derives it from the pane's session (`:42-56`), so the spec's env var would be dropped. A lead with `discord: true` gets `--channels plugin:discord@claude-plugins-official` on its command line (the orchestrator dedupes it and applies its held-bot check).
- **Ruling R3 (model):** `bin/claude-orchestrator:76` passes `--model opus` unless `--model` is given, so the snapshot's `model` is normally present; restore passes `--model M` only when `model` is not null.
- tmux from Python: `paneclass.tmux_cmd()` (same resolution as `bin/_tc_bins.zsh`; outside tmux it is `-L agent-board`). zsh tests use the scratch server from `tools/tests/lib.zsh` (`-f /dev/null`).
- No real `launchctl`, `sysctl`, `ps`, `route`, `tmux-ctl` or claude runs in unit tests: each has a seam (constructor argument or env var such as `TC_RESTORE_CTL`, `TC_RESTORE_ORCH`, `AW_LAUNCHCTL`-style `RS_LAUNCHCTL`).
- `boot_time()` probe on this Mac (run 2026-11-18): `sysctl -n kern.boottime` → `{ sec = 1794897652, usec = 245407 } Tue Nov 17 01:40:52 2026`.
- Commits: conventional with scope (`feat(restore): …`, `feat(dev): …`, `feat(discord): …`, `docs(install): …`); end with the attribution trailer your harness specifies. Stage only your own paths.

**User decisions (already made):** fully automatic restore, no click and no approval; keep-awake restored exactly as it was; leads resume by `--resume <sid>`; one LaunchAgent does snapshot and restore; queue integration = merge locally, no push (the user-gate reboot test waits for the user).

---

### Task 1: Snapshot, boot time and save guards

**Goal:** `board/restore.py` builds the spec §1 snapshot from a tmux server and saves it with both guards.

**Files:**
- Create: `board/restore.py`
- Test: `board/tests/test_restore.py`

**Acceptance Criteria:**
- [ ] `boot_time(run)` parses `{ sec = 1794897652, usec = 269307 } Tue Nov 17 01:40:52 2026` → `1794897652`; unreadable or failing sysctl → `None`.
- [ ] `snapshot(...)` emits one entry per project (session group wins over name); skips `*-bg`, `@tc_bg`-flagged, `_web-*`, `overseer`, and sessions with no `claude` window; `path` = `#{session_path}`.
- [ ] `lead` is `null` unless the `claude` window's pane runs a claude process; `session_id` from `paneclass.mod_records()` keyed by pane id (missing → `null`); `model` from `--model` in the claude argv; `discord` true iff argv carries `--channels … plugin:discord@claude-plugins-official`.
- [ ] `bridge` true iff `<name>-bg` has a `discord` window whose pane runs `node …/discord-bridge/bridge.js`.
- [ ] `awake` copies `lid`/`queue` from a live `awake.json` (caffeinate pid alive) and names `project`; dead or absent hold → `null`.
- [ ] `save()` writes `<restore dir>/snapshot.json` via `.next` + rename; a zero-project snapshot never replaces an existing one; an earlier-boot snapshot with `restored: false` is never replaced. Mutation: remove either guard → its test fails.
- [ ] A failing tmux/ps/status read skips that field or returns `None`; `snapshot` never raises.

**Verify:** `python3 -m unittest board.tests.test_restore -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1:** Write `board/tests/test_restore.py` with fakes for every external read (a `run(cmd) -> (rc, stdout)` callable passed into `boot_time`/`snapshot`, an agent-status dir in a temp dir written as the mod writes it: `{"session_id","pane","state":"idle","updatedAt":<now>}`, a temp `awake.json`). Cover every AC bullet, one test each. Run it: RED (module missing).
- [ ] **Step 2:** Implement `board/restore.py`: `restore_dir()` (R1), `boot_time(run=_run)`, `snapshot(run=_run, status_dir=None, awake_file=None, now=None, pid_alive=None)`, `load(dir)`, `save(dir, snap)`. tmux reads go through `paneclass.tmux_cmd()`; read sessions with one `list-sessions -F` carrying `#{session_name}\t#{session_group}\t#{session_path}\t#{@tc_bg}` and panes with one `list-panes -a -F '#{session_name}\t#{window_name}\t#{pane_id}\t#{pane_pid}'`. The claude process is the pane pid or a descendant whose argv[0] basename is `claude` (`ps -A -o pid=,ppid=,args=` once per snapshot). For `awake.project`: a `queue` hold → the first project with a lead; a `--pid` hold → the project whose lead claude pid (or an ancestor of it) equals the watched pid.
- [ ] **Step 3:** GREEN, then for each guard test apply its mutation once and confirm it fails; restore.
- [ ] **Step 4:** Commit `board/restore.py board/tests/test_restore.py` as `feat(restore): snapshot the agent-board server`.

```json:metadata
{"files": ["board/restore.py", "board/tests/test_restore.py"], "verifyCommand": "python3 -m unittest board.tests.test_restore -v 2>&1 | tail -3", "acceptanceCriteria": ["boot_time parses the probe line, None when unreadable", "project entries: group wins, skips -bg/@tc_bg/_web-*/overseer/no claude window", "lead session_id/model/discord parsed as spec", "bridge detection", "awake from live awake.json, null when dead", "save guards with named mutations", "snapshot never raises"], "modelTier": "standard"}
```

### Task 2: `dev` DEV_NO_LEAD and `agent-board restore`

**Goal:** `bin/dev` can create a session without typing a lead command, and `agent-board restore …` reaches `board/restore.py`.

**Files:**
- Modify: `bin/dev:21` (the `send-keys` line), `bin/agent-board` (case + help lines)
- Test: `tools/tests/test_dev_no_lead.zsh`

**Acceptance Criteria:**
- [ ] `DEV_NO_ATTACH=1 DEV_NO_LEAD=1 dev <tmpdir>` on the scratch server creates the session and its `claude` pane holds no typed command. Mutation: drop the `DEV_NO_LEAD` check → test fails.
- [ ] `DEV_NO_ATTACH=1 DEV_CLAUDE_CMD='echo restored-lead' dev <tmpdir2>` types that line (it appears in the pane).
- [ ] `bin/agent-board` dispatches `restore` to `python3 <repo>/board/restore.py` (its `--help` exit 0 is checked in Task 6); `agent-board help` lists `restore`.

**Verify:** `zsh tools/tests/test_dev_no_lead.zsh; echo rc=$?` → `rc=0`

**Steps:**

- [ ] **Step 1:** Write `tools/tests/test_dev_no_lead.zsh` following an existing scratch-server test (e.g. `tools/tests/test_bg.zsh`: `source lib.zsh`, `tt_setup`, assertions, `tt_teardown`). Run `dev` with `TMUX`/`TMUX_PANE` unset and `TMUX_DASH_TMUX_ARGS` pointing at the scratch socket, `TC_LAYOUT=/usr/bin/true` (skip the layout). After 1 s, `capture-pane -p -t "=<name>:claude"`: for DEV_NO_LEAD assert it does not contain `claude-orchestrator`; for the second case assert it contains `restored-lead`. Run: RED on case 1.
- [ ] **Step 2:** In `bin/dev` replace line 21 with:

```zsh
  [[ -n "$DEV_NO_LEAD" ]] || tc_tmux send-keys -t "=${name}:claude" "${DEV_CLAUDE_CMD:-${(q)${0:A:h}}/claude-orchestrator}" Enter   # agent team by default; DEV_NO_LEAD: restore of a project that had no lead
```

- [ ] **Step 3:** In `bin/agent-board` add `  restore) shift; exec python3 "${here:h}/board/restore.py" "$@" ;;` after `cleanup)`, and a help line `#   agent-board restore <cmd>  snapshot/restore after a reboot: tick, snapshot, again, status, schedule install|status|uninstall`; bump both `sed -n '2,11p'` ranges to `'2,12p'`. (Task 4 gives `restore.py` its argparse `main`; until then `--help` is checked only after Task 4 — Task 2's test asserts the dispatch line exists with `grep -q 'restore) shift; exec python3' bin/agent-board`.)
- [ ] **Step 4:** GREEN; commit `bin/dev bin/agent-board tools/tests/test_dev_no_lead.zsh` as `feat(dev): DEV_NO_LEAD creates a session without a lead; agent-board restore`.

```json:metadata
{"files": ["bin/dev", "bin/agent-board", "tools/tests/test_dev_no_lead.zsh"], "verifyCommand": "zsh tools/tests/test_dev_no_lead.zsh; echo rc=$?", "acceptanceCriteria": ["DEV_NO_LEAD session has no typed command (mutation named)", "DEV_CLAUDE_CMD still typed", "agent-board restore dispatch + help line"], "modelTier": "mechanical"}
```

### Task 3: `tmux-ctl discord send -m` without files

**Goal:** `tmux-ctl discord send --project <p> -m "<text>"` posts text alone.

**Files:**
- Modify: `tools/lib/discord.zsh` (`_dc_send`, `_dc_usage`), and `board/discord_send.py` only if it rejects zero files
- Test: `tools/tests/test_ctl_discord_send.zsh`

**Acceptance Criteria:**
- [ ] `send -m hi` with no files writes one post op with text `hi` and an empty file list, prints `send: 1 post, 0 files`, exit 0.
- [ ] `send` with neither files nor `-m` still prints usage, exit 2.
- [ ] The bridge posts a zero-file op as text (check `tools/discord-bridge/bridge.js`'s post handler; add a node test in `tools/discord-bridge/test/` only if it needs a change).
- [ ] Existing `test_ctl_discord_send.zsh` cases stay green.

**Verify:** `zsh tools/tests/test_ctl_discord_send.zsh; echo rc=$?` → `rc=0`

**Steps:**

- [ ] **Step 1:** Add the two cases to `tools/tests/test_ctl_discord_send.zsh` in its existing style; RED on the first.
- [ ] **Step 2:** In `_dc_send` change `(( ${#files} )) || { _dc_usage; return 2 }` to `(( ${#files} )) || [[ -n "$text" ]] || { _dc_usage; return 2 }`; update `_dc_usage` to `send [--thread <key>] [<file>…] [-m <text>]`. Run the test; if `discord_send.py` refuses zero files, make the smallest change there.
- [ ] **Step 3:** GREEN; commit as `feat(discord): send -m posts text without files`.

```json:metadata
{"files": ["tools/lib/discord.zsh", "board/discord_send.py", "tools/tests/test_ctl_discord_send.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_discord_send.zsh; echo rc=$?", "acceptanceCriteria": ["send -m alone writes one text post", "no files and no -m still usage exit 2", "bridge posts a zero-file op", "existing cases green"], "modelTier": "mechanical"}
```

### Task 4: The tick and the restore

**Goal:** `agent-board restore tick` snapshots or restores per spec §2-3, with `snapshot --print`, `again` and `status` subcommands.

**Files:**
- Modify: `board/restore.py`
- Test: `board/tests/test_restore_tick.py`

**Constraints:** spec §2 and §3 in full, with Rulings R1-R3. Restore runs each step through injectable seams: `TC_RESTORE_CTL` (replaces every `tmux-ctl`/`agent-board` call; a stub that logs argv), `TC_RESTORE_ORCH` (replaces the absolute `bin/claude-orchestrator` path), `TC_RESTORE_DEV` (replaces `bin/dev`; default the repo's `bin/dev`), plus constructor/keyword seams for sleep, clock, `route -n get default`, pid lookup. `RESUME_PROMPT` is the spec's text verbatim. Every tick appends at most one log line for a snapshot (only when the project-name list changed); every restore step logs a line. A project failure never stops the others; the snapshot is marked `restored: true` with `restored_at` and per-project `results` even after failures. `tmux-ctl awake on` with `--queue` resolves the server through `tc_tmux_resolve`, which outside tmux is `-L agent-board`: no `$TMUX` switch is needed (checked by reading `bin/_tc_bins.zsh:36-48`); the e2e task confirms it on a scratch socket via `TMUX_DASH_TMUX_ARGS`.

**Acceptance Criteria:**
- [ ] tick: same boot → snapshot saved; newer boot + `restored: false` → restore; `TC_RESTORE=0` and `<dir>/restore.off` → nothing written, exit 0; lock held by another fd → exit 0 without work.
- [ ] restore `bin/dev` env: resume lead → `DEV_CLAUDE_CMD` = `<orch> [--model M] [--channels plugin:discord@claude-plugins-official] --resume <sid> <shell-quoted RESUME_PROMPT>`; lead without sid → `--continue` in place of `--resume <sid>`; `lead: null` → `DEV_NO_LEAD=1`; always `DEV_NO_ATTACH=1`, `TMUX`/`TMUX_PANE` unset; no `DISCORD_STATE_DIR` (R2).
- [ ] `bridge: true` only → `discord bridge start --project <name>`; gone folder → reported, not created; live session → left alone, reported `already open`.
- [ ] awake args for plain (`--pid <pid>`), lid (`--pid <pid> --lid`), queue (`--queue`, plus `--lid` when lid); `awake: null` → no awake call.
- [ ] Discord text: `Mac restarted at HH:MM (boot), restored at HH:MM: lead resumed (<sid8>) · bridge · keep-awake <lid|plain|none>` plus one `failed: <step>: <error>` line per failure, sent with `discord send --project <name> -m`.
- [ ] Network wait polls `route -n get default` every 5 s up to 300 s, then carries on; dash start runs as `(cd ~ && agent-board dash start)` equivalent (cwd `$HOME`).
- [ ] `RESUME_PROMPT` contains `TaskList` and `awake status`; `again` clears `restored`; `snapshot --print` prints the snapshot JSON without saving; `status` prints the snapshot's age, boot and project names. `agent-board restore --help` exits 0.
- [ ] Mutation: make restore skip marking `restored` after a failure → the "marked restored after a failure" test fails.

**Verify:** `python3 -m unittest board.tests.test_restore board.tests.test_restore_tick -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/restore.py", "board/tests/test_restore_tick.py"], "verifyCommand": "python3 -m unittest board.tests.test_restore board.tests.test_restore_tick -v 2>&1 | tail -3", "acceptanceCriteria": ["tick branches incl. TC_RESTORE=0, restore.off, lock", "exact bin/dev env for resume/continue/no-lead, no DISCORD_STATE_DIR", "bridge start only for bridge:true; gone folder; live session left alone", "awake args plain/lid/queue", "Discord text with failure lines", "network wait and dash start from HOME", "RESUME_PROMPT, again, snapshot --print, status", "marked restored after failure (mutation named)"], "modelTier": "standard"}
```

### Task 5: LaunchAgent schedule and INSTALL docs

**Goal:** `agent-board restore schedule install|status|uninstall` manages `com.user.agent-board-restore`, and INSTALL.md documents it.

**Files:**
- Create: `board/restore_schedule.py`
- Test: `board/tests/test_restore_schedule.py`
- Modify: `docs/INSTALL.md`

**Constraints:** mirror `board/worktree_safety.py:598-690` (`_plist_path`, `plist_text`, `_launchctl`, `schedule_install/uninstall/status`). Differences that change behaviour, all from spec §4: label `com.user.agent-board-restore`; `RunAtLoad` true and `StartInterval` 60 instead of a calendar interval; `WorkingDirectory` `$HOME`; `ProgramArguments` = [absolute `bin/agent-board`, `restore`, `tick`]; PATH `~/.local/bin:/opt/homebrew/bin:~/.bun/bin:/usr/bin:/bin` (adds `~/.bun/bin`); stdout/stderr to `<restore dir>/launchd.log` (R1 dir); launchctl seam env `RS_LAUNCHCTL`; on Linux (`sys.platform != "darwin"`) every subcommand prints `macOS only` and exits 2. `status` prints loaded/not loaded plus the snapshot's age, boot and project names. Task 4 wires `schedule` into `restore.py`'s argparse by importing this module; this task exposes `install()`, `uninstall()`, `status()` returning lists of lines.

**Acceptance Criteria:**
- [ ] With a temp `HOME` and `RS_LAUNCHCTL` stub, `install()` writes a plist whose keys equal the constraints above (parsed with `plistlib`), backs up an existing plist as `.bak-YYYYMMDD`, calls `bootout` then `bootstrap gui/<uid> <plist>`.
- [ ] `uninstall()` boots out and removes the plist; `status()` reports not loaded when the stub's `print` fails.
- [ ] Non-darwin → `macOS only`, exit code 2 (test patches `sys.platform`).
- [ ] `docs/INSTALL.md` has a "Restore after a reboot (recommended)" section: what it does, `agent-board restore schedule install`, `status`, the `TC_RESTORE=0` / `restore.off` switches, `restore again`, and the FileVault known limit.

**Verify:** `python3 -m unittest board.tests.test_restore_schedule -v 2>&1 | tail -3` → `OK`

```json:metadata
{"files": ["board/restore_schedule.py", "board/tests/test_restore_schedule.py", "docs/INSTALL.md"], "verifyCommand": "python3 -m unittest board.tests.test_restore_schedule -v 2>&1 | tail -3", "acceptanceCriteria": ["plist keys match spec §4", "backup + bootout + bootstrap", "uninstall/status", "non-darwin exit 2", "INSTALL section"], "modelTier": "standard"}
```

### Task 6: End-to-end restore on a scratch server, plus a real-state read

**Goal:** A faked older-boot snapshot restores two projects on a scratch tmux server with the expected lead lines, and `snapshot --print` reads the user's live server correctly.

**Files:**
- Create: `tools/tests/test_restore_e2e.zsh`
- Modify: `board/restore.py` only to fix what this test exposes

**Acceptance Criteria:**
- [ ] Scratch server (`tools/tests/lib.zsh`, `-f /dev/null`), `TC_STATE` = a temp dir, `TMUX_DASH_TMUX_ARGS` = the scratch socket, `TC_RESTORE_ORCH` = a stub script path, `TC_RESTORE_CTL` = a stub logging argv to a file, `TC_LAYOUT=/usr/bin/true`: a snapshot with `boot` = 1 and two projects (one resume+discord+bridge, one `lead: null`) → after `python3 board/restore.py tick` both sessions exist; project A's `claude` pane shows `<stub> --model opus --channels plugin:discord@claude-plugins-official --resume <sid> …`; project B's pane has no typed command; the ctl log has `dash start`, `discord bridge start --project A`, `discord send --project A -m …`; the snapshot now has `restored: true`.
- [ ] A second `tick` right after does not restore again (log unchanged except a snapshot line).
- [ ] Real state (read-only): `python3 board/restore.py snapshot --print` against the user's live `-L agent-board` server lists `agent-board` with a non-null `lead.session_id` and `bridge: true`; record the output in the task report. Nothing is written (check `ls ~/.local/state/agent-board/restore/` before and after).

**Verify:** `zsh tools/tests/test_restore_e2e.zsh; echo rc=$?` → `rc=0`

```json:metadata
{"files": ["tools/tests/test_restore_e2e.zsh", "board/restore.py"], "verifyCommand": "zsh tools/tests/test_restore_e2e.zsh; echo rc=$?", "acceptanceCriteria": ["two projects restored on scratch server with expected lead lines", "ctl log has dash start, bridge start, send -m", "no second restore", "real-state snapshot --print lists agent-board with session_id and bridge, writes nothing"], "modelTier": "standard"}
```

### Task 7: User gate — install on this Mac and a real reboot

**Goal:** The LaunchAgent is installed on this Mac and a real reboot restores the stack unattended.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none (runs on the merged `main`)

**Acceptance Criteria:**
- [ ] `agent-board restore schedule install` then `agent-board restore schedule status` shows loaded and a snapshot listing the open projects.
- [ ] Two projects open, one with a Discord lead and bridge, a queue hold on; the user runs `sudo shutdown -r now`; after login, untouched: both sessions exist, the leads show their old conversations, the bridge posts the `Mac restarted at …` line, `tmux-ctl awake status` shows the hold, and `pmset -g log | grep -i "idle sleep"` shows none in the 10 minutes after login.

**Verify:** `agent-board restore schedule status && tail -20 ~/.local/state/agent-board/restore/restore.log`

```json:metadata
{"files": [], "verifyCommand": "agent-board restore schedule status && tail -20 ~/.local/state/agent-board/restore/restore.log", "acceptanceCriteria": ["schedule status loaded with a snapshot", "after a real reboot: sessions exist, leads resumed, Discord restart line, awake hold, no idle sleep in 10 min"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
