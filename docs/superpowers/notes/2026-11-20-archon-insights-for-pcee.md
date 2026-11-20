# Archon: insights transferable to PCEE and agent-board

Date: 2026-11-20 · Author: archon (research teammate) · Not committed. These are findings and suggestions; the design decisions stay with the user and the lead.

## Summary

- Archon (`coleam00/Archon`, MIT, commit `f841a1be268c2ffb566d1ba735976bdcee6d249b`, branch `dev`) is a TypeScript workflow engine with an "SDLC pack": intake, build, review, merge and discoveries queues that run as YAML workflows, pausing as typed "attention items" for a person.
- Its design inverts ours: agents judge (route, sweep, answer) and scripts guard the irreversible edges; PCEE's strategy is a pure function and the engine does the judging in code. Do not copy that part.
- Eight ideas are worth taking or adapting: a typed ask with a mandatory recommendation and a "recommendation followed" rate, a per-run budget that fails on unmeasurable cost, verifier votes on blocking findings, a merge-gate checklist pinned to the head commit, a store of answers already given, a drain for out-of-scope discoveries, an idle-versus-stuck outcome, and a frozen review bench.
- Four ideas are skipped with reasons (agent-routed queues and YAML DAGs, per-concern model aliases, work orders, a model-judged test-value metric).

## How Archon works (as read)

Paths are in the Archon repo. "Docs" means files under `packages/docs-web/src/content/docs/`, read as the project's own description; every claim below was checked against a file I read.

- **Workflow format.** YAML, one of `steps:`, `loop:` or `nodes:` (a DAG): node types `command`, `prompt`, `bash`, `script`, `loop`, `loop_group`, `wait: attention`, `gate` (approval), `workflow` (child), with `depends_on`, `when:`, `trigger_rule` and typed `output_format` between nodes (`.claude/docs/workflow-yaml-reference.md`; nodes under `packages/workflows/src/dag/nodes/`).
- **Queues.** `archon-build-queue` (`.archon/workflows/sdlc/build-queue/archon-build-queue.yaml`) takes one triaged issue to a reviewed PR; `archon-merge-queue` merges PRs; both run on a per-issue "work item", a versioned state document claimed with conditional writes and an engine lease (docs `guides/sdlc-operations.md`, "Work items and claims"; `.archon/workflows/sdlc/.shared/stuck.ts`). The engine admits one build run per item.
- **Approval and answering.** A `wait: attention` node raises one attention item: question, options (id, label, does, value), recommendation (option, why, confidence), flat labels (`packages/workflows/src/schemas/wait-node.ts`). Surfaces: web console, browser push, and chat plugins that declare `attentionNotices`; Slack is in `packages/chat-slack/`, Discord and Telegram are in `packages/adapters/src/community/chat/discord/` and `packages/adapters/src/chat/telegram/` (docs `guides/workflow-triggers.md`, "Get notified in chat"). I did not read the Discord adapter's code.
- **Models.** Three tiers `small|medium|large` plus `@alias` names per concern (`@build-route`, `@sweep`, `@reviewer`, `@review-<lens>`), each falling back to a tier; set in a sealed per-run config (`.archon/config.example.yaml`; alias table in docs `guides/sdlc-operations.md`, "Policy and models"). `effort:` is a separate per-node field (`.claude/docs/workflow-yaml-reference.md`).
- **Cost and events.** Each agent attempt records `spend.costUsd` with a source or an "unavailable" reason; a run budget (`max_work_units`, `max_spend_usd`) is checked before each attempt and its ledger is rebuilt from durable rows on resume (`packages/workflows/src/run-budget.ts`, `packages/workflows/src/schemas/workflow.ts` lines 112-135, 210-215). Node events are persisted per run (`packages/workflows/src/node-event-write.ts`); logs are `logs/{workflow-id}.jsonl` under `~/.archon/` (`packages/paths/src/archon-paths.ts`).
- **How loops end.** `until_bash` (exit 0), `until_field` (a schema-validated boolean) or a `<promise>` sentinel, OR'd; `max_iterations` is required and reaching it fails the node unless `on_exhausted: complete`. The docs say externally checkable conditions use `until_bash` only, so a model cannot end a loop by saying a word (docs `guides/loop-nodes.md`, "Choosing a completion channel").
- **Worktrees.** A seven-step resolver (reuse by workflow identity, adopt a PR branch, a limit of 25 with auto-removal of merged branches, then create) in `packages/isolation/src/resolver.ts` as described by `.claude/docs/isolation-and-worktree-guide.md`; a workflow serializes runs on one path unless it sets `mutates_checkout: false` (`packages/workflows/src/schemas/workflow.ts` line 217). I read the guide, not the resolver.
- **Failure and retry.** AI nodes retry transient errors twice by default (3 s delay); `on_error` is a ladder transient, schema_unmet, all; script nodes get no default retry so side effects are never silently repeated (`packages/workflows/src/dag/retry.ts`).
- **Stores.** SQLite by default or PostgreSQL (`README.md`, `packages/core/src/db/adapters/`); run artifacts and logs under `~/.archon/`; work items, orders and metrics as state documents with `--if-revision` writes (docs `guides/sdlc-operations.md`).

