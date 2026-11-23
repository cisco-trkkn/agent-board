# Engine part 1: real run on a scratch worktree (2026-11-23)

Task 13, the part 1 done criterion: `engine run` took one tiny spec from a committed plan to a kept branch with real Claude workers in tmux windows and no lead turn in between. It needed three runs and one engine fix; the sections below record all of it.

## Setup

Spec `docs/superpowers/specs/2099-01-01-e2e-helper-design.md` (add `engine/lib/e2e_helper.js` exporting `slugWords(s)`, and its test). Plan `docs/superpowers/plans/2099-01-01-e2e-helper.md` with a `.tasks.json` of two tasks, each with a `verifyCommand`: Task 1 mechanical (the helper), Task 2 standard (its `node --test` file with an edge case).

Commands (run 3, the one that counts):

    git -C /Users/francisco.ruiz/agent-board worktree add -b e2e-engine-scratch \
        /Users/francisco.ruiz/agent-board/.claude/worktrees/engine-e2e-1795473713 spec-pcee-engine-part-1
    # in it: commit the spec, plan and .tasks.json (640f810)
    export TC_ENGINE_DIR=/tmp/e2e-tmp-1795473713/engine TC_PROJECT=agent-board TC_SESSION=agent-board-bg   # TC_STATE unset
    node engine/bin/engine.js run docs/superpowers/specs/2099-01-01-e2e-helper-design.md --integration keep --backend claude-tmux
    # stopped at the last step (finding 2 below); fix 5b52252 cherry-picked as fad4776, then:
    node engine/bin/engine.js resume

It ran in the foreground through `tmux-ctl send shell "… > log; echo rc=$? >> log"`, so the windows opened in the live `agent-board-bg` session.

Deviations from the dispatch, each decided by the lead:

1. **Scratch worktree instead of a `/tmp` clone.** Runs 1 and 2 used a clone (run 1 under `/tmp/engine-e2e-1795473158`, run 2 under `/Users/francisco.ruiz/agent-board/.claude/e2e/engine-e2e-1795473449`). A clone is its own git repository, and Claude's folder trust is per directory in `~/.claude.json`, so every worker stopped at "Do you trust this folder?". A git worktree of the trusted repo showed no prompt. This is also how the engine is meant to be used (specs in worktrees).
2. **Real `TC_STATE`** (unset, not a temp dir), so the worker hooks and the engine read the same agent-status directory. `TC_ENGINE_DIR` stayed a temp dir. Not tested with a temp `TC_STATE`: the workers never started in runs 1 and 2.
3. **Runs 1 and 2 failed on the trust prompt** (see Result, finding 1).

Guard on the live checkout `/Users/francisco.ruiz/agent-board`, before run 3 and after the cleanup: `git rev-parse HEAD main` printed `0dfbcb58499a4a955615eda18cb86f405dcd3f42` twice both times, and `git branch --show-current` printed `main` both times.

Job windows whose name contains `·` (`tmux list-windows -a -F '#{window_name}' | grep -c '·'`): 0 before each run, 0 after the cleanup.

Real-state check: with `TC_ENGINE_DIR` unset, `TC_PROJECT=agent-board node engine/bin/engine.js status` printed `no specs` (rc=0). `~/.local/state/agent-board/engine/` did not exist before and does not exist after (checked right after that status call and again after the cleanup): `status` creates nothing when there is no database.

## Event log

`tmux-ctl engine events docs/superpowers/specs/2099-01-01-e2e-helper-design.md` after the resume (79 lines; local times):

