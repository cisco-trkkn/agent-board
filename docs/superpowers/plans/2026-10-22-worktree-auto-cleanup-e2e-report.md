# Worktree auto-cleanup: real-state e2e report

Run on 2026-10-26 from the plan worktree (`feat/worktree-auto-cleanup`, HEAD 3980b28), with the real `git`, `glab` and `tmux`.

## Classify (real repos)

`bin/agent-worktrees classify ~/agent-board` (full fetch; agent-board's `origin` is a GitHub remote, so the fetch is a no-op for glab). Exit 0, 1.3 s.

    $ git -C ~/agent-board worktree list
    /Users/francisco.ruiz/agent-board                       445696e [main]
    …/scratchpad/frozen                                     8179153 (detached HEAD) prunable
    …/agent-board/.claude/worktrees/docs-compose            71b2c12 [feat/docs-compose]
    …/agent-board/.claude/worktrees/runtime-audit           e423fc7 [audit/runtime-baseline]
    …/agent-board/.claude/worktrees/wt-cleanup              3980b28 [feat/worktree-auto-cleanup]

    $ bin/agent-worktrees classify ~/agent-board
    docs-compose    safe    merged
    runtime-audit   safe    merged
    wt-cleanup      dirty   uncommitted or untracked files

`bin/agent-worktrees classify ~/master-gcp-repo` (real GitLab remote; exit 0, 1.6 s):

    connector-framework    dirty    uncommitted or untracked files

Against the brief's expectations:

- `docs-compose` is `safe` (merged), as expected.
- `frozen` (the scratchpad worktree, outside `.claude/worktrees/`) is not listed, as expected. It is also `prunable` in git's own list.
- `end-marker` is no longer listed: its worktree directory is gone by now, so there is nothing to classify.
- The plan's own worktree (`wt-cleanup`) reads `dirty`, not `in_use`: other teammates have uncommitted files in it, and the check order is dirty, then lock and panes, then merged. Both states keep it from removal. The `in_use` path on a real tmux pane is shown under External commands.
- `runtime-audit` (branch `audit/runtime-baseline`) is also `safe`: it was merged into main (b2151bd, the "Merge branch 'audit/runtime-baseline'" commit), no pane is inside it and it has no lock. It was not in the brief's list; see the note under Real sweep.

`sweep --dry-run ~/agent-board` (nothing removed):

    would-remove docs-compose
    would-remove runtime-audit
    kept wt-cleanup (uncommitted or untracked files)

## External commands

**Real glab, parsed by the engine.** In `~/master-gcp-repo`, `glab mr list --merged --output json` returns one JSON array of 30 MRs (default page size), exit 0, stderr empty; first MR: `iid 333`, `state merged`, `source_branch staging`, `sha df65a5650dee17c86c24ec3b999510c22e95017b`. The engine's own `_squash_mr` (the function classify uses, with `--source-branch`), run against that real glab:

    _squash_mr(repo, 'staging', 'df65a565…017b')  -> (333, None)      # equal sha: verified squash
    _squash_mr(repo, 'staging', '0000…0000')      -> (None, None)     # other sha: not verified
    _squash_mr(repo, 'no-such-branch-aw', '0…')   -> (None, None)     # no merged MR

Note: a first attempt that piped `2>&1` into a JSON parser failed with "Extra data": that was stderr text mixed into stdout by my own redirect. The engine captures stdout and stderr separately and is not affected; a rerun with stderr separate gave an empty stderr.

**Real scratch tmux server.** `~/.local/bin/tmux -L aw-e2e -f /dev/null`, one session whose pane cwd is inside a fixture worktree (`<scratch>/repo/.claude/worktrees/fx`):

    $ tmux -L aw-e2e list-panes -a -F '#{pane_pid} #{pane_current_path}'
    80120 …/e2e/repo/.claude/worktrees/fx
    $ AW_TMUX="~/.local/bin/tmux -L aw-e2e" bin/agent-worktrees classify <scratch>/repo --offline
    fx    in_use    tmux pane inside
    $ tmux -L aw-e2e kill-server
    $ AW_TMUX=… classify <scratch>/repo --offline      # same worktree, server gone
    fx    safe    merged

After the kill, `tmux -L aw-e2e ls` prints `no server running on …/aw-e2e`, which the engine reads as "no panes".

**Bare environment, as launchd runs it (found a bug).** `env -i HOME=$HOME PATH=$HOME/.local/bin:/opt/homebrew/bin:/usr/bin:/bin bin/agent-board worktrees sweep --recent --dry-run` (no `TMPDIR`, no `TC_STATE`):

    would-remove docs-compose
    would-remove runtime-audit
    kept wt-cleanup (uncommitted or untracked files)
    kept connector-framework (tmux pane inside)
    skip /Users/francisco.ruiz/x-dev-notgit (not a repo)

This output did NOT prove the recent-projects.json lookup. Checking where the repos came from showed that the confstr fallback was dead: `os.confstr('CS_DARWIN_USER_TEMP_DIR')` raises `ValueError: unrecognized configuration name` (Python lists no name for it in `os.confstr_names`), the engine swallowed the error, and `recent_dir()` fell back to `/tmp/tmux-ctl-503`, where nothing exists. The unit test had patched `os.confstr`, which hid it. The repos above came from the live tmux sessions. Fixed in 7596477: the engine now calls `os.confstr(65537)` (`_CS_DARWIN_USER_TEMP_DIR`, accepted by both Python 3.9 and the Homebrew/system 3.x here), with a test that runs the real `os.confstr`. After the fix, in the same bare env: `recent_dir()` -> `/var/folders/2p/…/T/tmux-ctl-503`, and its `recent-projects.json` is read: `['/Users/francisco.ruiz/Desktop', '/Users/francisco.ruiz/MultiCloudTAGgen1']` (both resolve to repos with no agent worktrees: `~` is itself a git repo, so they print nothing). The sweep output above is identical after the fix.

**Real worker shutdown: NOT RUN (blocked, per the brief's stop rule).** In a scratch fixture repo on the `aw-e2e` server, `claude -w aw-e2e-w --permission-mode plan 'reply ok and stop'` stopped at once with `Error creating worktree: Workspace trust not yet accepted. Run claude once in this directory and accept the trust dialog, then retry with --worktree.` Accepting that dialog for a scratch directory is a permission I was not given, so I stopped. What this leaves open: the real shell-vs-Claude pid relationship behind `stop_agent`'s wait is still only covered by the two-process unit tests. It can be closed by one real worker shutdown on the live board.

**Real fzf picker.** Fixture repo with `picker-merged` (merged) and `picker-fresh` (one commit, unmerged), `bin/tmux-agent-cleanup <fixture>` in a pane of the `aw-e2e` server (state dir and tmux pointed at scratch):

    clean up ›
      3/3 (0)
      ⟳ = remove every merged, clean, unused worktree
    ▌ ⟳ remove all safe (1)
    ▌ picker-fresh      kept   not merged
    ▌ picker-merged     safe   merged

Enter on the first row:

    › remove all safe
      kept picker-fresh (not merged)
      removed picker-merged
    Done. Press any key…

Afterwards the fixture had only `picker-fresh` left, and the scratch sweep log had the two lines (`kept picker-fresh not merged`, `removed picker-merged`).

**Leak check.** The `aw-e2e` tmux server is killed (`tmux -L aw-e2e ls` -> `no server running`); the scratch repos and state dirs are deleted; no `sleep 30`/`aw-e2e` processes remain; `git worktree list` of the plan worktree (5 lines) and of `~/agent-board` are unchanged apart from this branch's HEAD. Side effect to know about: every `sweep --dry-run` run here appended its `would-remove`/`kept` lines to the real `~/.local/state/agent-board/worktree-sweep.log` (the board's "last sweep" ignores `would-remove` lines, but a `kept` line from a dry-run does move the "last sweep HH:MM" time).

## Real sweep

Not run. Waiting for the user's go-ahead (relayed by the lead). Open question for that go-ahead: the dry-run also lists `runtime-audit` (branch `audit/runtime-baseline`, merged by b2151bd, no pane or lock), which was not in the brief's expectations.

## Schedule

Not run. `agent-board worktrees schedule install` happens after the branch is merged to main, on the user's go-ahead. On this host `~/.local/bin/agent-board` does not exist, so the install will target the `agent-board` beside the CLI.
