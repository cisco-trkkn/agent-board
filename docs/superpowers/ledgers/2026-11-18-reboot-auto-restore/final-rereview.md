# Final-review fix wave: scoped re-review (5df0198..15829c5)

## Finding Verdicts

- **I1: the e2e `env -i` case dropped TMUX_TMPDIR and leaked a server that loaded ~/.tmux.conf.** ADDRESSED.
  - tools/tests/test_restore_e2e.zsh:66-71 now passes `TMUX_TMPDIR` and `TC_REAL_TMUX_TMPDIR` through `env -i`.
  - It sets `TMUX_DASH_TMUX_ARGS="-S <scratch socket path> -f /dev/null"`. `-S` is an absolute path, so even a mistaken new server is created at the scratch socket, and `-f /dev/null` keeps it from loading `~/.tmux.conf`.
  - Evidence: the report shows a run with `TMUX_TMPDIR=/tmp/tcs.DfJ0dq` ending ALL PASS with rc=0 and no stray socket.
  - The earlier leak (pid 92687) is gone (`ps -p 92687` returns nothing). Only its dead socket file is left.
- **I2: `restore again` stopped working after one tick.** ADDRESSED.
  - board/restore.py:412-415: `do_restore` writes `last-restore.json`.
  - board/restore.py:629-637: `again` replays that file with `boot` set to at most `boot_time() - 61`.
  - test_restore_tick.py: `test_again_after_a_later_tick_still_restores_the_failed_project` runs restore, then a fresh tick, then `again`, then a tick, and checks the failed project's `dev` is called again. The report names a mutation that makes this test fail.
- **I3: projects closed on purpose came back (judged against the lead's ruling).** ADDRESSED.
  - restore.py:530-547 and 576-584: a running server with zero projects replaces the snapshot only after two ticks at least 50 s apart, using the `zero_since` file. Any tick with projects, and any tick with the server down, restarts that clock.
  - restore.py:571-573: a server that is down never replaces the snapshot.
  - restore_schedule.py:101-125: `uninstall` marks the snapshot restored.
  - Tests: `test_zero_projects_replace_only_after_two_ticks_50s_apart` (with a mutation), `test_a_tick_with_projects_resets_the_zero_clock`, `test_server_down_never_replaces`, `test_uninstall_marks_the_snapshot_restored`.
  - A stale `zero_since` left from before a reboot cannot wipe an unrestored snapshot, because the restore branch (restore.py:565) runs before the zero branch.
- **M1: a small kern.boottime drift could start a restore.** ADDRESSED.
  - restore.py:234-238: `_newer_boot` requires a gap over 60 s. It is used in `save` (restore.py:251) and in `tick` (restore.py:565).
  - Tests: `test_boot_within_60s_counts_as_the_same_boot` and `test_boot_within_60s_does_not_restore`; a mutation setting BOOT_SLACK to 0 fails both.
- **M2: no LANG for the tmux server started under launchd.** ADDRESSED.
  - restore_schedule.py:62-63: the plist sets `LANG` to the installer's value, else `en_US.UTF-8`.
  - Asserted in `test_plist_keys`.
  - `_restore_project` copies `os.environ` into `dev`'s environment, so the tmux server inherits LANG.
- **M4: INSTALL said FileVault always stops at the unlock screen.** ADDRESSED. docs/INSTALL.md:144 now matches the spec's Known limit (the MDM path uses an authenticated restart; a panic or power loss waits for login).
- **M5: `snapshot()` swallowed errors with no log.** ADDRESSED.
  - restore.py:140-148 adds an `on_error` hook to `snapshot()`.
  - restore.py:567-568: `tick` logs `snapshot error: <type>: <msg>` at most once an hour (marker file `snapshot-warn`).
  - Tests: `test_unexpected_error_goes_to_on_error` and `test_snapshot_error_logged_once_per_hour`.
- **T3 leftover: INSTALL.md:253 showed the old `send` usage.** ADDRESSED. docs/INSTALL.md:254 now reads `send [--thread <key>] [<file>…] [-m <text>]`.

## New Breakage in the Fix Diff

None at Critical or Important. Two Minor:

- **Minor, restore.py:412-415:** `last-restore.json` is written directly, not through `.next` plus rename. A crash in the middle of the write leaves a truncated file. `load_file` then returns None and `again` falls back to clearing the flag, so the only loss is the replay.
- **Minor, restore.py:575-578:** the zero-project branch writes with `_write`, which skips `save`'s guards. If `boot_time()` failed inside `snapshot()` on that one tick (after `tick` had already read it), the stored snapshot gets `boot: null`. That is harmless: there are no projects to restore, and the next save replaces it.

## Out-of-Scope Observations

- By the lead's I3 ruling, a user who closes projects and then runs `kill-server` still gets those projects back at the next reboot (the server is down, so the snapshot is never replaced). The new INSTALL text states this ("a server that is down never replaces it").
- `_carry_session_ids` (restore.py:500-502, not touched by this diff) still compares boot times exactly. A clock-step drift only skips one carry-forward, which costs nothing.

## Verdict

**Fix round:** all findings addressed, with no new Critical or Important breakage.
- I re-ran no tests. The report names the covering tests and shows their output: 94 OK, the e2e ALL PASS both standalone and with TMUX_TMPDIR set, and the dev and send tests ALL PASS.
- I checked the claims against the diff, and the test base's sysctl seam returns BOOT_NEW (test_restore_tick.py:358-360).
- all.zsh is the lead's to read.
