# all.zsh interrupt: real-state check (2026-11-14)

Task 2 of `docs/superpowers/plans/2026-11-14-all-zsh-interrupt-sweep.md`. The real suite ran from the worktree `queue/all-zsh-interrupt-sweep`, was interrupted with C-c, and the scratch tmux servers under its socket root were checked.

## Rulings

- The spec's `grep -c '[t]mux.*tc-all'` count is replaced by the socket check (`find <sockroot> -type s`, `tmux -S <sock> has-session`, and `lsof -U`). The brief's premise is that a `-L` server's command line does not contain the run dir path, so the grep would read 0 both during and after the run. Observed during the run: the test server `tmux -L tctest-57873-26142 ... -c /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.WALjjz/tmp/74/tctest.BRq5dD` does contain the run dir path, so the grep would have matched during the run. The socket check was used anyway, as the brief says.
- The socket root is `/tmp/tcs.GdA9UK`, not `<rundir>/tmp`, per Task 1's ruling. The root was identified as the `mktemp -d /tmp/tcs.XXXXXX` of the run's own `all.zsh` (PID 57469): its children carry `TMUX_TMPDIR=/tmp/tcs.GdA9UK/<job>`. The brief's selector `ls -dt /tmp/tcs.* | head -1` picked a different, short-lived root, `/tmp/tcs.nVDgpS`, which belonged to another process and was gone by the next check. That selector was not used for the count.

## Run

- Start: `tmux-ctl send -C /Users/francisco.ruiz/agent-board/.claude/worktrees/all-zsh-interrupt-sweep tests "zsh tools/tests/all.zsh"` at 21:06:10 (epoch 1794708370). The command printed nothing, rc=0. The window was `tests` (in `tmux-ctl list`: `0  tests  [busy]  ... (bg)`).
- The run's process: `57469 22355 zsh tools/tests/all.zsh`, where 22355 is the `tests` window's shell (`-zsh`, parent `12354`, the `agent-board` tmux server).

## Socket counts

- First check, 21:06:25 (epoch about 1794708385): `find /tmp/tcs.GdA9UK -type s | wc -l` gave `1`, so the first socket was seen about 15 s after the start. The poll was a single check at that time, not a 5 s loop, so the time of the first socket is an upper bound.
- Check at 21:07:01 (before the interrupt): `find /tmp/tcs.GdA9UK -type s | wc -l` gave `1`, with the socket `/tmp/tcs.GdA9UK/74/tmux-503/tctest-57873-26142`. Recorded in `$TMPDIR/sweep-check/socks`.
- The count was 1, so the 120 s retry was not needed.

## Interrupt

- At 21:07:08: `tmux-ctl keys tests C-c` (rc=0).
- At 21:07:19, `tmux-ctl read tests 20` showed the runner's line verbatim: `^Call.zsh: interrupted, run dir /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.WALjjz`. The line is cut at the start by the terminal's `^C` echo; the text is `all.zsh: interrupted, run dir /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.WALjjz`.
- Caveat: that read was taken at 21:07:19, 11 s after the C-c, so it does not prove the sweep finished within 10 s.

## After the interrupt

- At 21:07:23 (15 s after the C-c), the socket check over the counted list:

```
gone /tmp/tcs.GdA9UK/74/tmux-503/tctest-57873-26142
```

- `lsof -U 2>/dev/null | grep -c '/tmp/tcs.GdA9UK'` gave `0`.
- `find /tmp/tcs.GdA9UK -type s 2>/dev/null | wc -l` gave `0`. The socket root directory itself was gone (`ls -la /tmp/tcs.GdA9UK` → `No such file or directory`).
- `ps -axo pid,ppid,command | grep -E 'tctest-57873|GdA9UK'` gave no output. `ps -p 57469 60789` listed only the header, so the run's `all.zsh` processes were gone.
- The 10 s criterion is not strictly shown, because the first check after the C-c was at 21:07:23 (15 s).

## Result

- Every counted socket (1) fails `has-session`. No `tmux` process for the counted socket remains, and the `lsof` count is 0.
- The runner printed `all.zsh: interrupted, run dir /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.WALjjz`.
- No server was ALIVE after the interrupt, so no stop was needed.

## Positive control (fix round 1)

The first pass checked only `has-session` and `lsof` after the run had deleted its socket root, so "gone" could not be told apart from "never alive". This section re-runs the check with a baseline of server PIDs taken during the run, and records each PID's state after the interrupt. Scratch files are in `$TMPDIR/sweep-check2/`.