## Ideas

"Take" means nearly as is; "adapt" means take the shape and change it; "skip" means do not copy. Ideas already in the ECC note or in loop spec R1-R5 are not repeated; where Archon extends one, the entry says so.

### 1. A typed ask: mandatory recommendation, options that say what they do, and a followed-rate (adapt)

- **Archon:** an attention item must carry a recommendation naming one of its options; the run fails if the recommendation is not an option id (`.archon/workflows/sdlc/.shared/policy/attention.md`; the build queue "refuses an attention item without the choice it recommends", docs `guides/sdlc-operations.md`, "Build queue"). Four labels (`stage`, `kind`, `item`, `pr`) classify it. The engine counts asks per label and how often the answer followed the recommendation (`packages/workflows/src/attention-counts.ts`; the command is quoted in `.archon/workflows/sdlc/CONSTITUTION.md`, "Stops the pack can't answer pause"). The constitution's stated direction: a recurring class gets a small handler that answers it.
- **We today:** a parked spec carries "the architect's ruling as the question" with options `approve|deny|fail` and a card in the feed (engine spec §4 and §13, `docs/superpowers/specs/2026-11-10-pcee-engine-design.md`). There is no required recommendation field and no count of asks by class or of answers that matched.
- **Change:** in the engine spec's `inbox`/`awaiting_you` payload (§10.3, §12), require `recommendation {option, why, confidence}` and a `kind` class; show it on the Discord card. Add one query to stage 1's metrics (`tmux-ctl metrics`): asks per `kind`, and the share answered as recommended.
- **Gain:** a phone answer becomes one tap; the followed-rate is the evidence stage 10's project owner needs to decide which classes it may answer alone, which today would be a guess.
- **Cost or risk:** the recommender is a model, so a high followed-rate may mean the user rubber-stamps, not that the model is right. Treat the rate as a candidate for autonomy, never as a grant; keep the high-authority classes of loop spec §6 always asked.
- **Verdict:** adapt.

### 2. A per-spec run budget in the engine core; unmeasured cost fails (adapt)

- **Archon:** a workflow may declare `budget: {max_work_units, max_spend_usd}`. A work unit is one started attempt, retries included. The engine writes a `run_budget_work_unit` event before the attempt starts and refuses a new attempt past the ceiling; attempts in flight may overshoot. Cost that cannot be proven is "unavailable, never zero", and a spend-limited run fails on it (`packages/workflows/src/run-budget.ts`, header comment; `packages/workflows/src/schemas/workflow.ts` lines 112-135). Loops and fan-out are rejected at load while a budget is declared (same file, line 212).
- **We today:** retry attempts are capped per job kind (engine spec §10.2) and loop spec R4 adds a spend cap per improvement trial. Nothing caps one spec's total attempts or tokens in a normal engine run; a spec can chain several jobs each within its own cap.
- **Change:** an engine-core `budget` per spec in `docs/superpowers/engine.json` (max job attempts, max tokens), checked when a job is admitted, with the intent event written first so a restart keeps the total (§10.4 journal). Treat a job whose tokens cannot be read from the statusline tap as unmeasured and park the spec instead of counting zero. Reuse the same number for R4's trial cap.
- **Gain:** a runaway spec stops in the night with a stated reason; R4's rule that failures stay in the sum gets one shared implementation.
- **Cost or risk:** how well our token capture covers every worker is unmeasured here. A strict unmeasured-fails rule could park specs on capture gaps; start with warn-only until K2 data shows the gap rate. Overshoot is by design; say so in the spec.
- **Verdict:** adapt (extends R4).

### 3. Independent verifiers vote on each blocking review finding (adapt)

