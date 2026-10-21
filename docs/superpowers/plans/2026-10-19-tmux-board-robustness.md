# tmux and Board Robustness (Group C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix seven robustness gaps in the tmux toolkit and the Agent Board:
- the board's offline poll;
- `tmux-ctl`'s busy check and the `test_bg` flake;
- the teammate hook acting on every pane;
- agent labels;
- the artifact kind;
- the doc pane across projects;
- a staged `~/.tmux.conf` patch.

**Architecture:**
- **`tmux-ctl`:** decides idle and busy from the foreground command and the pane shell's children (`pgrep -P`).
- **`tmux-teammate-window`:** gains a `--hook <pane>` mode.
- **Labels:** `board/usage.py` shares one window-matching helper between `card_alerts` and a new `card_labels`. `board/server.py` writes `@tc_label` from the indexer thread through an `on_snapshot` callback.
- **`board/index.html`:**
  - an offline banner, with polls skipped while offline;
  - `role · model · effort` on cards;
  - the doc pane keyed on `docSess`.
- **`~/.tmux.conf`:** changes are staged as a generated patch, never edited.

**Tech Stack:** zsh (tmux scripts and the scratch-server test harness), Python 3 stdlib (`unittest`), vanilla JS/HTML/CSS.

**Spec:** `docs/superpowers/specs/2026-10-19-tmux-board-robustness-design.md`

**Where to work:** a git worktree, `.claude/worktrees/group-c`, on branch `feat/group-c-robustness`. The live install is symlinked to the main checkout (`~/.local/bin/tmux-ctl` → `~/agent-board/bin/tmux-ctl`, and so on). Never edit `~/agent-board` on `main`.

## Global Constraints

**Tests:**
- The zsh tests default to the LIVE scripts. In the worktree, always run them with the worktree's scripts:
  `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/<file>.zsh`. `test_teammate_window.zsh` already defaults to the repo copy.
- Run suites through `tmux-ctl run tests "<cmd>"` (see the teammate rules). Run the board suite and `run-all.zsh` one after the other, never in parallel. The exception is Task 2's load loop, which runs them in parallel on purpose.
- Every scratch tmux server starts with `-f /dev/null`, and `tools/tests/lib.zsh` already does this. Never touch the user's live tmux server. Task 10 runs only read-only commands against it.
- A test written from this plan must be able to fail. Each task names the mutation that makes its new test fail. Run that mutation once and report the FAIL.

**Behaviour:**
- **Idle and busy:** a pane is idle when its `#{pane_current_command}` matches `SHELLS` AND `pgrep -P #{pane_pid}` finds no child. Otherwise it is busy.
- **Labels:**
  - The label text is `<window name> · <family>` plus `·<effort>` when there is an effort. The family is `usage._family(model)`.
  - Efforts are abbreviated `low→low`, `medium→med`, `high→high`, `max→max`. Any other value is shown as is.
- **`card_labels(sessions, live)`:**
  - sets `s["usage_labels"] = {pane_id: {"role","model","effort","label"}}`, with matched windows only;
  - returns `{pane_id: entry or None}` for EVERY agent window (teammate, worker, `claude`), so `sync_labels` can unset unmatched ones.

  This refines the spec's "returns `{pane_id: …}`": the return value adds `None` entries, and the card payload is unchanged.
- `sync_labels` writes `@tc_label` only on change. It runs only in the indexer thread, never on the `api/state` path.
- Nothing edits `~/.tmux.conf`. Its change is `~/.claude/staged/tmux.conf.patch`, generated with `diff -u` and checked with `patch --dry-run`.

**Commits:**
- Conventional, with a scope: `feat(board): …`, `fix(tmux-ctl): …`, `test(tmux-ctl): …`.
- End each commit with the attribution trailer your harness specifies.
- Python stdlib only. No new dependencies.

**User decisions (already made):**
- Agent labels show in both the tmux tabs and the board cards.
- The board server keeps `@tc_label` up to date from the usage index. Labels update only while the board runs.
- The window number `#I` is dropped from the tmux tab format.
- `~/.tmux.conf` is changed only by a staged patch that the user installs.
- The spec was approved as written on 2026-10-19.

**Parallel lanes (for the SDD controller):**
- Tasks 1, 2 and 4 edit `bin/tmux-ctl`, and run in that order.
- Tasks 3 and 9 cover the hook and its staged line.
- Tasks 5, 6, 7 and 8 edit `board/`, and run in that order.

Lanes don't share files. Task 10 runs last.

---

## File Structure

| File | Change |
| --- | --- |
| `bin/tmux-ctl` | `pane_idle()` replaces the three shell-name checks; `artifact` passes `--kind` only when given and prints the recorded kind |
| `tools/tests/test_ctl_busy.zsh` | new: busy and idle detection, and a lane for a busy `tests` window |
| `tools/tests/test_ctl_artifact.zsh` | new: kind decided by the hook; an explicit kind wins |
| `tools/tests/test_bg.zsh` | only if the debugging in Task 2 shows a test-side cause |
| `bin/tmux-teammate-window` | `--hook <pane>` mode; `--hook` with no pane, or no args, does the full scan |
| `tools/tests/test_teammate_window.zsh` | hook line uses `--hook #{pane_id}`; new checks |
| `board/usage.py` | `_project_live`, `_agent_windows` (shared matching), `EFFORT_ABBR`, `card_labels`; `Indexer(on_snapshot=)` |
| `board/server.py` | `label_targets()`, `sync_labels()`, `card_labels` in `build_state`, indexer wired with `on_snapshot` |
| `board/index.html` | offline banner and gated polls; card label text; doc pane on `docSess` |
| `board/tests/test_usage.py` | `CardLabelsTest`, Indexer `on_snapshot` tests, `sync_labels` and `build_state` label tests |
| `~/.claude/staged/tmux.conf.patch` | new, outside the repo: the hook line and both tab formats |

---

### Task 1: `tmux-ctl` busy check with `pgrep -P`

**Goal:** `tmux-ctl` treats a pane as busy when its shell has a child process, so a `tests` window running `zsh script.zsh` is busy and a second `run` goes to a lane.

**Files:**
- Modify: `bin/tmux-ctl:84-108` (`settle_win`, `SHELLS`, `is_idle`, `need_idle`) and `:187` (`list`)
- Create: `tools/tests/test_ctl_busy.zsh`

**Acceptance Criteria:**
- [ ] `pane_idle <pane>` is true only when `#{pane_current_command}` matches `SHELLS` and `pgrep -P #{pane_pid}` finds nothing.
- [ ] `is_idle`, `settle_win` and `list`'s `[idle]`/`[busy]` column all use `pane_idle`. No other shell-name comparison decides idleness.
- [ ] `tmux-ctl list` shows `tests  [busy` while the bg `tests` pane runs `zsh -c 'sleep 8; :'`, whose `#{pane_current_command}` is `zsh`.
- [ ] `tmux-ctl run tests 'echo lane-ok'` prints `using lane tests·claude` on stderr and `lane-ok` on stdout while that pane is busy.
- [ ] An idle shell is still `[idle]`.
- [ ] Mutation check: with `pane_idle` reverted to the shell-name test, `test_ctl_busy.zsh` reports FAIL on `script pane is busy`.
- [ ] `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/run-all.zsh` → ALL PASS for every file except a `test_bg` "parallel runs stay clean" failure, which is Task 2's.

