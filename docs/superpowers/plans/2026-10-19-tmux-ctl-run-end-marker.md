# tmux-ctl run end-marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-ctl run` takes the command's output from between a start marker and an end marker that the typed line prints. It no longer trims the last captured line with `sed '$d'`, so the residual 1-in-120 empty-output flake in `tools/tests/test_bg.zsh` goes away.

**Architecture:** The typed line already prints `@@TCSTART-<id>` before the command. It will also print `@@TCEND-<id>` after the command and before `_done` writes the exit code. After the `.rc` file appears, `run` polls `capture-pane` until the end marker is visible, which is bounded. It keeps the lines between the two markers. If the command's last line has no trailing newline, the text before the marker on that line is kept too. If the end marker never shows up within the bound, `run` falls back to today's start-marker capture, so nothing gets worse.

**Tech Stack:** zsh (`bin/tmux-ctl`), tmux 3.8, the zsh test harness in `tools/tests/lib.zsh` (scratch tmux server).

**Spec:** none. The input is the parked idea from 2026-10-19 21:33 in `~/.claude/ideas/agent-board.md` and the handoff `~/.claude/handoffs/2026-10-19-after-group-c.md` ("The `tmux-ctl run` end-marker fix").

## Global Constraints

- The typed line keeps calling `~/.local/bin/tmux-ctl _done $id $?`, the LIVE path. `_done` must not change: worktree tests run the live `_done`, so any marker it printed would be missing there.
- The end marker is split in the source, like the start marker (`printf '@@TC%s\n' END-$id`), so the echo of the typed line can never match it.
- `run`'s stdout format is unchanged: the output lines, then `[exit N]`. `savelog` (timeout and interrupt) keeps its start-marker-only capture.
- The wait for the end marker is bounded: at most 3 s after the `.rc` file appears, polled every 0.1 s.
- In a worktree, tests run with `TC_CTL=$PWD/bin/tmux-ctl`. The zsh tests default to the live scripts.
- Run the suites with `tmux-ctl run tests "<cmd>"`. Kill processes by PID only.
- Work happens in a worktree on branch `fix/tmux-ctl-end-marker`, never on `main`. Commits use conventional commits (`fix(tmux-ctl): …`) and end with the attribution trailer your harness specifies.

**User decisions (already made):** the user picked this fix over groups D and E and the Group C minors (2026-10-19).

---

### Task 1: Reproduce the empty-output flake and name its cause

**Goal:** Capture at least one failing iteration of `run` returning empty output under load, together with the raw pane capture taken before `trim | sed '$d'`. Either confirm or refute the hypothesis that `_done` writes the `.rc` file before the last output line is in the capture, and that `sed '$d'` then drops the real output.

**Files:**
- Create (scratch, not committed): a loop script and an instrumented copy of `bin/tmux-ctl` in the scratchpad
- Create: `docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task1-report.md`

