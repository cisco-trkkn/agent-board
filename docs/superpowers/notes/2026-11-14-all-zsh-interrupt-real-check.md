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