**Verify:** `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_busy.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** `tools/tests/test_ctl_busy.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup claude shell
$C run tests true >/dev/null                       # creates the bg session tt-bg with its tests window
check "idle shell is idle"        sh -c "$C list | grep -q '  tests  \[idle\]'"
# a zsh script in the pane: #{pane_current_command} stays "zsh", but the pane's shell has a child
tt send-keys -t '=tt-bg:tests' "zsh -c 'sleep 8; :'" Enter
tt_wait 3 sh -c "pgrep -P \$($TT_BIN display -p -t '=tt-bg:tests' '#{pane_pid}') >/dev/null"
check "script shows as zsh"       test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = zsh   # precondition: the bug's shape
check "script pane is busy"       sh -c "$C list | grep -q '  tests  \[busy'"
out="$($C run -t 5 tests 'echo lane-ok' 2>&1)"
check "run goes to a lane"        sh -c "print -r -- ${(q)out} | grep -q 'using lane tests·claude'"
check "lane ran the command"      sh -c "print -r -- ${(q)out} | grep -qx lane-ok"
tt_wait 10 sh -c "$C list | grep -q '  tests  \[idle\]'"
check "idle again after the script" sh -c "$C list | grep -q '  tests  \[idle\]'"
tt_done
```

- [ ] **Step 2: Run it to see it fail**

Run: `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_busy.zsh`
Expected: `FAIL - script pane is busy` and `FAIL - run goes to a lane`, while `ok - script shows as zsh` passes. If `script shows as zsh` fails, the test does not reproduce the bug: stop and report.

- [ ] **Step 3: Implement.** In `bin/tmux-ctl`, keep `SHELLS` and add `pane_idle` directly under it:

```zsh
SHELLS='(zsh|bash|sh|fish|-zsh|-bash)'
# pane_idle <pane>: at a prompt — the foreground command is a shell AND that shell has no child.
# `zsh script.zsh` shows as "zsh" in #{pane_current_command}, but it runs as a child of the pane's shell.
pane_idle() {
  local cmd pid
  IFS='|' read -r cmd pid <<< "$(t display -p -t "$1" '#{pane_current_command}|#{pane_pid}')"
  [[ "$cmd" == ${~SHELLS} ]] && ! pgrep -P "$pid" >/dev/null 2>&1
}
```

Make three replacements:
- `is_idle() { pane_idle "$(target "$1")" }`
- in `settle_win`: `pane_idle "$1" || return` replaces `[[ "$(t display -p -t "$1" '#{pane_current_command}')" != ${~SHELLS} ]] && return`
- in `list`: `state=busy; pane_idle "${mp:-=$SESSION:$name}" && state=idle` replaces `state=busy; [[ "$pcmd" == ${~SHELLS} ]] && state=idle`. `pcmd` is still read for the `cmd=` column.

`SHELLS` moves above `settle_win`'s first use, or `pane_idle` is defined after `SHELLS`. Both are functions resolved at call time, so the order of the definitions doesn't matter as long as both are defined before `case "$cmd"`.

- [ ] **Step 4: Run it to see it pass, then the mutation**

Run: `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_busy.zsh` → `ALL PASS`.
Temporarily change `pane_idle`'s last line to `[[ "$cmd" == ${~SHELLS} ]]`, re-run, confirm `FAIL - script pane is busy`, and restore it.

- [ ] **Step 5: Full zsh suite.** Run `tmux-ctl run tests 'TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/run-all.zsh'`. Expected: every file passes, except possibly `test_bg` "parallel runs stay clean", which is Task 2's. Report the output.

- [ ] **Step 6: Commit**

```bash
git add bin/tmux-ctl tools/tests/test_ctl_busy.zsh
git commit -m "fix(tmux-ctl): a pane whose shell has a child is busy"
```

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_busy.zsh"], "verifyCommand": "TC_CTL=\"$PWD/bin/tmux-ctl\" zsh tools/tests/test_ctl_busy.zsh", "acceptanceCriteria": ["pane_idle = shell foreground AND no pgrep -P child", "is_idle, settle_win, list use pane_idle", "list shows tests [busy while zsh -c script runs", "run goes to lane tests·claude and prints lane-ok", "idle shell stays [idle]", "mutation to shell-name test FAILs 'script pane is busy'", "run-all passes except possibly test_bg parallel"], "modelTier": "standard"}
```

---

### Task 2: Debug the `test_bg` "parallel runs stay clean" flake

**Goal:** With the new busy check in place, find the cause of the `test_bg.zsh` parallel-run flake by evidence, and fix only that. The test must then pass 20 runs in a row under load.

**Files:**
- Modify: `bin/tmux-ctl` and/or `tools/tests/test_bg.zsh`, whichever the evidence shows. The candidate is `lock_win` at `bin/tmux-ctl:73-84`.
- Create (scratch, not committed): a loop script in the scratchpad

**Acceptance Criteria:**
- [ ] `superpowers-extended-cc:systematic-debugging` is followed. The report names the root cause with evidence: a captured failing iteration's `oa`/`ob` output, plus the interleaving that explains it. Or it states that 40 loaded runs did not reproduce the flake after Task 1, with the loop output.
- [ ] Any fix changes only what the evidence implicates. Its commit message names the cause.
- [ ] Under load (a parallel `run-all.zsh` loop running), `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_bg.zsh` passes 20 consecutive runs. The loop output, with 20 `ALL PASS` and 0 `FAILED`, is in the report.
- [ ] After any fix, the full `run-all.zsh` passes.

**Verify:** `for i in {1..20}; do TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_bg.zsh | tail -1; done | sort | uniq -c` → `20 ALL PASS` (while the load loop from Step 1 runs)

**Steps:**

- [ ] **Step 1: Reproduce under load.** Start the load with `tmux-ctl send shell 'while :; do TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/run-all.zsh >/dev/null 2>&1; done'`. Note the `shell` pane's loop and stop it by PID afterwards. Then run the Verify loop 2 times (40 runs) with `tmux-ctl run tests`, and save every failing run's full output. To keep `oa`/`ob` on failure, temporarily add `cp "$TT_DIR"/o? "$SCRATCH/"` inside the failing branch of a local copy of the test. Never commit that line.
- [ ] **Step 2: Investigate** following `superpowers-extended-cc:systematic-debugging`: one hypothesis at a time, with evidence for each. Candidate: in `lock_win`, the `mkdir` succeeds before `pid` is written, and a waiter that reads an empty owner never reclaims, so the 30 s timeout (`n++ >= 300`) does not explain a fast failure. Check what `oa`/`ob` actually contain first.
- [ ] **Step 3: Fix** only the evidenced cause. Write a regression check into `test_bg.zsh` if the cause is deterministic enough to test, and name the mutation that makes it fail.
- [ ] **Step 4: Prove it.** Run the Verify loop under load, 20 runs → `20 ALL PASS`, then the full `run-all.zsh`. Stop the load loop by its PID.
- [ ] **Step 5: Commit** (only if code changed): `git commit -m "fix(tmux-ctl): <evidenced cause>"`, ending with the attribution trailer your harness specifies.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_bg.zsh"], "verifyCommand": "for i in {1..20}; do TC_CTL=\"$PWD/bin/tmux-ctl\" zsh tools/tests/test_bg.zsh | tail -1; done | sort | uniq -c", "acceptanceCriteria": ["systematic-debugging followed; root cause named with captured evidence, or 40 loaded runs show no repro after Task 1", "fix limited to evidenced cause", "20 consecutive ALL PASS under a parallel run-all load loop, output in report", "full run-all passes after fix", "load loop stopped by PID"], "modelTier": "standard"}
```

---

### Task 3: `tmux-teammate-window --hook <pane>`

**Goal:** The after-split hook checks only the pane that was just split, so other windows' teammate panes are never moved by somebody else's split.

**Files:**
- Modify: `bin/tmux-teammate-window` (the top, before the `if [[ -n "$1" ]]` branch)
- Modify: `tools/tests/test_teammate_window.zsh`

**Acceptance Criteria:**
- [ ] `tmux-teammate-window --hook <pane>` moves that pane when it is a teammate: the start command carries `--agent-name`, or it is `cat`, the window has more than one pane, and `@tc_teammate` is not set. It leaves any other pane alone.
- [ ] `tmux-teammate-window --hook`, with no pane, and `tmux-teammate-window`, with no args, both still run the full scan.
- [ ] Tests, on a scratch server with the hook line `run-shell -b '<H> --hook #{pane_id}'`:
  - the direct and the `cat` shapes get windows;
  - a plain split stays;
  - an unflagged teammate pane in another window is NOT moved by a split in `claude`;
  - `--hook` without a pane and the bare call each move such a pane.
- [ ] Mutation check: with the `--hook <pane>` branch replaced by a full scan, `--hook ignores other panes` FAILs.

**Verify:** `zsh tools/tests/test_teammate_window.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Update the test.** In `tools/tests/test_teammate_window.zsh`, change the hook line to:

```zsh
tt set-hook -g after-split-window "run-shell -b '$H --hook #{pane_id}'"
```

Insert this before the final `tt_done`, after the existing "plain split stays" check:

```zsh
# --hook <pane> acts on that pane only: an unflagged teammate pane in another window stays put
tt set-hook -gu after-split-window
tt split-window -d -t '=tt:shell' "exec sh -c 'sleep 60; :' teammate --agent-name probe-c"
tt set-hook -g after-split-window "run-shell -b '$H --hook #{pane_id}'"
tt split-window -d -t '=tt:claude'
sleep 2
check "--hook ignores other panes"   test -z "$(win_of probe-c)"
# --hook with no pane: the full scan, as an old hook line would do
"$H" --hook
tt_wait 12 test -n "$(win_of probe-c)"
check "--hook without pane scans"    test -n "$(win_of probe-c)"
tt set-hook -gu after-split-window
tt split-window -d -t '=tt:shell' "exec sh -c 'sleep 60; :' teammate --agent-name probe-d"
"$H"
tt_wait 12 test -n "$(win_of probe-d)"
check "bare call scans"              test -n "$(win_of probe-d)"
```

- [ ] **Step 2: Run it to see it fail.** Run `zsh tools/tests/test_teammate_window.zsh`. Expected: `FAIL - direct shape gets a window`, because the old script treats `--hook` as a pane id and exits.
- [ ] **Step 3: Implement.** In `bin/tmux-teammate-window`, add this right after `T="$HOME/.local/bin/tmux"`, and update the header comment's "Run by the after-split-window hook" line to mention `--hook #{pane_id}`:

```zsh
# Hook with the new pane (`--hook #{pane_id}`): look only at that pane. `--hook` alone, or no
# arguments (an old hook line), falls through to the full scan at the bottom.
if [[ "$1" == --hook && -n "$2" ]]; then
  IFS=$'\t' read -r panes flag cmd <<< "$("$T" display -p -t "$2" '#{window_panes}	#{?#{@tc_teammate},1,0}	#{pane_start_command}' 2>/dev/null)"
  [[ "$panes" -gt 1 && "$flag" != 1 ]] || exit 0
  if [[ "$cmd" =~ "--agent-name '?([A-Za-z0-9_-]+)" ]]; then exec "$0" "$2" "$match[1]"
  elif [[ "$cmd" == (cat|\"cat\") ]]; then exec "$0" "$2"
  fi
  exit 0
fi
[[ "$1" == --hook ]] && shift
```

The separators inside the format string are literal TAB characters. `exec "$0" <pane> [name]` reuses the existing single-pane branch, which waits for the name and moves the pane.

- [ ] **Step 4: Run it to see it pass, then the mutation.** Run `zsh tools/tests/test_teammate_window.zsh` → `ALL PASS`. Temporarily replace the new block's body with `shift 2`, so it falls through to the full scan, re-run, confirm `FAIL - --hook ignores other panes`, and restore it.
- [ ] **Step 5: Commit**

```bash
git add bin/tmux-teammate-window tools/tests/test_teammate_window.zsh
git commit -m "feat(tmux): teammate hook acts only on the split pane with --hook"
```

```json:metadata
{"files": ["bin/tmux-teammate-window", "tools/tests/test_teammate_window.zsh"], "verifyCommand": "zsh tools/tests/test_teammate_window.zsh", "acceptanceCriteria": ["--hook <pane> moves only that pane when it is an unflagged teammate in a multi-pane window", "--hook alone and no-args keep the full scan", "tests: direct+cat shapes, plain split stays, other window's teammate untouched, --hook-without-pane and bare call scan", "mutation (full scan in --hook branch) FAILs '--hook ignores other panes'"], "modelTier": "mechanical"}
```

---

### Task 4: `tmux-ctl artifact` lets the hook decide the kind

**Goal:** `tmux-ctl artifact <path>` registers plans and specs with their real kind. It passes `--kind` only when the user gave one.

**Files:**
- Modify: `bin/tmux-ctl` (`artifact)` case, ~:369-377)
- Create: `tools/tests/test_ctl_artifact.zsh`

**Acceptance Criteria:**
- [ ] Without `--kind`, `artifact-register.sh` gets no `--kind`, and the manifest records `plan` for `…/docs/superpowers/plans/x.md`, `spec` for `…/specs/y.md`, and `other` for any other `.md`.
- [ ] `--kind other` on a spec path records `other`.
- [ ] The printed line is `registered <path> (<kind recorded in the manifest>)`.
- [ ] Mutation check: restoring the hard-coded `k=other` FAILs `plan auto kind`.

**Verify:** `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_artifact.zsh` → `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the failing test** `tools/tests/test_ctl_artifact.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup claude
m="$TC_STATE/artifacts-tt.jsonl"
kind_of() { jq -r --arg p "$1" 'select(.path==$p)|.kind' "$m" | tail -1 }
mkdir -p "$TT_DIR/r/docs/superpowers/plans" "$TT_DIR/r/docs/superpowers/specs"
plan="$TT_DIR/r/docs/superpowers/plans/x.md"; print "# X" > "$plan"
spec="$TT_DIR/r/docs/superpowers/specs/y.md"; print "# Y" > "$spec"
note="$TT_DIR/r/notes.md"; print "# N" > "$note"
$C artifact "$plan" >/dev/null
check "plan auto kind"      test "$(kind_of "$plan")" = plan
$C artifact "$spec" >/dev/null
check "spec auto kind"      test "$(kind_of "$spec")" = spec
$C artifact "$note" >/dev/null
check "other fallback"      test "$(kind_of "$note")" = other
print "# Y2" > "$spec"
$C artifact "$spec" --kind other >/dev/null
check "explicit kind wins"  test "$(kind_of "$spec")" = other
check "prints the kind"     sh -c "$C artifact ${(q)plan} | grep -q '(plan)\$'"
tt_done
```

- [ ] **Step 2: Run it to see it fail.** Run `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_artifact.zsh`. Expected: `FAIL - plan auto kind` and `FAIL - spec auto kind`.
- [ ] **Step 3: Implement.** Replace the `artifact)` case body in `bin/tmux-ctl` with:

```zsh
  artifact)
    [[ -n "$1" ]] || die "usage: tmux-ctl artifact <path> [--kind plan|spec|handoff|report|other]"
    p="${1:A}"; shift; k=""
    [[ "$1" == --kind && -n "$2" ]] && k="$2"
    [[ -f "$p" ]] || die "no file '$p'"
    warn_web_key
    # no --kind: the hook's kind_of() decides (plan, spec, handoff, report), else "other"
    "$HOME/.claude/hooks/artifact-register.sh" --path "$p" ${k:+--kind "$k"} --project "$FEEDKEY"
    k="$(jq -r --arg p "$p" 'select(.path==$p)|.kind' "$STATE/artifacts-$FEEDKEY.jsonl" 2>/dev/null | tail -1)"
    print -r -- "registered $p (${k:-unknown})" ;;
```

- [ ] **Step 4: Run it to see it pass, then the mutation.** The test → `ALL PASS`. Then `TC_CTL="$PWD/bin/tmux-ctl" zsh tools/tests/test_ctl_relay.zsh` → `ALL PASS`, since it uses `--kind handoff`. Temporarily set `k=other` on the `p=` line, re-run, confirm `FAIL - plan auto kind`, and restore it.
- [ ] **Step 5: Commit**

```bash
git add bin/tmux-ctl tools/tests/test_ctl_artifact.zsh
git commit -m "fix(tmux-ctl): artifact passes --kind only when given"
```

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_ctl_artifact.zsh"], "verifyCommand": "TC_CTL=\"$PWD/bin/tmux-ctl\" zsh tools/tests/test_ctl_artifact.zsh", "acceptanceCriteria": ["no --kind: plan/spec/other recorded by hook kind_of", "explicit --kind other wins on a spec path", "prints 'registered <path> (<recorded kind>)'", "test_ctl_relay still passes", "mutation k=other FAILs 'plan auto kind'"], "modelTier": "mechanical"}
```

---

### Task 5: `usage.card_labels` with shared window matching

**Goal:** Compute each agent window's `role · model · effort` label with the same project-scoped matching rules as `card_alerts`, through one shared helper.

**Files:**
- Modify: `board/usage.py` (`card_alerts` at ~:407-440; add `EFFORT_ABBR`, `_project_live`, `_agent_windows` and `card_labels`)
- Test: `board/tests/test_usage.py` (new `CardLabelsTest` after `CardAlertsTest`)

**Acceptance Criteria:**
- [ ] `card_alerts` is rewritten on `_agent_windows`, and every existing `CardAlertsTest` test still passes, unchanged.
- [ ] `card_labels` sets `s["usage_labels"]` (matched only) and returns `{pane_id: entry or None}` for every teammate, worker and `claude` window.
- [ ] The labels are `✦ mate · haiku·low` (teammate), `claude · opus·high` (lead), `w1 · sonnet·med` (worker), and `claude · sonnet` without an effort.
- [ ] Effort `medium→med`; `xhigh` is shown as is.
- [ ] A teammate with the same name in another project gets no label.
- [ ] Mutation check: dropping `_project_live` (using `live` directly) FAILs `test_same_name_teammate_in_other_project_gets_no_label`.

**Verify:** `python3 -m unittest board.tests.test_usage -v 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.** Add this to `board/tests/test_usage.py` after `CardAlertsTest`:

```python
class CardLabelsTest(unittest.TestCase):
    def sess(self):
        return CardAlertsTest.sess(self)

    def live(self, **kw):
        e = {"session_id": "x", "name": "n", "role": "lead", "model": "claude-sonnet-5-5", "effort": "medium",
             "agent_name": None, "cwd": "/r", "alerts": []}
        e.update(kw); return e

    def test_teammate_label(self):
        s = self.sess()
        out = usage.card_labels([s], [self.live(role="teammate", agent_name="mate", model="claude-haiku-5-5", effort="low",
                                                cwd="/r/.claude/worktrees/x")])
        want = {"role": "teammate", "model": "haiku", "effort": "low", "label": "✦ mate · haiku·low"}
        self.assertEqual(s["usage_labels"]["%2"], want)
        self.assertEqual(out["%2"], want)

    def test_lead_label(self):
        s = self.sess(); usage.card_labels([s], [self.live(model="claude-opus-5-5", effort="high")])
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · opus·high")

    def test_worker_label_uses_window_name(self):
        s = self.sess(); usage.card_labels([s], [self.live(role="worker", cwd="/r/.claude/worktrees/w1")])
        self.assertEqual(s["usage_labels"]["%3"]["label"], "w1 · sonnet·med")

    def test_effort_abbreviations(self):
        for eff, ab in [("low", "low"), ("medium", "med"), ("high", "high"), ("max", "max"), ("xhigh", "xhigh")]:
            s = self.sess(); usage.card_labels([s], [self.live(effort=eff)])
            self.assertEqual(s["usage_labels"]["%1"]["effort"], ab, eff)

    def test_no_effort_drops_suffix(self):
        s = self.sess(); usage.card_labels([s], [self.live(effort=None)])
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · sonnet")
        self.assertEqual(s["usage_labels"]["%1"]["effort"], "")

    def test_unmatched_agent_windows_map_to_none(self):
        s = self.sess(); out = usage.card_labels([s], [])
        self.assertEqual(out, {"%1": None, "%2": None, "%3": None})
        self.assertEqual(s["usage_labels"], {})

    def test_non_agent_window_not_returned(self):
        s = self.sess(); s["windows"].append({"name": "shell", "teammate": False, "worker": False, "panes": [{"id": "%4", "path": "/r"}]})
        self.assertNotIn("%4", usage.card_labels([s], [self.live()]))

    def test_same_name_teammate_in_other_project_gets_no_label(self):
        a, b = self.sess(), self.sess(); a["path"] = "/a"; b["path"] = "/b"
        usage.card_labels([a, b], [self.live(role="teammate", agent_name="mate", cwd="/b/.claude/worktrees/x")])
        self.assertNotIn("%2", a["usage_labels"])
        self.assertIn("%2", b["usage_labels"])
```

- [ ] **Step 2: Run them to see them fail.** Run `python3 -m unittest board.tests.test_usage -k CardLabels -v`. Expected: `AttributeError: module 'usage' has no attribute 'card_labels'`.
- [ ] **Step 3: Implement.** In `board/usage.py`, replace `card_alerts` with the following. The docstring of `card_alerts` keeps its rule text, now on `_agent_windows`.

```python
EFFORT_ABBR = {"low": "low", "medium": "med", "high": "high", "max": "max"}


def _project_live(s, live):
    repo = s.get("path") or ""
    return [e for e in live if repo and in_project(e.get("cwd"), repo)]   # every rule looks only at this project's sessions


def _agent_windows(s, mine):
    """Yield (window, pane, live entry or None) for each agent window of card s.

    `mine` is newest-first (live_sessions order), already scoped to the project. Rules: a teammate window
    "✦ <name>" matches the session whose agent_name is <name>; a worker pane matches a session without
    agent_name by cwd == pane path; the `claude` window's first pane matches the newest session without
    agent_name whose cwd is the repo. Other windows are not agent windows and are skipped.
    """
    repo = s.get("path") or ""
    for w in s.get("windows", []):
        panes = w.get("panes") or []
        if not panes:
            continue
        hit, target = None, panes[0]
        if w.get("teammate"):
            name = re.sub(r"^✦\s*", "", w.get("name", ""))
            hit = next((e for e in mine if e.get("agent_name") == name), None)
        elif w.get("worker"):
            for pane in panes:
                hit = next((e for e in mine if not e.get("agent_name") and e.get("cwd") == pane.get("path")), None)
                if hit:
                    target = pane
                    break
        elif w.get("name") == "claude":
            hit = next((e for e in mine if not e.get("agent_name") and e.get("cwd") == repo), None)
        else:
            continue
        yield w, target, hit


def card_alerts(sessions, live):
    """Attach usage alerts to board cards: s["usage_alerts"] = {pane id: [alerts]}, s["usage_alert_count"].

    Matching is _agent_windows'. The count covers every live session in the project, matched or not, so it
    equals the number of alerts the Usage tab lists.
    """
    for s in sessions:
        mine = _project_live(s, live)
        s["usage_alerts"] = {p["id"]: e["alerts"] for _, p, e in _agent_windows(s, mine) if e and e.get("alerts")}
        s["usage_alert_count"] = sum(len(e.get("alerts") or []) for e in mine)
    return sessions


def card_labels(sessions, live):
    """s["usage_labels"] = {pane id: {role, model, effort, label}} for matched agent windows.

    Returns {pane id: entry or None} for every agent window, so sync_labels can unset unmatched ones.
    Label: "<window name> · <family>" plus "·<effort>" when there is one.
    """
    wanted = {}
    for s in sessions:
        labels = {}
        for w, p, e in _agent_windows(s, _project_live(s, live)):
            if e is None:
                wanted[p["id"]] = None
                continue
            fam = _family(e.get("model") or "")
            eff = e.get("effort") or ""
            eff = EFFORT_ABBR.get(eff, eff)
            text = f"{w.get('name', '')} · {fam}" + (f"·{eff}" if eff else "")
            labels[p["id"]] = wanted[p["id"]] = {"role": e.get("role") or "", "model": fam, "effort": eff, "label": text}
        s["usage_labels"] = labels
    return wanted
```

- [ ] **Step 4: Run them to see them pass, then the mutation.** Run `python3 -m unittest board.tests.test_usage -v` → `OK`, with every `CardAlertsTest` test still passing. Temporarily make `_project_live` return `live`, confirm that `test_same_name_teammate_in_other_project_gets_no_label` FAILs, and restore it. Then run `python3 -m unittest discover -s board/tests` → `OK`.
- [ ] **Step 5: Commit**

```bash
git add board/usage.py board/tests/test_usage.py
git commit -m "feat(board): card_labels from the usage snapshot, sharing card_alerts matching"
```

```json:metadata
{"files": ["board/usage.py", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest board.tests.test_usage -v", "acceptanceCriteria": ["card_alerts rewritten on _agent_windows, CardAlertsTest unchanged and passing", "card_labels sets s[usage_labels] matched-only, returns pane->entry|None for every agent window", "labels: teammate/lead/worker/no-effort exact strings", "effort medium->med, xhigh as-is", "same-name teammate in another project unlabelled", "mutation (no project scoping) FAILs the cross-project test"], "modelTier": "mechanical"}
```

---

### Task 6: `sync_labels` writes `@tc_label`, `api/state` carries labels, cards show them

**Goal:** The board server keeps each agent window's `@tc_label` equal to its usage label, from the indexer thread and only on change. `api/state` carries `usage_labels`, and the card shows `role · model · effort` in place of `window N`.

**Files:**
- Modify: `board/usage.py` (`Indexer.__init__` and `Indexer.scan`: `on_snapshot` callback)
- Modify: `board/server.py` (new `label_targets`, `sync_labels`; `build_state` calls `usage.card_labels`; the `__main__` block wires `on_snapshot`)
- Modify: `board/index.html` (~:490, card `who` line)
- Test: `board/tests/test_usage.py` (`IndexerTest` and `UsageApiTest`)

**Acceptance Criteria:**
- [ ] `Indexer(…, on_snapshot=f)` calls `f(live)` after each successful snapshot. An exception in `f` is logged once through `_log_once` and does not set `ix.error` or stop the scan.
- [ ] `label_targets()` reads one `tmux list-panes -a` with no pane captures. It skips `_web-` sessions and `@tc_bg` sessions, and gives sessions shaped like `build_state`'s, plus each window's current `label`.
- [ ] `sync_labels(live, run=tmux)`:
  - issues `set-option -w -t <pane> @tc_label <label>` only when the wanted label differs from the current one;
  - issues `set-option -wu -t <pane> @tc_label` only for an agent window with a label and no match;
  - never touches a non-agent window.
- [ ] `build_state()` sessions carry `usage_labels` from the snapshot.
- [ ] The card's second line reads `teammate · haiku · low` when it has a label, and stays `… window N …` when it doesn't.
- [ ] Mutation check: removing the "unchanged" comparison in `sync_labels` FAILs `test_sync_labels_writes_only_on_change`.
- [ ] `python3 -m unittest discover -s board/tests` → OK.

**Verify:** `python3 -m unittest discover -s board/tests 2>&1 | tail -3` → `OK`

**Steps:**

- [ ] **Step 1: Write the failing tests.**

In `IndexerTest`, add:

```python
    def test_on_snapshot_gets_live_list(self):
        got = []
        ix = usage.Indexer(self.root, self.tmp / "u3.sqlite", alerts_path=self.tmp / "none.json", on_snapshot=got.append)
        self.addCleanup(ix.close)
        ix.scan()
        self.assertEqual(len(got), 1)
        self.assertEqual([e["session_id"] for e in got[0]], [e["session_id"] for e in ix.snapshot()])

    def test_on_snapshot_error_is_logged_not_fatal(self):
        import contextlib, io
        def boom(live): raise RuntimeError("tmux gone")
        ix = usage.Indexer(self.root, self.tmp / "u4.sqlite", alerts_path=self.tmp / "none.json", on_snapshot=boom)
        self.addCleanup(ix.close)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            ix.scan(); ix.scan()
        self.assertEqual(err.getvalue().count("tmux gone"), 1)
        self.assertIsNone(ix.error)
        self.assertTrue(ix.snapshot())
```

In `UsageApiTest`, add:

```python
    def label_rows(self, *rows):
        return "\n".join(self.server.SEP.join(r) for r in rows)

    def fake_tmux(self, listing):
        calls = []
        def run(*a, check=False):
            if a[0] == "list-panes":
                return listing
            calls.append(a); return ""
        return run, calls

    LEAD = {"session_id": "x", "role": "lead", "model": "claude-sonnet-5-5", "effort": "medium", "agent_name": None, "cwd": "/r", "alerts": []}

    def test_sync_labels_sets_wanted_label(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""]))
        self.server.sync_labels([self.LEAD], run=run)
        self.assertEqual(calls, [("set-option", "-w", "-t", "%1", "@tc_label", "claude · sonnet·med")])

    def test_sync_labels_writes_only_on_change(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", "claude · sonnet·med"]))
        self.server.sync_labels([self.LEAD], run=run)
        self.assertEqual(calls, [])

    def test_sync_labels_unsets_unmatched_agent_window(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""],
                                                    ["p", "2", "✦ gone", "", "1", "", "%2", "/r", "old label"]))
        self.server.sync_labels([], run=run)
        self.assertEqual(calls, [("set-option", "-wu", "-t", "%2", "@tc_label")])

    def test_sync_labels_leaves_non_agent_and_bg_windows(self):
        run, calls = self.fake_tmux(self.label_rows(["p", "1", "claude", "", "", "", "%1", "/r", ""],
                                                    ["p", "2", "shell", "", "", "", "%2", "/r", "x"],
                                                    ["p-bg", "1", "claude", "", "", "1", "%3", "/r", "y"],
                                                    ["_web-1", "1", "claude", "", "", "", "%4", "/r", "z"]))
        self.server.sync_labels([], run=run)
        self.assertEqual(calls, [])

    def test_build_state_carries_usage_labels(self):
        fake = mock.Mock(); fake.snapshot.return_value = [dict(self.LEAD)]
        S = self.server.SEP
        row = S.join(["proj", "1", "1", "claude", "0", "", "0", "%1", "t", "zsh", "/r", "1", "1", "", ""])
        with mock.patch.object(self.server, "INDEXER", fake), mock.patch.object(self.server, "tmux", return_value=row), \
             mock.patch.object(self.server, "pane_text", return_value=[]), mock.patch.object(self.server, "cached_worktrees", return_value=[]):
            s = self.server.build_state()["sessions"][0]
        self.assertEqual(s["usage_labels"]["%1"]["label"], "claude · sonnet·med")
```

- [ ] **Step 2: Run them to see them fail.** Run `python3 -m unittest board.tests.test_usage -v 2>&1 | grep -E 'FAIL|ERROR' | head`. Expected: an `unexpected keyword argument 'on_snapshot'` TypeError, `no attribute 'sync_labels'`, and a `KeyError: 'usage_labels'`.
- [ ] **Step 3: Implement `on_snapshot`** in `board/usage.py`:
  - `def __init__(self, root, db, alerts_path=None, on_snapshot=None):` stores `self.on_snapshot = on_snapshot`.
  - In `scan`, right after the `with self._lock:` block that sets `self._snapshot = live` (still inside the outer `try`), add:

```python
            if self.on_snapshot:
                try:
                    self.on_snapshot(live)
                except Exception as e:   # noqa: BLE001 - a tmux hiccup must not stop indexing
                    self._log_once("on_snapshot", e)
```

- [ ] **Step 4: Implement the server side** in `board/server.py`.
  - Add this after `build_state`:

```python
def label_targets(run=None):
    """Sessions shaped like build_state's, with each window's current @tc_label; one list-panes, no captures."""
    fmt = SEP.join(["#{session_name}", "#{window_index}", "#{window_name}", "#{@tc_agent}", "#{@tc_teammate}",
                    "#{@tc_bg}", "#{pane_id}", "#{pane_current_path}", "#{@tc_label}"])
    sessions = {}
    for f in ((run or tmux)("list-panes", "-a", "-F", fmt).splitlines()):
        f = f.split(SEP)
        if len(f) != 9 or f[0].startswith("_web-") or f[5] == "1":
            continue
        sess, widx, wname, agent, mate, _, pid, path, label = f
        s = sessions.setdefault(sess, {"name": sess, "path": None, "windows": {}})
        w = s["windows"].setdefault(widx, {"name": wname, "worker": agent == "1", "teammate": mate == "1",
                                           "label": label, "panes": []})
        w["panes"].append({"id": pid, "path": path})
        if s["path"] is None or widx == "1":
            s["path"] = path
    for s in sessions.values():
        s["windows"] = [s["windows"][k] for k in sorted(s["windows"], key=int)]
    return list(sessions.values())


def sync_labels(live, run=None):
    """Keep each agent window's @tc_label equal to its usage label; unset it when no live session matches.

    Runs in the indexer thread (Indexer on_snapshot), never on the api/state path. Writes only on change.
    """
    run = run or tmux
    sessions = label_targets(run)
    current = {p["id"]: w["label"] for s in sessions for w in s["windows"] for p in w["panes"]}
    for pane, e in usage.card_labels(sessions, live).items():
        want = e["label"] if e else ""
        if want == current.get(pane, ""):
            continue
        if want:
            run("set-option", "-w", "-t", pane, "@tc_label", want)
        else:
            run("set-option", "-wu", "-t", pane, "@tc_label")
```

  - In `build_state`, replace the `usage.card_alerts(out, INDEXER.snapshot() if INDEXER else [])` line with:

```python
    snap = INDEXER.snapshot() if INDEXER else []
    usage.card_alerts(out, snap)
    usage.card_labels(out, snap)
```

  - In `__main__`: `INDEXER = usage.Indexer(usage.root(), usage.db_path(), on_snapshot=sync_labels)`.

- [ ] **Step 5: The card text** in `board/index.html` (~:490). Replace `` `window ${w.index}` `` in the `who.append(el("span", …))` array with `lab ? [lab.role, lab.model, lab.effort].filter(Boolean).join(" · ") : `window ${w.index}``. Declare `const lab = (s.usage_labels || {})[p.id];` on the line above `who.append(el("b", …))`.
- [ ] **Step 6: Run them to see them pass, then the mutation.** Run `python3 -m unittest discover -s board/tests` → `OK`. Temporarily delete the `if want == current.get(pane, ""): continue` lines, confirm that `test_sync_labels_writes_only_on_change` FAILs, and restore them.
- [ ] **Step 7: Commit**

```bash
git add board/usage.py board/server.py board/index.html board/tests/test_usage.py
git commit -m "feat(board): sync agent labels to @tc_label and show them on cards"
```

```json:metadata
{"files": ["board/usage.py", "board/server.py", "board/index.html", "board/tests/test_usage.py"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["Indexer on_snapshot called with live after each snapshot; exception logged once, not fatal, error stays None", "label_targets: one list-panes, skips _web- and @tc_bg, carries current label", "sync_labels sets only on change, unsets only labelled unmatched agent windows, ignores non-agent windows", "build_state sessions carry usage_labels", "card line shows role · model · effort when labelled, window N otherwise", "mutation (no change check) FAILs test_sync_labels_writes_only_on_change", "board suite OK"], "modelTier": "standard"}
```

---

### Task 7: Board offline banner, with polls gated on `refresh()`

**Goal:** While the board server is down, the board shows one banner, skips the other pollers and logs nothing to the console. It recovers on the next successful poll.

**Files:**
- Modify: `board/index.html` (header markup ~:294-306, CSS near `.live` ~:72, `refresh()` ~:630, `poll()` ~:1428)

**Acceptance Criteria:**
- [ ] `refresh()` returns `true` after `api/state` answered with JSON, and `false` otherwise.
- [ ] `poll()` calls `pollArtifacts`, `pollIdeas` and `pollActivity` only after a `true`.
- [ ] `#offline-banner` with the text "Board server unreachable — retrying" is visible (non-zero bounding box) while offline, and `hidden` after the next `true`. The `#live` dot still switches to `offline`.
- [ ] No `console.error` while offline. A `TypeError` from `fetch` inside the gated pollers marks the board offline instead of logging. Other errors are logged once per distinct message.
- [ ] Both themes: the banner uses `--red-soft` / `--red` tokens.
- [ ] `python3 -m unittest discover -s board/tests` → OK. The live behaviour is proven in Task 10.

**Verify:** `grep -c 'offline-banner' board/index.html` → `≥ 3` (markup, CSS, JS), and `python3 -m unittest discover -s board/tests` → `OK`

**Steps:**

- [ ] **Step 1: Markup.** Add `<div class="offline-banner" id="offline-banner" role="status" hidden>Board server unreachable — retrying</div>` on the line right after `</header>`.
- [ ] **Step 2: CSS.** Add this after the `.live.off i` rule:

```css
.offline-banner { background: var(--red-soft); color: var(--red); border-bottom: 1px solid var(--red); padding: 6px 16px; font-size: 13px; text-align: center; }
.offline-banner[hidden] { display: none; }
```

- [ ] **Step 3: `refresh()`.** Replace the function with:

```js
function setOffline(off) {
  $("#live").classList.toggle("off", off); $("#live span").textContent = off ? "offline" : "live";
  $("#offline-banner").hidden = !off;
}
async function refresh() {
  try {
    const r = await fetch(`${API}/state`, { cache: "no-store" });
    data = await r.json();
  } catch (e) { setOffline(true); return false; }
  setOffline(false);
  if (!session() && data.sessions[0]) current = data.sessions[0].name;
  const n = (session() || {}).usage_alert_count || 0;
  $("#act-alerts").textContent = n ? `${n} alert${n === 1 ? "" : "s"}` : "";
  render();
  return true;
}
```

- [ ] **Step 4: `poll()`.** Replace the last line (~:1428) with:

```js
const loggedErrors = new Set();   // log each distinct error once, not every 2 s
function logOnce(e) { const k = String((e && e.message) || e); if (!loggedErrors.has(k)) { loggedErrors.add(k); console.error(e); } }
(async function poll() {
  try { if (await refresh()) { await pollArtifacts(); await pollIdeas(); await pollActivity(); } }
  catch (e) { if (e instanceof TypeError && /fetch/i.test(e.message)) setOffline(true); else logOnce(e); }
  finally { setTimeout(poll, 2000); }
})();
```

- [ ] **Step 5: Check.** Run `grep -n 'offline-banner\|setOffline\|logOnce' board/index.html` to confirm the markup, CSS, the two functions and the poll. Then `python3 -m unittest discover -s board/tests` → `OK`.
- [ ] **Step 6: Commit**

```bash
git add board/index.html
git commit -m "fix(board): offline banner and no poll errors while the server is down"
```

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["refresh returns true/false", "poll runs other pollers only after true", "#offline-banner shown offline, hidden after recovery, #live still toggles", "no console.error offline; fetch TypeError sets offline; others logged once per message", "banner uses --red-soft/--red tokens", "board suite OK"], "modelTier": "mechanical"}
```

---

### Task 8: Doc pane follows its own project

**Goal:** A document opened in project A keeps rendering from A's versions, saves and comments to A, and isn't re-rendered while the board shows project B.

**Files:**
- Modify: `board/index.html` (`renderDoc` ~:1050 and its save handler, the `#doc-comment` handler ~:1111, `pollArtifacts` ~:938)