- **Archon:** when a review verdict is "not ready", three independent verifiers judge each blocking finding; a finding most of them reject is demoted, a pre-existing defect to a discovery and an unreal one to "disproved" (`.archon/workflows/sdlc/review/archon-review.yaml`, description). Review also holds each change to the accepted contract with cited evidence per acceptance item (same description).
- **We today:** `critical` and `important` findings become a `fix` job straight away, up to five rounds (engine spec §3 step 5); the architect handles exhaustion (§4). No step checks that a finding is real before a fix round is spent on it.
- **Change:** in the `spec-driven` strategy (§3 step 5), before a `fix` job, one cheap standard-tier `verify_finding` job per blocking finding with only the finding and the diff, as a fresh session; fix only the confirmed ones, log the rest as `disproved` or `pre-existing`. One verifier, not three, as the first version.
- **Gain:** fewer fix rounds spent on mistaken findings, and fewer fix jobs that make the code worse to satisfy a wrong review. The K2 data would show it as fewer rounds per task.
- **Cost or risk:** one extra job per blocking finding; Archon's own cost is three. A verifier tends to agree with its reviewer when it sees the reviewer's reasoning, so give it the finding's claim and file lines, not the review text.
- **Verdict:** adapt.

### 4. A merge-gate checklist, pinned to the head commit (adapt, for stage 5)

- **Archon:** a script merges only what the sweep named, and only if the gate reads fresh that: the review verdict is Ready for this head; what the project's `ci` setting trusts passes at this head; the default branch's CI is not red; the PR is open, not a draft, at the head named; the head contains the default branch or merges cleanly; and, in the manual lane or for protected paths, a maintainer approved exactly that head. The merge is pinned to that head. An approval carries to a later head only when everything since is merges of the base, and any doubt voids it. Only review comments from a listed maintainer count, and the list is read from the default branch on the remote, so "a local copy does nothing". A red default branch merges nothing, ends the run with a failed outcome naming the suspect, and is reported once per change of head or check state (docs `guides/sdlc-operations.md`, "The gate" and "The default branch"; `.archon/workflows/sdlc/README.md`, step 4).
- **We today:** stages 4 and 5 are not designed (decomposition Status table: stage 4 and 5 "not started", gates K3 and K4). The Queue-mode merge approval is pinned to a branch name: on `[Discord] merge approved for <spec>` the lead runs `finishing-a-development-branch` with `merge` for that spec's branch (`claude/orchestrator.md`, Queue mode step 2).
- **Change:** (a) when stage 5 is designed, start from this list as its integrate-gate checklist, adding our own tests-after-merge and revert rule (engine spec §4). (b) Smaller and now: put the commit SHA in the `merge-request` Discord card and the approval line, and refuse the merge if the branch head moved since the card.
- **Gain:** (b) closes the window where a worker pushes after the user approved and the approved text is no longer what merges.
- **Cost or risk:** (b) means a re-ask when a late fix lands, which is the point. Archon's maintainer-allowlist rule has no counterpart here because only the user approves.
- **Verdict:** adapt.

### 5. A store of answers already given, read before asking (adapt)

- **Archon:** each ruling a maintainer gives is appended to `rulings.md` with a date and the issue it came from; plan and review read it before they stop to ask, and a question a ruling answers is settled (`.archon/sdlc/policy/rulings.md`, `.archon/factory/policy/rulings.md`). The chosen option's `ruling` text is also written into the issue body as a dated "Current scope" section so the next run reads it (`.archon/workflows/sdlc/.shared/policy/attention.md`, `options`). Policy files layer: a shared default, then the project's file, project wins (docs `guides/sdlc-operations.md`, "Policy and models").
- **We today:** the architect's `ruling` events are per spec (engine spec §4); a parked question's answer is stored with that spec's events. The project owner of stage 10 would hold "policy and budget" (decomposition, third revision), with no named place for answers to carry across specs.
- **Change:** a `rulings` file per project (`docs/superpowers/rulings.md`), one dated line per user answer to a parked or architect-escalated question, each with the case class from idea 1. The architect job's case file (§4) includes it; stage 10's owner reads it first.
- **Gain:** the same question is not asked on Discord twice; the project owner has a concrete input on day one.
- **Cost or risk:** stale rulings. Each carries a date and the spec path, and the architect cites the ruling it relied on so a wrong one is traceable. Writing a ruling is a user-visible step, so a single "remember this?" tap on the answered card, never automatic.
- **Verdict:** adapt.

### 6. Drain out-of-scope discoveries, once, with an idempotency marker (adapt)

