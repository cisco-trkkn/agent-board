# Supervised improvement loop: outcomes, proposals, trials on real work, promotion with a protected set

Date: 2026-11-16 · Decided with the user over Discord, 2026-11-16, from two of the user's ChatGPT conversations
("Compare Pi Frameworks": autonomous execution, supervised evolution; "Beyond Spec Deployment": outcome-driven goal
loops, observability contracts, champion and challenger configurations).
Needs merged: `2026-11-10-pcee-engine-design.md` part 1 and part 2 (inbox §12, approval holds §13, schedules §14,
engine-run specs and briefs), `2026-11-10-queue-metrics-design.md` (run log, configurations, decision rule §5),
`2026-11-12-execution-analytics-design.md` (per-task records). Reads what these write, unchanged:
`2026-11-12-memory-consolidation-design.md`, `2026-11-12-opportunity-discovery-design.md`,
`2026-11-13-trend-scout-design.md`, and the task-observer workspace.
Queue position: last, after `2026-11-10-pcee-engine-design.md#part-2`.
Related ideas: guardrails for agent-board self-change, finding-to-work pipeline (ideas file, 2026-11-13); Pi spike
(filed 2026-11-16, not part of this spec).

## Problem

agent-board already produces improvement ideas from four places: the trend scout drafts specs, opportunity discovery
ranks work, memory consolidation distils recurring rulings into proposals, and task-observer stages skill updates. Each
lands as a Discord card, an idea or a staged note. Nothing connects them to a goal, nothing measures whether an adopted
change helped, and nothing takes a change back when it made things worse. The only judge is the user's attention.

The opposite failure is just as real: letting the system rewrite its own skills, rules and evaluation because a model
inferred a pattern. Models are not yet reliable judges of their own improvements.

The rule this spec builds: **learning is cheap, changing behaviour needs evidence, changing authority needs approval.**

## Decisions (user, 2026-11-16)

- **One spec**, queued last; the queued specs stay as approved. Small adapters read what they already write.
- **First outcome (O1):** tokens per merged task down 25% against the baseline configuration over at least 2 queues,
  with guardrails: failed specs, tests red after a merge, and critical/important final-review findings per spec must
  not rise.
- **Autonomy:** challengers run on their own. Low-authority changes (procedure wording, memory-entry rewrites) are kept
  or reverted automatically by evidence. Skills, rules, prompts and routing are promoted only by the user. Permissions
  and protected files are never trialled; they become drafted specs.
- **Evidence is real work only** (as the PCEE decomposition requires): a trial attaches the change to half of the
  engine-run specs, assigned by hash; after 5 trial specs the metrics decision rule compares the halves. No replays,
  no benchmark runs.
- **Protected set:** the loop never changes the evaluator, the decision rule, outcomes, gates, baseline flags, the lead
  and worker rules, hooks, settings and permissions, or its own code, and never promotes its own proposals beyond the
  low-authority class.
- **Start quiet:** Discord gets a card only for a decision that is the user's, and one weekly digest line.
- Claude Code stays the runtime. A Pi spike is an idea, not part of this spec.

## Revision 2026-11-20: lessons from Everything Claude Code (user: "Spec it", Discord 14:10Z)

Source: `docs/superpowers/notes/2026-11-20-ecc-insights-for-pcee.md` (affaan-m/ECC v2.2.3 at 4adeee6, MIT). The
ideas are taken; no ECC file, hook or plugin is installed or copied. These amendments bind the sections they name and
win over the text below where they differ.

- **R1. Deterministic evidence only (§1, §3).** Every `evidence` citation of a proposal, and every number a trial
  decision reads, comes from a deterministic capture: engine events, run records (`runs.jsonl`, `tasks.jsonl`), ledger
  lines written by code, or hook-written rows. A model's free-text note ("I noticed…") is never evidence by itself;
  an adapter that reads model-written text (dream, observer) cites the code-written record it came with (report
  file, run id) and the proposal stays at most `high`. Test: a proposal whose only evidence is model prose is
  refused with `no deterministic evidence`.
