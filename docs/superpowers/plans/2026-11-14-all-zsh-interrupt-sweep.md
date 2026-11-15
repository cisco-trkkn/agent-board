# all.zsh interrupt sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On an interrupt, all.zsh sends TERM (no INT) to live job groups, KILLs what is left after 3 s, then kills every scratch tmux server whose socket is under the run's socket root.

**Architecture:** all.zsh gives each job its own `TMUX_TMPDIR` under a short per-run socket root, `killjobs` drops INT, and the INT-TERM trap sweeps that root; three new cases in `tools/tests/test_all_runner.zsh` using its stub-job pattern; one real-state check against the live suite.

**Tech Stack:** zsh, tmux, perl (timeout fallback).

**Spec:** docs/superpowers/specs/2026-11-11-all-zsh-interrupt-sweep-design.md

## Global Constraints

- **Ruling (plan, 2026-11-14): socket root.** The spec says a `-L` server started under a job's TMPDIR puts its socket in `$TMPDIR/tmux-<uid>/`. It does not: tmux reads `TMUX_TMPDIR` (default `/tmp`), never `TMPDIR`. Probe: `env -u TMUX_TMPDIR TMPDIR=$d tmux -f /dev/null -L probestub new-session -d 'sleep 30'` → socket at `/tmp/tmux-503/probestub`, nothing under `$d`. So all.zsh creates a per-run socket root `sockroot="$(mktemp -d /tmp/tcs.XXXXXX)"` and starts job `i` with `TMUX_TMPDIR="$sockroot/$i"` (made with `mkdir -p`) next to its TMPDIR and TC_STATE. Short on purpose: `/tmp/tcs.XXXXXX/123/tmux-503/sesspath-99999-abcdef12` is 54 bytes, while the same under `<rundir>/tmp/<n>` on this Mac (TMPDIR is 49 bytes) is about 103, at macOS's 104-byte socket path limit. Cost if wrong: a test that relies on its socket being in `/tmp/tmux-<uid>` (e.g. one that clears its environment) breaks; the full suite run in the acceptance criteria catches that.
- The sweep touches only sockets found by `find "$sockroot" -type s`; never the default tmux server, never a socket outside `$sockroot`.
- A normal run removes `$sockroot` with the run dir (`rm -rf`); the interrupt path removes it after the sweep.
- The sweep runs only on the interrupt path (the trap), not after a normal run.
- Each `kill-server` is bounded to 2 s (`timeout 2` when coreutils `timeout` exists, else a perl alarm), stderr to /dev/null, errors ignored. The whole interrupt path stays under about 5 s.
- Tmux binary: `tmux` from PATH (the same one the tests use).
- The comment above `killjobs` describes exactly what it does (TERM, 3 s poll, KILL, then the sweep) and states the limitation: a test that sets its own TMUX_TMPDIR (e.g. `test_fresh_path.zsh`) is not swept.
- Scratch tmux servers in tests start with `-f /dev/null`.

**User decisions (already made):** none beyond the spec.

---

### Task 1: TERM-only killjobs and the scratch-server sweep, with tests

**Goal:** Each job runs with its own `TMUX_TMPDIR` under a per-run socket root, `killjobs` stops sending INT, and the interrupt trap sweeps scratch tmux servers under that root; three new runner tests prove it.

**Files:**
- Modify: `tools/tests/all.zsh` (run dir setup ~line 68, the job launch lines 74–79, comment at 105–108, `killjobs` at 109–125, the trap at 126, the final `rm -rf` ~171)
- Modify: `tools/tests/test_all_runner.zsh` (new cases after the I3 / wind-down cases, ~line 318)

