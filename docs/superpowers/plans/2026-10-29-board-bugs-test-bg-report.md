# test_bg.zsh flake: report

## Root cause

The spec's first cause: the early-TERM bug in `bin/tmux-ctl run`. The start record (`exit: null`) was written at line 270 and the interrupt trap that finalises it (exit 143, summary `interrupted`) was installed only on the next line. Until then the earlier trap (`unlock_win; exit 143`) was active, so a TERM landing during or right after the start-record append left the record at `exit: null`: a stuck run in the Activity drawer.

Deciding evidence:
- Under 2×ncpu load the original test failed 1 of 5 reproduction runs (`interrupted exit 143`, `interrupted summary`, `no stuck records` together, the spec's signature). The six instrumented reruns that were meant to capture the record all passed, so no record was captured from a loaded failure.
- Unloaded, deterministic probe (scratch script, TERM sent the moment the `sleep 30` start record appears, 15 trials, original `bin/tmux-ctl`): 13 of 15 trials ended with the record at `exit: null` (`[null]`), two with `[null,143]`. That is the captured `exit: null` record after an early TERM.
- The test's own 5 s `tt_wait` polls every 0.25 s and so lands TERM in that window under load.

Second cause, found after review (a flake in `test_bg.zsh`'s first lines, not the early-TERM window): first use of the hidden bg session. `ensure_bg` returns once the session and windows exist; `pick_win` then asks `pane_idle` about a pane whose shell is still starting, gets "busy", and opens a lane `tests·claude`. That breaks `bg windows` (expects exactly `shell tests `) and `read bg`. Evidence: the failing unloaded run printed `tmux-ctl: 'tests' is busy — using lane tests·claude` as its very first line, on a fresh server, so no earlier step can have left a run unsettled. Reproduced on scratch servers with the real `bin/tmux-ctl` under 48 `yes` and 3 parallel first-use trials: 3 busy in about 24 trials (about 5%; none in 12 serial trials under 24 `yes`). The exact `pane_current_command` at the decision was not captured (the debug-instrumented runs, 54 trials, did not hit it), so the transient-startup reading is an inference; what is certain is that the pane is `zsh` with no child a few ms later.

## Change

- `bin/tmux-ctl` (`run`): the interrupt trap is now installed before `run_record null`, and it releases the record lock first (`RLOCKD`), because the TERM can land inside `append_capped`, and the handler's own `run_record` would otherwise wait on that lock.
- `tools/tests/test_bg.zsh`: the interrupted-run block waits on conditions with a 30 s cap (one loaded iteration of the file took 51 to 103 s, so no single step needs more), every wait is failure-checked under its own name (start record, `sleep` running in the pane, exit 143 written, pane idle). New step: six trials of TERM sent as soon as the start record lands, each checking exit 143, summary `interrupted` and an idle pane.
- Test first: with the original `bin/tmux-ctl` the new step failed (9 FAILED in one run, 2 of 3 runs failing with the single-trial form); with the change, 3 of 3 unloaded runs pass. Mutation (revert the `bin/tmux-ctl` change) is the RED run above.

- `bin/tmux-ctl` (`ensure_bg`, `pick_win`): `ensure_bg` sets `BG_FRESH` when this call created the bg session; `pick_win` then waits up to 3 s (0.05 s steps, the same `is_idle`) for the base pane to reach a prompt before deciding. Panes that already existed get no wait, so a busy existing pane still goes to a lane at once. A caller that lost the creation race (it waits on `@tc_bg`) gets no wait either; not seen failing.
- `tools/tests/test_bg_fresh.zsh` (new, picked up by `run-all`): first use with a slow shell (`.zshrc` sleeps 1 s) must print the output, not mention busy, and leave exactly `shell tests `. Mutation: with the original `tmux-ctl` in place the 3 checks fail (3 FAILED); with the change they pass (3 of 3 runs). `test_bg.zsh` also gained the `bg_idle` checks and the bounded start-record poll from the review round.

## Load runs

Load: `2 * hw.ncpu` = 24 `yes > /dev/null` processes, PIDs saved, killed in a `trap`, checked gone with `ps -p` afterwards (none alive); the earlier loaded runs ran under `caffeinate -i` (the brief asks `-w <pid>`; the fix-round runs used `caffeinate -w $$`), and the failing reproduction iteration did keep its full output and `ps` snapshot (`run4.out`, `run4.ps`). Runs are `zsh tools/tests/test_bg.zsh` directly.

Step 0 (one timed loaded iteration, original test): pass, 81.0 s.

Reproduction on the original code (tally):

    pass 2026-10-29T02:43:50 102.7s
    pass 2026-10-29T02:45:04 73.6s
    pass 2026-10-29T02:46:45 101.1s
    fail 2026-10-29T02:47:52 66.3s   (interrupted exit 143, interrupted summary, no stuck records)

Final, fixed code (tally):

    pass 2026-10-29T03:09:19 56.3s
    pass 2026-10-29T03:10:15 55.9s
    pass 2026-10-29T03:11:12 56.7s
    pass 2026-10-29T03:12:02 50.7s
    pass 2026-10-29T03:13:00 57.6s

5 of 5 pass.

`run-all.zsh` through `tmux-ctl run -t 900 tests`: the first run gave `rc=1` with one failure, `FAIL - send returns fast` (a pre-existing `< 2 s` timing assertion, line 79 of `test_bg.zsh`, on code this change does not touch), while the machine's load average was 12 to 26 from other agents' work. The rerun gave `rc=0`, and `grep -c FAIL` on its output was 1 (the passing test name `zsh FAILED line beats unittest OK`).

Fix round (both files per iteration, 48 `yes` = 4×ncpu, `caffeinate -w`, PIDs trapped and checked gone):
pass 2026-10-29 12:20:41 66s rc=0 run1
pass 2026-10-29 12:21:46 65s rc=0 run2
Unloaded (`test_bg.zsh` then `test_bg_fresh.zsh`): 3 of 3 rc=0 (44 s each). `zsh tools/tests/run-all.zsh; echo rc=$?` -> `rc=0`, `grep -c FAIL` -> 1 (the passing test name).
