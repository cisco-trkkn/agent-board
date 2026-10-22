# Worktree Auto-Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove finished agent worktrees automatically and safely (when work ends, on one click, and daily), and flag stale unmerged ones for the user.

**Architecture:**
- One safety engine: a library `board/worktree_safety.py` with a thin CLI `bin/agent-worktrees`. It classifies each `.claude/worktrees/*` entry and removes only the safe ones, checking each again right before removal.
- Everything else calls the engine: the board server, the `Ctrl-a W` picker, a PostToolUse hook, and a launchd job.

**Tech Stack:** Python 3 stdlib (engine, board), zsh (picker, hook, tests), git, glab, tmux, launchd.

**Spec:** `docs/superpowers/specs/2026-10-22-worktree-auto-cleanup-design.md`

## Global Constraints

- **Safe means all of these hold:**
  - clean: `git status --porcelain` is empty, untracked files included;
  - merged: an ancestor of the local base, of `origin/<base>` after `git fetch --prune origin`, or of the main checkout's current branch; OR the verified squash case: the upstream is `[gone]` AND `glab mr list --merged --source-branch <br>` returns an MR whose head SHA equals the worktree's HEAD;
  - no live Claude lock;
  - no tmux pane with a cwd at or inside the worktree, on the default server or on agent-board's own server (resolved by `board/paneclass.py` `tmux_cmd()`).
- Branch delete: `git branch -d`, and `-D` only in the verified-squash case.
- Never `git worktree remove --force`.
- **Fail closed.** A check that cannot run gives **kept** with the reason, and the sweep exits 0. A non-zero exit means only that the engine itself broke.
- **Stale:** clean, not merged, last commit 7+ days old (a constant). Never removed automatically.
- Only paths under `<repo>/.claude/worktrees/` are ever listed or touched.
- **Offline classify** (`fetch=False`: no `git fetch`, no `glab`) is what the board's 30 s poll uses. `sweep` always does the full classify.
- **Sweep lock:** a `mkdir` lockdir `~/.local/state/agent-board/sweep-<sha1(repo)[:12]>.lock` holding `pid`. It is taken over if that pid is dead.
- **Sweep log:** `~/.local/state/agent-board/worktree-sweep.log`, one line per worktree: `<ISO time>\t<repo>\t<action>\t<name>\t<reason>`.
- Tests make external commands go through the seams `AW_GLAB`, `AW_TMUX` (a full command, word-split) and `AW_STATE_DIR`, so they never touch the real state dir, glab or tmux servers.
- **Execution:** this checkout is the live install, so the plan runs in a worktree under `~/agent-board/.claude/worktrees/`. Commits end with the attribution trailer your harness specifies.

**User decisions (already made):**
- Triggers: when work ends (a merge or a worker shutdown), a one-click "remove all safe" sweep, and a daily scheduled sweep. Not on project close or dev start.
- Unmerged clean worktrees are never removed automatically. Stale ones (7+ days) are flagged, and the user removes them.
- Merge detection covers both local merges and GitLab squash merges. `-D` only when the glab MR's head SHA equals the worktree's HEAD.
- Approach A: one engine with thin callers.

---

### Task 1: Engine classify (library + CLI)

**Goal:** `agent-worktrees classify [dir] [--json] [--offline]` reports each agent worktree's state (safe / stale / in use / dirty / kept) with a reason.

**Files:**
- Create: `board/worktree_safety.py`, `bin/agent-worktrees` (executable)
- Modify: `board/server.py`: move `claude_lock_owner`, `lock_is_stale` and `proc_args` (if only those use it) into `worktree_safety.py`, and import them back, so `board/tests/test_worktree_lock.py` keeps passing unchanged
- Test: `board/tests/test_worktree_safety.py`

**Acceptance Criteria:**
- [ ] `classify(repo, fetch=True, now=None)` returns `{"repo", "base", "current", "items":[{"path","name","branch","head","state","reason","age_days","squash"}]}`. `state` is one of `safe`, `stale`, `in_use`, `dirty`, `kept`.
- [ ] Each fixture lands in its state:
  - merged into base (ancestor) → `safe`;
  - merged only into the main checkout's current branch → `safe`;
  - unmerged with a last commit 2 days old → `kept` (reason `not merged`);
  - unmerged and 9 days old → `stale`;
  - a modified file → `dirty`, and an untracked file alone → `dirty`;
  - a live Claude-pid lock → `in_use`; a dead-pid lock + merged → `safe`; a `manual hold` lock → `kept`;
  - a tmux pane cwd inside the worktree (stub `AW_TMUX`) → `in_use`;
  - upstream `[gone]` + stub glab returns a merged MR with an equal SHA → `safe` with `squash: true`;
  - the same but the SHA differs → `kept`;
  - stub glab exits 1 → `kept` (reason contains `can't verify MR`).