```
17:42:14 spec_added - docs/superpowers/specs/2099-01-01-e2e-helper-design.md
17:42:14 spec_started - docs/superpowers/specs/2099-01-01-e2e-helper-design.md
17:42:14 check_requested -
17:42:32 stale_result - fresh
17:42:32 job_created e2e-helper:implement1:1
17:42:32 step_intent - start_worker:e2e-helper:implement1:1
17:42:32 dispatched e2e-helper:implement1:1 e2e-helper·implement1 (mechanical, haiku)
17:42:32 step_done - start_worker:e2e-helper:implement1:1
17:42:37 job_session e2e-helper:implement1:1
17:42:37 inbox_worker e2e-helper:implement1:1
17:42:58 job_done e2e-helper:implement1:1 implement1 done
17:42:58 inbox_worker e2e-helper:implement1:1
17:42:58 check_requested -
17:42:58 check_result -
17:42:58 green_check -
17:42:58 job_created e2e-helper:review1:1
17:42:58 step_intent - close_window:e2e-helper:implement1:1
17:42:58 step_done - close_window:e2e-helper:implement1:1
17:42:58 step_intent - start_worker:e2e-helper:review1:1
17:42:58 dispatched e2e-helper:review1:1 e2e-helper·review1 (standard, sonnet)
17:42:58 step_done - start_worker:e2e-helper:review1:1
17:43:03 job_session e2e-helper:review1:1
17:43:03 inbox_worker e2e-helper:review1:1
17:43:14 job_done e2e-helper:review1:1 review1 pass
17:43:14 inbox_worker e2e-helper:review1:1
17:43:14 review -
17:43:14 task_complete -
17:43:14 job_created e2e-helper:implement2:1
17:43:14 step_intent - close_window:e2e-helper:review1:1
17:43:14 step_done - close_window:e2e-helper:review1:1
17:43:14 step_intent - start_worker:e2e-helper:implement2:1
17:43:14 dispatched e2e-helper:implement2:1 e2e-helper·implement2 (standard, sonnet)
17:43:14 step_done - start_worker:e2e-helper:implement2:1
17:43:19 job_session e2e-helper:implement2:1
17:43:19 inbox_worker e2e-helper:implement2:1
17:43:35 job_done e2e-helper:implement2:1 implement2 done
17:43:34 inbox_worker e2e-helper:implement2:1
17:43:35 check_requested -
17:43:35 check_result -
17:43:35 green_check -
17:43:35 job_created e2e-helper:review2:1
17:43:35 step_intent - close_window:e2e-helper:implement2:1
17:43:35 step_done - close_window:e2e-helper:implement2:1
17:43:35 step_intent - start_worker:e2e-helper:review2:1
17:43:35 dispatched e2e-helper:review2:1 e2e-helper·review2 (standard, sonnet)
17:43:35 step_done - start_worker:e2e-helper:review2:1
17:43:41 job_session e2e-helper:review2:1
17:43:41 inbox_worker e2e-helper:review2:1
17:43:51 job_done e2e-helper:review2:1 review2 pass
17:43:51 inbox_worker e2e-helper:review2:1
17:43:51 review -
17:43:51 task_complete -
17:43:51 spec_state -
17:43:51 job_created e2e-helper:final_review:1
17:43:51 step_intent - close_window:e2e-helper:review2:1
17:43:51 step_done - close_window:e2e-helper:review2:1
17:43:51 step_intent - start_worker:e2e-helper:final_review:1
17:43:51 dispatched e2e-helper:final_review:1 e2e-helper·final_review (frontier, fable)
17:43:51 step_done - start_worker:e2e-helper:final_review:1
17:43:56 job_session e2e-helper:final_review:1
17:43:56 inbox_worker e2e-helper:final_review:1
17:45:52 timer_fired e2e-helper:final_review:1
17:45:52 deadline e2e-helper:final_review:1
17:45:52 inbox_timer e2e-helper:final_review:1
17:47:38 timer_fired e2e-helper:final_review:1
17:47:38 deadline e2e-helper:final_review:1
17:47:38 inbox_timer e2e-helper:final_review:1
17:49:04 job_done e2e-helper:final_review:1 final_review pass
17:49:04 inbox_worker e2e-helper:final_review:1
17:49:04 spec_state -
17:49:04 integrate_requested -
17:49:04 step_intent - commit_ledger:docs/superpowers/specs/2099-01-01-e2e-helper-design.md
17:49:04 step_done - commit_ledger:docs/superpowers/specs/2099-01-01-e2e-helper-design.md
17:49:04 step_intent - metrics_record:docs/superpowers/specs/2099-01-01-e2e-helper-design.md
17:49:05 step_failed - metrics record failed: metrics: record: unknown batch null
17:56:40 integrated - kept e2e-engine-scratch
17:56:40 spec_done - kept e2e-engine-scratch
17:56:40 step_intent - close_window:e2e-helper:final_review:1
17:56:40 step_done - close_window:e2e-helper:final_review:1
```

The gap between 17:49:05 and 17:56:40 is the stop of run 3 and the lead's fix. The resume's foreground output also printed `17:56:40 resumed -`, which the events listing above does not show.

## Windows

Opened = the `dispatched` event; closed = `step_done close_window` for that job. Every window was closed by the engine; the window count after the cleanup is 0.

