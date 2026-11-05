# Overnight queue: run queued specs without input

Idea (2026-11-04 22:20): "when i have multiple specs queued up (like before going to bed) i want all of these
to be implemented without needing any input from me. i want the lead to recognize the multiple queued specs
scenario and ask me all the questions it will need to upfront (for example how to integrate finished features)".

## Problem

`claude/orchestrator.md` already queues approved specs as pending `Plan & run: <spec path>` tasks (`regroup`
step 4) and runs them in order in the Next steps round. That run still stops for the user:

- `finishing-a-development-branch` asks how to integrate every finished branch (orchestrator.md, Workflow
  table: "it asks the user how to integrate").
- `subagent-driven-development` stops for its four stop classes (irreversible, security-sensitive, a side
  effect outside the worktree that norms say to ask about, a plan so broken every path is a guess).
- Pushing and opening an MR (`gitlab-ci-loop`) runs "only after the user asked".
- User-gate tasks wait for the user.

So a queue of three specs left overnight finishes the first plan and then waits at the integration menu.

## Decisions (user, 2026-11-05)

- **Trigger:** two or more pending `Plan & run:` tasks. No explicit command, no single-spec mode.
- **Integration answers:** one default for the whole queue, plus a second question for specs that differ.
- **On a failed spec:** keep its branch unmerged, note it for the morning, go on with the next spec, based on
  `main` as it stands.
- **Approach A:** rules in `claude/orchestrator.md` only; answers stored as metadata on the `Plan & run:`
  tasks. No new command or state file.

## Design

All changes are in `claude/orchestrator.md`, in a new subsection **Queue mode** under "Ideas inbox", plus
one-line pointers where the existing text would otherwise contradict it.

### 1. Entering queue mode

The lead checks the queue at two points: when a Next steps round starts, and right after `regroup` step 4
creates a `Plan & run:` task. If two or more `Plan & run:` tasks are pending and none carries
`metadata.queue` yet, it enters queue mode and asks the up-front batch (§2) before it runs anything else.
A queue that already has answers (a resumed or handed-off session) is not asked again.

A spec queued after the batch was answered (a later `regroup`) gets its own one-question ask at queue time,
with the queue default as the recommended option.

### 2. The up-front batch

At most two AskUserQuestion calls, each question standing on its own (the user may only see the dialog):

**Call 1** (always):
1. **Default integration** for every queued spec: merge to `main` locally / push and open an MR / keep the
   branch. The question names the queued specs by title.
2. **Exceptions** (multiSelect, with a "None" option): which specs differ from the default.
3. **Push consent**, asked only when the default is "push and open an MR": consent to push those branches and
   run `gitlab-ci-loop` on them.

**Call 2** (only when call 1 named exceptions): one question per excepted spec for its option (up to four;
more excepted specs than four get a third call), plus the push-consent question if an exception chose
"push and open an MR" and call 1 did not ask it. This is the last question of the night.

A push-consent yes is the user's "asked to push" for those branches only. Never `main` or `master`. A no
turns those specs' option into "keep the branch".

The answers are written to each `Plan & run:` task with TaskUpdate:
`metadata.queue = {"integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}`.

When a plan is still running (the `regroup` path), the batch also asks how to integrate that plan (same
three options, counted in call 1's question cap). The answer is stored on the first `Plan & run:` task as
`metadata.queue.current`, and that plan's `finishing-a-development-branch` uses it. `answeredAt` is read from
`date -u +%Y-%m-%dT%H:%M:%SZ`, never written by hand. A spec queued after the batch gets its question; apart
from that one, the lead asks nothing until the morning report.

The Next steps round queues too (user, 2026-11-05): when two or more groups are picked in step 2, each goes
through `brainstorming` to an approved written spec (no `writing-plans`), is queued as a `Plan & run:` task in
order (each blocked by the previous), and queue mode starts. One group picked: unchanged.

### 3. Running the queue

For each `Plan & run:` task in order:

1. Branch off `main` as it stands now (so a spec merged earlier tonight is included), in a worktree under
   `.claude/worktrees/` as usual.
2. `writing-plans` (with `writing-plans-extras`), then a fresh Skill call to `subagent-driven-development`.
3. `finishing-a-development-branch` with the stored option: the lead does not present the menu. It still runs
   every step around the menu: tests before, the merge-result tests after, the worktree cleanup rules. The
   live-checkout rules stay: check `ListAgents`, `git status` and `git log -3` before merging, and carry any
   uncommitted user edit across the merge as a patch (dry-run first; if the patch doesn't apply, do not merge
   and treat the spec as failed, §4).
4. Mark the task completed with `metadata.outcome`: `merged <sha>` / `mr <url>` / `kept <branch>` /
   `failed — <one line>`.

### 4. What changes in queue mode

- **Stop classes become skip-and-record.** Where `subagent-driven-development` would stop and ask (its four
  classes), the lead stops that spec only: keeps the branch, records `failed — <class>: <one line>`, and goes
  on. A red merged result, a final review with load-bearing residuals, or a patch that won't apply is the
  same.
- **A spec whose spec text depends on a failed spec** is still attempted; its plan is written against `main`
  as it is, and its own review catches a missing piece.
- **User-gate tasks** are not run. They stay pending in the plan and are listed in the morning report.
- **Handoffs** relay without asking (already the rule for a self-started handoff). The handoff doc's State
  section says `Queue mode: on` and lists each queued spec (spec path, its `metadata.queue`, the running plan's
  `metadata.queue.current`, its outcome if done). Task lists are per session, so the new lead recreates the
  pending `Plan & run:` tasks from those lines and asks nothing.
- **The ideas round** (Next steps round steps 1–4) is skipped until the queue is empty, because it asks
  questions.
- **Permission prompts** in teammate windows cannot be answered for the user (unchanged rule). The lead
  records each one it sees waiting longer than 10 minutes and, if the spec cannot progress, treats it as
  failed with `blocked on a permission prompt in ✦ <name>`.

### 5. Morning report

When the last `Plan & run:` task is completed, the lead writes
`docs/superpowers/reports/YYYY-MM-DD-queue.md` (date of the run's start) and commits it on `main` (or leaves
it uncommitted if the live checkout is mid-change), then runs `tmux-ctl artifact <path>`. Content, per spec:
title and spec path, outcome (`metadata.outcome`), branch or merge commit or MR URL, every `Ruling:` line
from its ledger with what it costs if wrong, user-gate checks waiting, permission prompts seen. Then the
lead leaves queue mode and runs the normal ideas round.

The Rules line "Don't push, merge or delete branches unless the user asks" notes that a queue-mode answer is
the user asking, for those branches only.

## Out of scope

- A board view of the queue, a `tmux-ctl queue` command, a queue state file.
- Running queued specs in parallel.
- Answering permission prompts.

## Testing

- `tools/tests/test_plugin.zsh` (or a new `test_orchestrator_queue.zsh` beside it) checks that
  `claude/orchestrator.md` has the Queue mode subsection, names `metadata.queue`, the ≥2 trigger, the
  three-question batch and the morning report path, and that the Workflow table's finishing row points at
  queue mode.
- One real dry run before merge: a scratch repo with two tiny doc-only specs queued as `Plan & run:` tasks;
  a lead started there asks exactly one batch, then finishes both with the stored options and writes the
  report. Its transcript and report go in the plan's final report.

## Implementation notes

- The live checkout holds the user's uncommitted `claude/orchestrator.md` edit (the "Carrying out a plan"
  row). This change also edits `claude/orchestrator.md`: work in a worktree, and at integration carry the
  user's edit across as a patch, dry-run against the branch version first.