- **R2. A guardrail regression fixture (§4, §6, Testing).** The decision-rule tests gain a fixture in which a
  harmful proposal improves the outcome signal (tokens per merged task down) while a guardrail worsens (tests red
  after a merge up); the rule must return `reverted`, never `kept`/`awaiting_you`. Mutation named in the test: drop
  the guardrail check → the fixture is kept.
- **R3. Stop-blocking gates block once (§6, engine hooks).** Any hook or gate the loop adds that can block a Stop
  blocks at most once per stop attempt: when Claude Code reports `stop_hook_active`, it allows the stop and records a
  `gate_overridden` event instead. An unfixable condition can never trap a session. Test: a gate whose condition
  never clears blocks the first stop and allows the second, with one event.
- **R4. Spend cap per trial, failures counted (§2, §4).** Each proposal's trial carries a spend cap (default: 2× the
  control half's mean tokens per spec, times the trial length); a trial spec that would cross it ends the trial as
  `reverted` with `over budget`. O1's tokens-per-merged-task is computed with failed and abandoned trial specs
  included in the token sum (their tokens count; they add no merged task), so a variant cannot look cheaper by
  failing early. Tests: a trial whose failed specs are cheap but unmerged does not beat control; the cap ends a trial.
- **R5. Retire proposals (§3, §5).** New `kind` `retire`: the patch removes or disables a skill, rule, prompt section
  or memory entry. Class is derived as for other kinds (protected targets stay protected). Applying a kept/promoted
  retire is a soft delete: the target moves to `.superpowers/improve/retired/<id>/` (or its section is commented out
  with a `retired: <id>` marker) and an undo line is logged; `tmux-ctl improve revert <id>` restores it. At most 5
  retire proposals per tick; the dream and observer adapters may emit them for entries/skills unused for 30 days
  (from deterministic usage records only, per R1). Tests: retire then revert restores the file byte for byte; the
  cap holds.

## Design

### 1. Outcomes and observability contracts

- One file per outcome: `docs/superpowers/outcomes/<id>.json`, committed, in the protected set (section 6): only the
  user edits it (by hand, or by approving a drafted spec).
- Shape:

  ```json
  {"id": "O1",
   "statement": "Cheaper specs, quality held",
   "signal": {"metric": "tokens_per_task", "source": "metrics", "compare": "trial_vs_baseline"},
   "completion": {"change": -0.25, "min_queues": 2},
   "guardrails": [
     {"metric": "failed_specs", "rule": "not_worse"},
     {"metric": "red_after_merge", "rule": "not_worse"},
     {"metric": "final_review_crit_imp_per_spec", "rule": "not_worse"}],
   "state": "active"}
  ```

- Metric names are the run record's fields (queue-metrics §3, execution analytics §1). `not_worse` means the metrics
  decision rule (queue-metrics §5) does not return a worse verdict for that metric, with its noise allowance.
- States: `active`, `achieved`, `paused`. `tmux-ctl improve outcome status [<id>]` prints each active outcome's current
  value against the baseline, its guardrails, and the verdict.
- The spec's plan adds O1 as written above.

### 2. The goal loop

- An engine schedule (pcee engine §14): `improve tick`, rule `weekly Sun 08:00`, plus one run after every queue's
  morning report (the engine inserts a `schedule` inbox row for `improve` when it writes the report). Skipped at or
  over 85% weekly usage like every schedule.
- Code only; no model decides success. Each tick, in order, one transaction and event per step:
  1. **Observe:** `metrics report` for every active outcome; trial specs and control specs separated by their
     `variants` field (section 4).
  2. **Evaluate trials:** for each proposal in `trial` with at least 5 trial specs since it started: compare the trial
     half with the control half by the decision rule on the outcome's signal and every guardrail. Low authority:
     better or equal on the signal and no guardrail worse → `kept`; else `reverted` (the overlay is dropped; nothing was
     committed). High authority: the same comparison, then `awaiting_you` with a promote/reject card carrying the
     numbers.
  3. **Evaluate outcomes:** completion condition met → `achieved`, one Discord post. A guardrail worse across all
     engine-run specs since the last tick → every `trial` is reverted, `kept` changes since the last tick are listed in
     a card with a Revert button each (nothing reverted without the user, since a kept change may not be the cause).
  4. **Pick trials:** at most 2 proposals in `trial` at once. Candidates are `proposed` items in the low or high
     class whose target is not already in a trial. One model step (mechanical tier, at most 2k output tokens) ranks
     them by expected effect on the active outcomes, given each one's evidence; the top ones start (state `trial`).
     A ranking failure picks nothing that tick.