| Job | Window | Tier, model | Opened | Closed |
|---|---|---|---|---|
| e2e-helper:implement1:1 | e2e-helper·implement1 | mechanical, haiku | 17:42:32 | 17:42:58 |
| e2e-helper:review1:1 | e2e-helper·review1 | standard, sonnet | 17:42:58 | 17:43:14 |
| e2e-helper:implement2:1 | e2e-helper·implement2 | standard, sonnet | 17:43:14 | 17:43:35 |
| e2e-helper:review2:1 | e2e-helper·review2 | standard, sonnet | 17:43:35 | 17:43:51 |
| e2e-helper:final_review:1 | e2e-helper·final_review | frontier, fable | 17:43:51 | 17:56:40 |

The final_review window stayed open for 13 minutes because the engine stopped (finding 2) before its close step; the resume closed it (`step_intent` and `step_done close_window:e2e-helper:final_review:1` at 17:56:40). The windows of runs 1 and 2 (`e2e-helper·implement1`) were killed by name by the implementer when those runs were stopped.

## Result

Outcome: `kept e2e-engine-scratch` (spec state `done`). The resume printed `outcome: kept e2e-engine-scratch`, rc=0 (wall 1 s). Run 3 took 430 s to its stop (rc=1); all five jobs had `done` on the first attempt.

Branch head `fad477652e3185c335a15389f0e294b4eccf64b8`. `git log --oneline spec-pcee-engine-part-1..e2e-engine-scratch` (the branch was cut from the engine branch, so that is the base, not `main`):

    fad4776 fix(engine): metrics record never blocks finalize
    c40e4b3 docs(ledger): docs/superpowers/specs/2099-01-01-e2e-helper-design.md progress
    c5042ae test(engine): e2e helper slugWords tests
    0c048de feat(engine): e2e helper slugWords
    640f810 docs: e2e spec and plan

`c5042ae` and `0c048de` are the workers' commits, `c40e4b3` is the engine's ledger commit, `fad4776` is the lead's fix cherry-picked in.

The plan's verify commands on the branch, run after the resume: Task 1's `node -e '…slugWords("Hello, World")…'` rc=0; Task 2's `node --test engine/test/e2e_helper.test.js` rc=0 (3 tests pass, 0 fail).

Findings:

1. **The engine did not see Claude's trust prompt as needs-you.** Runs 1 and 2 (clone paths above): job `e2e-helper:implement1:1` stayed on "Do you trust this folder? ❯ No, exit / Yes, I trust this folder" and failed with `heartbeat_timeout` after 2 minutes (17:33:14 to 17:35:15 in run 1; 17:38:01 to 17:40:02 in run 2). The retry hit the same prompt. The window's last lines were in each clone's `.superpowers/engine/logs/e2e-helper_implement1-1.log` (the clones are removed). No needs-you state was raised before the heartbeat deadline.
2. **A `keep` run without `--batch` could not finish.** After the final review passed (17:49:04), `integrate.js finalize` ran `tmux-ctl metrics record … --batch null`, `board/metrics.py` raised `unknown batch null`, and the engine stopped with `[Engine] stopped: metrics record failed: metrics: record: unknown batch null`, rc=1, spec left in `integrating`. Fixed by lead commit 5b52252 (no metrics record without a batch; a failed record never stops finalize). The resume then completed the integrate in 1 s with no new worker tokens.
3. **The final_review window was left open** when the engine stopped, and closed by the resume (see Windows).
4. The `final_review` worker (fable) ran the whole engine test suite on a three-line change; a cost observation, not an engine failure.

## Rebuild

`TC_ENGINE_DIR=/tmp/e2e-tmp-1795473713/engine TC_PROJECT=agent-board node engine/bin/engine.js rebuild --check` printed `replay matches the live tables`, rc=0, after the resume and before the cleanup.

Cleanup: `git worktree list` before listed `engine-e2e-1795473713 fad4776 [e2e-engine-scratch]` beside the three existing worktrees (the live checkout, `spec-pcee-engine-part-1`, `supervised-improvement-loop`, `troubleshoot-why-agent-board`). After `git worktree remove --force` of it, `git branch -D e2e-engine-scratch` and `rm -rf /tmp/e2e-tmp-1795473713`, only those remain, `git branch --list 'e2e*' '*e2e-helper*'` prints nothing, and the `.claude/e2e/` directory is gone.