- [ ] `fetch=False` never runs `git fetch` or glab: a stub glab that writes a marker file is never called. The squash case is then `kept` (`offline`).
- [ ] When the tmux stub exits non-zero with a message other than "no server running", the result is `kept` (`can't check tmux panes`). "no server running" on a server means that server has no panes.
- [ ] A worktree outside `.claude/worktrees/` is not listed.
- [ ] The CLI's `--json` prints `json.dumps(result)`. Without it, the CLI prints one line per item: `name<TAB>state<TAB>reason`. Exit 0, or exit 2 for not a repo.
- [ ] `python3 -m unittest discover -s board/tests` passes in full (`test_worktree_lock.py` included).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_worktree_*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Fixtures and failing tests.**
  - Build real repos in `tempfile.mkdtemp()`, with `GIT_CONFIG_GLOBAL=/dev/null`, author env, and `git init -b main`.
  - Add worktrees with `git worktree add <repo>/.claude/worktrees/<n> -b <n>`.
  - Ageing: commit with `GIT_COMMITTER_DATE`/`GIT_AUTHOR_DATE` set to `now - 9d`, and pass `now` explicitly.
  - Squash case: create a bare `origin` and push the branch with `-u`. Then delete the remote branch (`git push origin --delete <br>`) and run `git fetch --prune`, so the upstream reads `[gone]`.
  - Stub glab: a script that prints `[{"iid":1,"sha":"<head>","state":"merged"}]`. Stub tmux: a script that prints `"<pid>\t<path>"` lines.
  - Lock lines use the format captured in `board/tests/test_worktree_lock.py`.
  - Run the tests and see them fail (module missing).
- [ ] **Step 2: Implement `classify`.**
  - Parse `git worktree list --porcelain`. Include `HEAD <sha>` and detached entries.
  - Base: `git symbolic-ref --short refs/remotes/origin/HEAD`, stripped of `origin/`, falling back to `main`.
  - Ancestor check: `git merge-base --is-ancestor <head> <ref>` for each of `<base>`, `origin/<base>` (if it exists) and `<current>`.
  - Upstream gone: `git for-each-ref --format='%(upstream:track)' refs/heads/<br>` equals `[gone]`.
  - Squash check:
    - `glab mr list --merged --source-branch <br> --output json`, run with `cwd=repo`, using the command from `AW_GLAB` (default `glab`).
    - It passes if any MR's `sha` equals HEAD.
    - If glab is missing or exits non-zero → `kept`.
  - Panes:
    - Run `<tmux> list-panes -a -F '#{pane_pid}\t#{pane_current_path}'` for each server: `AW_TMUX` if set (one server), else `tmux_cmd()` from `paneclass` plus plain `tmux`.
    - A pane is a match if its path equals the worktree or starts with the worktree path plus `/`.
  - Check order: dirty → in_use → merged → stale/kept.
  - Every subprocess runs with `timeout=20`. A timeout gives `kept`.
