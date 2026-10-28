# Faster Fix Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local skill, `subagent-driven-development-extras`, cuts wasted review rounds in plan execution. It adds three levers: green verify before any review, a cheaper re-review for small fixes on mechanical tasks, and one batched review for runs of mechanical tasks.

**Architecture:** One Markdown skill in `claude/skills/`, loaded alongside the plugin's `subagent-driven-development` the same way the three existing `-extras` skills are loaded (a `~/.claude/skills` symlink plus a companion line in `~/.claude/CLAUDE.md`). The lead's rules in `claude/orchestrator.md` name it. No plugin code changes.

**Tech Stack:** Markdown skill (frontmatter `name` + `description`), written with `superpowers-extended-cc:writing-skills` and `writing-for-agents`.

**Spec:** `docs/superpowers/specs/2026-10-28-faster-fix-loop-design.md`

## Global Constraints

Quoted from the spec; the skill must state each exactly:
- **Bounce:** a report without the task's `verifyCommand` result (command, output, exit code), or, where `.agent-ci.yml` exists, without `agent-ci check` output, or with either one red, goes back to the same implementer before any reviewer. It is not a fix round and does not count toward the 5-round cap. Ledger: `Task <N>: bounced <k>/2 (<what was missing or red>)`. A third bounce makes the task `BLOCKED` (base escalation).
- **Small fix:** FIX_BASE..HEAD has ≤20 changed lines, ≤2 files, no added files, no deleted or skipped tests, and covering tests green in the fix report.
- **Small-fix re-review:** only on a `mechanical` task. Dispatched with `model: haiku` and an effort-low agent type, using the base `re-review-prompt.md` unchanged. Every other fix uses the base standard-tier re-review. The re-review is never skipped. Ledger: `Task <N>: fix round <R>/5 (small, mechanical re-review) …`.
- **Batch:** consecutive `mechanical` tasks that passed the bounce check; it closes at 5 tasks, at the next non-mechanical task, or at the plan's end. Never batched: a task whose files or brief touch security (auth, IAM, secrets), migrations, CI configuration or shared config. A batched task stays `in_progress` until its batch is reviewed. One standard-tier reviewer gets `scripts/review-package PLAN_FILE <batch base> <batch head>`, each task's brief and report paths, and the global constraints, and returns spec and quality verdicts **per task**. Findings enter that task's normal fix loop. The final whole-branch review is unchanged.
- The skill stays inside the plugin's routing gate (dispatch models are limited to the in-progress task's tier and `standard`) and never tells anyone to set `SUPERPOWERS_ROUTING_GUARD=0`.
- No changes to the plugin's skills or hooks.
- Work happens in the worktree `~/agent-board/.claude/worktrees/execution-flow` (branch `feat/execution-flow`).

**User decisions (already made):**
- Approach A, with all three levers, as a new `subagent-driven-development-extras` skill.
- Thresholds: small fix ≤20 lines / ≤2 files; batch ≤5 tasks; at most 2 bounces.
- Rejected: lever 1 alone; reviewers patching trivial findings themselves.

**Ruling made while planning (deviation from the spec, 2026-10-28):** the spec's acceptance run (a scratch plan with a planted red verify and a planted small finding) moves to "After merge", step 4, and runs on the next real plan. Why: the skill loads only through the `~/.claude/skills` link into the live checkout, so before the merge no session can load it by name. Cost if wrong: the levers are first exercised on real work; step 4 reports any lever that was not exercised.

---

### Task 3: subagent-driven-development-extras skill and orchestrator row

**Goal:** `claude/skills/subagent-driven-development-extras/SKILL.md` states the three levers as overrides of the base skill's "Review the task" and "The fix loop" sections, and the orchestrator's "Carrying out a plan" row names it.

**Files:**
- Create: `claude/skills/subagent-driven-development-extras/SKILL.md`
- Modify: `claude/orchestrator.md` (workflow table row "Carrying out a plan")

**Acceptance Criteria:**
- [ ] Frontmatter has `name: subagent-driven-development-extras`, and the `description` starts with "Local additions to superpowers-extended-cc:subagent-driven-development. Use together with subagent-driven-development, every time it runs".
- [ ] The body has these H2 headings, in this order: `## 1. Green before review`, `## 2. Small-fix re-review on the task's tier`, `## 3. Batched review for consecutive mechanical tasks`, `## Before you finish`.
- [ ] Each Global Constraints bullet appears with its numbers and ledger line forms verbatim: `bounced <k>/2`, `≤20 changed lines`, `≤2 files`, `(small, mechanical re-review)`, `5 tasks`, `per task`.
- [ ] The skill names the routing-gate limit and contains no instruction to set `SUPERPOWERS_ROUTING_GUARD=0` (the only occurrence of that string, if any, says not to set it).
- [ ] The skill says where it wins over the base skill and that everything else in the base skill stands, in the style of `claude/skills/writing-plans-extras/SKILL.md` (first paragraph).
- [ ] `orchestrator.md`'s "Carrying out a plan" row contains `subagent-driven-development-extras`.
- [ ] Under 120 lines (the largest existing extras skill is 110).