- **Archon:** a run records "discoveries" it noticed outside its scope; a separate workflow later claims finished runs with undecided discoveries, verifies each against the default branch, merges duplicates across runs and earlier decisions, and decides each: file an issue, track on an existing one, drop with a reason, ask, or wait while the code is on an open PR. Filing is idempotent through a marker per key. The merge queue fires the drain after a sweep that merged something (`.archon/workflows/sdlc/discoveries/archon-discoveries.yaml`, description; docs `guides/sdlc-operations.md`, "Discoveries", "After a merge").
- **We today:** `minor` findings are "logged as deferred" and the final review is pointed at the deferred and parked events (engine spec §3 steps 5 and 6); `claude/worker.md` says a noticed pre-existing bug goes in the report as a follow-up. Ideas go to the ideas inbox by hand (`claude/orchestrator.md`, "Ideas inbox"). Nothing reads deferred findings across specs.
- **Change:** a typed `discoveries` list in the report contract (§2 workers), and a morning-report step that dedups them across the night's specs against the ideas file and writes the survivors as one list of `idea:` candidates for the user. Do not build the issue-filing half.
- **Gain:** follow-ups noticed by workers stop dying in per-spec ledgers.
- **Cost or risk:** one more model step per night; it is cheaper to have it run only when the report has more than a few discoveries.
- **Verdict:** adapt (small).

### 7. An idle queue run that finds stuck items reports a failure, not "empty" (take)

- **Archon:** a queue run that claims nothing while a stored item cannot be acted on (document does not parse, or a claim whose run holds no lease) names each such item once and ends as a failed outcome; "reports an empty queue" is not allowed to hide it. The report is recorded on the item so later idle runs do not repeat it (`.archon/workflows/sdlc/.shared/stuck.ts`, header comment; docs `guides/sdlc-operations.md`, "Work items and claims").
- **We today:** engine recovery (§9, §11) restarts what it can; the morning report summarizes the batch. The spec text does not say what the queue run reports when every remaining spec is parked, failed to start or stuck in `backoff`.
- **Change:** in engine spec §11 and §7 (morning report), name the case: queue drained with specs not in a terminal state ends `failed`, and the report lists each such spec once with its reason.
- **Gain:** a night where nothing ran never reads as a quiet success.
- **Cost or risk:** none beyond a few lines in two sections.
- **Verdict:** take.

### 8. A small frozen bench for review and prompt proposals (adapt)

- **Archon:** `archon-review-eval` runs the shipped review plus the simplify pass over a sealed sample (patch plus work order), and `bench.ts` launches it once per sample and collects what each lens wrote; a judge workflow scores it. The sample set is in the repo (`.archon/workflows/sdlc/review-eval/`, `.archon/workflows/sdlc/review-eval-judge/`, `.archon/sdlc/eval/review/{set.json,patches,work-orders}`). I read the workflow description and the file listing, not the bench script.
- **We today:** the improvement loop trials a proposal on real engine specs, half and half, against a frozen decision rule (loop spec §4); there is no offline pre-screen, so a plainly bad review-prompt proposal still costs live specs before it is reverted.
- **Change:** an optional cheap stage before a trial for proposals that change a review or architect prompt: replay N stored diffs (taken from past merged specs with known later fixes) through the changed prompt and compare found-versus-known defects. A failed bench ends the proposal as `rejected: bench` with no live spec spent.
- **Gain:** cheaper rejection of bad prompt proposals; builds the regression fixture set that R2 asks for.
- **Cost or risk:** a stored diff set must be curated and kept; the judge is a model, which R1 forbids as evidence, so score only against recorded later fixes (code-written), not a judge's opinion.
- **Verdict:** adapt, low priority.

### 9. Agents route and decide, scripts guard the edges (skip)

- **Archon:** "YAML coordinates, code computes, agents judge": the build queue's route, answer and revisit nodes, and the merge queue's sweep, are agent nodes on the `large` tier that decide what to run and what to merge (`.archon/workflows/sdlc/CONSTITUTION.md`, "Agents judge, scripts act at boundaries"; model aliases `@build-route`, `@build-answer`, `@sweep` in docs `guides/sdlc-operations.md`).
- **We today:** the `spec-driven` strategy is a pure function over rows and events; only review, architect and implementation are model work (engine spec §3).
- **Why skip:** each queue pass costs several large-tier agent runs, which cuts against PCEE's cost goal, and routing decisions that code can make would turn from testable to prompt-dependent. Our strategy tests feed events and compare commands; Archon's own constitution says not to test a prompt's route. The same applies to the YAML DAG format as an engine definition: our needs are one strategy and a job table.
- **Keep from it:** the rule "an exact value is never prose an agent interprets" is already how our policy tables work.
- **Verdict:** skip.

### 10. Per-concern model aliases with tier fallback and a sealed run config (skip)

