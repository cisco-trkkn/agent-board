# Task 1 report: tmux-ctl `run` empty-output flake

## Repro

- Instrumented copy of `bin/tmux-ctl` (scratchpad `tmux-ctl-instr`, not committed). In the `run)` branch it records the `.rc` mtime (`zstat`, taken just before `.rc` is read and removed), the time `.rc` was seen, and the time of the capture. It saves the raw `capture-pane -p -J -S $(( start - hist )) | awk start-marker` output (before `trim | sed '$d'`, shown with `cat -v`) to `dump-$id.txt`. It deletes the dump when the final `out` is non-empty. `out` is derived from the same raw capture, so the dump is exactly what `trim | sed '$d'` saw.
- Harness: `tt_setup claude shell` (isolated scratch tmux server from `tools/tests/lib.zsh`), then 240 × `$C run tests "echo A$i"` with `TC_CTL` pointing at the instrumented copy. A run counts as bad unless its first output line is exactly `A$i`.
- Load: `while :; do TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh; done &` in the worktree. Batch 2 ran two such loops. Each loop was killed by PID, along with its current `run-all` child via `pgrep -P`. The machine also carried other agents' test loops, which made the load heavier than my own loops alone.
- Scratch pane: `tt_setup` (tools/tests/lib.zsh:13) starts tmux with `-f /dev/null`, so the pane runs the default shell `/bin/zsh` (interactive, 200x50) with the default zsh prompt. `~/.zshrc` and `~/.zshenv` define no `precmd`, `PROMPT` or `PS1` (checked by grep), so there was no slow precmd.
- Batch 1 (discarded): the dump code used `cat -A`, which macOS `cat` lacks, so all 240 runs were bad because of my instrumentation. The result is void and I fixed it to `cat -v`.

| Batch | Load | Empty/wrong outputs |
|---|---|---|
| 1b | one run-all loop; 1-minute load average 6.8 at start, peak 49 seen during the batch (other agents' loops included) | 0 / 240 |
| 2 | two parallel run-all loops; 1-minute load average 4.6 at start, 6.5 at the end | 0 / 240 |

## Evidence

- No dump files were left in either batch (`ls b1 b2` empty), so there is no failing iteration and no raw capture to quote.
- Tally lines: `TALLY empty/wrong=0 total=240` (batch 1b) and `TALLY empty/wrong=0 total=240` (batch 2): 0 of 480 loaded runs.
- The base rate of about 1 in 120 comes from the handoff `~/.claude/handoffs/2026-10-19-after-group-c.md` (line 12: "the residual 1/120 empty-output flake in `tools/tests/test_bg.zsh` under load") and the Group C Task 2 report (not re-read here). At that rate 480 runs would give about 4 hits. The chance of seeing none by luck at that rate is about 2%. This suggests the trigger needs a condition my loads did not create. It is not proof that the flake is gone.

## Cause

Not reproduced: 0 of 480 loaded runs (240 + 240) gave an empty output. The hypothesis (`_done` writes `.rc` before the last output line is in the capture, so `sed '$d'` drops the real output) is neither confirmed nor refuted.

Candidate mechanisms, from reading `bin/tmux-ctl` (code reading, not measurement; none was observed failing):
1. Late output in the capture. The typed line runs the command and then `_done`, so the bytes are ordered in the pty. That order is not guaranteed in tmux's grid: the bytes sit in the pty buffer until the tmux server reads and parses them, and `_done` (bin/tmux-ctl:275-277) writes `.rc` without knowing the grid's state. `capture-pane` goes through the same server event loop, so under load it can run before the last pty read is drained. The last output line is then missing, and `sed '$d'` removes a real line (or the only one).
2. Late prompt. If the shell prompt has not been redrawn when the capture runs, the last captured line is real output, and `sed '$d'` drops it. For a one-line output the result is empty.
3. Start marker not found (unexamined, same empty result). If `capture-pane -S $(( start - hist )) | awk '$0==m'` (bin/tmux-ctl:235-236, 264-265) never matches the start marker line, `out` is empty. Possible reasons: the history limit trims scrollback so the offset drifts, `-J` joins a wrapped line, or the start marker has not rendered yet. I did not test this.

Mechanisms 1 and 2 stay open. Mechanism 3 was not examined.

## Implication for Task 2

The planned end marker is printed after `_done`, through the same pty. If the marker substring is in the capture, all earlier output is in it too. That is why waiting for it covers mechanisms 1 and 2, and it stops depending on whether the prompt was redrawn. Test for the "marker substring", not a "marker line": the marker can share a line with unterminated output such as `printf x`. Cut the output between the start marker and the marker substring.

Limits:
- If the marker has not appeared after the 3 s bound, the old `sed '$d'` fallback runs, and the flake can still happen there.
- Mechanism 3 (start marker not found) is not covered by the end marker. Task 3 should keep the raw capture before the awk filter, and save it whenever the output is empty, so a recurrence shows which mechanism it was.
- Because the flake was not reproduced, Task 3 is the real check: loop the new `run` under heavy load and count empty outputs.

### Skill findings

- systematic-debugging: Phase 1 says to reproduce consistently, but the brief's time box (480 runs) forces a stop at "not reproduced". The skill gives no guidance for that case, so I documented what was tried and stopped instead of guessing at a fix.
- Platform gotcha for instrumentation scripts on macOS: BSD `cat` has no `-A` (use `cat -v`). Capture the instrumentation's stderr separately so a bug in it cannot pollute the measured output.
