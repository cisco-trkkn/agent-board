# all.zsh interrupt sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On an interrupt, all.zsh sends TERM (no INT) to live job groups, KILLs what is left after 3 s, then kills every scratch tmux server whose socket is under `<rundir>/tmp`.

**Architecture:** Two changes inside `killjobs` / the INT-TERM trap of `tools/tests/all.zsh`; three new cases in `tools/tests/test_all_runner.zsh` using its stub-job pattern; one real-state check against the live suite.

**Tech Stack:** zsh, tmux, perl (timeout fallback).

**Spec:** docs/superpowers/specs/2026-11-11-all-zsh-interrupt-sweep-design.md

## Global Constraints

- The sweep touches only sockets found by `find "$rundir/tmp" -type s`; never the default tmux server, never a socket outside `<rundir>/tmp`.
- The sweep runs only on the interrupt path (the trap), not after a normal run.
- Each `kill-server` is bounded to 2 s (`timeout 2` when coreutils `timeout` exists, else a perl alarm), stderr to /dev/null, errors ignored. The whole interrupt path stays under about 5 s.
- Tmux binary: `tmux` from PATH (the same one the tests use).
- The comment above `killjobs` describes exactly what it does (TERM, 3 s poll, KILL, then the sweep) and states the limitation: a test that sets its own TMUX_TMPDIR outside the run dir (e.g. `test_fresh_path.zsh`) is not swept.
- Scratch tmux servers in tests start with `-f /dev/null`.

**User decisions (already made):** none beyond the spec.

---

### Task 1: TERM-only killjobs and the scratch-server sweep, with tests

**Goal:** `killjobs` stops sending INT, and the interrupt trap sweeps scratch tmux servers under `<rundir>/tmp`; three new runner tests prove it.

**Files:**
- Modify: `tools/tests/all.zsh` (comment at lines 105–108, `killjobs` at 109–125, the trap at 126)
- Modify: `tools/tests/test_all_runner.zsh` (new cases after the I3 / wind-down cases, ~line 318)

