# Final whole-branch review: reboot-auto-restore (f702497..5df0198)

Reviewer: rar-final. I reviewed the whole diff in one pass with no subagents, and read the code at HEAD 5df0198 in the worktree.

What I ran (read-only plus scratch runs):
- `python3 -m unittest board.tests.test_restore board.tests.test_restore_tick board.tests.test_restore_schedule`: Ran 84 tests, OK.
- `zsh tools/tests/test_restore_e2e.zsh`: rc=0, 18 ok, 0 FAIL. `test_dev_no_lead.zsh`: rc=0, 5 ok. `test_ctl_discord_send.zsh`: rc=0, 33 ok.
- `TMUX_TMPDIR=$(mktemp -d /tmp/tcs.XXXXXX)/1 zsh tools/tests/test_restore_e2e.zsh` (how `all.zsh` runs every job): rc=1, `1 FAILED` (`launchd env: both sessions recreated`). It also leaked a tmux server, described under I1. I killed that server by its socket and removed the socket and the temp root.
- `sysctl -n kern.boottime` returns `{ sec = 1794897652, usec = 245407 }`. The spec probe for the same boot recorded `usec = 269307`.
- `launchctl print gui/$UID/com.user.agent-board-discord-watch` shows the job environment holds only PATH, XPC_SERVICE_NAME and OSLogRateLimit. Launchd-started processes (seen with `ps eww`) do get HOME and TMPDIR, so `tc_env.state_dir()` and `awake.json` resolve the same way under launchd as in a terminal.

## Strengths

- The launchd path resolves correctly. The plist runs `~/.local/bin/agent-board` (restore_schedule.py:44-48), and `REPO` is the resolved main checkout (restore.py:256). `dev` and `paneclass.tmux_cmd()` both fall through to `-L agent-board -f <repo>/config/tmux.conf` when `$TMUX` is unset (bin/_tc_bins.zsh:46-47), so a tmux server that the restore starts never reads `~/.tmux.conf`. `~/.tmux.conf` has 0 legacy hook lines, so the legacy branch (_tc_bins.zsh:42) is not taken.
- The tmux server starts with cwd `$HOME`, because `dev` runs with `cwd=cfg.home` (restore.py:427). The 11-10 §4 hazard cannot occur here.
- AbandonProcessGroup (restore_schedule.py:57) keeps ttyd, server.py (`nohup … &` in tmux-dash) and caffeinate (`&!` in awake.zsh:121) alive after the tick exits. The tmux server daemonizes on its own. Every background child redirects stdout (tmux-dash:39-49, awake.zsh:46,121, tmux-dev-layout:85), so `_sh`'s `capture_output` cannot hang on an inherited pipe.
- `/usr/sbin/sysctl` and `/sbin/route` are absolute (restore.py:25), and a real `env -i` run under the plist PATH (test_restore_e2e.zsh:66) proves it, with a mutation that fails without them.
- Failures stay inside one project. Each project runs in its own try (restore.py:372-376), awake and report have their own guards, `_safe` wraps every external call, and the snapshot is marked restored even after failures (restore.py:393-396). A broken project cannot make the tick loop every 60 s.
- Things the user stopped on purpose stay stopped. A lead that was quit gives `lead: null` and `DEV_NO_LEAD`. A bridge stopped with `bridge stop` is not running, so `bridge: false`. A released hold gives `awake: null`. A session that already exists is left alone.
- R2 holds: claude-orchestrator:34-56 derives `DISCORD_STATE_DIR` from the pane's session group or name, which is the snapshot name. R1 and R3 are applied as ruled.
- The e2e stub records its own argv from inside the pane, so the resume-command check proves what a real shell received.

## Issues

### Critical

None.

### Important

**I1. Under `all.zsh`, the e2e `env -i` case fails and leaks a tmux server that loads `~/.tmux.conf`** (tools/tests/test_restore_e2e.zsh:66-70)
- What is wrong: `env -i` drops `TMUX_TMPDIR`. `all.zsh` gives every job `TMUX_TMPDIR=<root>/i`, so the scratch server lives under that root. Inside the `env -i` run, `dev` resolves `-L tctest-…` to `/private/tmp/tmux-503/`, finds no server there, and starts a new one. `TMUX_DASH_TMUX_ARGS` is an explicit override and adds no `-f` (_tc_bins.zsh:38-39), so that server loads `~/.tmux.conf`.
- Reproduced: `show-options -g` on the leaked server lists `@plugin tmux-plugins/tmux-continuum`, `@continuum-save-interval 15` and `@resurrect-processes "~claude->claude --continue"`. `all.zsh`'s cleanup only kills sockets under its own root, so the server survives the run. The check `launchd env: both sessions recreated` fails, which makes `all.zsh` red on this branch.
- Why it matters: this breaks the rule "Scratch tmux servers must start with `-f /dev/null`". A surviving continuum server can also write resurrect saves; I found none newer than Nov 2 in `~/.tmux/resurrect`.
- A leak from an earlier run is still alive: pid 92687, socket `/private/tmp/tmux-503/tctest-91766-28422`, started 18:04, from a `tc-all.O49wB3` run (not mine). Kill it with `~/.local/bin/tmux -S /private/tmp/tmux-503/tctest-91766-28422 kill-server`.
- Fix: pass `TMUX_TMPDIR="${TMUX_TMPDIR-}"` through `env -i`, or set `TMUX_DASH_TMUX_ARGS="-S <absolute socket path> -f /dev/null"` (the deferred T6 minor already suggested `-f /dev/null`). Then run the case once under `zsh tools/tests/all.zsh`.