- [ ] **Step 3: CLI.** `bin/agent-worktrees` is a python3 script. It puts `<repo>/board` on `sys.path` (resolving its own symlink) and runs argparse subcommands. This task adds `classify`; Task 2 adds the rest.
- [ ] **Step 4: Move the lock helpers.** Move them from `server.py` into `worktree_safety.py`, and import them back with `from worktree_safety import claude_lock_owner, lock_is_stale`. Run the full board suite.
- [ ] **Step 5: Commit.** `feat(worktrees): safety engine classify`. End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["board/worktree_safety.py", "bin/agent-worktrees", "board/server.py", "board/tests/test_worktree_safety.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_worktree_*.py'", "acceptanceCriteria": ["classify returns documented shape and states", "every fixture state correct incl squash equal/differ/glab-fail", "offline never calls fetch/glab", "tmux failure fails closed; no server = no panes", "non-.claude/worktrees paths not listed", "CLI --json/plain, exit 2 not a repo", "full board suite passes"], "modelTier": "standard"}
```

### Task 2: Engine remove and sweep

**Goal:** `agent-worktrees remove <path>` (the user-chosen removal) and `agent-worktrees sweep [dir | --recent] [--only <path>] [--dry-run]` (the automatic removal of safe worktrees), with the lockdir and the log.

**Files:**
- Modify: `board/worktree_safety.py`, `bin/agent-worktrees`
- Test: `board/tests/test_worktree_safety.py`

**Acceptance Criteria:**
- [ ] `remove(repo, path)`:
  - it needs only: clean, no live Claude lock, under `.claude/worktrees/`;
  - it unlocks a stale lock, and puts it back if git refuses;
  - `git worktree remove` runs without `--force`, then `branch -d` (an unmerged branch is reported `kept branch`), then `worktree prune`;
  - it returns the message string the board shows today (`removed worktree X; deleted branch Y`).
- [ ] `sweep(repo, only=None, dry_run=False)`:
  - classify runs with `fetch=True`;
  - for each `safe` item, classify runs again for that one path right before removal, and the item is removed only if it is still `safe`. Test: a pane that appears between the two checks (stub tmux switched by a file) means `kept`;
  - squash-safe → `branch -D`; ancestor-safe → `branch -d`;
  - stale/kept/dirty/in_use are never removed;
  - it returns lines `removed <name>` / `kept <name> (<reason>)` / `stale <name> (<n>d)`, and appends each to the sweep log;
  - with `dry_run`, nothing is removed and log lines carry `would-remove`.
- [ ] Lockdir: a second `sweep` while the lock is held prints `sweep already running` and exits 0. A lockdir whose `pid` is dead is taken over.
- [ ] `--recent`:
  - the repos are the main checkouts of the paths in `<AW_STATE_DIR or ~/.local/state/agent-board>/recent-projects.json` (the format `board/dirs.py` writes) plus the session paths of `list-sessions -F '#{session_path}'` on the servers;
  - duplicates are removed;
  - non-repos are skipped with a `skip <path> (not a repo)` line.
- [ ] `--only <path>` sweeps just that worktree.
- [ ] The state dir comes from `AW_STATE_DIR` (tests point it at a temp dir).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_worktree_*.py'` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests** for each criterion, reusing Task 1's fixtures. The re-check race test uses a stub tmux that reads its output from a file the test rewrites after the first classify (patch `classify` to count calls, or write the file from a hook).
- [ ] **Step 2: Implement.** Lockdir: `os.mkdir(lockdir)`, then write `pid`. On `FileExistsError`, read the pid; if `os.kill(pid, 0)` raises `ProcessLookupError`, take the lock over, otherwise print `sweep already running`. Release it in `finally`.
- [ ] **Step 3: CLI subcommands** `remove`, `sweep`. Exit codes: 0 normally (kept items included), 2 for a bad argument or not a repo.
- [ ] **Step 4: Commit.** `feat(worktrees): engine remove and sweep`, with your harness's attribution trailer.

```json:metadata
{"files": ["board/worktree_safety.py", "bin/agent-worktrees", "board/tests/test_worktree_safety.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_worktree_*.py'", "acceptanceCriteria": ["remove: manual-path rules, lock restore, no --force, -d", "sweep: full classify, per-item recheck (race test), -D only squash, log lines, dry-run", "lockdir busy/takeover", "--recent from recent-projects.json + tmux sessions, deduped", "--only", "AW_STATE_DIR seam"], "modelTier": "standard"}
```

### Task 3: Board uses the engine

**Goal:**
- The Worktrees panel shows the engine's states, a `stale Nd` badge, a `Remove safe (N)` button and the last scheduled sweep's result.
- Per-row Remove and worker shutdown go through the engine.

**Files:**
- Modify: `board/server.py`:
  - `worktrees()` uses `classify(path, fetch=False)` for item states, and keeps its existing keys (`dirty`, `merged`, `age`, `locked`) for the current UI;
  - `remove_agent_worktree` calls `worktree_safety.remove`;
  - a new action `remove_safe_worktrees` runs `sweep` (full classify) for the session's repo;
  - `stop_agent` runs `sweep(repo, only=<that worker's worktree>)` after `kill-window`, if the window's path is under `.claude/worktrees/`, and appends the sweep line to its message;
  - `summary()` adds `last_sweep`: the last run's counts from the sweep log.
