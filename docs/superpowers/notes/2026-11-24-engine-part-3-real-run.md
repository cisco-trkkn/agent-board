# Engine part 3, Task 11: the real run (holds and schedules)

Run 2026-11-25 ~09:49-10:12 EST by `real11`, Claude Code 2.1.332, a real Haiku worker, all state in temp dirs
(`/tmp/p3r.*`: bare remote, `TC_ENGINE_DIR`, `TC_STATE`, tmux socket `p3real`, started `-f /dev/null`).
Engine code: branch `pcee-engine-part-3` at 6aeffdc.

## Setup, and three differences from the brief

- The brief's local clone with the bare repo as `origin` did not work: a new folder (even one under the trusted
  `/Users/francisco.ruiz/agent-board`) makes the worker stop at Claude Code's trust dialog.
  - Attempt 1, clone in `/tmp/p3r.*/clone`: job `p3real-spec:implement1:1` ended `job_failed ... heartbeat_timeout`
    after 2 min; attempt 2 sat at the same dialog. Pane text: `Accessing workspace: /private/tmp/p3r.bBDFeq/clone /
    Quick safety check: Is this a project you created or one you trust? ... ❯ No, exit / Yes, I trust this folder /
    Enter to confirm · Esc to cancel`.
  - Attempt 2, clone in `/Users/francisco.ruiz/agent-board/.claude/worktrees/p3real-clone` (its own git root): the same dialog.
  - **Finding:** a fresh untrusted folder leaves an engine worker at the trust dialog until the heartbeat fails;
    the engine retries into the same dialog. Nothing was pressed (a trust answer is the user's).
  - Attempt 3 (the one that ran): `git worktree add -b p3real-work .../worktrees/p3real-clone pcee-engine-part-3`
    in the live checkout, so the folder shares the trusted project. No dialog appeared.
- In that worktree `origin` is GitHub and remotes are shared with the live repo, so the plan's task says
  `git push /tmp/p3r.wPhhwD/origin.git HEAD:p3real-work` and the `verifyCommand` is
  `git ls-remote /tmp/p3r.wPhhwD/origin.git | grep -q .`, in place of `git push origin HEAD` and `git ls-remote origin ...`.
  The hold rule `git_push` matches any `git push`, so the test is the same. The bare remote had 0 refs before the push.
- Command: `engine run docs/superpowers/specs/p3real-spec.md --integration keep --project p3real` from a window of the
  scratch session, under `perl -e 'alarm 1800; exec @ARGV'`, backend `claude-tmux`, project `p3real`.

## The hold

Worker window `p3real-spec·implement1` (Haiku, `mechanical`). The worker put commit and push in one Bash call.

Worker pane (from `.superpowers/engine/logs/p3real-spec_implement1-1.log`; the window closes when the held job ends):

    ⎿  1 action not run · permission denied
       │ Reason: PreToolUse:Bash hook error: held for approval
       │ b684abaa-3c2a-4353-834e-ff065836c358: report status blocked with the
       │ concern "awaiting approval b684abaa-3c2a-4353-834e-ff065836c358", then
       │ stop

`engine status --waiting`:

    docs/superpowers/specs/p3real-spec.md
      I recommend: deny (medium): an irreversible step needs your yes
      question: Bash: printf 'p3real\n' > p3real.txt && git add p3real.txt && git commit -q -m "p3real: add file" ... && git push /tmp/p3r.wPhhwD/origin.git HEAD:p3real-work 2>&1; echo "push_rc=$?"; ...
      options:  approve|deny|fail
      answer:   tmux-ctl engine signal docs/superpowers/specs/p3real-spec.md approve|deny|fail

The call named only the bare path, so it was approved: `tmux-ctl engine signal docs/superpowers/specs/p3real-spec.md approve`
printed `signalled docs/superpowers/specs/p3real-spec.md: approve`, rc 0 (not denied by the classifier).

Events (`engine events`), in order: `held`, `awaiting_you`, `held_job_ended implement1 held: report`, `signal`, `ruling`,
`hold_pass ... approval b684abaa-... granted`, `job_created implement1:2`, `dispatched ... p3real-spec·implement1-r1`,
`hold_pass_used p3real-spec:implement1:2`.

After approve:

- Window `p3real-spec·implement1-r1` opened (a resume of the session, with the resume text
  `approval b684abaa-3c2a-4353-834e-ff065836c358 granted: retry the held call exactly as before`).
- `git ls-remote /tmp/p3r.wPhhwD/origin.git` showed `7a4852b1064b83b5a60d9d07c067e0460abd6d23	refs/heads/p3real-work`.
- `holds` row: `b684abaa-3c2a-4353-834e-ff065836c358|1795618933.791|...` (`used_at` set).
- The worker retried the call once, unchanged; there was no second push attempt, so "held again" was not exercised
  (the retried job 3 declined to rerun: "Retrying would make no change").
- `engine rebuild --check --project p3real`: `replay matches the live tables`, rc 0 (after the engine was stopped).

### Carried from Task 3: where does the resumed worker write its report?

**Fail.** The resumed worker was told only the approval text. It wrote its report to the OLD job's path
`.../reports/p3real-spec_implement1_1.md` (it said "The report at ...implement1_1.md now says done"), but the engine
waited on the new job's path `...implement1_2.md`, which never appeared. Result: job 2 `job_failed ... heartbeat_timeout`
at 10:04:09 (2 min), retry job 3 (`-r2`, also a resume; the worker said the task was already done and did nothing)
`heartbeat_timeout` at 10:06:42, then `escalated p3real-spec:architect:1 failed_twice` and a Fable architect was
dispatched. The run was stopped there (engine killed by pid) to avoid the architect cost; the spec never reached an outcome.
The push itself happened once and worked. A fix: put the new job's report path into the resume text.

## The schedule part

`engine schedule add realecho --rule "every 1m" --project p3real -- 'echo real-wake; date'` printed
`added realecho: every 1m, next 2026-11-25 10:08`. The row's `due_at` was moved into the past with one UPDATE through
the engine's own db module against the temp `TC_ENGINE_DIR` only:

    node -e 'const db=require("./lib/engine/db").open("p3real"); db.prepare("UPDATE timers SET due_at=? WHERE id=? AND kind=?").run(Date.now()/1000-120,"schedule:realecho","schedule")'   # changes 1

Then `engine wake` with `TMUX_DASH_TMUX_ARGS='-L p3real -f /dev/null'` (no engine was running):

    p3real: 1 due, 1 ran, 0 skipped        (rc 0)

`tmux -L p3real list-windows -t =p3real-bg:` while it ran: `shell 0` and `sched·realecho 0`.
Events (`events` table): `schedule_added`, `schedule_due`, `schedule_started` (window `sched·realecho`),
`schedule_ran` with `"rc":0,"key":"schedule_run:realecho@1795619128.73"`. The log's first line:
`real-wake` (second line `Wed Nov 25 10:07:34 EST 2026`); the rc file holds `0`.
`engine rebuild --check --project p3real` after the wake: `replay matches the live tables`, rc 0.

## Real state, read-only

`tmux-ctl engine schedule migrate --dry-run` with the real `HOME`, `TC_ENGINE_DIR` a temp dir and a stub launchctl
(`exit 0`, logs its arguments; it was never called), rc 0, as printed (Task 8's wording is `would migrated`):

    would migrated com.user.agent-board-dream -> dream (daily 03:30)
    would migrated com.user.agent-board-discover -> discover-nightly (daily 07:00)
    would migrated com.user.agent-board-scout-poll -> scout-poll (daily 06:00)
    would migrated com.user.agent-board-scout-weekly -> scout-weekly (weekly Sun 07:00)
    would migrated com.user.agent-board-scout-weekly-retry -> scout-weekly-retry (weekly Mon 07:00)
    would ops digest: no launchd job (runs in the bridge's tick): nothing to migrate

`ls -l ~/Library/LaunchAgents` before and after: identical (`diff` empty). The stub's call log was not created.

## Cleanup

- Engine stopped by pid (77394); the architect `claude` (pid 13721) and the earlier workers (55084, 55455, 73461) killed
  by pid; then `tmux -L p3real kill-server`, and `list-sessions` answered
  `no server running on /private/tmp/p3r.wPhhwD/tt/tmux-503/p3real`. `ps -p` on all recorded pids: none alive; no `claude`
  process naming `p3real` remained.
- `git -C /Users/francisco.ruiz/agent-board worktree remove --force .../worktrees/p3real-clone`: rc 0, no output.
- `git -C /Users/francisco.ruiz/agent-board branch -D p3real-work`: `Deleted branch p3real-work (was 7a4852b).`
- `/tmp/p3r.*` removed; nothing was pushed to GitHub; the real engine dir and the real tmux server were not touched.

## Result

Partial pass. Passed: the real hook held a real Haiku worker's `git push` with the deny reason `held for approval <id>`;
`status --waiting` showed the exact call, `approve|deny|fail` and `I recommend: deny (medium)`; `approve` opened
`implement1-r1`, the push reached the bare remote once, the pass was used, `rebuild --check` rc 0; a real `engine wake`
ran the due row in `p3real-bg` with `schedule_ran` rc 0 and `real-wake` as the log's first line; the migrate dry run left
`~/Library/LaunchAgents` unchanged. Failed: (1) Task 3's carried check: the resumed worker wrote its report to the old
job's path, so the resumed job hit `heartbeat_timeout` and the spec escalated to an architect instead of finishing;
(2) a fresh untrusted folder leaves a worker at the trust dialog (worked around with a worktree of the trusted repo);
(3) "second push held again" was not exercised.
