# Task 1 report: tmux-ctl `run` empty-output flake

## Repro

- Instrumented copy of `bin/tmux-ctl` (scratchpad `tmux-ctl-instr`, not committed). In the `run)` branch it records the `.rc` mtime (`zstat`, taken just before `.rc` is read and removed), the time `.rc` was seen, and the time of the capture. It saves the raw `capture-pane -p -J -S $(( start - hist )) | awk start-marker` output (before `trim | sed '$d'`, shown with `cat -v`) to `dump-$id.txt`. It deletes the dump when the final `out` is non-empty. `out` is derived from the same raw capture, so the dump is exactly what `trim | sed '$d'` saw.
- Harness: `tt_setup claude shell` (isolated scratch tmux server from `tools/tests/lib.zsh`), then 240 × `$C run tests "echo A$i"` with `TC_CTL` pointing at the instrumented copy. A run counts as bad unless its first output line is exactly `A$i`.
- Load: `while :; do TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh; done &` in the worktree. Batch 2 ran two such loops. Each loop was killed by PID, along with its current `run-all` child via `pgrep -P`. The machine also carried other agents' test loops, which made the load heavier than my own loops alone.
- Batch 1 (discarded): the dump code used `cat -A`, which macOS `cat` lacks, so all 240 runs were bad because of my instrumentation. The result is void and I fixed it to `cat -v`.

| Batch | Load | Empty/wrong outputs |
|---|---|---|
| 1b | one run-all loop (load avg 6.8 at start, 49 and 1-min peaks seen in other agents' runs) | 0 / 240 |
| 2 | two parallel run-all loops (load avg 4.6 at start) | 0 / 240 |

## Evidence

- No dump files were left in either batch (`ls b1 b2` empty), so there is no failing iteration and no raw capture to quote.
- Tally lines: `TALLY empty/wrong=0 total=240` (batch 1b) and `TALLY empty/wrong=0 total=240` (batch 2): 0 of 480 loaded runs.
- The known base rate is about 1 in 120, so 480 runs would have expected about 4 hits. The chance of seeing none by luck at that rate is about 2%. This suggests the trigger needs a condition my loads did not create. It is not proof that the flake is gone.

## Cause

Not reproduced. The hypothesis (`_done` writes `.rc` before the last output line reaches the capture, so `sed '$d'` drops the real output) is neither confirmed nor refuted.

Facts from reading `bin/tmux-ctl`, which are code reading, not measurement:
- `_done` is typed on the same line as the command, so `.rc` can only appear after the command's output has been printed to the pane. The output line is therefore in the pane before `.rc` exists. What the capture can miss is the redrawn prompt, not the output.
- `sed '$d'` always removes the last non-blank captured line. If the prompt has not been redrawn when the capture runs (slow precmd or a slow prompt theme), the last line is the real output, and it is dropped. For a one-line output this gives exactly the empty result seen. That is a different mechanism from "output not yet captured", and the end-marker design covers it too, because it stops depending on the prompt line.
- This reading is unproven, because no failing capture was observed.

## Implication for Task 2

An end marker plus a bounded wait covers both candidate mechanisms: the output being late, and the prompt being late. Cut the output between the start marker and the end marker and stop dropping "the last line". Then the result no longer depends on whether the prompt has been redrawn. The bounded wait should poll the capture until the end marker line appears (or time out), after `.rc` is seen. Because the flake is not reproduced, Task 3 should be the real check: loop the new `run` under heavy load, count empty outputs, and keep the instrumented dump idea (save the raw capture when the output is empty) so a recurrence leaves evidence.

### Skill findings

- systematic-debugging: Phase 1 says to reproduce consistently, but the brief's time box (480 runs) forces a stop at "not reproduced". The skill gives no guidance for that case, so I documented what was tried and stopped instead of guessing at a fix.
- Platform gotcha for instrumentation scripts on macOS: BSD `cat` has no `-A` (use `cat -v`). Capture the instrumentation's stderr separately so a bug in it cannot pollute the measured output.