### 3. Proposals

- Table `proposals` in the engine database: `id` (`P<n>`), `source` (`scout`, `discovery`, `dream`, `observer`,
  `loop`, `user`), `kind` (`memory`, `procedure`, `skill`, `rule`, `prompt`, `routing`, `permission`, `spec`),
  `target` (repo path or skill name), `patch` (path to a unified diff under
  `${TC_STATE}/improve/<project>/patches/`), `evidence` (JSON list of citations: ledger line, ruling, finding key,
  run record), `class` (`observation`, `low`, `high`, `protected`), `state` (`proposed`, `trial`, `kept`, `reverted`,
  `awaiting_you`, `promoted`, `rejected`, `drafted`), `outcome` (an outcome id or null), times, `commit` (once kept or
  promoted). Every state change is an engine event.
- **Adapters** (run at the start of each tick; idempotent; key = source + target + sha256 of the patch):
  - `dream`: memory consolidation's `out/report.json` `proposals` → kind `rule` or `procedure` by its `kind`
    (`observer` → `procedure`, `idea` → `spec`).
  - `discovery` and `scout`: findings in the shared findings core with a drafted spec → kind `spec` (state `drafted`;
    the scout's own approval flow stays as it is; this only links them to an outcome when their text names it).
  - `observer`: task-observer staged updates in its workspace → kind `skill` with the staged diff as the patch.
  - `user`: `tmux-ctl improve propose --kind … --target … --patch <file> [--outcome O1]`.
- **Class** is derived, never chosen by the source: target in the protected set → `protected`; kind `permission` →
  `protected`; kind `memory` → `observation`; kind `procedure` with a patch that changes only prose lines of a
  procedure section (no code fence, no frontmatter, no command) → `low`; everything else → `high`.
- A `protected` proposal becomes a drafted spec (`state: drafted`): the tick writes
  `docs/superpowers/specs/drafts/<date>-improve-<id>.md` on a branch `improve/<id>` from `main`, and a card offers
  Approve (queues it like a scout spec) or Reject.

### 4. Trials

- Only engine-run specs carry trials (the engine builds their briefs). A spec is in a proposal's trial half when
  `sha256(spec id + proposal id)` is even; the other half is its control. The run record gains
  `variants: [<proposal id>…]`.
- How a change reaches a trial spec's workers:
  - `procedure`, `rule`, `prompt`: an overlay block in every brief the engine writes for that spec:
    `## Trial <id>` followed by the changed text and one line saying it replaces the named section of the target.
  - `skill`: a challenger copy `claude/skills/<skill>@<id>/` is created from the patch in the spec's worktree only
    (git-ignored path `.superpowers/improve/skills/`), and the brief names it instead of the champion.
  - `routing`: the engine's tier-to-model map for that spec's jobs is taken from the patched copy.
- The champion files on `main` are never touched by a trial.
- A trial spec that fails for a reason the event log ties to the variant (an architect ruling or a review finding that
  cites the trial block) ends that proposal's trial at once as `reverted`.

### 5. Promotion, versioning and rollback

- `kept` (low) and `promoted` (high, after the user's Promote) apply the patch on `main` as one commit
  `improve(<kind>): <proposal id> <short title>` with trailers `Proposal: <id>` and `Engine-Step: <key>` (pcee engine
  §10.4), path-scoped, through the engine's merge step and its live-checkout checks. Observations go through memory
  consolidation's own path, unchanged.
- `tmux-ctl improve list [--state …]`, `improve show <id>` (patch, evidence, trial numbers, commit),
  `improve revert <id>` (a `git revert` of its commit, state `reverted`, one event; refused for a protected target or
  without a commit).
- Discord: a card per `awaiting_you` (Promote / Reject / Extend trial by 5) and per `drafted` (Approve / Reject); one
  weekly digest line `🧪 improve: <n> trials, <k> kept, <r> reverted, <a> awaiting you; O1 <value> vs target`.
  Nothing else is posted.

### 6. The protected set

- `docs/superpowers/improve/protected.txt`, one glob per line, itself protected. Initial content:
  `board/metrics.py`, `docs/superpowers/metrics/**` (decision rule, gates, configurations' baseline flags),
  `docs/superpowers/outcomes/**`, `docs/superpowers/improve/**`, `claude/orchestrator.md`, `claude/worker.md`,
  `claude/plugin/hooks/**`, `claude/plugin/mods/**`, `.claude/settings*.json`, `~/.claude/settings*.json`, the
  improve loop's own code (`board/improve.py`, `tools/lib/improve.zsh`), and `bin/tmux-ctl`'s `improve` section.
  `docs/superpowers/model-routing.json` is not in the set: routing changes are `high` and reach it only as a commit the
  user promoted.
- Enforced three times: class derivation (section 3); the engine's merge step refuses an `improve(...)` commit whose
  diff touches a protected path unless the proposal is `promoted` by the user and not `protected`; and the engine's
  hold patterns (§13) gain a default hold for Write or Edit on any protected path inside an engine worker.
- The loop never promotes a `high` proposal itself, never edits an outcome, and never changes a proposal's class.

## Error handling

- An adapter that cannot read its source logs one event and is skipped that tick; the others run.
- A patch that no longer applies on `main` (the target changed): state `rejected` with `stale patch`, and the source is
  told the next time it runs only through the adapter's key (a new patch is a new proposal).
- A trial whose specs stop running (the queue empties) keeps its state; it resumes counting with the next queue.
- Metrics too thin for a verdict (`too early` from the decision rule): the trial continues; after 15 trial specs with
  no verdict it is `reverted` with `no signal`.
- Any write to `main` goes through the engine's merge step; when the live checkout is mid-change the commit waits for
  the next tick.

## Testing

- **Class derivation:** each kind and target, protected globs, the prose-only rule for `low` (a fenced block, a
  frontmatter line or a command in the patch makes it `high`).
- **Adapters:** fixture `report.json`, findings core state and task-observer workspace in temp dirs; idempotent re-run
  inserts nothing; the dedupe key.
- **Trial assignment:** the hash split is stable and close to half over 100 synthetic spec ids; `variants` recorded;
  overlays appear only in trial specs' briefs; the challenger skill copy only in the trial worktree; champion files
  byte-identical after a trial.
- **Tick:** synthetic run logs for every verdict path: low kept, low reverted, high to `awaiting_you`, guardrail breach
  reverting trials and carding kept changes, outcome achieved, `too early` continuing, 15 specs without a verdict
  reverted; at most 2 trials; ranking failure picks none.
- **Protected set:** the merge step refuses an `improve(...)` commit touching a protected path; the hold pattern denies
  a worker's Edit of `claude/orchestrator.md`; a protected proposal becomes a drafted spec on its own branch.
- **Revert:** `improve revert` creates one revert commit with the trailer and refuses without a commit.
- **Isolation:** `TC_ENGINE_DIR`, `TC_STATE` and a scratch clone for every test that commits; a scratch tmux server
  with `-f /dev/null`; a leak check that the real engine database, state dir and `main` are untouched.
- **Real run (user gate):** one queue with O1 active and one low-authority proposal from a real memory consolidation
  report: the trial split, the overlay in a real brief, and the tick's verdict line, shown in the morning report.

## Out of scope

- Outcomes beyond agent-board itself (client or business outcomes).
- Meta-agents that design experiments, or any change to evaluators by the loop.
- Replays, benchmark runs, and running trials on lead-run specs.
- A Pi runtime (filed as an idea).
- Changing the four source specs' behaviour; the adapters only read their outputs.
