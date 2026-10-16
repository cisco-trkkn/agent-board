# Board Fix Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix five Agent Board defects: artifacts hidden after a reload, the comment-queue line missing without a plan, stale long-press menus, Remove failing on a stale Claude worktree lock, and the flaky `test_bg.zsh` "read bg" check.

**Architecture:** Three tasks in `board/index.html` (client only), one task in `board/server.py` + `bin/tmux-agent-cleanup` (one shared unlock rule), one task in `bin/tmux-ctl` + `tools/tests/test_bg.zsh`. No new files except one test module.

**Tech Stack:** vanilla JS in a single HTML file, Python 3 stdlib server + `unittest`, zsh + tmux test harness.

**Spec:** design approved in chat on 2026-10-16 (no spec file: bounded path). Root-cause reports: `.superpowers/investigations/vanished-plan.md` (item 1), `.superpowers/investigations/flake-and-locks.md` (items 3 and 5).

## Global Constraints

- Live install is symlinked to this checkout: work on a branch `fix/board-batch` in this repo (not a worktree, the board is served from here); keep each commit working; switch back to `main` at the end.
- Conventional commits with scope (`fix(board): …`, `fix(tmux-ctl): …`, `test(tmux-ctl): …`). End every commit message with the attribution trailer your harness specifies.
- Both suites must pass after every task: `python3 -m unittest discover -s board/tests` and `zsh tools/tests/run-all.zsh` (run suites with `tmux-ctl run tests "<cmd>"`).
- Never `git worktree remove --force`; a dirty worktree must stay protected.
- A worktree lock whose reason does not match the Claude pattern is never unlocked (fail closed).
- Restarting the board ends the `_web-*` viewer sessions; tell the lead, who tells the user to reload the tab.

**User decisions (already made):**
- Worker plans inside git worktrees are listed but never pinned (`artifacts.py:55-56` unchanged).
- Older sessions' artifacts are collapsed, never dropped.
- Long press on a rebuilt card opens the fresh card's menu (not cancel-on-rebuild).
- `stop_agent` graceful exit is out of scope (filed as an idea).
- `test_bg` fix: assert on output, and create the bg session at `-x 200 -y 50`.

---

### Task 1: Artifacts panel lists every item after a reload

**Goal:** After a page reload the artifacts panel shows every item the server returns, grouped by session; older sessions collapsed; old items load their text lazily.

**Files:**
- Modify: `board/index.html` (`artFor` ~833, `pollArtifacts` ~852-871, `renderArtifacts` ~894-922, `openDoc` ~924)
- Test: `board/tests/test_artifacts.py` (server returns all epochs)

**Acceptance Criteria:**
- [ ] `pollArtifacts` adds every `d.items` entry to `A.items`; `first` and `loadedAt` no longer gate visibility.
- [ ] Each epoch group is a `<details>`; current epoch open by default, older ones closed; the user's open/closed choice per session+epoch persists in `localStorage` (wrapped in try/catch).
- [ ] `trackVersion` runs each poll only for: the pinned plan, items in the current epoch, items with `latest.ts >= A.loadedAt`, and the open document. Other items are fetched in `openDoc` before rendering.
- [ ] Unit test: `artifacts.summary()` over a manifest with epochs 0, 1, 2 returns items from all three.
- [ ] Real state, read-only: reload the board on `master-gcp-repo`; `2026-10-16-fable-first-run.md` (epoch 0) and the board-layout-navigation plan and spec (epoch 1) are listed under collapsed groups; opening one shows its text.

**Verify:** `python3 -m unittest board.tests.test_artifacts -v` → OK; then browser check above (screenshot or `read_page` evidence).

**Steps:**

- [ ] **Step 1: Server test (guards the contract the client now relies on).** Add to `board/tests/test_artifacts.py`, following that file's existing manifest fixture helpers (read them first; reuse its setup for `TMPDIR`/state dir):

