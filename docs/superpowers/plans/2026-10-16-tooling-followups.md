# Tooling and Follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teammates get their own `✦` window again under Claude Code 2.1.301. `tmux-ctl run`/`send` refuse misplaced options. The harness's live-server check stops flaking. The four board fix-batch follow-ups land.

**Architecture:** Five independent tasks on disjoint files, plus one lead check after the merge. Shell changes are tested in the existing zsh harness (scratch tmux server, `-f /dev/null`). Board client changes are checked in a second board started from the worktree.

**Tech Stack:** zsh + tmux, vanilla JS in `board/index.html`, Python `unittest`.

**Spec:** design approved in chat on 2026-10-16 (bounded path, no spec file). Inputs:
- the teammate-window idea entry, 2026-10-16 13:36, in `~/.claude/ideas/agent-board.md`;
- the final review of `docs/superpowers/plans/2026-10-16-board-fix-batch.md`;
- `.superpowers/investigations/flake-and-locks.md` §Issue B in the main checkout.

## Global Constraints

- Work in a worktree (`.claude/worktrees/tooling`) on branch `fix/tooling-followups`, never in the live checkout `~/agent-board`: the live install is symlinked to it and other sessions use it.
- Shell tests use `tools/tests/lib.zsh` (`tt_setup` starts a scratch server with `-f /dev/null`). Never touch the user's tmux server. Never `pkill`/`killall`.
- To exercise worktree copies, set `TC_CTL=<worktree>/bin/tmux-ctl` for tmux-ctl tests. For the hook, pass the worktree path explicitly.
- `tmux-ctl run` syntax: options before the window, `tmux-ctl run -C <dir> tests "<cmd>"`.
- Conventional commits with scope. End every commit with the attribution trailer your harness specifies. Stage only your own paths, never `git add -A`.
- Both suites pass at the end: `python3 -m unittest discover -s board/tests` and `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh`.

**User decisions (already made):**
- Teammate-window fix first, before brainstorming group D (idea management).
- The tmux-ctl option-order bug and the harness flake are bundled into this plan.
- The four fix-batch follow-ups (long press, openDoc, real lock line, cleanup test) are bundled into this plan.
- Accept both teammate start shapes (`cat` and the direct `claude … --agent-name`). A plain split never moves.

---

### Task 1: Teammate panes started directly as claude get their own window

**Goal:** `bin/tmux-teammate-window` moves a teammate pane into a `✦ <name>` window after the lead's window, whether its start command is `cat` or `… --agent-name <name> …`, and never moves a plain split.

**Files:**
- Modify: `bin/tmux-teammate-window`
- Create: `tools/tests/test_teammate_window.zsh`

**Acceptance Criteria:**
- [ ] The hook branch accepts panes whose `#{pane_start_command}` is `cat`/`"cat"`, or contains `--agent-name`, and still requires `window_panes > 1` and `@tc_teammate` unset.
- [ ] When the start command contains `--agent-name '?<name>`, the name is taken from it. The `ps -t <tty>` lookup remains the fallback (used for the `cat` shape).
- [ ] Test, start shape "direct": a split whose command contains `--agent-name probe-a` ends up as window `✦ probe-a`, placed right after the lead window, with `@tc_teammate` 1.
- [ ] Test, start shape "cat then respawn": a split started as `cat`, then `respawn-pane -k` into a command whose args contain `--agent-name probe-b`, ends up as `✦ probe-b`.
- [ ] Test: a plain split (`split-window -d` with a shell) stays in the lead's window.
- [ ] Test: a second teammate goes after the first teammate window (order: lead, `✦ probe-a`, `✦ probe-b`).
- [ ] Tests drive the real hook path: the scratch server gets `set-hook -g after-split-window 'run-shell -b "<worktree>/bin/tmux-teammate-window"'`, the same form as `~/.tmux.conf:62` with the worktree path.

**Verify:** `zsh tools/tests/test_teammate_window.zsh` → `ALL PASS`; RED first on the unchanged hook (the direct-shape check fails).

**Steps:**