**Acceptance Criteria:**
- [ ] Sweep case: a stub job starts `tmux -f /dev/null -L stub new-session -d 'sleep 600'` under its own TMPDIR (the runner gives it `<rundir>/tmp/<n>`), then sleeps; the test sends TERM to the runner; within 5 s `tmux -S <that socket> has-session` fails, no tmux process for that socket remains, and the runner exits 130. RED on the current all.zsh: the server survives.
- [ ] No-INT case, two checks. (a) A stub job that traps TERM (appending `TERM` to a file, then exiting) records exactly one `TERM` after the interrupt. (b) INT cannot be observed inside a job (a non-interactive shell cannot trap a signal ignored on entry, and jobs inherit SIGINT ignored), so the no-INT half is a source check: the body of `killjobs` in all.zsh (from `killjobs() {` to its closing `}`) contains no `-INT`. Mutation: put back `for p in $pids; do kill -INT -- -$p 2>/dev/null; done` → (b) fails; RED on the current all.zsh.
- [ ] Scope case: a scratch server started by the test itself with a socket outside `<rundir>/tmp` (`tmux -f /dev/null -S "$SCR/outside.sock" new-session -d 'sleep 60'`) is still alive after the interrupt; killed by the test afterwards.
- [ ] Existing cases still pass; `zsh tools/tests/test_all_runner.zsh; echo rc=$?` ends ALL PASS and rc=0.
- [ ] Leak check after the file: `pgrep -f 'tmux.*-L stub'` prints nothing (the test file's EXIT trap kills any stub server it may leave).
- [ ] Each new case names its mutation in a comment (e.g. "remove the sweep → sweep case fails"), and the implementer's report shows each new case failing on the unmodified all.zsh (run with `TC_ALL_RUNNER=<copy of the old all.zsh>`), then passing.

**Verify:** `zsh tools/tests/test_all_runner.zsh; echo rc=$?` → last verdict ALL PASS and `rc=0`

**Notes for the implementer:**
- Follow the existing interrupt cases (`# --- Important 1`, `I1`, `I3`, wind-down, ~lines 229–317): they build a `TC_TEST_ROOT` of stub jobs, start `zsh $ALL` in the background with `TMPDIR="$SCR"`, send TERM, `wait`, and check. Reuse that shape.
- The run dir is `$SCR/tc-all.XXXXXX` and is kept on interrupt (its path is printed on stderr: `all.zsh: interrupted, run dir <dir>`); the stub's socket is under `<rundir>/tmp/<n>/tmux-$UID/stub`. Have the stub write its socket path (`$TMPDIR/tmux-$(id -u)/stub`) to a file the test reads, rather than guessing `<n>`.
- Wait for the stub to have started its server before sending TERM (poll for the socket-path file, up to 10 s).
- The sweep in all.zsh: after the job groups are gone, `for s in ${(f)"$(find "$rundir/tmp" -type s 2>/dev/null)"}; do <bounded> tmux -S "$s" kill-server 2>/dev/null; done`. Guard the empty result (`${(f)…}` of an empty string yields one empty word: skip `[[ -n $s ]]`).
- Bounded call: `if (( $+commands[timeout] )); then timeout 2 tmux -S "$s" kill-server; else perl -e 'alarm 2; exec @ARGV' tmux -S "$s" kill-server; fi 2>/dev/null`.
- Use TDD (superpowers-extended-cc:test-driven-development + test-driven-development-extras): write the three cases, run them RED against the unmodified runner, then change all.zsh.
- Commit: `fix(tests): all.zsh interrupt sends TERM only and sweeps scratch tmux servers`, ending with the attribution trailer your harness specifies. Stage only the two files.

```json:metadata
{"files": ["tools/tests/all.zsh", "tools/tests/test_all_runner.zsh"], "verifyCommand": "zsh tools/tests/test_all_runner.zsh; echo rc=$?", "acceptanceCriteria": ["sweep case: stub's scratch server gone within 5 s of TERM, runner exits 130; RED on old runner", "no-INT case: stub records exactly one TERM; killjobs body has no -INT (RED on old runner)", "scope case: server with socket outside <rundir>/tmp survives", "existing cases pass; ALL PASS rc=0", "leak check: pgrep -f 'tmux.*-L stub' empty", "each new case names its mutation and was shown RED first"], "modelTier": "standard"}
```

### Task 2: Real-state interrupt check on the live suite

**Goal:** Prove on the real suite that an interrupted `all.zsh` leaves no scratch tmux server alive under its run dir.

**Files:**
- Create: `docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md` (the evidence)

**Acceptance Criteria:**
- [ ] The real suite (`zsh tools/tests/all.zsh`, from the worktree) is started in the bg `tests` window (or its lane) with `tmux-ctl send -C <worktree> tests "zsh tools/tests/all.zsh"`.
- [ ] While it runs, the sockets under its run dir are counted: `find <rundir>/tmp -type s | wc -l`, polled every 5 s until ≥ 1 (up to 120 s); the run dir is the newest `${TMPDIR}/tc-all.*` created after the start. The count and the time are recorded. If no socket appears within 120 s, that is recorded and the check is repeated once.
- [ ] The run is interrupted with C-c in that window (`tmux-ctl keys <window> C-c`, the window this task started).
- [ ] Within 10 s after: every socket that was counted fails `tmux -S <sock> has-session` and no process has that socket open (`lsof -U 2>/dev/null | grep -c <rundir>` → 0); the runner printed `all.zsh: interrupted, run dir <dir>`.
- [ ] The note records the commands, both counts, and the outputs verbatim. Ruling recorded in it: the spec's `grep -c '[t]mux.*tc-all'` count is replaced by the socket check because a `-L` server's command line does not contain the run dir path, so that grep would read 0 both during and after the run.

**Verify:** `grep -c '^- ' docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md` → at least 4 (start, during count, interrupt, after count)

**Steps:**
- [ ] Step 1: `tmux-ctl send -C /Users/francisco.ruiz/agent-board/.claude/worktrees/all-zsh-interrupt-sweep tests "zsh tools/tests/all.zsh"` and note the window it reports.
- [ ] Step 2: find the run dir: `ls -dt ${TMPDIR:-/tmp}/tc-all.* | head -1`; poll `find <rundir>/tmp -type s` every 5 s until it prints at least one socket; save the list to `$SCR/socks` (a scratch file).
- [ ] Step 3: `tmux-ctl keys <window> C-c`; wait 10 s; `tmux-ctl read <window> 20` and look for `all.zsh: interrupted`.
- [ ] Step 4: `while read -r s; do tmux -S "$s" has-session 2>/dev/null && echo "ALIVE $s" || echo "gone $s"; done < $SCR/socks`, and `lsof -U 2>/dev/null | grep -c "<rundir>"`.
- [ ] Step 5: write the note with each step as a `- ` bullet and the verbatim outputs; commit it alone: `git add docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md && git commit -m "docs(notes): all.zsh interrupt real-state check"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md"], "verifyCommand": "grep -c '^- ' docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md", "acceptanceCriteria": ["real suite started in the bg tests window from the worktree", "socket count under <rundir>/tmp taken during the run, >= 1", "interrupted with C-c; runner printed interrupted line", "every counted socket's server gone within 10 s; lsof count 0", "note records commands, counts and verbatim outputs, and the grep ruling"], "modelTier": "mechanical"}
```