**Acceptance Criteria:**
- [ ] `renderDoc` reads versions from `artFor(docSess)`, and returns early when `!docSel || !docSess`. It never reads `session()`.
- [ ] The save, conflict and comment calls inside the doc pane send `session: docSess`.
- [ ] `pollArtifacts` re-renders the doc only when `docSess === s.name`.
- [ ] `grep -n 'session()' board/index.html` shows no use inside `renderDoc` or the `#doc-comment` handler.
- [ ] `python3 -m unittest discover -s board/tests` → OK. The live behaviour is proven in Task 10.

**Verify:** `awk '/^function renderDoc/,/^}/' board/index.html | grep -c 'session()'` → `0`

**Steps:**

- [ ] **Step 1: `renderDoc`.** Replace its first two lines with:

```js
function renderDoc() {
  if (!docSel || !docSess) return;
  const A = artFor(docSess), vs = A.versions.get(docSel) || [];
```

Inside `renderDoc`, replace every `s.name` (the `post({ action: "save", session: s.name, … })` call and `showConflict(s.name, …)`) with `docSess`.

- [ ] **Step 2: Comment box.** In the `$("#doc-comment").onclick` handler, change `const s = session(), box = …` to `const box = …`, and the post's `session: s.name` to `session: docSess`.
- [ ] **Step 3: `pollArtifacts`.** Change `if (docSel && docMode !== "edit") {` to `if (docSel && docSess === s.name && docMode !== "edit") {`.
- [ ] **Step 4: Check.** Run the Verify command → `0`, and `grep -n 'docSess' board/index.html` to show each new use. Then run the board suite → `OK`.
- [ ] **Step 5: Commit**

