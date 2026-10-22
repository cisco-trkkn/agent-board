# Worktree auto-cleanup: design

Date: 2026-10-22
Ideas: "manual worktree removal is arduous. It should be automated safely" (2026-10-20 13:25) and
"worktrees for a given project tend to pile up and I need a simple automated way to delete them
safely" (2026-10-21 22:04), both in `~/.local/state/agent-board/ideas/francisco_ruiz.md`.

## Problem

Agent worktrees under `<repo>/.claude/worktrees/` are removed only by hand: the `Ctrl-a W` fzf picker
(`bin/tmux-agent-cleanup`) or the board's per-row Remove (`board/server.py` `remove_agent_worktree`).
Both pick one worktree at a time, and both carry their own copy of the safety rules. Finished
worktrees pile up across projects.

## Decisions (from brainstorming)

- Three triggers: when work ends (a merge, or a worker shutdown), a one-click "remove all safe" sweep,
  and a daily scheduled sweep.
- Clean worktrees whose branch is not merged are never removed automatically. If they have no commits
  for 7+ days they are flagged **stale**, for the user to remove.
- Merge detection covers both local merges and GitLab squash merges.
- Approach: one safety engine with thin callers (not two copies of the rules, and not a per-repo
  git hook).

## 1. Safety engine: `bin/agent-worktrees`

A stdlib-only Python 3 CLI.

- `agent-worktrees classify [dir] [--json]` prints every worktree under `.claude/worktrees/` of the
  repo containing `dir` (default: cwd), each with a state and a reason.
- `agent-worktrees sweep [dir | --recent] [--only <path>] [--dry-run]` removes the **safe** ones and
  prints one line per worktree (`removed …`, `kept … (reason)`, `stale … (9d)`). `--recent` walks
  the board's recent-projects list (`board/dirs.py`, `recent-projects.json`, at most 10 entries) and
  the paths of the open tmux sessions, without duplicates. `--only`
  limits it to one worktree.
- `agent-worktrees remove <path>` is the user-chosen single removal: used by the picker and the
  board's per-row Remove. It needs only the rules of today's manual path (clean, no live Claude lock).
  It does not need "merged", because the user chose it. The branch goes with `-d`, so an unmerged
  branch is kept and reported.

Worktrees outside `.claude/worktrees/` (the main checkout, scratchpad worktrees) are never listed or
touched.

### States

A worktree is **safe** only when all of these hold:

1. **Clean:** `git -C <wt> status --porcelain` is empty, with no modified and no untracked files.
   Ignored files do not count.
2. **Merged**, in one of two ways:
   - **Ancestor:** HEAD is an ancestor of the local base branch, of `origin/<base>` after
     `git fetch --prune origin`, or of the main checkout's current branch. `<base>` comes from
     `origin/HEAD`, falling back to `main`.
   - **Verified squash:** the branch had an upstream that is now `[gone]`, AND
     `glab mr list --merged --source-branch <branch>` returns an MR whose head SHA equals the
     worktree's HEAD. A commit made after the MR therefore keeps the worktree.
3. **Not in use:**
   - No live Claude lock. The lock parse and pid/start-time check are moved from
     `tmux-agent-cleanup` and `remove_agent_worktree` into the engine.
   - No tmux pane on the default server has a `pane_current_path` equal to the worktree or inside it.

When a safe worktree is removed, its branch is deleted with `git branch -d`. `git branch -D` is used
only in the verified-squash case.

The other states:

- **stale:** clean and not merged, with a last commit 7+ days old (a constant). It is listed and never
  removed automatically.
- **in use:** a live lock or a pane inside it.
- **dirty:** uncommitted or untracked files.
- **kept:** anything else, with the reason. That includes "can't verify": a fetch failure, `glab`
  missing or not logged in, or the tmux server unreachable.

### Removal

- Just before each removal, the engine checks that worktree's state again. It never acts on the
  output of an earlier `classify`. This closes the gap where a session starts in the worktree between
  the two steps.
- A stale Claude lock (dead or reused pid) is unlocked first.
- `git worktree remove <path>` runs without `--force`. If git refuses, any lock that was lifted is put
  back, and the result is `kept: <git's message>`.
