# Report: relay respawns with an explicit login shell

## Cause (confirmed)
`relay.respawn()` ran `tmux respawn-pane -k -t <pane> -c <root>` with no command. tmux then re-runs the pane's
original start command. Live pane `%138`: `tmux display -p -t %138 '#{pane_start_command}'` prints
`"/Users/francisco.ruiz/agent-board/bin/claude-orchestrator 'Read .../handoffs/2026-11-19-spec-c-task2-fix.md and continue from where the previous session lef…"`,
so every relay and every `restart_orchestrator` (both call `respawn()`) started a lead on that stale handoff.

## Fix (`board/relay.py`)
New `login_shell(tmux)`: the global `default-shell` (`show-options -gv default-shell`, accepted only if absolute),
else `$SHELL`, else `/bin/sh`. `respawn()` passes `<shell> -l` as the command, with send-keys unchanged after it.

## Tests
- New `RespawnCommandTest` in `board/tests/test_relay.py`:
  `test_respawn_pane_ends_with_the_tmux_default_shell_as_login_shell`,
  `test_falls_back_to_SHELL_then_bin_sh`, `test_send_keys_still_follow_respawn`.
- Updated exact-argv assertions: `test_relay.py` (`test_relay_respawns_and_writes_lineage`) and, outside the owned list
  but needed because it asserted the old argv, `board/tests/test_restart_orchestrator.py` (two assertions).
- RED seen first: 2 failures + 1 error on the new tests before the fix; 43 tests across test_relay,
  test_orchestrator_path, test_restart_orchestrator pass after.

## Real check (scratch server `-L relayprobe -f /dev/null`, launch_line patched to `true`, server killed afterwards)
    before: "sleep 1000" | sleep
    after: /bin/zsh -l | zsh
`tmux -L relayprobe ls` afterwards: "no server running".

## Verdicts
- `python3 -m unittest discover -s board/tests`: `Ran 1902 tests in 695.053s` / `OK` (rc=0).
- `zsh tools/tests/all.zsh`: verdict `FAIL 2/172: zsh/test_all_runner.zsh, zsh/test_discord_always_on.zsh`, `rc=1`, run while another
  worktree's all.zsh shared the machine (job `board/test_worktree_safety_recent` took 447s). The failing lines were
  `interrupt: a job ignoring INT and TERM is KILLed, runner exits 130 in under 8 s` and `typed in the gap: logged as not
  quiet`, both timing checks that do not touch relay. Rerun alone: `zsh tools/tests/test_all_runner.zsh` ends ALL PASS
  with 0 FAIL lines, and `zsh tools/tests/test_discord_always_on.zsh` ends ALL PASS with 0 FAIL lines. So the suite is
  not clean in one run: 170/172 plus those two passing on rerun. Not a green single all.zsh verdict.

Assumption: `show-options` is used (not the `show` alias) because the existing fakes dispatch on that name.

Context learned:
- Gotchas: `respawn-pane` without a command re-runs the pane's stored start command; pass the shell explicitly (files: board/relay.py)
- Gotchas: the restart_orchestrator test `Fake` answers every `show-options` with `1`, so `login_shell` ignores non-absolute answers (files: board/relay.py, board/tests/test_restart_orchestrator.py)