```python
    def test_summary_returns_items_from_every_epoch(self):
        # three relays: items written in epochs 0, 1 and 2 must all be returned
        for epoch, name in enumerate(["old-plan.md", "mid-spec.md", "new-plan.md"]):
            self.add_entry(name, epoch=epoch)   # use the file's existing helper; adapt the name if it differs
        s = self.summary()
        self.assertEqual(sorted(it["latest"]["epoch"] for it in s["items"]), [0, 1, 2])
```

Run it; it should already PASS (the bug is client-side). If the file has no such helper, write the jsonl entries directly in the same shape as the existing tests do.

- [ ] **Step 2: Admit every item.** In `pollArtifacts`, replace the seed lines:

```js
  for (const it of d.items) A.items.set(it.url || it.path, it);
  const hot = (it) => it.path === A.plan || it.latest.epoch === d.epoch || it.latest.ts >= A.loadedAt || it.path === docSel;
  for (const it of A.items.values()) if (!it.url && hot(it)) await trackVersion(s.name, A, it);
```

Remove `first` from `artFor` and the `A.first = false;` line. Keep `loadedAt` (used by `hot`).

- [ ] **Step 3: Lazy load on open.** Make `openDoc` fetch before rendering when no version is cached:

```js
async function openDoc(path) {
  const A = artFor(session().name), it = A.items.get(path);
  if (it && !A.versions.get(path)) await trackVersion(session().name, A, it);
  // …existing body unchanged…
}
```

Check every caller of `openDoc` still works with an async function (they ignore its return value).

- [ ] **Step 4: Collapsible groups.** In `renderArtifacts`, build each group as a `<details>`:

```js
  const openKey = (e) => `dash.art.${s.name}.${e}`;
  for (const e of [...groups.keys()].sort((a, b) => b - a)) {
    const g = el("details", "art-group");
    let saved = null; try { saved = localStorage.getItem(openKey(e)); } catch (err) {}
    g.open = saved ? saved === "open" : e === A.epoch;
    const sum = el("summary"); sum.append(el("h4", "", `Session ${e + 1}${e === A.epoch ? " (current)" : ""} · ${groups.get(e).length}`));
    g.append(sum);
    g.addEventListener("toggle", () => { try { localStorage.setItem(openKey(e), g.open ? "open" : "closed"); } catch (err) {} });
    for (const it of groups.get(e).sort((a, b) => b.latest.ts - a.latest.ts)) g.append(artButton(A, it));
    box.append(g);
  }
```

Add CSS next to the existing `.art-group` rules so `summary` has no default marker clash and `h4` stays inline (`summary h4 { display: inline; }`). The panel re-renders every 2 s; because `g.open` comes from `localStorage` each time, a toggle survives re-render.

- [ ] **Step 5: Browser check on real state.** Restart the board (tell the lead first), reload, check the acceptance criteria on `master-gcp-repo`, and check the browser console has no errors.

- [ ] **Step 6: Commit** `fix(board): list every artifact after a reload, older sessions collapsed`.

```json:metadata
{"files": ["board/index.html", "board/tests/test_artifacts.py"], "verifyCommand": "python3 -m unittest board.tests.test_artifacts -v", "acceptanceCriteria": ["every d.items entry rendered", "older epochs collapsed via details, state persisted", "trackVersion only for hot items, lazy on open", "summary test covers epochs 0-2", "real master-gcp-repo reload lists fable-first-run and layout-navigation items"], "modelTier": "standard"}
```

### Task 2: Comment-queue line shows without a pinned plan

**Goal:** "N comments waiting for the lead" renders whenever comments are queued, pinned plan or not.

**Files:**
- Modify: `board/index.html` (`renderArtifacts`, the `if (plan)` block ~898-905)

**Acceptance Criteria:**
- [ ] With `A.comments.length > 0` and no pinned plan, `#pin-plan` contains the line.
- [ ] With a pinned plan, the line still appears under the plan button (unchanged position).