- [x] **Step 1: Seam check.** The hook calls `$HOME/.local/bin/tmux` with no `-L`, so it reaches whichever server `$TMUX` names. Under `run-shell` from the scratch server, `$TMUX` is the scratch socket. Confirm this in Step 3's RED run (no window appears on the user's server). If it doesn't hold, add `T="${TC_TMUX:-$HOME/.local/bin/tmux}"` and export `TC_TMUX` in the test.
- [x] **Step 2: Failing test.** Create `tools/tests/test_teammate_window.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
H="${TC_TEAMMATE_HOOK:-${0:A:h:h:h}/bin/tmux-teammate-window}"
tt_setup claude shell
tt set-hook -g after-split-window "run-shell -b '$H'"
lead="$(tt display -p -t '=tt:claude' '#{window_index}')"
win_of() { tt list-windows -t '=tt' -F '#{window_index} #{window_name}' | awk -v n="✦ $1" '$0 ~ n {print $1}' }
# direct shape: the start command itself carries --agent-name (Claude Code 2.1.301)
tt split-window -d -t '=tt:claude' "exec sh -c 'sleep 60' teammate --agent-name probe-a"
tt_wait 12 test -n "$(win_of probe-a)"
check "direct shape gets a window"   test -n "$(win_of probe-a)"
check "placed after the lead"        test "$(win_of probe-a)" = $(( lead + 1 ))
check "flagged teammate"             test "$(tt show-options -wqv -t "=tt:✦ probe-a" @tc_teammate)" = 1
# cat shape: started as cat, then respawned into the teammate command (older Claude)
p="$(tt split-window -d -P -F '#{pane_id}' -t '=tt:claude' cat)"
tt respawn-pane -k -t "$p" "exec sh -c 'sleep 60' teammate --agent-name probe-b"
tt_wait 12 test -n "$(win_of probe-b)"
check "cat shape gets a window"      test -n "$(win_of probe-b)"
check "second teammate after first"  test "$(win_of probe-b)" = $(( lead + 2 ))
# a plain split must stay where it is
before="$(tt list-panes -t '=tt:claude' | wc -l | tr -d ' ')"
tt split-window -d -t '=tt:claude'
sleep 2
check "plain split stays"            test "$(tt list-panes -t '=tt:claude' | wc -l | tr -d ' ')" = $(( before + 1 ))
tt_done
```

Adapt the `sh -c … --agent-name` form if `ps -o args=` doesn't show it. The check is that the args or the start command carry `--agent-name probe-x`, as Claude's do. Run it: `zsh tools/tests/test_teammate_window.zsh`. Expected: "direct shape gets a window" FAILs, and "cat shape" passes or fails depending on the respawn path. Check `~/.local/bin/tmux ls` is unchanged before and after.

- [x] **Step 3: Implement.** In the hook branch at the bottom of `bin/tmux-teammate-window`:

```zsh
# Called by the hook: find new teammate panes still sharing a window. Older Claude starts them
# as `cat` and respawns; 2.1.301 starts them directly as `claude … --agent-name <name> …`.
for line in ${(f)"$("$T" list-panes -a -F '#{pane_id} #{window_panes} #{?#{@tc_teammate},1,0} #{pane_start_command}')"}; do
  read -r id panes flag cmd <<< "$line"
  [[ "$panes" -gt 1 && "$flag" != 1 ]] || continue
  if [[ "$cmd" =~ "--agent-name '?([A-Za-z0-9_-]+)" ]]; then "$0" "$id" "$match[1]" &!
  elif [[ "$cmd" == (cat|\"cat\") ]]; then "$0" "$id" &!
  fi
done
```

In the pane branch, take an optional name: `pane="$1" name="${2:-}"`. Skip the polling loop when `name` is already set: wrap the loop in `if [[ -z "$name" ]]; then … fi`. Update the header comment to describe both shapes.

- [x] **Step 4:** Run the test → `ALL PASS`. Run it 3 times (the hook is async). Run `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/run-all.zsh` through `tmux-ctl run -C <worktree> tests "…"`.
- [x] **Step 5: Commit** `fix(tmux): teammate panes started directly as claude get their own window`.

```json:metadata
{"files": ["bin/tmux-teammate-window", "tools/tests/test_teammate_window.zsh"], "verifyCommand": "zsh tools/tests/test_teammate_window.zsh", "acceptanceCriteria": ["accepts cat or --agent-name start commands with guards", "name from start command, ps fallback", "direct shape test", "cat-respawn shape test", "plain split stays", "second teammate ordered after first", "tests use the real after-split-window hook path"], "modelTier": "standard"}
```

