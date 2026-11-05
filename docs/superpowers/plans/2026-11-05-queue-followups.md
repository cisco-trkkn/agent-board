# Queue mode follow-ups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mark ideas when their specs are queued, and make the running plan an item of Queue mode's exceptions list with a stated `metadata.queue.current` shape.

**Architecture:** Rule text only: two sentences in `claude/orchestrator.md`, one paragraph in the overnight-queue spec, three `check` lines in `tools/tests/test_plugin.zsh`.

**Tech Stack:** Markdown, zsh test harness (`tools/tests/lib.zsh` `check`).

**Spec:** `docs/superpowers/specs/2026-11-05-queue-followups-design.md`

## Global Constraints

- The Queue mode step 1 line ("  1. **Ask once, up front**…") must not grow: it is 1743 bytes before the change, ≤ 1743 after.
- Never commit the user's uncommitted "Carrying out a plan" row edit (it lives only in the main checkout, not in this worktree).
- Run only `zsh tools/tests/test_plugin.zsh`, never the full suites (user rule).

**User decisions (already made):**
- The running plan gets no separate question; it is the first item of the exceptions multiSelect (2026-11-05).
- Queue mode integration for this branch: merge to main locally.

---

### Task 1: Rule text, spec alignment and plugin checks

**Goal:** `claude/orchestrator.md` marks ideas at queue time and lists `Running plan: <title>` first in the exceptions multiSelect with the full `metadata.queue.current` shape; the overnight-queue spec says the same; three new `test_plugin.zsh` checks pass.

**Files:**
- Modify: `claude/orchestrator.md` (Next steps round step 3, line 69; Queue mode step 1, line 72)
- Modify: `docs/superpowers/specs/2026-11-05-overnight-queue-design.md` (the "When a plan is still running" paragraph, lines 66-70)
- Test: `tools/tests/test_plugin.zsh` (append before `tt_done`)

**Acceptance Criteria:**
- [ ] Three new checks fail before the rule edit (RED output captured) and pass after.
- [ ] `zsh tools/tests/test_plugin.zsh; echo rc=$?` prints `ALL PASS` and `rc=0`; `grep -c FAIL` on its output is 0.
- [ ] The Queue mode step 1 line is ≤ 1743 bytes.
- [ ] The spec paragraph no longer contains `counted in call 1's question cap` and contains `"plan": "<plan path>"`.

**Verify:** `zsh tools/tests/test_plugin.zsh; echo rc=$?` → `ALL PASS`, `rc=0`

**Steps:**

- [ ] **Step 1: Add the failing checks.** Insert these three lines in `tools/tests/test_plugin.zsh` immediately before the final `tt_done`:

```zsh
check "lead rules: ideas are marked when queued" grep -qF 'ideas are marked when queued' "$O"
check "lead rules: running plan is the first exceptions item" grep -qF '`Running plan: <title>`' "$O"
check "lead rules: metadata.queue.current shape names the plan" grep -qF 'metadata.queue.current = {"plan": "<plan path>"' "$O"
```

Mutation: each one fails on the current `orchestrator.md` (the phrases are absent).

- [ ] **Step 2: RED.** Run `zsh tools/tests/test_plugin.zsh 2>&1 | grep -E 'FAIL|ALL PASS'`. Expected: exactly those three names as FAIL.

- [ ] **Step 3: Edit Next steps round step 3** in `claude/orchestrator.md`. Replace this exact text:

```
queue each approved spec as a `Plan & run:` task in the order chosen (each blocked by the previous one), then apply Queue mode below.
```

with:

```
queue each approved spec as a `Plan & run:` task in the order chosen (each blocked by the previous one), mark their ideas now as step 4 says (ideas are marked when queued, so the round after the queue never offers them), then apply Queue mode below.
```

- [ ] **Step 4: Replace Queue mode step 1.** Replace the whole line starting `  1. **Ask once, up front**` with exactly this line (keep the two leading spaces):

```
  1. **Ask once, up front**, before running anything, with at most two AskUserQuestion calls; every question names the specs by title and stands on its own. Call 1: the default integration for every item (merge to `main` locally / push and open an MR / keep the branch); which items differ from it, as a multiSelect with a None option, the running plan (the `regroup` path) first as `Running plan: <title>`, then the specs (3 items per question, AskUserQuestion's 4-option limit: more go in further questions, 4 per call, call 1 first); and, only when the default is the MR, consent to push those branches, the running plan's too, and run `gitlab-ci-loop` on them (If installed). Call 2, only when needed: each excepted item's option, 4 per call, plus the push consent if an exception chose the MR and call 1 did not ask it. More than two calls only for a queue too big for two. A push yes is the user's "asked to push" for those branches only, never `main` or `master`; a no turns them into "keep the branch". Write each answer to its task with TaskUpdate: `metadata.queue = {"integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}`, with `answeredAt` read from `date -u +%Y-%m-%dT%H:%M:%SZ`, never written by hand. The running plan's answer goes on the first `Plan & run:` task as `metadata.queue.current = {"plan": "<plan path>", "integration": …, "push": …, "answeredAt": …}`; that plan's `finishing-a-development-branch` uses it. A spec queued after the batch gets one question then, with the queue default recommended. Apart from that one question, after the batch the lead asks the user nothing until the morning report; anything that would need an answer fails that spec instead (step 3).
```

Length check: `grep '^  1. \*\*Ask once' claude/orchestrator.md | wc -c` → ≤ 1744 (1743 + newline).

- [ ] **Step 5: Align the spec.** In `docs/superpowers/specs/2026-11-05-overnight-queue-design.md`, replace the paragraph that starts `When a plan is still running (the \`regroup\` path), the batch also asks` and ends `the lead asks nothing until the morning report.` with:

```
When a plan is still running (the `regroup` path), it takes the queue's default integration and is the
first item of the "which differ" multiSelect, as `Running plan: <title>` (one item toward the 3 per
question); if picked, call 2 asks its option like an excepted spec's. The MR push consent covers its branch
too, never `main` or `master`. The answer is stored on the first `Plan & run:` task as
`metadata.queue.current = {"plan": "<plan path>", "integration": "merge" | "mr" | "keep", "push": true | false, "answeredAt": "<ISO>"}`,
and that plan's `finishing-a-development-branch` uses it. `answeredAt` is read from
`date -u +%Y-%m-%dT%H:%M:%SZ`, never written by hand. A spec queued after the batch gets its question; apart
from that one, the lead asks nothing until the morning report.
```

- [ ] **Step 6: GREEN.** `zsh tools/tests/test_plugin.zsh > /tmp/tp.out 2>&1; echo rc=$?; grep -c FAIL /tmp/tp.out; tail -1 /tmp/tp.out` → `rc=0`, `0`, `ALL PASS`.

- [ ] **Step 7: Commit** (stage only these paths):

```bash
git add claude/orchestrator.md docs/superpowers/specs/2026-11-05-overnight-queue-design.md tools/tests/test_plugin.zsh
git commit -m "docs(orchestrator): mark ideas at queue time; running plan is an exceptions item"
```

End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/orchestrator.md", "docs/superpowers/specs/2026-11-05-overnight-queue-design.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh; echo rc=$?", "acceptanceCriteria": ["three new checks RED then GREEN", "test_plugin ALL PASS rc=0, 0 FAIL lines", "Queue mode step 1 line <= 1743 bytes", "spec paragraph drops 'counted in call 1's question cap' and has the plan key"], "modelTier": "mechanical"}
```