**Verify:** browser: in the console, `artFor(session().name).comments = [{}]; artFor(session().name).plan = null; renderArtifacts();` → `#pin-plan` text contains "1 comment waiting for the lead".

**Steps:**

- [ ] **Step 1:** Move the line out of `if (plan)`:

```js
  const plan = A.plan && A.items.get(A.plan);
  if (plan) {
    pin.append(el("div", "art-group"), artButton(A, plan));
    pin.firstChild.append(el("h4", "", "Plan"));
  }
  if (A.comments.length) pin.append(el("div", "pending", `${A.comments.length} comment${A.comments.length > 1 ? "s" : ""} waiting for the lead`));
  if (plan) {
    const vs = A.versions.get(A.plan);
    const txt = vs && vs[vs.length - 1].text;
    if (txt && /- \[x\]/i.test(txt) && !/- \[ \]/.test(txt)) pin.append(el("div", "pending", `Plan done · ${window.ideasOpen || 0} ideas ready for next steps`));
  }
```

- [ ] **Step 2:** Run the Verify console check (the next poll overwrites the stub; run it right after a poll).
- [ ] **Step 3: Commit** `fix(board): show queued comments without a pinned plan`.

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "browser console check of #pin-plan", "acceptanceCriteria": ["line shows with comments and no plan", "line unchanged with plan"], "modelTier": "mechanical"}
```

### Task 3: Long press opens the current card's menu

**Goal:** A long press whose card was rebuilt mid-press opens the menu of the card now showing that agent, built from fresh data, or nothing if the agent is gone.

**Files:**
- Modify: `board/index.html` (`bindAgentMenu` ~774-790, card creation ~455)

**Acceptance Criteria:**
- [ ] The card stores its items function (`card._menuItems = items`).
- [ ] When the timer fires and `!card.isConnected`, it looks up `document.querySelector(`[data-key="${CSS.escape(card.dataset.key)}"]`)`; if found it opens with that card's `_menuItems()` and that card as `from`; if not found it opens nothing.
- [ ] A card with no `data-key` and disconnected opens nothing.

**Verify:** browser, touch emulation (or `pointerType` "touch" via dispatched `PointerEvent`): start a long press, force a rebuild within 500 ms (`refresh()`), confirm the menu opens anchored to the new card and lists items matching its current state; remove the agent's card before 500 ms → no menu.

**Steps:**

- [ ] **Step 1:** Check the card element has `dataset.key` set where it is built (search for `dataset.key` near line 430-455; `openAgentMenu` already reads `from.dataset.key`). If it is not set, set it from the existing `key` variable.
- [ ] **Step 2:** Change `bindAgentMenu`:

```js
function bindAgentMenu(card, items) {
  card._menuItems = items;
  // …contextmenu listener unchanged…
  let lp = null, x0 = 0, y0 = 0;
  const cancel = () => { clearTimeout(lp); lp = null; };
  const fire = () => {
    lp = null;
    let c = card;
    if (!c.isConnected) {   // the 2 s rebuild replaced the card mid-press: use the one showing now
      const k = card.dataset.key;
      c = k ? document.querySelector(`[data-key="${CSS.escape(k)}"]`) : null;
      if (!c || !c._menuItems) return;
    }
    openAgentMenu(x0, y0, c._menuItems(), c);
  };
  card.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    x0 = e.clientX; y0 = e.clientY; cancel();
    lp = setTimeout(fire, 500);
  });
  // …pointermove / pointerup / pointercancel unchanged…
}
```

If the new card's `_menuItems()` returns an empty list, do not open (guard: `const its = c._menuItems(); if (its.length) openAgentMenu(x0, y0, its, c);`).
- [ ] **Step 3:** Run the Verify browser check; capture evidence.
- [ ] **Step 4: Commit** `fix(board): long press after a card rebuild uses the current card`.

```json:metadata
{"files": ["board/index.html"], "verifyCommand": "browser long-press with forced rebuild", "acceptanceCriteria": ["card._menuItems stored", "disconnected card resolves current card by data-key", "missing card or empty items opens nothing"], "modelTier": "mechanical"}
```

### Task 4: Remove unlocks a stale Claude worktree lock

**Goal:** The board's Remove and `tmux-agent-cleanup` remove a worktree whose Claude lock is held by a dead or reused pid, refuse when a live Claude holds it, and never touch other locks or dirty trees.

**Files:**
- Modify: `board/server.py` (`worktrees()` ~183-215, `remove_worktree` action ~319-330)
- Modify: `bin/tmux-agent-cleanup` (~44-66)
- Create: `board/tests/test_worktree_lock.py`

**Acceptance Criteria:**
- [ ] `server.claude_lock_owner(reason)` returns the pid for reasons matching `^claude \S+ .+ \(pid (\d+)( start .+)?\)$`, else `None`.
- [ ] `server.lock_is_stale(pid)` is True when `os.kill(pid, 0)` raises `ProcessLookupError`, or the process is alive and `ps -o args= -p <pid>` does not contain `claude` (case-insensitive); False otherwise (including `PermissionError` on kill, which means alive).
- [ ] `worktrees()` items carry `"locked": <reason or None>`.
- [ ] `remove_worktree`: if locked with a Claude reason and stale → `git worktree unlock`, then plain `git worktree remove`, and the message says "unlocked stale lock (pid N)"; if a live Claude holds it → RuntimeError "in use by a running Claude session (pid N)", no unlock; non-Claude reason → RuntimeError naming the reason, no unlock; dirty tree → git's refusal surfaces and the tree is re-locked with the original reason. `forget_worktrees()` is called after any unlock.
- [ ] `tmux-agent-cleanup` applies the same rule (same regex, `kill -0`, `ps -o args=`) and prints git's actual error instead of "kept (has uncommitted changes)".
- [ ] Tests run against a real scratch git repo with a real `git worktree lock --reason`; reason strings follow the format the Claude 2.1.301 binary writes, `claude session <name> (pid <pid> start <procStart>)` and `claude session <name> (pid <pid>)` (format from `.superpowers/investigations/flake-and-locks.md` §Issue B; if a live Claude worktree lock exists when you run this, copy its exact reason from `git worktree list --porcelain` into the fixture and note it).

**Verify:** `python3 -m unittest board.tests.test_worktree_lock -v` → all pass; full board suite passes.

**Steps:**

- [ ] **Step 1: Failing tests.** Create `board/tests/test_worktree_lock.py`, loading `server.py` the way `board/tests/test_agent_controls.py` does (`importlib.util.spec_from_file_location`, `TMUX_DASH_TOKEN` env). Fixture: `tempfile` repo, `git init -b main`, one commit, `git worktree add <repo>/.claude/worktrees/w1 -b w1`. Dead pid: start `subprocess.Popen(["true"])`, `wait()` it, use its pid. Live non-Claude pid: `subprocess.Popen(["sleep", "30"])` (kill it in tearDown by that object). Live Claude pid: patch `server.lock_is_stale`'s `ps` lookup by patching `server.proc_args` (define it in Step 3) to return `"/usr/bin/claude -w w1"` for the sleep pid. Cases:
  1. `claude_lock_owner` parses both formats; returns None for `"manual hold"` and `"claude"`.
  2. dead pid, clean tree → `server.action(...)`/the remove helper removes it; `git worktree list` no longer shows w1.
  3. live Claude pid → RuntimeError containing "in use"; still locked.
  4. live non-Claude pid (`sleep`) → removed (pid reuse).
  5. reason `"manual hold"` → RuntimeError; still locked.
  6. dead pid, dirty tree (write an untracked file) → RuntimeError; still locked with the original reason; files intact.
  7. `worktrees(repo)["items"][0]["locked"]` equals the reason.

  Call the removal through a function you can test without a tmux session: factor the body of the `remove_worktree` action into `remove_agent_worktree(repo, item)` and have the action call it with `session_worktree(...)` results. Run: `python3 -m unittest board.tests.test_worktree_lock -v` → FAIL (names missing).

- [ ] **Step 2: Parse the lock in `worktrees()`.** In the porcelain loop add `elif line.startswith("locked"): cur["locked"] = line[7:] or "locked"` and put `"locked": b.get("locked")` in each item.

- [ ] **Step 3: Rule and removal.**

```python
CLAUDE_LOCK = re.compile(r"^claude \S+ .+ \(pid (\d+)( start .+)?\)$")