### Task 2: Harness live-server check compares only its own sessions

**Goal:** `test_harness.zsh` "live server untouched" checks that the test left no `tt`/`tt-*` session on the live server, not that the live server's whole `ls` is unchanged.

**Files:**
- Modify: `tools/tests/test_harness.zsh:2,15`

**Acceptance Criteria:**
- [ ] `live_before` and the check use only session names matching `^tt(-|$)` from `"$TT_BIN" ls -F '#{session_name}'` on the live server (no `-L`).
- [ ] The check passes while windows are opened and closed on the live server during the run.

**Verify:** `zsh tools/tests/test_harness.zsh` → `ALL PASS`, 3 runs in a row while another lane is busy.

**Steps:**

- [x] **Step 1:** Replace line 2 and line 15:

```zsh
live_tt() { "$TT_BIN" ls -F '#{session_name}' 2>/dev/null | grep -E '^tt(-|$)' }   # only names the harness could create
live_before="$(live_tt)"
```

```zsh
check "live server untouched"    test "$(live_tt)" = "$live_before"
```

`live_tt` is defined before `tt_setup`. At line 15, `TMUX` is unset, so `$TT_BIN ls` talks to the default (live) server, as before.
- [x] **Step 2:** Run it 3 times → `ALL PASS`.
- [x] **Step 3: Commit** `test(harness): live-server check looks only at harness sessions`.

```json:metadata
{"files": ["tools/tests/test_harness.zsh"], "verifyCommand": "zsh tools/tests/test_harness.zsh", "acceptanceCriteria": ["compares only tt/tt-* session names", "passes while live windows change"], "modelTier": "mechanical"}
```

### Task 3: `tmux-ctl run`/`send` refuse options after the window

**Goal:** `tmux-ctl run tests -C dir cmd` and `send shell -t 5 x` exit 2 with the usage line and type nothing. The reported `[exit N]` is always the command's own exit code. The orchestrator rules show the correct order.

**Files:**
- Modify: `bin/tmux-ctl` (`run` ~line 219, `send` ~line 272, and the exit reporting if Step 1 finds a bug)
- Modify: `claude/orchestrator.md:118,142,146`
- Create: `tools/tests/test_ctl_opts.zsh`

**Acceptance Criteria:**
- [ ] `run <win> -C …`, `run <win> -t …`, `send <win> -C …` exit 2 with "options go before the window", and the bg window shows nothing new typed.
- [ ] `run -C <dir> tests 'pwd'` still prints `<dir>`.
- [ ] Reproduced first: what `tmux-ctl run tests -C /tmp 'true'` prints and its exit status on the unchanged code, recorded in the report. If it ever reports `[exit 0]` for a command that failed, that is fixed and covered by a test (`run tests 'false'` → `[exit 1]` and exit status 1).
- [ ] orchestrator.md rule 5 and the command list show `tmux-ctl run -C <dir> tests "<cmd>"` and say options go before the window.

**Verify:** `TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_ctl_opts.zsh` → `ALL PASS`.

**Steps:**

- [x] **Step 1: Reproduce** (systematic-debugging) on a scratch server via `lib.zsh`: `TC_CTL=<worktree>/bin/tmux-ctl`, then `$C run tests -C "$TT_DIR" 'true'; echo "status=$?"`, and `$C run tests 'false'; echo "status=$?"`. Record the output. One teammate saw `[exit 0]` and another saw exit 127 for the misplaced `-C`. Find out which is real before changing the exit path.
- [x] **Step 2: Failing test** `tools/tests/test_ctl_opts.zsh`:

```zsh
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup
(cd "$TT_DIR" && $C run tests true >/dev/null)            # create the bg session
mark="$(tt capture-pane -p -t '=tt-bg:tests' | grep -c .)"
$C run tests -C "$TT_DIR" 'echo nope' >"$TT_DIR/o" 2>&1; rc=$?
check "run: option after window -> exit 2"   test $rc -eq 2
check "run: says why"                        grep -q 'options go before the window' "$TT_DIR/o"
check "run: nothing typed"                   test "$(tt capture-pane -p -t '=tt-bg:tests' | grep -c .)" = "$mark"
$C run tests -t 5 'echo nope' >/dev/null 2>&1; check "run -t after window -> exit 2" test $? -eq 2
$C send shell -C "$TT_DIR" 'echo nope' >/dev/null 2>&1; check "send: option after window -> exit 2" test $? -eq 2
check "run -C before window still works"     test "$($C run -C "$TT_DIR" tests pwd | head -1)" = "$TT_DIR"
$C run tests false >/dev/null 2>&1; check "failing command -> status 1" test $? -eq 1
tt_done
```