**I2. `agent-board restore again` stops working after one tick, so the retry that INSTALL.md:142 promises does not exist** (restore.py:579-586, 531-537, 236)
- What is wrong: once `do_restore` marks the snapshot restored, the next tick (≤60 s later) takes a fresh snapshot of the current boot. `save` accepts it because the old one is restored, and it replaces the old one. A project whose restore failed is not running, so it drops out of the snapshot for good.
- `again` run after that only clears `restored` on a current-boot snapshot. `old.boot < boot` is false, so nothing restores, and the next tick overwrites it anyway.
- `test_again_clears_restored` (test_restore_tick.py:457) checks only the flag, never that a later tick restores.
- Fix: in `do_restore`, also write `restore/last-restore.json` (the snapshot that was restored). `again` copies it back to `snapshot.json` with `restored: false`. The next tick then restores it: live projects show as `already open` and failed ones are retried. Add a test: restore, tick (new snapshot saved), `again`, tick → `/dev` is called for the failed project.

**I3. Projects the user closed on purpose come back after a reboot** (restore.py:233-234, 531-533; spec §1 "never replace a snapshot with one that has zero projects", §2.3 "No server running → nothing written")
- What is wrong: if the user closes every project, or runs `kill-server`, every later tick keeps the last snapshot that had projects in it. The next reboot, days later, recreates all of them and resumes their leads.
- The same thing happens with `schedule uninstall`, a reboot, then `schedule install` later: RunAtLoad's first tick finds an older-boot unrestored snapshot and replays a stale one. The brief's focus names this ("never recreate something the user closed on purpose").
- This is a spec issue, not a deviation: the guard exists so that a tick during shutdown, while sessions are dying, does not wipe the snapshot.
- Suggested fix that keeps that protection: a same-boot "empty" observation (zero projects, or no server) is written only when it repeats on two ticks at least 50 s apart (a marker file holds the first one's time; a shutdown does not span two ticks). Also have `schedule uninstall` mark the snapshot restored.
- The lead or user should decide whether this lands before merge. If not, INSTALL.md should state the behaviour.

### Minor

- **M1. A small drift in `kern.boottime` can start a spurious restore** (restore.py:528, 236). macOS shifts `kern.boottime` when the calendar clock is stepped. This boot already moved by 24 ms (spec probe usec 269307, today 245407). An upward step across a second boundary gives `old.boot < boot`, and every fresh snapshot has `restored: false`. A restore then runs within the same boot. Live projects show `already open`, but a project closed in the last ≤60 s is reopened, and `awake on` re-runs. Fix: treat a boot as new only when `boot - old.boot > 60`, in both `tick` and `save`.
- **M2. The tmux server started under launchd has no `LANG`** (restore_schedule.py:61-62). The plist sets only PATH, and no shell rc file here exports LANG/LC_* (checked `~/.zshenv`, `~/.zprofile`, `~/.zshrc`). Every pane on that server, including later workers, then runs without a locale until the next reboot. Fix: add `LANG=en_US.UTF-8` to the plist environment. Check at the reboot gate with `~/.local/bin/tmux -L agent-board show-environment -g LANG`.
- **M3. Stale pid files after a reboot** (pre-existing, outside this diff). `tmux-dash`'s `alive()` (`kill -0` on `~/.local/state/tmux-dash/server.pid`) and `_report`'s `bridge.pid` check (restore.py:460-466) both read pid files that survive a reboot. A reused pid would leave the board unstarted (logged as `dash start ok`) or post the report before the bridge is up. Follow-up: check the command name as well, as `_aw_alive` does.
- **M4. INSTALL.md:143 says FileVault stops every reboot at the unlock screen.** The spec's Known limit says the MDM path uses an authenticated restart that logs the user in, and only a panic or power loss stops at the unlock screen. Align the doc with the spec.
- **M5. `snapshot()` swallows every exception with no log** (restore.py:143-146). A programming error looks like "tmux down", and the snapshot silently freezes at its last good value. Ledger minor T1; log one line per hour, the way `_warn_boot` does.

## Ledger triage

| Ledger line | Before merge? |
|---|---|
| T5 status() unguarded restore import/call | can wait |
| T5 vacuous assertIn("loaded") | can wait |
| T5 main() exit-1 untested | can wait |
| T1 `_discord` does not check the token follows `--channels` | can wait (the orchestrator builds that argv) |
| T1 `.next` test passes with a direct write | can wait |
| T1 snapshot catch-all hides programming errors | can wait; cheap fix in M5 |
| T5 install from a worktree; INSTALL has no "main checkout" note | can wait (`~/.local/bin/agent-board` exists here); one doc line is cheap |
| T3 INSTALL.md:253 still shows `send … <file>… [-m <text>]` | fix before merge (one line; the docs contradict the new text-only send) |
| T2 dispatch test only greps; negative grep passes on an empty capture | can wait (the e2e covers it) |
| T4 already-open project makes awake report "no lead pid" | can wait |
| T4 group-name entry with no same-named session gives a false "session name" failure | can wait (logged and reported, not silent) |
| T6 second-tick check passes on a crash | can wait |
| T6 `env -i` case runs against a live scratch server | fix before merge, as part of I1 |
| T6 launchd case skip is silent | can wait |
| Ruling R1 restore dir = agent_base()/restore | agree |
| Ruling R2 no DISCORD_STATE_DIR (orchestrator derives it) | agree, checked at claude-orchestrator:34-56 |
| Ruling R3 --model only when non-null | agree |
| Ruling: worktree recreated at f702497 | no effect on the code |
| Ruling: carry the previous lead.session_id forward within the same boot | agree (STATUS_TTL 45 s against the 15 s heartbeat) |
| Ruling: Task 3 widened to the tmux-ctl header | agree |
| Ruling: sessions keyed by the snapshot name | agree |

## Evidence checks

1. Fixture origin
   - The `test_restore.py` tmux, ps and agent-status fixtures are hand-written.
   - The sysctl line was captured from the real probe (plan Global Constraints).
   - A live read-only `snapshot --print` was run twice (T6 report and its review) and parsed real data. That is acceptable, but it is a one-off, not a repeatable test.
   - The e2e seed snapshot is hand-written in the real `snapshot()` shape.
2. Artefact under test
   - Unit tests load the real `board/restore.py` and `restore_schedule.py`.
   - The e2e runs the real `restore.py tick`, `bin/dev`, tmux and `/sbin/route`. Only ctl and the orchestrator are stubs, and the stub ctl is the documented seam.
   - Real external calls: `test_real_launchctl_runs` and `test_real_boot_time_under_the_launchd_environment`.
   - Real `tmux-ctl awake on` from launchd and real `discord bridge start` are not run by any test. They are left to the Task 7 reboot gate.
3. User-experienced check: none in this diff (no UI).
4. State
   - All zsh tests run on fresh scratch servers.
   - The `env -i` case met a live server when run standalone, and broke under `all.zsh`'s per-job `TMUX_TMPDIR` (I1).
   - No test starts the agent-board server from a dead state under the launchd environment. That is left to the reboot gate.
   - The `env -i` case hard-codes `$HOME/.local/bin` in PATH, which mirrors the plist.
5. Universal claims: the only one is "every background child redirects stdout". It rests on the full grep of `tmux-dev-layout` (1 background call, line 85), `tmux-overseer` (none) and awake.zsh (2 calls, lines 46 and 121).
6. Merge-gate items a human runs (Task 7):
   - [ ] Real reboot as in spec §Testing.
   - [ ] `~/.local/bin/tmux -L agent-board show-environment -g LANG` (M2).
   - [ ] `tail ~/.local/state/agent-board/restore/restore.log` shows `board: dash start ok`, and `agent-board dash status` shows the server running (M3).
   - [ ] `ps -o args= -p $(~/.local/bin/tmux -L agent-board display -p '#{pid}')` shows `-f …/config/tmux.conf`.
7. Runbook preconditions: INSTALL "Restore after a reboot" has no unresolved "must exist" claim. Install needs `~/.local/bin/agent-board` or the CLI beside the module (`worktree_safety.agent_board_path` raises otherwise, and the error says so).
8. Endpoint trust: not applicable.

## Assessment

**Ready to merge?** With fixes.

**Reasoning:** The restore flow is sound under launchd: PATH, cwd, process groups, the dedicated server config and per-project isolation all hold. I1 must be fixed because `all.zsh` is red on this branch and the test leaks a server that loads `~/.tmux.conf`. I2 should be fixed because the documented retry does not work. I3 needs a decision from the lead or user, because the spec's guard brings back projects that were closed on purpose.