```bash
git add board/index.html
git commit -m "fix(board): doc pane reads, saves and re-renders under its own project"
```

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "awk '/^function renderDoc/,/^}/' board/index.html | grep -c 'session()'", "acceptanceCriteria": ["renderDoc uses artFor(docSess), no session()", "save/conflict/comment send session: docSess", "pollArtifacts re-renders only when docSess === s.name", "board suite OK"], "modelTier": "mechanical"}
```

---

### Task 9: Staged `~/.tmux.conf` patch

**Goal:** Produce `~/.claude/staged/tmux.conf.patch`, which switches the teammate hook to `--hook #{pane_id}` and drops `#I ` from both window-status formats. It must pass `patch --dry-run` against the live file. The live file is not edited.

**Files:**
- Create: `~/.claude/staged/tmux.conf.patch` (outside the repo)
- Read only: `~/.tmux.conf`

**Acceptance Criteria:**
- [ ] The patch is generated with `diff -u` from a copy of the live file and an edited copy, never typed. It changes exactly 3 lines: the `after-split-window` hook, `window-status-format` and `window-status-current-format`.
- [ ] `patch --dry-run ~/.tmux.conf < ~/.claude/staged/tmux.conf.patch` succeeds.
- [ ] The edited lines load in a scratch server: `~/.local/bin/tmux -L tcconf -f /dev/null` with a file holding only the 3 edited lines sourced, and `show-hooks -g after-split-window` contains `--hook #{pane_id}`. The scratch server is killed afterwards. Never source the full file there: it restores resurrect/continuum sessions.
- [ ] `~/.tmux.conf` sha256 is unchanged before and after the task.
- [ ] The report gives the install command from the spec, and the note that the patch goes in only after the branch is merged to `main`, because the hook calls the `main` checkout through the symlink.