Run → the first checks FAIL.
- [x] **Step 3: Implement.** In both `run` and `send`, right after `win="$1"; shift`:

```zsh
    [[ "$1" == (-t|-C) ]] && die "options go before the window: tmux-ctl $cmd [-t secs] [-C dir] <win> <cmd>"
```

Use the variable that holds the subcommand name in this script (read how `die` and the `case` are written), and make sure `die` exits 2. Check: `grep -n '^die()' bin/tmux-ctl`. If Step 1 found a wrong exit report, fix it at its source and keep the `false` check.
- [x] **Step 4:** Docs: in `claude/orchestrator.md`, rule 5 becomes ``Run test suites and long builds with `tmux-ctl run tests "<cmd>"` (another directory: `tmux-ctl run -C <dir> tests "<cmd>"`; options always go before the window)``, keeping the rest of the sentence. Lines 142/146 get the same order.
- [x] **Step 5:** Run the test → `ALL PASS`, then the full tmux suite with `TC_CTL` set.
- [x] **Step 6: Commit** `fix(tmux-ctl): refuse options after the window name`.

```json:metadata
{"files": ["bin/tmux-ctl", "claude/orchestrator.md", "tools/tests/test_ctl_opts.zsh"], "verifyCommand": "TC_CTL=$PWD/bin/tmux-ctl zsh tools/tests/test_ctl_opts.zsh", "acceptanceCriteria": ["options after window exit 2, nothing typed", "-C before window works", "misreported exit reproduced and fixed if real", "orchestrator.md shows the correct order"], "modelTier": "standard"}
```

### Task 4: Long press cancels on any release; openDoc selects first

**Goal:** A tap or drag that spans the 2 s card rebuild never opens the agent menu. Opening an old doc selects it at once, shows "Loading…", renders only if still selected, and shows an error line if the fetch fails.

**Files:**
- Modify: `board/index.html` (`bindAgentMenu` ~776-803, `openDoc` ~942-951)

**Acceptance Criteria:**
- [ ] One module-level press timer and start point. `pointerup`/`pointercancel` on `document` cancel it, and `pointermove` on `document` beyond 10 px cancels it.
- [ ] A rebuilt card still resolves to the current card when the timer fires (Task 3 of the fix batch kept).
- [ ] `openDoc` sets `docSel`, renders ("Loading…") and highlights the item before any fetch. After the fetch, it renders only if `docSel === path`. On a failed fetch the doc body shows "Couldn't load this document." and no unhandled rejection appears in the console.

**Verify:** browser on a worktree board (port 7710):
- (a) touch `pointerdown` on a card, rebuild, then `pointerup` dispatched on the NEW card within 500 ms → no menu after 700 ms;
- (b) the same without `pointerup` → the menu opens on the new card;
- (c) click two old docs in quick succession → the second one shows;
- (d) `openDoc` with the server stopped → error line, no console error.

**Steps:**

- [x] **Step 1:** Replace the press handling in `bindAgentMenu` (keep the `contextmenu` listener and `card._menuItems = items;`):

```js
  card.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    cancelPress();
    press = { card, x: e.clientX, y: e.clientY, timer: setTimeout(firePress, 500) };
  });
}
// one long press at a time, at page level: the 2 s rebuild replaces the card under the finger,
// so release and move events land on the new card and must still cancel the pending press
let press = null;
function cancelPress() { if (press) clearTimeout(press.timer); press = null; }
function firePress() {
  const p = press; press = null; if (!p) return;
  let c = p.card;
  if (!c.isConnected) {   // the rebuild replaced the card mid-press: use the one showing now
    const k = c.dataset.key;
    c = k ? document.querySelector(`[data-key="${CSS.escape(k)}"]`) : null;
    if (!c || !c._menuItems) return;
  }
  const its = c._menuItems();
  if (its.length) openAgentMenu(p.x, p.y, its, c);
}
document.addEventListener("pointerup", cancelPress);
document.addEventListener("pointercancel", cancelPress);
document.addEventListener("pointermove", (e) => { if (press && Math.hypot(e.clientX - press.x, e.clientY - press.y) > 10) cancelPress(); });
```