def claude_lock_owner(reason):
    m = CLAUDE_LOCK.match(reason or "")
    return int(m.group(1)) if m else None


def proc_args(pid):
    r = subprocess.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True)
    return r.stdout.strip()


def lock_is_stale(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass   # alive, owned by someone else
    return "claude" not in proc_args(pid).lower()   # alive but not Claude: the pid was reused


def remove_agent_worktree(repo, item):
    path, reason, note = item["path"], item.get("locked"), ""
    if reason:
        pid = claude_lock_owner(reason)
        if pid is None:
            raise RuntimeError(f"locked by something other than Claude ({reason}); unlock it yourself")
        if not lock_is_stale(pid):
            raise RuntimeError(f"in use by a running Claude session (pid {pid})")
        git(repo, "worktree", "unlock", path)
        forget_worktrees()
        note = f"unlocked stale lock (pid {pid}); "
    r = git(repo, "worktree", "remove", path)
    if r.returncode != 0:
        if reason:
            git(repo, "worktree", "lock", "--reason", reason, path)
        raise RuntimeError((r.stderr or r.stdout).strip() or "git refused (uncommitted changes?)")
    msg = f"{note}removed worktree {item['name']}"
    br = item.get("branch")
    if br:
        d = git(repo, "branch", "-d", br)
        msg += f"; deleted branch {br}" if d.returncode == 0 else f"; kept branch {br} (not merged)"
    git(repo, "worktree", "prune")
    forget_worktrees()
    return msg
```

The action becomes: `wt = session_worktree(sess, body["path"]); return remove_agent_worktree(wt["repo"], wt["item"])`. Check `session_worktree` returns an item built by `worktrees()` (so `locked` is present); if it reads the cache, call `forget_worktrees()` first so the lock state is fresh.

- [ ] **Step 4:** Run the tests → PASS. Run the full board suite.

- [ ] **Step 5: Cleanup script.** In `bin/tmux-agent-cleanup`, track `locked` in the porcelain loop (`locked*) lk="${line#locked}"; lk="${lk# }"` and reset it with `wt` and `br`), carry it as a 7th tab field, and replace the remove block:

```zsh
  lk="$(print -r -- "$row" | cut -f7)"
  if [[ -n "$lk" ]]; then
    if [[ "$lk" =~ '^claude [^ ]+ .+ \(pid ([0-9]+)( start .+)?\)$' ]]; then
      pid="$match[1]"
      if kill -0 "$pid" 2>/dev/null && ps -o args= -p "$pid" | grep -qi claude; then
        print "  kept (in use by a running Claude session, pid $pid)"; continue
      fi
      git worktree unlock "$path_" && print "  unlocked stale lock (pid $pid)"
    else
      print "  kept (locked: $lk)"; continue
    fi
  fi
  if err="$(git worktree remove "$path_" 2>&1)"; then
    …existing removed/branch lines…
  else
    [[ -n "$lk" ]] && git worktree lock --reason "$lk" "$path_"
    print "  kept: $err"
  fi