**Acceptance Criteria:**
- [ ] Sweep case: a stub job starts `tmux -f /dev/null -L stub new-session -d 'sleep 600'` with the environment the runner gave it (its `TMUX_TMPDIR` is `$sockroot/<n>`), then sleeps; the test sends TERM to the runner; within 5 s `tmux -S <that socket> has-session` fails, no tmux process for that socket remains, and the runner exits 130. RED on the current all.zsh: the server survives.
- [ ] No-INT case, two checks. (a) A stub job that traps TERM (appending `TERM` to a file, then exiting) records exactly one `TERM` after the interrupt. (b) INT cannot be observed inside a job (a non-interactive shell cannot trap a signal ignored on entry, and jobs inherit SIGINT ignored), so the no-INT half is a source check: the body of `killjobs` in all.zsh (from `killjobs() {` to its closing `}`) contains no `-INT`. Mutation: put back `for p in $pids; do kill -INT -- -$p 2>/dev/null; done` → (b) fails; RED on the current all.zsh.
- [ ] Scope case: a scratch server started by the test itself with a socket outside the socket root (`tmux -f /dev/null -S "$SCR/outside.sock" new-session -d 'sleep 60'`) is still alive after the interrupt; killed by the test afterwards.
- [ ] Env case: a stub job writes its `TMUX_TMPDIR` to a file; it is `/tmp/tcs.*/<n>` (an existing directory), and after a normal (not interrupted) run no `/tmp/tcs.*` directory created by that run remains.
- [ ] The full suite still passes with the new job environment: `zsh tools/tests/all.zsh; echo rc=$?` → `ALL PASS` verdict line and `rc=0`.
- [ ] Existing cases still pass; `zsh tools/tests/test_all_runner.zsh; echo rc=$?` ends ALL PASS and rc=0.
- [ ] Leak check after the file: `pgrep -f 'tmux.*-L stub'` prints nothing (the test file's EXIT trap kills any stub server it may leave).
- [ ] Each new case names its mutation in a comment (e.g. "remove the sweep → sweep case fails"), and the implementer's report shows each new case failing on the unmodified all.zsh (run with `TC_ALL_RUNNER=<copy of the old all.zsh>`), then passing.

**Verify:** `zsh tools/tests/test_all_runner.zsh; echo rc=$?` → last verdict ALL PASS and `rc=0`

**Notes for the implementer:**
- Follow the existing interrupt cases (`# --- Important 1`, `I1`, `I3`, wind-down, ~lines 229–317): they build a `TC_TEST_ROOT` of stub jobs, start `zsh $ALL` in the background with `TMPDIR="$SCR"`, send TERM, `wait`, and check. Reuse that shape.
- The run dir is `$SCR/tc-all.XXXXXX` and is kept on interrupt (its path is printed on stderr: `all.zsh: interrupted, run dir <dir>`); the stub's socket is `$TMUX_TMPDIR/tmux-$(id -u)/stub`. Have the stub write that path to a file under `$SCR` the test reads.
- Wait for the stub to have started its server before sending TERM (poll for the socket-path file, up to 10 s).
- The sweep in all.zsh: after the job groups are gone, `for s in ${(f)"$(find "$sockroot" -type s 2>/dev/null)"}; do <bounded> tmux -S "$s" kill-server 2>/dev/null; done`, then `rm -rf "$sockroot"`. Guard the empty result (`${(f)…}` of an empty string yields one empty word: skip `[[ -n $s ]]`).
- This Mac has no coreutils `timeout` (probed: `(( $+commands[timeout] ))` is false), so the perl branch is the one that runs here; `perl -e 'alarm 2; exec @ARGV' true` was probed OK.
- Bounded call: `if (( $+commands[timeout] )); then timeout 2 tmux -S "$s" kill-server; else perl -e 'alarm 2; exec @ARGV' tmux -S "$s" kill-server; fi 2>/dev/null`.
- Use TDD (superpowers-extended-cc:test-driven-development + test-driven-development-extras): write the three cases, run them RED against the unmodified runner, then change all.zsh.
- Commit: `fix(tests): all.zsh interrupt sends TERM only and sweeps scratch tmux servers`, ending with the attribution trailer your harness specifies. Stage only the two files.

```json:metadata
{"files": ["tools/tests/all.zsh", "tools/tests/test_all_runner.zsh"], "verifyCommand": "zsh tools/tests/test_all_runner.zsh; echo rc=$?", "acceptanceCriteria": ["sweep case: stub's scratch server gone within 5 s of TERM, runner exits 130; RED on old runner", "no-INT case: stub records exactly one TERM; killjobs body has no -INT (RED on old runner)", "scope case: server with socket outside the socket root survives", "existing cases pass; ALL PASS rc=0", "leak check: pgrep -f 'tmux.*-L stub' empty", "env case: job TMUX_TMPDIR is /tmp/tcs.*/<n>; root removed after a normal run", "full suite: zsh tools/tests/all.zsh ALL PASS rc=0", "each new case names its mutation and was shown RED first"], "modelTier": "standard"}
```

### Task 2: Real-state interrupt check on the live suite

**Goal:** Prove on the real suite that an interrupted `all.zsh` leaves no scratch tmux server alive under its run dir.

**Files:**
- Create: `docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md` (the evidence)

**Acceptance Criteria:**
- [ ] The real suite (`zsh tools/tests/all.zsh`, from the worktree) is started in the bg `tests` window (or its lane) with `tmux-ctl send -C <worktree> tests "zsh tools/tests/all.zsh"`.
- [ ] While it runs, the sockets under its socket root are counted: `find <sockroot> -type s | wc -l`, polled every 5 s until ≥ 1 (up to 120 s); the socket root is the newest `/tmp/tcs.*` created after the start. The count and the time are recorded. If no socket appears within 120 s, that is recorded and the check is repeated once.
- [ ] The run is interrupted with C-c in that window (`tmux-ctl keys <window> C-c`, the window this task started).
- [ ] Within 10 s after: every socket that was counted fails `tmux -S <sock> has-session` and no tmux process remains whose socket was counted (`lsof -U 2>/dev/null | grep -c <sockroot>` → 0); the runner printed `all.zsh: interrupted, run dir <dir>`.
- [ ] The note records the commands, both counts, and the outputs verbatim. Ruling recorded in it: the spec's `grep -c '[t]mux.*tc-all'` count is replaced by the socket check because a `-L` server's command line does not contain the run dir path, so that grep would read 0 both during and after the run; and the socket root (Task 1's ruling) replaces `<rundir>/tmp`.

**Verify:** `grep -c '^- ' docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md` → at least 4 (start, during count, interrupt, after count)

**Steps:**
- [ ] Step 1: `tmux-ctl send -C /Users/francisco.ruiz/agent-board/.claude/worktrees/all-zsh-interrupt-sweep tests "zsh tools/tests/all.zsh"` and note the window it reports.
- [ ] Step 2: find the socket root: `ls -dt /tmp/tcs.* | head -1`; poll `find <sockroot> -type s` every 5 s until it prints at least one socket; save the list to `$SCR/socks` (a scratch file).
- [ ] Step 3: `tmux-ctl keys <window> C-c`; wait 10 s; `tmux-ctl read <window> 20` and look for `all.zsh: interrupted`.
- [ ] Step 4: `while read -r s; do tmux -S "$s" has-session 2>/dev/null && echo "ALIVE $s" || echo "gone $s"; done < $SCR/socks`, and `lsof -U 2>/dev/null | grep -c "<sockroot>"`.
- [ ] Step 5: write the note with each step as a `- ` bullet and the verbatim outputs; commit it alone: `git add docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md && git commit -m "docs(notes): all.zsh interrupt real-state check"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md"], "verifyCommand": "grep -c '^- ' docs/superpowers/notes/2026-11-14-all-zsh-interrupt-real-check.md", "acceptanceCriteria": ["real suite started in the bg tests window from the worktree", "socket count under the socket root taken during the run, >= 1", "interrupted with C-c; runner printed interrupted line", "every counted socket's server gone within 10 s; lsof count 0", "note records commands, counts and verbatim outputs, and the grep ruling"], "modelTier": "mechanical"}
```