- Start: `tmux-ctl send -C /Users/francisco.ruiz/agent-board/.claude/worktrees/all-zsh-interrupt-sweep tests "zsh tools/tests/all.zsh"` at epoch 1794708600, rc=0 (no output). `tmux-ctl list` showed `0  tests  [busy]  cmd=zsh  /Users/francisco.ruiz/agent-board/.claude/worktrees/all-zsh-interrupt-sweep  (bg)`.
- Socket root from the run's own processes: `ps eww -axo pid=,command= | grep 'TMUX_TMPDIR=/tmp/tcs\.'` showed `TMUX_TMPDIR=/tmp/tcs.9qVSXO/<job>` on the job processes (for example pid 70942, `board.tests.test_metrics_backfill`, `TMUX_TMPDIR=/tmp/tcs.9qVSXO/17`). The run's `all.zsh` is pid 70367 (parent 22355, the `tests` window shell). A parent walk from each of the 23 processes carrying that root reached 70367 for 21 of them; the other 2 did not resolve in the walk and were not examined further. The other root in `ps` output, `/tmp/tcs.8OeLaq`, belongs to another session's run and was not used.
- Run dir (from the interrupt line below): `tc-all.yjkg00`.
- Baseline poll, every 5 s, up to 120 s: `lsof -U -a -c tmux 2>/dev/null | awk -v r="/tmp/tcs.9qVSXO" 'index($0, r) {print $2}' | sort -u`, first poll at epoch 1794708641 (41 s after the start). Output: `t=0s epoch=1794708641 pids=[71039 ]`. The loop ended at the first poll because a PID was found.
- Baseline PID count: 1 (pid 71039), recorded to `$TMPDIR/sweep-check2/baseline_pids.txt`.
- `ps -o pid=,command= -p 71039` at baseline: `71039 /Users/francisco.ruiz/.local/bin/tmux -L tctest-70950-17223 -f /dev/null new-session -d -s tt -n claude -c /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.yjkg00/tmp/74/tctest.EzxcJG -x 200 -y 50`.
- `lsof -U -a -p 71039 | grep -F /tmp/tcs.9qVSXO` at baseline: `tmux    71039 francisco.ruiz    6u  unix 0x5fcba17413494285      0t0      /private/tmp/tcs.9qVSXO/74/tmux-503/tctest-70950-17223`. This PID is the server of the `zsh/test_ctl_awake.zsh` job (pid 70950, in the run's tree).
- Interrupt: `tmux-ctl keys tests C-c` at epoch 1794708652, rc=0.
- After checks, `ps -o pid= -p 71039` with ALIVE/gone. The first check was labelled "+3s" in the loop, but it ran at epoch 1794708657, so it is +5 s; the actual offsets are used below.
  - `+5s epoch=1794708657 pid=71039 gone`
  - `+6s epoch=1794708658 pid=71039 gone`
  - `+10s epoch=1794708662 pid=71039 gone`
- `ps -o pid=,command= -p 70367,70950,71039` after the interrupt: no output, rc=1.
- `lsof -U 2>/dev/null | grep -c '/tmp/tcs.9qVSXO'`: `0`. `ls -ld /tmp/tcs.9qVSXO`: `ls: /tmp/tcs.9qVSXO: No such file or directory`.
- `tmux-ctl read tests 25` after the interrupt showed the runner's line: `^Call.zsh: interrupted, run dir /private/var/folders/2p/brsv4hcx1wx5rv2_086ljvww0000gq/T/tc-all.yjkg00` (the `^C` echo cuts the start of `all.zsh:`).
- The run dir `tc-all.yjkg00` has no `*.res` file, so no job wrote its result. The `zsh/test_ctl_awake.zsh.log` ends with `error connecting to /private/tmp/tcs.9qVSXO/74/tmux-503/tctest-70950-17223 (No such file or directory)` and `no such file or directory: .../ttawake.RGB34Z/batt.cur`, so the job was still running when its socket went away.

Result: the baseline had 1 server PID. At 5 s, 6 s and 10 s after the C-c it was gone; the sweep stopped it within the 10 s limit. The socket root is removed and the `lsof` count is 0.

Caveat: the baseline was taken 11 s before the C-c. The `test_ctl_awake.zsh` process (pid 70950) was not sampled as alive at the C-c itself. Its evidence is the missing `.res` and the log errors above, not a direct process check.