```

Do not name any variable `path` (zsh). Check `kill -0` on a pid owned by another user returns non-zero with "operation not permitted": treat that as alive (`kill -0 "$pid" 2>&1 | grep -q 'not permitted'`), matching the Python rule.

- [ ] **Step 6:** Manual check of the script against a scratch repo with a stale lock (dead pid) and one with `manual hold`: the first is removed, the second kept with its reason printed. Paste the output in the report.

- [ ] **Step 7: Commit** `fix(board): Remove clears a stale Claude worktree lock; cleanup reports git's error`.

```json:metadata
{"files": ["board/server.py", "bin/tmux-agent-cleanup", "board/tests/test_worktree_lock.py"], "verifyCommand": "python3 -m unittest board.tests.test_worktree_lock -v", "acceptanceCriteria": ["claude_lock_owner parses both reason formats, None otherwise", "lock_is_stale: dead or non-claude alive pid", "worktrees items carry locked", "stale claude lock unlocked then plain remove", "live claude lock refused", "non-claude lock refused", "dirty tree refused and re-locked", "cleanup script same rule and real git error"], "modelTier": "standard"}
```

### Task 5: `test_bg` "read bg" asserts on output; bg session is wide

**Goal:** The "read bg" check passes on a warm window for any run-id length, and the bg session is created 200x50 so typed lines don't wrap.

