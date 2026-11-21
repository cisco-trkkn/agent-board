# Discover: real-state checks (2026-11-21)

Branch `spec-opportunity-discovery`, run from its worktree (`bin/tmux-ctl` of the worktree), data root the live checkout `/Users/francisco.ruiz/agent-board` (read-only, HEAD 52073ad). Model: a fake script, never the real `claude`.

## Collect

`env -u TMUX bin/tmux-ctl discover collect agent-board --root /Users/francisco.ruiz/agent-board --json` exited 0 and the output parses as JSON (keys `project, root, at, head, candidates, sources_skipped`).

Candidates per signal (all others: 0):

| signal | candidates |
|---|---|
| deferred_minor | 5 |
| repeated_ruling | 0 |
| flaky_test, slow_test, failed_run, todo, dependency, stale_idea | 0 |

`sources_skipped`:

- `flaky_test`: no test history
- `slow_test`: no test history
- `dependency`: `gh: Dependabot alerts are disabled for this repository. (HTTP 403)`

(The history file did not exist before the suite run, so both test signals were skipped, not just thin. `failed_run`, `todo` and `stale_idea` produced nothing and were not skipped.)

### The 3 highest-count keys, checked by hand

Each was checked against the ledger line (`sed -n <line>p`) and `git log --since=<ledger date> --format=%h -- <path> | wc -l` in the live checkout; the commit count equals the candidate's `count` in every case.

1. `deferred_minor:2026-11-18-reboot-auto-restore:d57a1d75`, count 10. Ledger `docs/superpowers/ledgers/2026-11-18-reboot-auto-restore/progress.md:43`: "Task 3: minor (deferred): docs/INSTALL.md:253 still shows send <file>… [-m <text>]". `git log --since=2026-11-18 -- docs/INSTALL.md` = 10 commits. Matches.
2. `deferred_minor:2026-11-19-remote-discord-only:7752e3df`, count 10. Ledger `…/2026-11-19-remote-discord-only/progress.md:115`: "Ruling: Task 7 adds tools/discord-bridge/bridge.js + its test to clear reply_armed … (Task 5 deferred minor) …". `git log --since=2026-11-19 -- tools/discord-bridge/bridge.js` = 10. Matches the count, but see the false-positive note below.
3. `deferred_minor:2026-10-28-shared-project-context:1f13755c`, count 8. Ledger `…/2026-10-28-shared-project-context/progress.md:45`: "Task 5: parked — claude/skills/tmux-orchestrator/SKILL.md (legacy copy) lacks tmux-ctl context — Ruling: leave it; …". `git log --since=2026-10-28 -- claude/skills/tmux-orchestrator/SKILL.md` = 8. Matches. (The other two: planview.py 6, CLAUDE.md 1; both verified by the same command.)

Quality observations (not blockers):

- Candidate 2 is a weak finding: the ledger line is the ruling that schedules the fix (Task 7 of that plan), so "deferred" there means "done later in the same plan". The signal cannot tell a deferral that was resolved by the plan's own later task from an open one; only a later ledger line with `fix`/`fixed` and the path suppresses it.
- Candidate 3 is a deliberate "leave it" ruling, not an open item; the user would likely Dismiss it.

### repeated_ruling

None qualifies. 44 ledger dirs have `Ruling:` lines, but no group of 3+ distinct ledger dirs shares the same first 6 words or the same first cited path plus first 3 words. The real ledger `Ruling:` texts are task-specific ("Task 7 adds …", "Task 5: … Ruling: leave it …"), so the first-6-words rule rarely collides. The criterion is met by the `deferred_minor` candidates above.

## Dry-run with a fake model

The fake (`scratchpad/fake-claude.py`, outside the repo) reads `collected.json` from its cwd and answers the `--output-format json` envelope with the top 3 keys by `count`.

### Guard, as the brief wrote the command

`TC_DISCOVER_CLAUDE=<fake> env -u TMUX bin/tmux-ctl discover nightly --project agent-board --dry-run`

```
discover: skipped, weekly 94%
```

The weekly usage guard (`dream.weekly_pct >= 85`) skipped it on real state, which proves the guard. The lead approved `--force` for this check.

### With `--force`

`TC_DISCOVER_CLAUDE=<fake> env -u TMUX bin/tmux-ctl discover nightly --project agent-board --dry-run --force` (rc 0):