**Verify:** `f=claude/skills/subagent-driven-development-extras/SKILL.md; grep -c '^## ' $f; grep -cE 'bounced <k>/2|≤20 changed lines|≤2 files|\(small, mechanical re-review\)|5 tasks|per task' $f; grep -c 'subagent-driven-development-extras' claude/orchestrator.md; wc -l < $f` → `4`, ≥`6`, `1`, <`120`

**Steps:**

- [ ] **Step 1: Load the authoring skills.** Invoke `superpowers-extended-cc:writing-skills` and `writing-for-agents`. Read `claude/skills/writing-plans-extras/SKILL.md` and `claude/skills/requesting-code-review-extras/SKILL.md` for the house style (a frontmatter description that says when to load it, a short "where this file and the base skill disagree, this file wins" paragraph, numbered H2 sections, each with the rule, a one-line why, and a concrete example, and a closing self-check). Read the base skill's sections "3. Review the task" and "4. The fix loop" in `~/.claude/plugins/cache/superpowers-extended-cc-marketplace/superpowers-extended-cc/6.5.3-dev/skills/subagent-driven-development/SKILL.md`, so each lever names the base rule it overrides.

- [ ] **Step 2: Write the skill.** Create `SKILL.md` with the four headings from the Acceptance Criteria. Each lever section states the rule from Global Constraints, the base-skill rule it replaces or narrows, its ledger line form, and one example (e.g. lever 1: "a report saying 'tests pass' with no command output is bounced, not reviewed"). `## Before you finish` is a checklist: every reviewer dispatch was preceded by a green bounce check; every Haiku re-review was on a mechanical task with a small fix; no batch held a security, migration, CI or shared-config task; every batched task got its own verdicts.

- [ ] **Step 3: Update the orchestrator row.** In `claude/orchestrator.md`, in the "Carrying out a plan" row, replace `` `subagent-driven-development`, started as soon `` with `` `subagent-driven-development` with `subagent-driven-development-extras` (not a superpowers skill), started as soon ``. (Task 2 of the plan-handoff plan wrote "started as soon as the plan is written"; if that text is absent, stop and report it.)

- [ ] **Step 4: Run the Verify command** and check the four values.

- [ ] **Step 5: Commit.**

```bash
git add claude/skills/subagent-driven-development-extras/SKILL.md claude/orchestrator.md
git commit -m "feat(skills): subagent-driven-development-extras for a faster fix loop"
```
End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/skills/subagent-driven-development-extras/SKILL.md", "claude/orchestrator.md"], "verifyCommand": "f=claude/skills/subagent-driven-development-extras/SKILL.md; grep -c '^## ' $f; grep -cE 'bounced <k>/2|≤20 changed lines|≤2 files|\\(small, mechanical re-review\\)|5 tasks|per task' $f; grep -c 'subagent-driven-development-extras' claude/orchestrator.md; wc -l < $f", "acceptanceCriteria": ["frontmatter name and description as specified", "four H2 headings in order", "Global Constraints numbers and ledger forms verbatim", "routing-gate limit named; no instruction to set SUPERPOWERS_ROUTING_GUARD=0", "wins-over-base paragraph in the extras house style", "orchestrator row names subagent-driven-development-extras", "under 120 lines"], "modelTier": "standard"}
```

---

## After merge (lead, at the integration step)

The skill goes live through files outside git, so these run after `finishing-a-development-branch` merges to `main`, not as plan tasks.

1. **Install the link:** `ls -l ~/.claude/skills/subagent-driven-development-extras` must not exist yet; then `ln -s ~/agent-board/claude/skills/subagent-driven-development-extras ~/.claude/skills/subagent-driven-development-extras`.
2. **Companion line:** back up `cp ~/.claude/CLAUDE.md ~/.claude/CLAUDE.md.bak-$(date +%Y%m%d)`, then add under "# Plan and review companions":
   `- Whenever \`superpowers-extended-cc:subagent-driven-development\` runs, also load \`subagent-driven-development-extras\` (green before review, small-fix re-review tier, batched mechanical review).`
3. **Real-state check (read-only):** a new session lists `subagent-driven-development-extras` among its skills; `readlink ~/.claude/skills/subagent-driven-development-extras` points into `~/agent-board/claude/skills/`.
4. **End-to-end, on the next real plan with ≥3 mechanical tasks:** before Finish deletes the workspace, `grep -E 'bounced|small, mechanical re-review|batch' <repo>/.superpowers/sdd/<plan>/progress.md` shows the levers that fired, and the session shows no routing-gate block. Report what fired and what did not. A lever that never had a trigger is "not exercised", not "passed".