Remove the old `lp`, `x0`, `y0`, `cancel` and `fire` and the per-card `pointermove`/`pointerup`/`pointercancel` listeners.
- [x] **Step 2:** Replace `openDoc`:

```js
async function openDoc(path) {
  docSel = path; docMode = "read"; docSelection = null; docRendered = null;
  document.querySelectorAll(".cbox").forEach((b) => b.remove());
  $("#doc-comment").disabled = true;
  const name = session().name, A = artFor(name), it = A.items.get(path);
  docBase = A.seen.get(path);   // changes are shown against what was last viewed before opening
  $("#main").classList.add("with-doc");
  renderDoc(); renderArtifacts();   // selected at once; renderDoc shows "Loading…" until text arrives
  if (!it || A.versions.get(path)) return;
  try { await trackVersion(name, A, it); }
  catch (e) { if (docSel === path) $("#doc-body").textContent = "Couldn't load this document."; return; }
  if (docSel === path) renderDoc();
}
```

Check `trackVersion` returns without throwing on `!r.ok`. A non-OK response leaves "Loading…" and the next poll retries, because `hot()` includes `docSel`. That's acceptable. Only a network error throws.
- [x] **Step 3:** Run the Verify browser checks (a)–(d) on your own board: `TMUX_DASH_TOKEN=bb$RANDOM TMUX_DASH_PORT=7710 TMUX_DASH_TTYD_PORT=7701 python3 board/server.py &`. Kill only that PID. Don't click agent-menu items: they stop agents.
- [x] **Step 4:** `python3 -m unittest discover -s board/tests` → OK.
- [x] **Step 5: Commit** `fix(board): long press cancels on any release; openDoc selects before loading`.

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "browser checks (a)-(d) on a worktree board at :7710", "acceptanceCriteria": ["module-level press timer cancelled by document pointerup/cancel/move", "rebuilt card resolution kept", "openDoc selects first, renders only if still selected, error line on failure"], "modelTier": "mechanical"}
```

### Task 5: Real Claude lock line in the tests; committed cleanup test

**Goal:** `board/tests/test_worktree_lock.py` uses a lock reason captured from a real Claude worktree lock (or records why none could be captured). `bin/tmux-agent-cleanup` has a committed zsh test of its four lock cases.

**Files:**
- Modify: `board/tests/test_worktree_lock.py` (fixture strings + provenance comment)
- Modify: `bin/tmux-agent-cleanup` (seam: `FZF_BIN="${FZF_BIN:-$HOME/.local/bin/fzf}"`)
- Create: `tools/tests/test_agent_cleanup.zsh`

**Acceptance Criteria:**
- [ ] Capture attempt:
  - in a temp git repo (one commit), run `claude -w lockprobe -p "reply ok"` in the background;
  - poll `git worktree list --porcelain` every 0.2 s until it exits;
  - record the first `locked …` line seen, or "none observed".
- [ ] If a line was captured: the fixture uses it verbatim (pid substituted), with a comment naming the Claude version and date. If not: a comment says so, and the binary-derived strings stay.
- [ ] `FZF_BIN` can be overridden from the environment. The default is unchanged.
- [ ] `test_agent_cleanup.zsh` runs the real script against a temp repo, with a stub `FZF_BIN` that selects every row. It checks: dead-pid Claude lock → removed; live Claude pid (a process whose args contain `claude`) → kept, "in use"; `manual hold` → kept with the reason; dead-pid lock on a dirty tree → kept, git's error printed, still locked with the original reason.
- [ ] The test leaves no processes behind (kill by the PID it started) and no temp dirs.

**Verify:** `zsh tools/tests/test_agent_cleanup.zsh` → `ALL PASS`; `python3 -m unittest board.tests.test_worktree_lock -v` → OK.

**Steps:**

- [x] **Step 1: Capture** (side-effecting: starts a short Claude session; isolate it in a temp repo, and check afterwards that the temp repo and its `.claude/worktrees/lockprobe` are removed):

```zsh
r="$(mktemp -d)"; git -C "$r" init -qb main && git -C "$r" commit -q --allow-empty -m init
( cd "$r" && claude -w lockprobe -p "reply ok" >/dev/null 2>&1 ) & cp=$!
seen=""; while kill -0 $cp 2>/dev/null; do l="$(git -C "$r" worktree list --porcelain | grep '^locked')"; [[ -n "$l" ]] && { seen="$l"; break; }; sleep 0.2; done
wait $cp; print -r -- "seen: ${seen:-none observed}"; git -C "$r" worktree list --porcelain
```

Record the output in the report. Remove the worktree and repo afterwards: `git -C "$r" worktree remove -f` only for this temp repo's `lockprobe` worktree, then `rm -rf "$r"`.
- [x] **Step 2:** Update the fixture strings in `test_worktree_lock.py` per the acceptance criteria. Run the Python tests.
- [x] **Step 3: Seam.** In `bin/tmux-agent-cleanup`, change line `FZF_BIN="$HOME/.local/bin/fzf"` to `FZF_BIN="${FZF_BIN:-$HOME/.local/bin/fzf}"`.
- [x] **Step 4: Test.** Write `tools/tests/test_agent_cleanup.zsh`:
  - It needs no tmux server, but sources `lib.zsh` for `check`/`tt_done`. Use its own `mktemp -d` and an `EXIT` trap that removes the dir and kills the PIDs it started.
  - Stub fzf: a script that `cat`s its stdin (all rows selected).
  - Build the four worktrees under `<repo>/.claude/worktrees/` with `git worktree add`, and lock them with `git worktree lock --reason`.
  - Dead pid: run `true &`, `wait` it, use `$!`.
  - Live Claude pid: a script named `claude-fake` running `sleep 60`.
  - Dirty tree: write an untracked file.
  - Run `FZF_BIN=<stub> zsh <worktree>/bin/tmux-agent-cleanup <repo> </dev/null`, capture the output, then check `git worktree list --porcelain` and the output per the acceptance criteria.
- [x] **Step 5:** Run both checks, then the full suites.
- [x] **Step 6: Commit** `test(cleanup): real lock fixture and a committed tmux-agent-cleanup test`.

```json:metadata
{"files": ["board/tests/test_worktree_lock.py", "bin/tmux-agent-cleanup", "tools/tests/test_agent_cleanup.zsh"], "verifyCommand": "zsh tools/tests/test_agent_cleanup.zsh && python3 -m unittest board.tests.test_worktree_lock -v", "acceptanceCriteria": ["real lock capture attempted and recorded", "fixture uses captured line or documents why not", "FZF_BIN overridable", "cleanup test covers dead, live claude, manual, dirty", "no leftover processes or dirs"], "modelTier": "standard"}
```

### Task 6: Live check after merge (lead)

**Goal:** After the branch is merged into `main` (live install), a teammate spawned by the lead opens as its own `✦ <name>` window, and a manual split in the lead's window stays put.

**Files:**
- none (verification only)

**Acceptance Criteria:**
- [ ] Real state: in this `dev` session, after the merge, spawning a short-lived teammate with the Agent tool produces a window `✦ <name>` right after the `claude` window (`tmux list-windows` output recorded). The teammate is then shut down and its window closes.
- [ ] A manual split of the lead's window (`tmux split-window -d -t <lead window>`) stays in that window; then close that split pane by its id.

**Verify:** `tmux list-windows -t <session> -F '#{window_index} #{window_name}'` shows `✦ <name>` after `claude`.

**Steps:**

- [ ] **Step 1:** Merge (finishing-a-development-branch). Then spawn a teammate named `probe` whose only job is to reply "ready" and wait for shutdown.
- [ ] **Step 2:** Record `list-windows`, send it a shutdown request, and confirm the window is gone.
- [ ] **Step 3:** Split check as above. Kill only the pane id you created.

```json:metadata
{"files": [], "verifyCommand": "tmux list-windows -t <session> -F '#{window_index} #{window_name}'", "acceptanceCriteria": ["real teammate gets its own window after the lead", "manual split stays"], "modelTier": "mechanical"}
```
