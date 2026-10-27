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

Run by the user, not by the engine teammate: the Claude Code permission classifier denied `bin/agent-worktrees sweep ~/agent-board` in the teammate's session ("Irreversible Local Destruction"), and the user answered "Sweep both" to the lead's question about `runtime-audit`. The dry-run just before (run again by the teammate) listed exactly `would-remove docs-compose` and `would-remove runtime-audit`, with `wt-cleanup` kept. Output below is the user's, relayed by the lead, and the after-state was re-read by the teammate afterwards.

Before, `git -C ~/agent-board worktree list`:

    /Users/francisco.ruiz/agent-board                                     445696e [main]
    …/scratchpad/frozen                                                   8179153 (detached HEAD) prunable
    …/agent-board/.claude/worktrees/docs-compose                          71b2c12 [feat/docs-compose]
    …/agent-board/.claude/worktrees/runtime-audit                         e423fc7 [audit/runtime-baseline]
    …/agent-board/.claude/worktrees/wt-cleanup                            b5c760b [feat/worktree-auto-cleanup]

The sweep (`bin/agent-worktrees sweep ~/agent-board`, from the plan worktree's `bin/`):

    removed docs-compose
    removed runtime-audit
    kept wt-cleanup (uncommitted or untracked files)

After (re-read by the teammate):

    /Users/francisco.ruiz/agent-board                                     445696e [main]
    …/agent-board/.claude/worktrees/wt-cleanup                            b5c760b [feat/worktree-auto-cleanup]

    $ git -C ~/agent-board branch --list feat/docs-compose audit/runtime-baseline
    (empty)

Sweep log (`~/.local/state/agent-board/worktree-sweep.log`, new lines, fields time, action, name, reason):

    2026-10-26T13:05:14-04:00  removed  docs-compose
    2026-10-26T13:05:15-04:00  removed  runtime-audit
    2026-10-26T13:05:15-04:00  kept     wt-cleanup  uncommitted or untracked files

Both removed worktrees' branches were deleted with `git branch -d` (merged branches), and the directories under `.claude/worktrees/` are gone; only `wt-cleanup` remains.

**Observed side effect, not fixed:** the `frozen` scratchpad entry (`prunable`, outside `.claude/worktrees/`) also disappeared from the list. The sweep ends with `git worktree prune`, which drops the metadata of any worktree whose directory is gone from git's view; here `frozen`'s metadata was dropped (its directory still exists on disk). The engine never lists or removes worktrees outside `.claude/worktrees/`, but `git worktree prune` is repo-wide. Left as is for the final review to rule on.

## Schedule

Installed 2026-10-27 from `~/agent-board` on `main` (75442ab), on the user's go-ahead:

- `agent-board worktrees schedule install` → `installed ~/Library/LaunchAgents/com.user.agent-worktree-sweep.plist: sweep --recent every day at 04:00`, exit 0.
- `schedule status` → `state = not running`, `last exit code = (never exited)`; `launchctl list` shows `com.user.agent-worktree-sweep`.
- The plist runs `~/agent-board/bin/agent-board worktrees sweep --recent` with `PATH=~/.local/bin:/opt/homebrew/bin:/usr/bin:/bin`, logging to `~/.local/state/agent-board/worktree-sweep.launchd.log`.
- A bare-environment dry run (`env -i HOME=… PATH=<plist PATH> … sweep --recent --dry-run`) exited 0, with `would-remove connector-framework` in master-gcp-repo.

That dry run exposed a gap: `connector-framework` was clean and squash-merged, but held MR 1's SDD workspace (`.superpowers/`) and `.agent-ci/` state, both git-ignored, which `git worktree remove` deletes. The lead copied the SDD files into `ga4-connector-refit` (add-only), locked `connector-framework` until the fix landed, and the engine now keeps a would-be-safe worktree that holds ignored files other than caches (965a500).
