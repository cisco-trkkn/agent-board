# Runtime optimization, Phase 1 — design

Date: 2026-10-28 · Source: roadmap Phase 1 of `docs/superpowers/reports/runtime-audit/report.md`
(items 1.1–1.11; 1.7 already done in c24ce6b) · Baseline: the 2026-10-25 audit run.

## Goal

Act on the audit's low-risk findings in one round: cut what every session loads (skill listing,
observer mandate, Stop-hook time), and record what is lost today (handoff lineage, SDD ledgers,
teammate spawns, late context warnings). One spec, one plan, one before/after measurement.

## Out of scope

- Editing any third-party or plugin file (task-observer, superpowers-extended-cc, anthropic-skills).
  Their changes go upstream as feedback drafts.
- Installing the task-observer 2026-10-28 staged round (its own manual step).
- tmux-orchestrator's duplicate copy (observation #70 beyond handoff).
- Phase 2+ items (instrumentation, experiments, autonomy).

## Ownership and delivery

| Area | Files | Who edits |
| --- | --- | --- |
| Hooks | `claude/hooks/*.sh`, `claude/hooks/tests/` | implementer (repo) |
| Prose rules | `claude/orchestrator.md`, `claude/worker.md`, `claude/skills/subagent-driven-development-extras/`, our skill descriptions | implementer (repo) |
| Board state | `board/relay.py`, `board/artifacts.py`, `claude/plugin/scripts/artifact-register.sh`, `bin/tmux-session-closed` | implementer (repo) |
| Review job | `claude/hooks/task-observer-review.sh` | implementer (repo) |
| User config | `~/.claude/settings.json`, `~/.claude/skills/handoff` link, `~/.claude/handoffs/`, lineage migration | lead, main session only |

User-config changes follow the CLAUDE.md procedure: back up as `F.bak-20261028`, stage a generated
`F.next`, `patch --dry-run` against live, then swap. `settings.json` is swapped once, carrying every
key and registration this spec adds. The repo's `claude/settings.json` gets the same keys.

## 1.1 Skill listing

- Our skills (links into `claude/skills/` and `claude/plugin/skills/`): descriptions over 300 chars are
  shortened to at most 300. The trigger sentence stays; for the `-extras` skills the "use together
  with X, every time it runs" trigger is kept verbatim, because CLAUDE.md depends on it. Rule
  summaries move into the body.
- Plugin and third-party skills: `skillOverrides` only. A skill gets `name-only` when the audit
  window shows 0 Skill calls for it and its description exceeds 300 chars; `off` only when it is out
  of scope for this user's work. The list is computed from the toolkit's per-skill call counts in the
  plan, not chosen by hand; skills already overridden stay as they are.

## 1.2 Observer stub

