# Scoped re-review: final fix wave (`fc0e59c..1835b00`)

Reviewer: finalrev. Read-only. Scope: the findings below and the fix diff. I read the production and docs diff in full, the test diff by grep, and ran three read-only probes (named where used). I did not rerun the suites.

### Finding Verdicts

- **C1, heartbeat PATH has no node; migrate guard only checks "loaded"** — ADDRESSED. `launchd.js:70-74` puts `dirname(process.execPath)` first, deduplicated. `wake.js:55-66` stamps `<engine dir>/wake.last` on every pass, also when the pass throws. `launchd.js:106-120` and `:206-209`: migrate refuses (exit 2) unless the stamp parses, shows rc 0 and its mtime is newer than the plist's. A heartbeat that dies in `tmux-ctl` before node starts writes no stamp, so the guard refuses: the C1 case is closed. Report quotes the real `env -i` run with the new PATH (rc 0, stamp `rc 0`) and the old PATH (rc 2).
- **I1, a launchd wake reaches the default socket** — ADDRESSED for the launchd-reachable paths. `schedule.js:73-78` `tmuxArgsFromEnv` follows `tc_tmux_resolve`'s order (override, `$TMUX`'s socket, `-L <socket> -f config/tmux.conf`); `wake.js:54` uses it, and `run-now` goes through `wake.run`, so both are covered. The plist carries `AGENT_BOARD_TMUX_SOCKET` (`launchd.js:74`). The env-only test asserts the window on the scratch socket and no default-socket server. See "Points to judge" for the running-engine path.
- **I2, failed bootout recorded as a removal** — ADDRESSED. `launchd.js:176-178` throws `still loaded` before the unlink; `:237-241` prints `cannot migrate <label>: still loaded`, keeps the plist, leaves the step not done, exit 1. Test `engine_migrate.test.js:276-288`. One leftover, below (N1).
- **I3, `rm -r` forms missed** — ADDRESSED. Probe (`hold.match`, default rules): held: `rm -rf $HOME/foo`, `rm -rf "$HOME/foo"`, `rm -r "/tmp/a b"`, `rm -f -r /tmp/x`, `rm -rf ${TMPDIR}x`, `rm -v -f -R ../x`, `rm --force --recursive /tmp/x`, a backslash-newline path. Not held, as they should be: `rm -rf node_modules`, `rm -rf "./a b"`, `rm -rf dist && echo ok`, `rm -f a.txt`, `rm -rf build; ls /tmp`. The new pattern (`hold.js:19`) has no ambiguous repetition.
- **I5, finished runs rescanned every tick** — ADDRESSED. `schedule.js:193-213`: only done steps without `ran` are selected; the step is finished again with `ran: true` after the event; a crash between the two is healed without a second event. `wake.js:28` uses the same filter. The test spies `prepare` for a second tick.
- **ENGINE_DIR fail-open** — ADDRESSED. `hold.js:137, 147-148`. Probe: `ENGINE_JOB=J`, no `ENGINE_DIR`: `git push` returns deny `engine hold: ENGINE_DIR not set for job J`; `ls` returns none. Denying only matched calls is the right scope: an unmatched call never needed the database, so nothing risky passes.
- **I4 docs part (INSTALL preconditions, G1-G4)** — ADDRESSED, with one wrong command (N2). Both preconditions and all four gates are in `docs/INSTALL.md:226-238`, G1 and G2 updated for the new behaviour.
- **Note minors ("may explain"; stale status files)** — ADDRESSED. Real-run note lines 88 and 92.

### Points to judge

- **`AGENT_BOARD_TMUX_CONF` seam.** The production default is `<repo>/config/tmux.conf` resolved from the module's own path (`schedule.js:77`), the same file `_tc_bins.zsh:47` passes. `AGENT_BOARD_REPO`, which that config needs, is exported by `tmux-ctl` itself when it sources `_tc_bins.zsh` outside tmux (`bin/tmux-ctl:93`, `_tc_bins.zsh:48`) and is inherited by node and tmux. So a server the wake starts gets the same config. Two differences remain, both minor: the JS runs `tmux` from PATH where zsh prefers `~/.local/bin/tmux` (same binary with the plist PATH on this machine), and a server born from launchd has launchd's environment as its global one (see out-of-scope).
- **Every launchd-reachable path.** Wake and run-now: yes. Schedule rows in a running engine still use the old rule (`cli.js:108`, `TMUX_DASH_TMUX_ARGS` only, with `TMUX` blanked in `schedule.js:79`). That path is not started by launchd, and it works on this machine because the live server's global environment carries `TMUX_DASH_TMUX_ARGS` (checked: `tmux -L agent-board show-environment -g`), the same thing every part 2 step already relies on. Not a blocker; N3.
- **Migrate guard.** Newer-than-plist and rc 0 are both enforced (`launchd.js:114-120`). A reinstall invalidates an older stamp until the next beat. One limit: N4.

### New Breakage in the Fix Diff

No Critical or Important breakage.

- **N1 (Minor), `launchd.js:228-241`.** When the bootout fails, the schedule row was already added. The message says `cannot migrate <label>`, but the job now has two runners (the loaded plist and the row) until someone acts. It is loud (exit 1) and G2 catches it; a rerun after a manual `launchctl bootout` prints `already migrated` and removes the plist. Better: remove the row again on this failure, or say `row added, plist still loaded: bootout it and rerun`. The test does not assert the row either way. For the lead's Finishing: treat this line as "bootout by hand, rerun migrate", not as "nothing changed".
- **N2 (Minor), `docs/INSTALL.md:228`.** The node precondition check says `env -i HOME=$HOME PATH=<that path> tmux-ctl engine status` exits 0. Probe with the new PATH and a scratch `TC_ENGINE_DIR`: `engine: no project: run it from a tmux session or pass --project`, rc 2. The fix report notes the same. The command needs `--project <name>` (any name: it then prints `no specs`, rc 0).
- **N3 (Minor), `cli.js:108`.** The running engine should use `schedule.tmuxArgsFromEnv` too, so one rule covers all three paths.
- **N4 (Minor), `wake.js:56`.** The stamp does not say who ran the pass: a `tmux-ctl engine wake` or `schedule run-now` typed in a pane after install also satisfies the guard. In Finishing, do not run either between `wake install` and `schedule migrate`; G1's `launchctl print … last exit code = 0` is the check that is launchd's own.
- **N5 (Minor), `hold.js:59-88`.** Any `rm -r` word with `$` is now held, inside the worktree or not (`rm -rf "$d"`). This is the decided trade (one approval); expect more parks from workers that clean up through a variable.

### Out-of-Scope Observations

- A dedicated server started by a 03:30 wake after a reboot has launchd's environment as its global one (no `TMUX_DASH_TMUX_ARGS`, a short PATH). I did not check how `dev` or the restore job treat a server that already exists with only `<project>-bg` in it. Worth one manual look before relying on overnight runs after a reboot.
- launchd itself has still not run the heartbeat; G1-G4 are owed on the live machine, as the fix report says.

### Verdict

**Fix round:** All findings addressed, no new Critical/Important breakage. **Ready to merge.** N2 is a one-line doc fix worth making before the lead follows INSTALL; N1 and N4 are things to know while running Finishing; N3 and N5 are follow-ups.