**Acceptance Criteria:**
- [ ] `superpowers-extended-cc:systematic-debugging` is followed. The report has these sections: `## Repro`, `## Evidence`, `## Cause`, `## Implication for Task 2`.
- [ ] The repro loop runs `run tests 'echo A'`-style calls, using the instrumented copy through `TC_CTL`, at least 240 times while a parallel `zsh tools/tests/run-all.zsh` load loop runs. Its kill line kills that loop by PID. The report gives the count of empty outputs out of the total.
- [ ] For each empty output, the instrumented copy saved the raw capture (`capture-pane … | awk start-marker`, before `trim` and `sed '$d'`) and the time the `.rc` file appeared. At least one such dump is quoted in `## Evidence`. If 240 loaded runs show 0 empty outputs, the report says so, quotes the loop tally, and `## Cause` reads "not reproduced".
- [ ] `## Implication for Task 2` says whether the bounded wait for the end marker covers the cause. If the evidence points somewhere else, it describes the shape of the fix instead.
- [ ] No change to `bin/tmux-ctl` is committed.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task1-report.md` → `4`

**Steps:**

- [ ] **Step 1:** Copy `bin/tmux-ctl` into the scratchpad. In the copy's `run)` branch, just before the `out=` line, add a dump: write `EPOCHREALTIME`, the `.rc` mtime and the raw `capture-pane -p -J -S $(( start - hist ))` output to `$SCRATCH/dump-$id.txt`, then delete that file again if the final `out` is non-empty.
- [ ] **Step 2:** Start the load loop in the background (`while :; do zsh tools/tests/run-all.zsh >/dev/null 2>&1; done & load=$!`). Run the repro loop with a scratch harness from `tools/tests/lib.zsh` (`tt_setup claude shell`, then 240 × `$C run tests "echo A$i"`, counting outputs that are not exactly `A$i`). Then `kill $load`.
- [ ] **Step 3:** Read the dumps. Compare the raw capture's last line with what `sed '$d'` removed. Write the report.
- [ ] **Step 4:** Commit only the report: `git add docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task1-report.md && git commit -m "docs(plan): end-marker task 1 flake evidence"`, with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task1-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task1-report.md", "acceptanceCriteria": ["systematic-debugging followed; report has Repro/Evidence/Cause/Implication sections", "240+ loaded runs with instrumented copy via TC_CTL; empty-output count reported; load loop killed by PID", "raw pre-trim capture quoted for an empty output, or 'not reproduced' with the tally", "implication for Task 2 stated", "no bin/tmux-ctl change committed"], "modelTier": "standard"}
```

---

### Task 2: Capture `run` output between the start and end markers

**Goal:** `run` prints exactly the command's output, cut between `@@TCSTART-<id>` and `@@TCEND-<id>`, after a bounded wait for the end marker. Tests pin a multi-line prompt and output with no trailing newline, both of which `sed '$d'` gets wrong today.

**Files:**
- Modify: `bin/tmux-ctl` (the `run)` branch: the typed `send-keys` line near line 248 and the `out=` capture near line 261)
- Test: `tools/tests/test_bg.zsh`

**Acceptance Criteria:**
- [ ] RED first. With a two-line prompt in the bg `tests` pane, `run tests 'echo x'` prints exactly `x` and `[exit 0]`, and `run tests 'printf y'` prints `y` and `[exit 0]`. Both checks fail on the current code; the RED output is in the report.
- [ ] GREEN: the typed line prints `@@TCEND-<id>` (split in the source) after the command, and keeps `~/.local/bin/tmux-ctl _done $id $?` with the command's own exit code. `run` waits at most 3 s for the end marker, and if it is still missing, falls back to the old start-marker capture with `sed '$d'`.
- [ ] `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh` → `ALL PASS`, and `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh` exits 0 with no `FAIL` line.
- [ ] `run tests 'false'` still prints `[exit 1]`. The test file already covers this with "exit recorded".
- [ ] One real run against a non-scratch shell: `bin/tmux-ctl run tests 'echo real-$RANDOM'` from the worktree, against the real `<project>-bg` session, prints the echoed value and `[exit 0]`. That output is in the report.

**Verify:** `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh | tail -1` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `tools/tests/test_bg.zsh`, before `tt_done`:

```zsh
# output is cut at an end marker, not by dropping the last line (two-line prompt, no trailing newline)
$C run tests "PS1=\$'top\\nbot> '; PROMPT=\$PS1" >/dev/null
check "two-line prompt: only the output" test "$($C run tests 'echo x')" = $'x\n[exit 0]'
check "no trailing newline kept"         test "$($C run tests 'printf y')" = $'y\n[exit 0]'
```

- [ ] **Step 2: Run them to see them fail.** `tmux-ctl run tests "TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh"`. Expected: both new checks FAIL. The first gets `x` plus the `top` prompt line; the second gets an empty or prompt-joined line.

- [ ] **Step 3: Implement.** In `bin/tmux-ctl`, change the typed line:

```zsh
    t send-keys -t "$tgt" -l -- "printf '@@TC%s\\n' START-$id; $(wrap_cd "$win" "$*") ; ~/.local/bin/tmux-ctl _done $id \$? ; printf '@@TC%s\\n' END-$id"
```

The marker goes after `_done`, so `$?` is still the command's code. `run` then waits for the marker. Replace the `out=` line with:

```zsh
    grab() { t capture-pane -p -J -t "$tgt" -S $(( start - hist )) | awk -v m="@@TCSTART-$id" 'f{print} $0==m{f=1}' }
    n=0; raw="$(grab)"
    while [[ "$raw" != *"@@TCEND-$id"* ]] && (( n++ < 30 )); do
      sleep 0.1; hist="$(t display -p -t "$tgt" '#{history_size}')"; hist="${${hist:-0}//[^0-9]/}"; raw="$(grab)"
    done
    if [[ "$raw" == *"@@TCEND-$id"* ]]; then   # cut at the end marker; keep text the command left before it on the same line
      out="$(print -r -- "$raw" | awk -v e="@@TCEND-$id" '{i=index($0,e); if(i){if(i>1) print substr($0,1,i-1); exit} print}' | trim)"
    else
      out="$(print -r -- "$raw" | trim | sed '$d')"   # no end marker within 3s: old behaviour (last line = the prompt again)
    fi
```

If Task 1's report shows a different cause, change the implementation the way its `## Implication for Task 2` says, and note that in your report.

- [ ] **Step 4: Run to green.** Run `test_bg.zsh` (`ALL PASS`), then the full `run-all.zsh` with `TC_CTL`, both through `tmux-ctl run tests`. Then do the one real run from the acceptance criteria.

- [ ] **Step 5: Commit.** `git add bin/tmux-ctl tools/tests/test_bg.zsh && git commit -m "fix(tmux-ctl): run cuts output at an end marker, not the last line"`. The body names the cause from Task 1 and ends with the attribution trailer your harness specifies.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_bg.zsh"], "verifyCommand": "TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh | tail -1", "acceptanceCriteria": ["two-line-prompt and no-trailing-newline checks RED on old code, output in report", "typed line prints split END marker after _done; bounded 3s wait; fallback to old capture", "test_bg ALL PASS and run-all exit 0 with TC_CTL", "exit codes preserved", "one real run against the real bg session, output in report"], "modelTier": "standard"}
```

---

### Task 3: Stress-check the fix under load

**Goal:** Show by counting that the flake is gone: 120 loaded `test_bg.zsh` runs on the fixed branch, all `ALL PASS`.

**Files:**
- Create: `docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task3-report.md`

**Acceptance Criteria:**
- [ ] A parallel `run-all.zsh` load loop runs during the whole count, and is killed by PID afterwards.
- [ ] `for i in {1..120}; do TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_bg.zsh | tail -1; done | sort | uniq -c` prints `120 ALL PASS`. That tally, plus `uptime` before and after, is in the report.
- [ ] The report has `## Load`, `## Tally`, `## Verdict`.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task3-report.md` → `3`

**Steps:**

- [ ] **Step 1:** In the worktree, run `uptime`, then `while :; do TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh >/dev/null 2>&1; done & load=$!; echo $load`.
- [ ] **Step 2:** Run the tally command from the acceptance criteria through `tmux-ctl run -t 3600 tests "<cmd>"`.
- [ ] **Step 3:** `kill $load`, check with `ps -p $load` that it is gone, and run `uptime`.
- [ ] **Step 4:** Write the report with the three sections and commit it: `git add docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task3-report.md && git commit -m "docs(plan): end-marker stress tally"`, with the attribution trailer your harness specifies.

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task3-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-19-tmux-ctl-run-end-marker-task3-report.md", "acceptanceCriteria": ["load loop runs throughout and is killed by PID", "120 ALL PASS tally with uptime before/after in report", "report has Load/Tally/Verdict sections"], "modelTier": "mechanical"}
```
