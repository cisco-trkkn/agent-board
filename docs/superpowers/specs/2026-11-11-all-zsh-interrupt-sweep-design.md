# all.zsh interrupt: drop the no-op INT, sweep scratch tmux servers

Date: 2026-11-11 · Depends on: the fast-test-suite spec (2026-11-10-fast-test-suite-design.md) being merged, because it adds `tools/tests/all.zsh`.

## Problem

1. On an interrupt, `killjobs` in `tools/tests/all.zsh` sends INT, then TERM, waits up to 3 s for the job groups to end, then sends KILL. The INT step does nothing:
   - Jobs are started with `&` from a non-interactive zsh, so they inherit SIGINT as ignored, and that survives exec.
   - The final re-review of the fast-test-suite branch probed this inside a job: `getsignal(SIGINT)` was SIG_IGN.
   - The comment "INT then TERM" describes behaviour that does not happen.
2. A scratch tmux server started by a python test survives an interrupted run:
   - A tmux server leaves its job's process group when it daemonizes, so the group kill never reaches it.
   - Python's unittest runs no cleanups on SIGTERM.
   - These servers do exit on their own within 10 minutes, because their panes run `sleep 600` or `sleep 60`. Until then they hold sockets and processes.

## Design

**Drop INT.** `killjobs` sends TERM to each live job's group (live = no `.res` file yet), polls up to 3 s until the groups are gone, then KILLs what is left. The comment describes exactly that.

**Sweep scratch servers.** After the job groups are gone, all.zsh finds every tmux socket under `<rundir>/tmp/` and runs `tmux -S <socket> kill-server` on each, ignoring errors.
- **Why this works:** every job's TMPDIR is `<rundir>/tmp/<n>`, and a test that starts a scratch server with `-L <name>` and no TMUX_TMPDIR of its own puts the socket in `$TMPDIR/tmux-<uid>/`.
- **Finding sockets:** `find <rundir>/tmp -type s`.
- **Which tmux:** the same tmux binary the tests use (`tmux` from PATH).
- **When:** the sweep runs only on the interrupt path. A normal run ends with every job finished, and each test's own cleanup has run.
- **Limitation, stated in the comment:** a test that sets its own TMUX_TMPDIR outside the run dir is not swept. `test_fresh_path.zsh` does this to stay under macOS's 104-byte socket path limit, but it is a zsh test with its own EXIT trap.

**Out of scope.** The Python 3.9 CI segfault idea stays parked: one occurrence, and faulthandler is already on.

## Error handling

- `kill-server` on a dead socket fails silently: errors are ignored and stderr goes to /dev/null.
- The whole interrupt path stays under about 5 s: 3 s of grace, then the sweep. Each `kill-server` call is bounded with `timeout 2`, or a perl alarm where coreutils `timeout` is missing.
- The sweep never touches a socket outside `<rundir>/tmp`. The default tmux server and the live `dev` session are never in that tree.

## Testing

All cases go in `tools/tests/test_all_runner.zsh`, using stub jobs in a scratch `TC_TEST_ROOT`:

1. **Sweep:** a stub job starts a scratch tmux server with `-L stub` under its TMPDIR, then sleeps. Interrupt the runner with TERM.
   - Pass: within 5 s the server is gone (`tmux -S <sock> has-session` fails, and no tmux pid for that socket remains), and the runner exits 130.
   - RED on the current code: the server survives.
2. **No INT:** a stub job records every signal it receives. After an interrupt it has seen TERM and no INT; a job that ignores TERM is KILLed.
3. **Scope:** a scratch server whose socket is outside `<rundir>/tmp`, started by the test itself, is still alive after the interrupt.
4. **Regression:** the existing interrupt and finished-job cases still pass, and the file ends ALL PASS with rc=0.

Leak check after the suite: `pgrep -f 'tmux.*-L stub'` finds nothing.

## Acceptance

- `zsh tools/tests/test_all_runner.zsh; echo rc=$?` gives ALL PASS and rc=0, with the three new cases red first.
- Real-state check: start `zsh tools/tests/all.zsh` in the live tests window, interrupt it after about 30 s with C-c, and run `ps -Ao pid,command | grep -c '[t]mux.*tc-all'`. The count must be 0, against a count taken while the run was going.