- Modify: `board/index.html` (Worktrees panel)
- Test: `board/tests/test_worktree_board.py`

**Acceptance Criteria:**
- [ ] The board poll never calls `git fetch` or glab. Test: the stub glab with a marker file stays uncalled across `worktrees()`.
- [ ] Action `remove_safe_worktrees` removes a merged clean fixture worktree and keeps an unmerged one. It returns a message containing `removed` and `kept`.
- [ ] Per-row Remove on a dirty worktree raises a RuntimeError with git's message, as today. On a stale-locked merged one, it unlocks and removes.
- [ ] `stop_agent` on a worker whose worktree is merged and clean removes that worktree. If it's unmerged, the worktree stays and the message says `kept`.
- [ ] The panel renders a `stale 9d` badge and a `Remove safe (N)` button (N = items whose offline state is `safe`, which is a hint only: the action re-checks online). It shows `last sweep HH:MM: removed X, Y stale` when the log has entries. Check by loading the board from the worktree (`TMUX_DASH_PORT=7710 python3 board/server.py`) and taking a screenshot.
- [ ] The full board suite passes.

**Verify:** `python3 -m unittest discover -s board/tests` → `OK`

**Steps:**

- [ ] **Step 1: Failing tests** in `test_worktree_board.py`, with the fixture repos from `test_worktree_safety.py` (import its helpers) and `AW_GLAB`/`AW_TMUX`/`AW_STATE_DIR` stubs.
- [ ] **Step 2: Implement** the server changes. Existing callers of `worktrees()` keep working: add `state`, `reason` and `age_days` to each item, and drop nothing.
- [ ] **Step 3: Panel.** Follow the existing Worktrees row markup and action-button pattern in `index.html`. The `Remove safe (N)` button posts the `remove_safe_worktrees` action and shows the result in the same toast area as Remove.
- [ ] **Step 4:** Run the full suite, then do the screenshot check from the worktree on port 7710.
- [ ] **Step 5: Commit.** `feat(board): worktrees panel uses the safety engine`, with your harness's attribution trailer.

```json:metadata
{"files": ["board/server.py", "board/index.html", "board/tests/test_worktree_board.py"], "verifyCommand": "python3 -m unittest discover -s board/tests", "acceptanceCriteria": ["poll is offline (no fetch/glab)", "remove_safe_worktrees removes merged, keeps unmerged", "per-row remove behaviour unchanged", "stop_agent sweeps only its worktree", "stale badge, Remove safe (N), last sweep line rendered (screenshot from 7710)", "full board suite OK"], "modelTier": "standard"}
```

### Task 4: Ctrl-a W picker and `agent-board worktrees`

**Goal:**
- The picker lists rows from the engine. Its first row is `⟳ remove all safe (N)`, stale rows show `stale Nd`, and marked rows are removed through the engine.
- `agent-board worktrees <args>` runs the CLI.

**Files:**
- Modify: `bin/tmux-agent-cleanup`, `bin/agent-board` (add `worktrees) shift; exec "$here/agent-worktrees" "$@" ;;` and its help line)
- Test: `tools/tests/test_agent_cleanup.zsh`

**Acceptance Criteria:**
- [ ] The existing four lock-case checks in `test_agent_cleanup.zsh` still pass. Their messages may change wording only where the engine's `remove` message differs; update those checks to the engine's text.
- [ ] New checks, with the stub fzf selecting a given row:
  - selecting `⟳ remove all safe` removes a merged worktree and keeps an unmerged one;
  - a 9-day-old unmerged row shows `stale 9d`.
- [ ] The picker gets rows from `agent-worktrees classify --offline --json` (parsed with `python3 -I -c`), and runs `agent-worktrees sweep <repo>` for the all-safe row. It has no lock or merge logic of its own left.
- [ ] `agent-board worktrees classify <dir>` prints the plain table.

**Verify:** `zsh tools/tests/test_agent_cleanup.zsh | tail -1` → `ALL PASS`

**Steps:**

