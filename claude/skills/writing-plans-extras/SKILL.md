---
name: "writing-plans-extras"
description: Local additions to superpowers-extended-cc:writing-plans. Use together with writing-plans, every time it runs, before drafting any task. It overrides three base rules. Step granularity follows each task's modelTier (frontier tasks get goal, constraints and acceptance criteria instead of code). Audit or discovery tasks are exempt from code in every step. In autonomous sessions the execution handoff is a printed kickoff prompt instead of AskUserQuestion. It also requires every e2e task to check real, aged state and not only a fresh scratch fixture, and commit steps to name the harness attribution trailer instead of a literal model line.
---

# writing-plans extras

Load alongside `superpowers-extended-cc:writing-plans`. Where this file and the base skill disagree, this file wins; everything else in the base skill stands.

## 1. Granularity follows modelTier

How much a plan prescribes should match how capable its executor is. Scripted steps help a small model and hurt a frontier one, which does better with a goal and room to choose the method.

- `mechanical`: full steps with code, as the base skill says.
- `standard`: the base format, with code where the pattern is non-obvious.
- `frontier`: Goal, Constraints, Acceptance Criteria, Verify. No Steps block and no code. The executor chooses the method. "No Placeholders" does not apply; the acceptance criteria and the Verify line are the contract.

Example, a frontier task:

```
**Goal:** Reconnect a dropped worker session without losing its queue.
**Constraints:** no change to the queue file format; reconnect within 5s.
**Acceptance Criteria:** [ ] kill -9 on a worker, queue length unchanged after reconnect
**Verify:** `tests/e2e/reconnect.sh` → exit 0
```

## 2. Audit or discovery tasks

A security review, threat model or inventory cannot have its code written in advance. Write the task around its deliverable, a document with checkable structure, and the executor decides how to find the content.

- Name the output path.
- List the required sections or fields.
- Acceptance Criteria count and cover: "every route in `routes/` appears in the table", "each finding cites file:line".
- Verify is a command that checks that structure, e.g. `grep -c '^## ' report.md` against the expected number.

## 3. Handoff in autonomous sessions

When nobody is watching (worker mode, a system prompt that forbids questions, a scheduled run), skip the `AskUserQuestion` in Execution Handoff: it fails there. Print the base skill's Parallel Session kickoff prompt in a fenced block, name the plan path, and end the turn. A line before the fence says which execution skill the prompt invokes.

## 4. e2e acceptance criteria use real state

A fresh scratch project hides every bug that needs accumulated state. Each e2e task carries at least one of these in its Acceptance Criteria and Verify:

- a read-only check against the user's existing long-lived state (real board, real logs, installed config);
- or a fixture aged past a day boundary and seeded with several agents or sessions.

Example: "the feed renders in order for a log that spans midnight" is verified by `feed --dry-run ~/.agent-board/log` (read-only), not by a log created five minutes ago.

## 5. Values the executor's environment supplies

When tasks route to different models, don't write a value that each executor's harness provides. Commit steps say "end with the attribution trailer your harness specifies", never a literal `Co-Authored-By: Claude <model>` line. A hardcoded line contradicts the trailer a Haiku or Sonnet teammate is told to use, and each one stops to ask or picks its own.

## Before you finish

Re-read the plan's tasks: every `frontier` task has no Steps block, every e2e task names a real-state or aged-fixture check, no commit step hardcodes a model attribution line, and an autonomous session ends with a printed prompt, not a question.