`claude/hooks/task-observer-session-start.sh` runs the cheap parts of the Session Start Protocol
itself: the storage `ls`, the open count, the review-due check (unchanged rule: `never` or 7+ days
with open observations), `review-started.txt` not reading `completed` (reported as "fired <date>, no
review recorded"), and the count of entries in `skill-updates/`.

It emits one short summary line plus the rule: load the task-observer skill only when (a) writing an
observation, (b) a review is due and the user opts in, or (c) staged updates need reconciling. The
"before writing or proposing a plan" clause becomes "re-read this summary". The worker exemption
(`TC_ROLE=worker`) and the teammate exemption are kept. Observation files are still created only by
`scripts/new-observation.sh`. A feedback draft proposes the same split to the plugin upstream.

## 1.3 Stop-hook short-circuit

`claude/hooks/superpowers-hook.sh` reads stdin once, extracts `session_id`, and exits 0 before
resolving the plugin script when the guard cannot act. The marker is the session's native task
directory, `~/.claude/tasks/session-<first 8 chars of session_id>/`, which the wait guard itself
reads (its condition 4):

- `stop-wait-guard.sh`: no `*.json` there contains `"status": "in_progress"`.
- `stop-revalidate-user-gates.sh`: no `*.json` there matches `userGate`, `user-gate` or
  `USER-ORDERED GATE` (case-insensitive).

A transcript-text marker was rejected: probe 2026-10-28, 199 of the 200 most recent transcripts
contain both `executing-plans` and `user-gate`, because the skill listing carries them.

Otherwise the buffered stdin is piped to the real script unchanged. Missing `session_id`: pass
through to the real script (it fails open itself). `post-task-complete-revalidate.sh` is not
short-circuited. The plugin's own disable variables keep working.

## 1.4 Review job budget

`claude/hooks/task-observer-review.sh` adds `--max-budget-usd <value set in the script>` and
`--fallback-model sonnet` to its `claude -p` call (both flags confirmed in `claude --help` on
2026-10-28). After the run:

- output containing the usage-limit message ("hit your … limit"): write `limit-hit <date>` to
  `review-started.txt`;
- budget cap reached: write `budget-hit <date>`;
- otherwise the existing `completed <date>` behaviour.

The 1.2 stub surfaces any non-`completed` value, so a limit death is no longer silent. The next
Mon/Wed/Fri slot is the retry.

## 1.5 State paths

**Lineage.** One helper resolves `~/.local/state/agent-board/lineage/<project>.jsonl` (overridable for
tests through the existing state-dir variable). `board/relay.py` writes it, `board/artifacts.py` and
`claude/plugin/scripts/artifact-register.sh` read it, and `bin/tmux-session-closed` no longer
deletes it. Runs, artifacts and feeds stay in `$TMPDIR`. A one-time lead step appends the existing
`$TMPDIR` `lineage-*.jsonl` records to the new files.

**Handoffs.** The repo copy `claude/plugin/skills/handoff` becomes canonical. The lead repoints
`~/.claude/skills/handoff` (today → `~/.agents/skills/handoff`, recorded before the change) to it,
moves the docs in `~/.claude/handoffs/` into `~/.local/state/agent-board/handoffs/`, and leaves
`~/.claude/handoffs` as a symlink to the new directory. `claude/skills/docs-report/SKILL.md:55` names
the new path. `orchestrator.md:31` keeps reading both.

## 1.6 Dedupe the agent rules

`claude/worker.md` becomes the single home for rules common to every agent the lead starts, with a
short "If you are a teammate" section for the differences (ask the lead instead of deciding; gates
per rule 3; end the turn when waiting on an answer; the context-guard rule; the shutdown-response
schema, now rule 7).

The teammate list in `claude/orchestrator.md` keeps only what is brief-specific: role and owned
files (with the shared-worktree staging rule), skills to use, questions and gates. It ends with
"Read `~/agent-board/claude/worker.md`; its common rules and teammate section apply to you." The
duplicated rules removed from `orchestrator.md`: the `tmux-ctl run` rule, the pkill rule, the
task-observer exemption, and the CI-check sentence. Worker behaviour is unchanged.

## 1.8 Ledger archive

`claude/skills/subagent-driven-development-extras/SKILL.md` adds a Finish step before the workspace
is deleted: copy `<workspace>/progress.md` to `docs/superpowers/ledgers/<plan-basename>/progress.md`,
commit it as `docs(ledger): …`, and check that the plan's `.tasks.json` sits beside the plan.

## 1.9 Context guard everywhere

`claude/hooks/context-size-guard.sh` is also registered on `Stop` and on `PostToolUse` with matcher
`SendMessage|Agent`. It reads the event name from its input. It fires once per 50K band at or above
the threshold: the last band warned is stored in
`~/.local/state/agent-board/context-guard/<session_id>.band`, and the hook stays silent until a higher
band. Output: `UserPromptSubmit` and `PostToolUse` get `systemMessage` plus `additionalContext`;
`Stop` gets `systemMessage` only. Teammates get the rule in `worker.md`: past the threshold, tell the
lead in your next message and carry on.

## 1.10 Spawn record

New `claude/hooks/spawn-record.sh`, registered async on `PostToolUse` with matcher `Agent`. It
appends one JSON line to `~/.local/state/agent-board/spawns.jsonl`:

`{ts, lead_session, name, subagent_type, model, tier, reason}`

- `model`: the call's model, or `"inherit"` when omitted.
- `tier`: the call's model mapped back through `docs/superpowers/model-routing.json` (haiku →
  mechanical, sonnet → standard, fable → frontier), else `null` (an Opus or inherited spawn has no tier).
- `reason`: the text after a `Reason:` line in the prompt, or `null`.

It fails open and never blocks a spawn. `orchestrator.md`'s "Models and effort" adds: a spawn that
leaves the tier's model carries a `Reason:` line; on a Fable limit error, re-dispatch on Opus with
`Reason: fable-limit`.

## 1.11 Answers up front

- `orchestrator.md`: every teammate brief carries a "Decided" block — each choice the lead can
  foresee, with its answer. Rules adds: send the brief before setting a task's `owner` (setting
  `owner` dispatches; observation 0087).
- `worker.md` teammate section: a teammate that needs an answer before a gated step sends the
  question and ends its turn; it does not continue on a default while the question is unread. Rule
  3's carve-outs stay.

## Testing

Each hook test lives under `claude/hooks/tests/`, runs the repo script the live path links to (not
a copy), and uses hook JSON captured from a real transcript in the audit window.

| Item | Test |
| --- | --- |
| 1.2 | scratch workspace: summary counts match; `review-started.txt` not `completed` is reported; `TC_ROLE=worker` gives the exemption |
| 1.3 | task dirs with and without the markers: short-circuit skips; with a marker the real plugin guard runs (its trace log gets a line) |
| 1.4 | the post-run classification on captured outputs (limit message, budget cap, clean) writes the right marker |
| 1.5 | close a scratch tmux session (`-f /dev/null`): lineage file survives; relay writes and the board reads the new path |
| 1.9 | band file: one warning per band; replay of session `48822fd2` gives more than 0 warnings on `PostToolUse`/`Stop` |
| 1.10 | one line per Agent call; `reason: null` when absent; a malformed input exits 0 |

Existing suites stay green: `board/tests`, `tools/tests`, `tools/tests/run-all.zsh`, and the three
skill suites listed in `CLAUDE.md`.

## Measurement

On the merged result, re-run `injection_costs.py` and `run_baseline.sh` and compare with the
2026-10-25 baseline: `skill_listing` median chars, `first_request_prompt_tokens` median, and the
`hook:SessionStart` size. One live session gives Stop `durationMs` per guard.

Dated follow-up, 2026-11-04 (not a plan task): every entry in `spawns.jsonl` has a non-null reason
where its model differs from the tier's; Stop medians over the week; observations per week roughly
hold; the review job records `completed` or a `limit-hit`/`budget-hit` marker.

## Rollback

Repo changes: git revert. User config: the `.bak-20261028` copies of `settings.json`, the recorded
old handoff link target, and the moved handoff docs (the `~/.claude/handoffs` symlink is replaced
by the directory again).