- [ ] **Step 1:** Extend the stub fzf so it can pick rows matching `$FZF_PICK` (`grep -- "$FZF_PICK"`), defaulting to every row as today. Write the new checks and see them fail.
- [ ] **Step 2:** Rewrite the row building and the removal loop over the engine. Keep the fzf flags and colours, the header text (plus a line `⟳ = remove every merged, clean, unused worktree`) and the final `Press any key`.
- [ ] **Step 3:** Run the test through `tmux-ctl run tests "zsh tools/tests/test_agent_cleanup.zsh"`, then `run-all.zsh`.
- [ ] **Step 4: Commit.** `feat(cleanup): picker uses the safety engine, remove-all-safe row`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/tmux-agent-cleanup", "bin/agent-board", "tools/tests/test_agent_cleanup.zsh"], "verifyCommand": "zsh tools/tests/test_agent_cleanup.zsh | tail -1", "acceptanceCriteria": ["existing lock-case checks pass", "remove-all-safe row removes merged keeps unmerged", "stale Nd shown", "no own lock/merge logic left", "agent-board worktrees subcommand"], "modelTier": "standard"}
```

### Task 5: Merge hook

**Goal:**
- A PostToolUse Bash hook starts a background sweep of the command's repo after `git merge`, `git pull`, `glab mr merge` or `git branch -d/-D`.
- The sweep's summary goes to the session's shell feed.

**Files:**
- Create: `claude/plugin/scripts/worktree-sweep.sh` (canonical), and the symlink `claude/hooks/worktree-sweep.sh -> ../plugin/scripts/worktree-sweep.sh`
- Modify: `claude/plugin/hooks/hooks.json` (PostToolUse Bash, `--scoped`, `async: true`, `timeout: 5`), `claude/settings.json` (the same, as the legacy global entry, following bash-mirror's pattern), `tools/tests/test_plugin.zsh` (its "all three hooks" and symlink checks also cover worktree-sweep)
- Test: `tools/tests/test_worktree_hook.zsh`, registered in `run-all.zsh` the way the other tests are

**Acceptance Criteria:**
- [ ] The match runs on the command with quoted strings blanked (the same idea as bash-mirror's `classify`). It fires on: `git merge x`, `cd a && git pull`, `glab mr merge 3`, `git branch -d f`, `git -C ~/r merge x`. It does not fire on `git status`, `echo "git merge"`, or `git log --merges`.
- [ ] The repo is the main checkout of the payload's `cwd`. A `git -C <dir>` in the command takes precedence over that. A non-repo → no-op.
- [ ] The sweep runs detached (`nohup … &!`), so the hook exits 0 within 1 s even when the sweep takes longer (test: a stub `AW_CLI` that sleeps 5). The hook never prints to stdout.
- [ ] When the sweep finishes, one entry is appended to `$TC_STATE_DIR/feed-<canon>-shell.log`. It uses bash-mirror's header format, with agent `worktree-sweep` and a body of `swept: removed X; kept Y (<reasons>)`. The feed is located the same way bash-mirror locates it; if there's no dev session, no feed is written. The sweep log is always written.
- [ ] The dedupe rule matches bash-mirror's: `[[ "$1" == --scoped || "$AGENT_BOARD" != 1 ]] || exit 0`.
- [ ] `zsh tools/tests/run-all.zsh` exits 0.

**Verify:** `zsh tools/tests/test_worktree_hook.zsh | tail -1` → `ALL PASS`

**Steps:**

- [ ] **Step 1:** Write the tests: feed the hook JSON payloads on stdin, with `AW_CLI` pointing at a stub that records its argv to a file and `TC_STATE`/`TC_STATE_DIR` in a temp dir. Run them, RED.
- [ ] **Step 2:** Implement, copying bash-mirror's structure: tc-env sourcing, dedupe line, payload parse in `python3 -I -c`, feed-path resolution. Differences from bash-mirror that change behaviour:
  - it acts only on matching commands, not on every Bash call;
  - it skips the `tmux-ctl` early-exit, because a `tmux-ctl run … "git merge"` is still a merge;
  - it starts a detached child instead of writing synchronously;
  - it writes only the shell feed;
  - it needs no tool exit code; a failed merge simply produces a sweep that removes nothing.
- [ ] **Step 3:** Register it in `hooks.json` and `settings.json`, and update `test_plugin.zsh`. Run `run-all.zsh` through `tmux-ctl run tests`.
- [ ] **Step 4: Commit.** `feat(hooks): sweep merged worktrees after a merge`, with your harness's attribution trailer.

```json:metadata
{"files": ["claude/plugin/scripts/worktree-sweep.sh", "claude/hooks/worktree-sweep.sh", "claude/plugin/hooks/hooks.json", "claude/settings.json", "tools/tests/test_plugin.zsh", "tools/tests/test_worktree_hook.zsh", "tools/tests/run-all.zsh"], "verifyCommand": "zsh tools/tests/test_worktree_hook.zsh | tail -1", "acceptanceCriteria": ["fires on the five merge shapes, not on the three non-merges", "repo from cwd or git -C; non-repo no-op", "detached: hook exits <1s with 5s stub sweep; silent stdout", "feed entry in bash-mirror header format; sweep log always", "dedupe rule as bash-mirror", "run-all exit 0"], "modelTier": "standard"}
```

### Task 6: Daily scheduled sweep

**Goal:** `agent-worktrees schedule install|uninstall|status` manages `~/Library/LaunchAgents/com.user.agent-worktree-sweep.plist`, which runs `sweep --recent` every day at 04:00.

**Files:**
- Modify: `bin/agent-worktrees`, `board/worktree_safety.py` (a `plist_text(cli_path, home)` function)
- Test: `board/tests/test_worktree_safety.py`

**Acceptance Criteria:**
- [ ] `plist_text`:
  - `Label` is `com.user.agent-worktree-sweep`;
  - `ProgramArguments` is `[<absolute path of ~/.local/bin/agent-board>, "worktrees", "sweep", "--recent"]`;
  - `StartCalendarInterval` is `{Hour: 4, Minute: 0}`;
  - `StandardOutPath` and `StandardErrorPath` go to `~/.local/state/agent-board/worktree-sweep.launchd.log`;
  - `EnvironmentVariables.PATH` includes `~/.local/bin:/opt/homebrew/bin:/usr/bin:/bin`, so glab, git and tmux resolve under launchd;
  - `plistlib.loads` round-trips it.
- [ ] `schedule install` writes the plist (backing up an existing one as `.bak-YYYYMMDD`), then runs `launchctl bootout gui/$UID/<label>` (errors ignored) and `launchctl bootstrap gui/$UID <plist>`. `uninstall` runs bootout and removes the file. `status` prints `launchctl print gui/$UID/<label>`'s `state` and `last exit code` lines, or `not installed`.
- [ ] The tests run `install`/`uninstall` with `AW_LAUNCHCTL` set to a stub and `AW_HOME` set to a temp dir, so they never touch the real LaunchAgents.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_worktree_safety.py'` → `OK`