```
discover: agent-board: 5 candidates, 3 ranked, 3 new, posted
🔎 discover agent-board: 3 new
1. Fix: Deferred in 2026-11-18-reboot-auto-restore and docs/INSTALL. — Deferred minor that keeps costing a look each time the file changes.
   value high · effort S · risk Low; docs or hint text only. · evidence: Task 3: minor \(deferred\): docs/INSTALL.md:253 still shows send <file\>… \[-m <text\>\]
2. Fix: Deferred in 2026-11-19-remote-discord-only and tools/discord — Deferred minor that keeps costing a look each time the file changes.
   value medium · effort S · risk Low; docs or hint text only. · evidence: Ruling: Task 7 adds tools/discord-bridge/bridge.js + its test to clear reply\_armed when an edit removes a dialog's buttons \(Task 5 deferred minor\) — otherwise a late reply to an answered dialog reaches the consumer — cost: one more file in Task 7.
3. Fix: Deferred in 2026-10-28-shared-project-context and claude/ski — Deferred minor that keeps costing a look each time the file changes.
   value low · effort S · risk Low; docs or hint text only. · evidence: Task 5: parked — claude/skills/tmux-orchestrator/SKILL.md \(legacy copy\) lacks tmux-ctl context — Ruling: leave it; install.sh --migrate moves \~/.claude/skills/tmux-orchestrator away because the plugin ships the skill, and the copy already diverges from the plugin copy in 5 places — cost if wrong: one table row missing in an uninstalled copy.
buttons: File as idea 1 | Dismiss 1 | File as idea 2 | Dismiss 2 | File as idea 3 | Dismiss 3
```

Output is 1542 bytes including the summary line (post limit 1900), 3 numbered items, 3 button rows (the dry-run prints them on one line: `File as idea n | Dismiss n`).

### State before and after

Before (`ls -la ~/.local/state/agent-board/discover/ ~/.local/state/agent-board/discord/agent-board/outbox/`, taken before the suite and the dry-runs):

```
ls: /Users/francisco.ruiz/.local/state/agent-board/discover/: No such file or directory
/Users/francisco.ruiz/.local/state/agent-board/discord/agent-board/outbox/:
total 0
drwxr-xr-x   3 francisco.ruiz  staff   96 Nov 21 03:45 .
drwx------  18 francisco.ruiz  staff  576 Nov 21 03:45 ..
drwxr-xr-x@  6 francisco.ruiz  staff  192 Nov 18 19:53 failed
```

`discover/` did not exist before. After the suite and both dry-runs:

```
ls: /Users/francisco.ruiz/.local/state/agent-board/discover/: No such file or directory
/Users/francisco.ruiz/.local/state/agent-board/discord/agent-board/outbox/:
total 0
drwxr-xr-x   3 francisco.ruiz  staff   96 Nov 21 03:55 .
drwx------  18 francisco.ruiz  staff  576 Nov 21 03:55 ..
drwxr-xr-x@  6 francisco.ruiz  staff  192 Nov 18 19:53 failed
```

`discover/` still does not exist (no state file, no run dir under `discover/runs/`: a `--dry-run` writes its run dir elsewhere or not at all). The outbox holds only the old `failed/` directory (same 4 files, dated Nov 18); no new outbox file. The outbox directory's own mtime moved from 03:45 to 03:54 with identical contents; the cause was not traced (a transient file by the live bridge or the suite's tests is the likely one).

## Test history

`tail -1 ~/.local/state/agent-board/tests/history.jsonl` (jobs trimmed): `{"ts": 1795251267, "root": "/Users/francisco.ruiz/agent-board/.claude/worktrees/spec-opportunity-discovery", "head": "e5e39333552f50660e025371e4023ab25db7ed9a", "dirty": false, "full": true, "jobs": {…187 jobs…}}`. The file did not exist before the run.

## Full suite

`zsh tools/tests/all.zsh; echo rc=$?` (through `tmux-ctl run -t 1500 tests`): `FAIL 9/187: board/test_metrics_backfill_privacy, board/test_metrics_weekly, zsh/test_ctl_approve_show.zsh, zsh/test_ctl_awake.zsh, zsh/test_ctl_context.zsh, zsh/test_ctl_discord_ops.zsh, zsh/test_ctl_discord.zsh, zsh/test_ctl_dream.zsh, zsh/test_ctl_wait_gone.zsh`, `rc=1`. All nine fail on the `bin/tmux-ctl` help range: line 754 prints `sed -n '2,77p'`, but the header's closing bare `#` line is now line 80, because `652d848` and `1e38741` added three `discover` usage lines (76-78 hold `discover collect|rank`, `discover nightly`, `discover schedule`) without raising the range. The range must become `2,80p`. The `discover nightly` line also still says "placeholder until it lands". Not fixed here (a fix round).