**Files:**
- Modify: `bin/tmux-ctl:63` (`ensure_bg`, `new-session`)
- Modify: `tools/tests/test_bg.zsh:24`
- Create (scratch only, not committed): a warm-window probe script in your scratchpad

**Acceptance Criteria:**
- [ ] RED first: a warm-window probe (one `run tests true`, then 20× `run tests 'echo hi'` + the current grep) misses at least once on the unfixed code. Record the count.
- [ ] `test_bg.zsh` "read bg" greps for an output line: `$C read tests 40 | grep -qx hi`.
- [ ] `ensure_bg` creates the session with `-x 200 -y 50`.
- [ ] The same warm probe with the new assertion: 20/20 pass.
- [ ] `zsh tools/tests/run-all.zsh` passes.

**Verify:** `tmux-ctl run tests "zsh tools/tests/run-all.zsh"` → all files pass; probe counts in the report.

**Steps:**

- [ ] **Step 1: Probe (RED).** Write `<scratchpad>/probe-bg.zsh` that sources `tools/tests/lib.zsh` (it creates a scratch tmux server with `-f /dev/null` and its own `TC_STATE`; never use the user's server), runs `tt_setup claude shell`, then `$C run tests true`, then loops 20× `$C run tests 'echo hi' >/dev/null; $C read tests 40 | grep -q 'echo hi' || (( miss++ ))`, prints `miss=$miss`, and calls `tt_done`. Run it with `C=$PWD/bin/tmux-ctl` (check how `test_bg.zsh` picks `TC_CTL` and pass the repo copy the same way). Expected: `miss` > 0.
- [ ] **Step 2:** In `bin/tmux-ctl` `ensure_bg`: `t new-session -d -s "$BG" -n tests -x 200 -y 50 -c "$root"`.
- [ ] **Step 3:** In `tools/tests/test_bg.zsh` line 24: `check "read bg" sh -c "$C read tests 40 | grep -qx hi"`.
- [ ] **Step 4:** Re-run the probe with the new grep (`grep -qx hi`): expect `miss=0`. Also run it with the old grep after the `-x 200` change and record the result (informational).
- [ ] **Step 5:** Run the full tmux suite through `tmux-ctl run tests "zsh tools/tests/run-all.zsh"`.
- [ ] **Step 6: Commit** `fix(tmux-ctl): wide bg session; test_bg reads output, not the typed line`.

```json:metadata
{"files": ["bin/tmux-ctl", "tools/tests/test_bg.zsh"], "verifyCommand": "zsh tools/tests/run-all.zsh", "acceptanceCriteria": ["warm probe misses on unfixed code", "read bg greps output line", "bg session 200x50", "warm probe 20/20 after", "run-all passes"], "modelTier": "standard"}
```