**Steps:**

- [ ] **Step 1:** Write the failing tests for `plist_text` and for install/uninstall against the stubs.
- [ ] **Step 2:** Implement with `plistlib.dumps`.
- [ ] **Step 3: Commit.** `feat(worktrees): daily scheduled sweep via launchd`, with your harness's attribution trailer.

```json:metadata
{"files": ["bin/agent-worktrees", "board/worktree_safety.py", "board/tests/test_worktree_safety.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_worktree_safety.py'", "acceptanceCriteria": ["plist fields and PATH as specified, round-trips", "install backs up, bootout+bootstrap; uninstall; status", "tests use AW_LAUNCHCTL/AW_HOME stubs only"], "modelTier": "standard"}
```

### Task 7: Rule text

**Goal:** The lead and skill text says that merged worktrees are removed automatically and stale ones are flagged.

**Files:**
- Modify: `claude/orchestrator.md` (the line near 204: "Finished worker worktrees are cleaned up by the user with `Ctrl-a W`"), `claude/plugin/skills/tmux-orchestrator/SKILL.md` (near line 78), `claude/skills/tmux-orchestrator/SKILL.md` (near line 88)

**Acceptance Criteria:**
- [ ] Each of the three places reads: "Merged agent worktrees are removed automatically (after a merge, on a worker shutdown, and daily at 04:00); stale unmerged ones are flagged on the board and in `Ctrl-a W` for the user to remove."
- [ ] `grep -rn 'cleaned up by the user with' claude/orchestrator.md claude/plugin/skills/tmux-orchestrator/SKILL.md claude/skills/tmux-orchestrator/SKILL.md` prints nothing.

**Verify:** `grep -rlc 'Merged agent worktrees are removed automatically' claude/orchestrator.md claude/plugin/skills/tmux-orchestrator/SKILL.md claude/skills/tmux-orchestrator/SKILL.md | wc -l` → `3`