- **Archon:** about 20 `@alias` names, each falling back to a tier; `.archon/config.<name>.yaml` is sealed at launch and a resume restores it (`.archon/config.example.yaml`; alias table in docs `guides/sdlc-operations.md`).
- **We today:** the tier map in `docs/superpowers/model-routing.json`, enforced effort, and engine spec §10.5's policy version, which records the policy a spec ran under.
- **Why skip:** the mapping per job kind is already a one-line table in our design, and §10.5 already freezes the setting for a spec. The one possible borrow, a per-run override of one job kind's model for an experiment, is what the improvement loop's `variants` already does.
- **Verdict:** skip.

### 11. Work orders: an approved set the pick may start from (skip)

- **Archon:** a state document lists issues approved for the factory; with `orders_only`, a pick starts only members (docs `guides/sdlc-operations.md`, "Work orders").
- **We today:** Queue mode asks once up front for the batch and stores each answer on the task; the lead then asks nothing until the morning report (`claude/orchestrator.md`, Queue mode step 1).
- **Why skip:** same function, already there. The approval is by the user's own batch, and an unattended pick never chooses what to build.
- **Verdict:** skip.

### 12. A model-judged test-value metric (skip)

- **Archon:** a workflow judges every test in each merged PR and records how many "protect nothing", with the judge's identity in the record and a calibrate workflow measuring agreement with humans (`.archon/workflows/sdlc/metrics-test-value/`, `metrics-test-value-calibrate`, `.archon/sdlc/metrics/test-value-cases.json`). I read the workflow descriptions, not the judge prompts.
- **We today:** nothing measures test quality; K2 measures tokens and merges (decomposition gates).
- **Why skip:** loop spec R1 forbids a model's opinion as evidence for a trial decision. The deterministic version, run the added tests against the pre-change source and count those that still pass, needs no judge; park that as an idea, not a take.
- **Verdict:** skip (the deterministic variant is an idea, below).

## What we already do better

- The engine core is durable and replayable: heartbeat, retry table by job kind, intent/result journal and replay check (engine spec §10), while Archon's pack leans on agent judgment for lifecycle decisions and keeps no comparable replay check in what I read.
- Improvement is measured: half-and-half trials against a frozen rule, with a protected set (loop spec §2, §4, §6). Archon has an eval bench and metrics but I found no promotion rule that changes its own prompts.
- Cost per task is measured and tiered with enforced effort (K2). Archon has per-run budgets but I found no per-task token metric against a baseline.
- Mobile control already works on the user's real Discord with dialogs and buttons for permission prompts; Archon's Discord adapter is a community plugin I did not read.
- Green checks are run by the engine against `verifyCommand`, not decided by an agent (engine spec §3 step 3); Archon's own docs reach the same rule for loops (`until_bash` only for externally checkable conditions) but its review verdict is model-written.

## Risks

- **Licence.** MIT, "Copyright (c) 2025-2026 Cole Medin" (`LICENSE`). Ideas and shapes carry no notice duty; copied text or code would.
- **Prompt-injection surface.** The repo is a bundle of agent prompts, hooks and a plugin installer. I read it as data and ran nothing from it. Do not install the `archon` CLI, its forge plugins or its skills into a project that runs engine workers.
- **Moving target.** `dev` changes daily (24k stars, many linked issue numbers in comments); any copied shape freezes at this commit. Claims about code are limited to the files named.
- **What I did not read.** The Discord and Telegram adapters' code, `packages/isolation/src/resolver.ts` (read the guide only), the review-eval `bench.ts`, the judge prompts, `packages/workflows/src/executor.ts` and the hooks and container features. Launchd scheduling (docs `guides/workflow-triggers.md`, "Configure a native macOS schedule") was not read beyond its heading.
- **No claim from memory.** Every Archon statement above names a file I opened in the clone; the stars figure and the adapters list come from the scan note and the directory listing.

## Suggested follow-ups (for the lead to decide)

1. Engine spec: require a recommendation and a `kind` on every parked question; add the followed-rate query to stage 1 metrics (idea 1).
2. Engine spec §10 and loop spec R4: one per-spec budget in the engine core, unmeasured cost parks (idea 2).
3. Engine spec §3 step 5: a `verify_finding` job before a `fix` job (idea 3).
4. Orchestrator Queue mode: put the commit SHA in the `merge-request` card and refuse a merge if the branch head moved (idea 4b).
5. Engine spec §7 and §11: a drained queue with non-terminal specs ends `failed` and lists them (idea 7).
6. Park as ideas: a `rulings` file per project (5), a discoveries list in the worker report (6), a frozen review bench (8), and a deterministic "do the added tests fail on the old code" metric (12).

## Source version

Archon commit `f841a1be268c2ffb566d1ba735976bdcee6d249b`, branch `dev`, committed 2026-11-20T15:15:44+02:00 (shallow clone, `HEAD`). The clone was read only, never run or built, and was deleted when the notes were finished.