**Verify:** `patch --dry-run ~/.tmux.conf < ~/.claude/staged/tmux.conf.patch && grep -c '^[-+][^-+]' ~/.claude/staged/tmux.conf.patch` → `checking file …` and `6`

**Steps:**

- [ ] **Step 1: Generate.**

```bash
S=$(mktemp -d); shasum -a 256 ~/.tmux.conf | tee "$S/sha.before"
cp ~/.tmux.conf "$S/live"; mkdir -p ~/.claude/staged
python3 - "$S/live" "$S/edited" <<'EOF'
import sys
s = open(sys.argv[1]).read()
old_hook = 'run-shell -b "~/.local/bin/tmux-teammate-window"'
assert s.count(old_hook) == 1, "hook line"
assert s.count('] #I #{?@tc_label') == 2, "status formats"
s = s.replace(old_hook, 'run-shell -b "~/.local/bin/tmux-teammate-window --hook #{pane_id}"')
s = s.replace('] #I #{?@tc_label', '] #{?@tc_label')
open(sys.argv[2], "w").write(s)
EOF
diff -u "$S/live" "$S/edited" | sed "1s|$S/live|$HOME/.tmux.conf|; 2s|$S/edited|$HOME/.tmux.conf|" > ~/.claude/staged/tmux.conf.patch
patch --dry-run ~/.tmux.conf < ~/.claude/staged/tmux.conf.patch
```