**Steps:**

- [ ] **Step 1:** Read each file around the cited line, and replace the sentence that says the user cleans up with `Ctrl-a W` with the sentence above. Keep each file's surrounding list or bullet format.
- [ ] **Step 2:** Run the two grep checks.
- [ ] **Step 3: Commit.** `docs(rules): worktrees are cleaned up automatically`, with your harness's attribution trailer.

```json:metadata
{"files": ["claude/orchestrator.md", "claude/plugin/skills/tmux-orchestrator/SKILL.md", "claude/skills/tmux-orchestrator/SKILL.md"], "verifyCommand": "grep -rlc 'Merged agent worktrees are removed automatically' claude/orchestrator.md claude/plugin/skills/tmux-orchestrator/SKILL.md claude/skills/tmux-orchestrator/SKILL.md | wc -l", "acceptanceCriteria": ["sentence present in all three", "old Ctrl-a W sentence gone"], "modelTier": "mechanical"}
```

### Task 8: Real-state e2e

**Goal:** Prove the engine on the user's real, aged repos and the real external commands. Then do one real sweep and install the schedule, after the lead's go-ahead.

**Files:**
- Create: `docs/superpowers/plans/2026-10-22-worktree-auto-cleanup-e2e-report.md` with `## Classify (real repos)`, `## External commands`, `## Real sweep`, `## Schedule`

**Acceptance Criteria:**
- [ ] `bin/agent-worktrees classify ~/agent-board` and `classify ~/master-gcp-repo`, both run from the plan worktree with full fetch, are quoted in the report:
  - `docs-compose` (its branch `feat/docs-compose` is merged into main at 693e8b3) is `safe`;
  - `end-marker` is not `safe` unless its branch has been merged by then;
  - the plan's own worktree is `in_use` (panes are inside it);
  - the scratchpad `frozen` worktree is not listed.
- [ ] `sweep --dry-run ~/agent-board` lists `would-remove docs-compose` and nothing else unexpected.
- [ ] A real `glab mr list --merged --output json` in `~/master-gcp-repo` (any merged MR) is parsed by the engine's parser without error. Quote the MR count and one `sha` field. A real scratch tmux server (`~/.local/bin/tmux -L aw-e2e -f /dev/null`) with a pane whose cwd is inside a fixture worktree gives `in_use`. Kill that server by its socket afterwards.
- [ ] **Wait for the lead's go-ahead**, then:
  - run `bin/agent-worktrees sweep ~/agent-board`;
  - `docs-compose` is removed and `git branch --list feat/docs-compose` is empty;
  - the sweep log has the line;
  - `git worktree list` is quoted before and after.
- [ ] **Wait for the lead's go-ahead**, then run `agent-board worktrees schedule install` (after the branch is merged to main, so the plist's `agent-board` path runs main's code). `schedule status` shows it loaded.
- [ ] Leak check: no `aw-e2e` tmux server and no scratch worktrees under `/tmp` from this task are left.

**Verify:** `grep -c '^## ' docs/superpowers/plans/2026-10-22-worktree-auto-cleanup-e2e-report.md` → `4`

**Steps:**

- [ ] **Step 1:** Run the read-only classify and dry-run on both repos, and the external-command checks. Write the first two sections.
- [ ] **Step 2:** Message the lead with the dry-run output and wait. After the go-ahead, run the real sweep and write `## Real sweep`.
- [ ] **Step 3:** The schedule install happens at integration time, after merge to main. Message the lead and wait, then write `## Schedule`.
- [ ] **Step 4: Commit** the report: `docs(plan): worktree auto-cleanup e2e report`, with your harness's attribution trailer.

```json:metadata
{"files": ["docs/superpowers/plans/2026-10-22-worktree-auto-cleanup-e2e-report.md"], "verifyCommand": "grep -c '^## ' docs/superpowers/plans/2026-10-22-worktree-auto-cleanup-e2e-report.md", "acceptanceCriteria": ["real classify on both repos: docs-compose safe, end-marker not safe, own worktree in_use, frozen not listed", "dry-run would-remove docs-compose only", "real glab parse and real scratch tmux in_use; scratch server killed", "lead go-ahead then real sweep removes docs-compose + branch, log line", "lead go-ahead then schedule install after merge, status loaded", "no leaks"], "modelTier": "standard"}
```