- `git worktree prune` runs at the end.

### Failure behaviour

- The engine fails closed. A check that cannot run makes that worktree **kept** with the reason, and
  the sweep still exits 0.
- A non-zero exit means the engine itself broke: not a repo, a parse error, or an unreadable
  recent-projects list.
- Each sweep holds a per-repo lock: a `mkdir` lockdir at
  `~/.local/state/agent-board/sweep-<hash of repo path>.lock`. macOS has no `flock` binary. When a
  second sweep finds the lock held, it prints `sweep already running` and exits 0. A lockdir left by a
  dead sweep (the pid in it is gone) is taken over.

## 2. Triggers and callers

1. **Merge hook.** `claude/hooks/worktree-sweep.sh` is registered as a PostToolUse `Bash` hook in
   `claude/settings.json`.
   - It acts only when the command that ran contains `git merge`, `git pull`, `glab mr merge`, or
     `git branch -d`/`-D`.
   - It starts `agent-worktrees sweep <repo of the command's cwd>` in the background, detached. It
     never blocks the tool call and never fails it.
   - The sweep's summary line (`swept: removed X; kept Y (reason)`) goes to the mirrored feed, the
     same way as `bash-mirror.sh`.
2. **Worker shutdown.** After the board's `shutdown_worker` closes the window (`tmux-ctl` has no
   worker-close command), it runs `agent-worktrees sweep --only <that worktree>`. A merged worker goes at once, and
   an unmerged one stays in Worktrees as before.
3. **One-click sweep.**
   - `Ctrl-a W` (`bin/tmux-agent-cleanup`): the first picker row is `⟳ remove all safe (N)`, which
     runs `sweep`. Stale rows are tagged `stale 9d`. Removal of marked rows calls
     `agent-worktrees remove`.
   - Board Worktrees panel: a `Remove safe (N)` button, a `stale` badge on stale rows, and the
     per-row Remove calls the engine's `remove`. `remove_agent_worktree`'s own lock and unlock logic
     is deleted.
4. **Scheduled sweep.** `com.user.agent-worktree-sweep.plist` runs `agent-worktrees sweep --recent`
   every day at 04:00. It appends to `~/.local/state/agent-board/worktree-sweep.log` (timestamp, repo,
   one line per worktree). The board shows the last run: `last sweep 04:00: removed 3, 2 stale`.
5. **Text.** `claude/orchestrator.md` (the "Finished worker worktrees are cleaned up by the user with
   `Ctrl-a W`" rule) and both `tmux-orchestrator` SKILL copies change to: "merged worktrees are
   removed automatically; stale ones are flagged on the board for the user to remove".

Out of scope: notifications beyond the feed line and the board, per-project configuration, and a
configurable stale threshold.

## 3. Testing

- **Engine (Python unittest):** the fixtures are real scratch git repos in a temp dir, one per state:
  merged, unmerged-fresh, unmerged-stale (`GIT_COMMITTER_DATE` in the past), dirty, untracked, locked
  with a live pid, locked with a dead pid, a pane cwd inside, and squash-merged with a `[gone]`
  upstream. The other cases are a squash MR whose head SHA differs, and a failing glab. External
  commands go through a seam (`AW_GLAB`, `AW_TMUX`), and fixtures for those commands are captured from
  real `glab` and `tmux` output.
- **One real run each:**
  - Against a scratch tmux server (`tmux -L <sock> -f /dev/null`) with a pane whose cwd is inside a
    worktree.
  - `glab mr list --merged --source-branch <a real merged branch>` in master-gcp-repo.
- **zsh harness (`tools/tests`):** the hook's command matching (it fires on merge and pull, not on
  `git status`), the hook never blocking, and the picker's new row.
- **Leak check:** no scratch worktrees, lockdirs or tmux servers are left after the suites.
- **Real, aged state (e2e):** `agent-worktrees classify` and `sweep --dry-run` on agent-board and
  master-gcp-repo as they are. Expected:
  - `docs-compose` (merged into main at 693e8b3) shows as safe.
  - `end-marker` is not safe until it is merged.
  - The scratchpad `frozen` worktree is not listed.
  - Then one real `sweep` removes `docs-compose`, and its branch is deleted with `-d`.