- [ ] **Step 2: Scratch load.**

```bash
grep -E 'after-split-window|window-status-(current-)?format' "$S/edited" > "$S/lines.conf"
~/.local/bin/tmux -L tcconf -f /dev/null new-session -d -s c
~/.local/bin/tmux -L tcconf source-file "$S/lines.conf"
~/.local/bin/tmux -L tcconf show-hooks -g after-split-window
~/.local/bin/tmux -L tcconf show-options -gw window-status-format
~/.local/bin/tmux -L tcconf kill-server
```

Expected: the hook shows `--hook #{pane_id}`, and the format starts `#[fg=#6c7086] #{?@tc_label`.

- [ ] **Step 3: Confirm the live file is untouched.** Run `shasum -a 256 ~/.tmux.conf | diff - "$S/sha.before"` → no output. Report the patch text, the dry-run output and the install command.

```json:metadata
{"files": ["~/.claude/staged/tmux.conf.patch"], "verifyCommand": "patch --dry-run ~/.tmux.conf < ~/.claude/staged/tmux.conf.patch", "acceptanceCriteria": ["patch generated by diff -u from live and edited copies, 3 changed lines", "patch --dry-run passes against live", "edited lines load in a -f /dev/null scratch server; hook has --hook #{pane_id}; server killed", "~/.tmux.conf sha256 unchanged", "report gives install command and install-after-merge note"], "modelTier": "mechanical"}
```

---

### Task 10: Live e2e on a scratch board, with real usage state

**Goal:** Prove the offline banner, the labels and the doc pane on a scratch board that reads the real `~/.claude/projects` read-only. Also prove the busy check against the real tmux server, read-only.

**Files:**
- None committed, unless a defect is found. In that case, report it to the lead; don't fix it in this task.

**Acceptance Criteria:**
- [ ] **Setup:**
  - a scratch board on `TMUX_DASH_PORT=7713` with `TMUX_DASH_TMUX_ARGS='-L gc -f /dev/null'`, scratch `TC_STATE` and `TC_IDEAS_DIR`, and `USAGE_ROOT` unset, so it reads the real `~/.claude/projects` read-only;
  - started from the worktree's `board/server.py`;
  - the scratch tmux server `gc` has a session `agent-board` whose `claude` window's cwd is `~/agent-board`, plus one `✦ <name>` window for each live teammate in this repo and one `✦ nobody` window with `@tc_teammate 1` and `@tc_label stale`.
- [ ] **Labels, real state:** within 15 s of indexing finishing, the `claude` window's `@tc_label` equals `claude · <family>·<effort>`.
  - The family and effort are taken independently from the newest assistant line of the newest `~/.claude/projects/-Users-francisco-ruiz-agent-board/*.jsonl` that has no `agentName`, read with `jq`, not through `board/usage.py`.
  - Each live teammate's window label matches its own transcript the same way.
  - `✦ nobody`'s `@tc_label` is unset.
- [ ] **Labels, aged state:** the `api/state` card for the `claude` window carries `usage_labels` with `role` `lead`. Report the transcript's first-line date, which must be older than today, and the number of live sessions in the snapshot, which must be ≥ 2.
- [ ] **Offline:** in a new Chrome tab with `window.confirm` overridden, the board loads.
  - After the scratch board's PID is killed, within 5 s `#offline-banner` has a non-zero `getBoundingClientRect()` and computed `display` is not `none`.
  - Over the next 3 poll ticks, `read_console_messages` with pattern `Failed to fetch|TypeError` returns nothing.
  - After a restart on the same port, the banner's box is zero within 5 s.
  - Negative control: before the kill, the banner's box is zero.
- [ ] **Doc pane:**
  - Register a plan in scratch project A (`tmux-ctl artifact` with `TC_STATE` pointed at the scratch dir and `TC_SESSION=A`) and open it in Changes view.
  - Switch to project B. `#doc-body` text is not `Loading…`, and `#doc-title` still names A's file.
  - Negative control: the same check on `main`'s `index.html`, served from a second scratch board on port 7714, shows `Loading…`.
- [ ] **Busy check, real state (read-only):** `bin/tmux-ctl list` from the worktree, against the user's live server, shows the user's `shell` window `[idle]` (when the user isn't running anything there) and this session's `claude` window `[busy]`. Paste the output.
- [ ] **Cleanup:** both scratch boards are stopped by PID, `tmux -L gc kill-server` is run, and the Chrome tab is closed. `~/.claude/projects`: `find ~/.claude/projects -newer <marker> -name '*.jsonl'` lists only files written by live sessions, and none of them is the scratch board's.

**Verify:** the report shows, for each criterion above, the command or probe, its raw output, and PASS or FAIL. A probe that could not fail (for example a negative control that didn't differ) counts as FAIL.

**Steps:**

- [ ] **Step 1:** `touch "$SCRATCH/marker"`. Create the `gc` tmux server with `-f /dev/null` and the windows from the Setup criterion. Set `@tc_teammate 1` on the `✦` windows.
- [ ] **Step 2:** Start the scratch board with `tmux-ctl send shell 'cd <worktree> && TMUX_DASH_TOKEN=gc TMUX_DASH_PORT=7713 TMUX_DASH_TMUX_ARGS="-L gc -f /dev/null" TC_STATE=<scratch>/state TC_IDEAS_DIR=<scratch>/ideas python3 board/server.py & echo PID=$!'`. Record the PID.
- [ ] **Step 3:** Poll `curl -s http://127.0.0.1:7713/gc/api/usage?session=agent-board` until indexing is done. Then check the labels (`~/.local/bin/tmux -L gc show-options -wqv -t '=agent-board:claude' @tc_label`) against the independent `jq` reading.
- [ ] **Step 4:** Load the Chrome tools (`claude-in-chrome` skill), open a new tab on `http://127.0.0.1:7713/gc/`, and run the offline and doc-pane probes with `javascript_tool`. Measure visibility only with `getBoundingClientRect()` and `getComputedStyle`, never `offsetParent`.
- [ ] **Step 5:** Run the read-only `bin/tmux-ctl list` on the live server.
- [ ] **Step 6:** Clean up as in the Cleanup criterion, and report.

```json:metadata
{"files": [], "verifyCommand": "report: each criterion with probe, raw output, PASS/FAIL", "acceptanceCriteria": ["scratch board 7713 on worktree server.py, gc tmux -f /dev/null, real ~/.claude/projects read-only", "claude and live teammate @tc_label match independent jq reading of real transcripts; ✦ nobody unset", "aged state: transcript older than today, >=2 live sessions, api/state usage_labels role lead", "offline banner visible within 5s after kill, no Failed to fetch console errors over 3 ticks, hidden after restart, zero box before kill", "doc pane in project B not Loading…; negative control on main shows Loading…", "real server read-only tmux-ctl list: shell idle, claude busy", "boards stopped by PID, gc server killed, tab closed, projects untouched"], "modelTier": "standard"}
```
