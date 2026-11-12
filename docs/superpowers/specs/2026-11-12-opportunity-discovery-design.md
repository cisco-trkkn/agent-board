# Opportunity discovery: a nightly ranked report of work worth doing

Date: 2026-11-12 · Decided with the user over Discord, 2026-11-12 (near-term item 3 of the "intelligence layer"
review: the system starts finding valuable work itself, the user decides)
Needs merged: `2026-11-11-discord-bridge-visibility-design.md` (outbox, tiers) and
`2026-11-11-discord-controls-design.md` (buttons, audit). Shares the signal of repeated rulings with
`2026-11-12-memory-consolidation-design.md`; the two do not duplicate filing (see §3).

## Problem

Work is found only when the user or a lead notices it. Signals that point at valuable work already exist on disk and
are never looked at together: flaky and slow tests in the run records, failed runs, the same ruling or deferred
review minor across specs, new TODOs, dependency alerts, ideas nobody picked up.

## Decisions (user, 2026-11-12)

- **Report only.** The job ranks and explains; the user taps "File as idea" or "Dismiss". It never files, drafts specs
  or starts work by itself.
- Dismissed items do not come back unless their evidence grows.

## Design

### 1. Signals (code only), `tmux-ctl discover collect <project> [--json]`

For a project's repo and state, each signal is a list of candidates `{signal, key, title, evidence: [...], first_seen,
count}` with a stable `key` (used for dedupe and dismissals):

| Signal | Source | Candidate when |
| --- | --- | --- |
| `flaky_test` | `tmux-ctl` run records of the last 30 days | the same test id both passed and failed on the same HEAD, or ≥ 2 pass/fail flips |
| `slow_test` | the suite runner's per-file timings (`all.zsh` records) | a file in the slowest 5 that grew ≥ 25% over 30 days |
| `failed_run` | run records | a non-zero exit on `main` not followed by a green run of the same command within 24 h |
| `repeated_ruling` | `docs/superpowers/ledgers/*/progress.md` `Ruling:` lines | similar rulings (same first 6 normalised words, or same cited file and rule) in ≥ 3 specs |
| `deferred_minor` | ledgers' deferred/parked review findings | a finding parked in one spec whose cited file was touched again later without a fix line |
| `todo` | `git log -p --since=30.days` additions | added `TODO`/`FIXME`/`XXX` lines still present at HEAD |
| `dependency` | `gh api` Dependabot alerts if the remote is GitHub and `gh` is authed; `npm audit --json` / `pip-audit -f json` where a lockfile and the tool exist | an open alert of severity ≥ moderate |
| `stale_idea` | the project's ideas file | `- [ ]` older than 30 days |

A missing source is skipped with a `sources_skipped` note; no signal fails the run.

### 2. Ranking (model), `tmux-ctl discover rank <project>`

- `claude -p --model sonnet --effort medium`, prompt `claude/discover.md`, input only the collected JSON (Read on that
  file), output `rank.json`: the top 5 `{key, title, why, expected_value: high|medium|low, effort: S|M|L, risk,
  evidence_refs: [indexes into the candidate's evidence]}`.
- The script drops an item whose `key` is not a collected candidate or whose `evidence_refs` are out of range.
- The prompt asks for value to the user's work (time saved, failures avoided, cost), not code tidiness for its own
  sake, and forbids items that change the orchestrator rules or its own prompt.

### 3. The nightly report

- launchd `com.user.agent-board-discover`, 07:00 local, `tmux-ctl discover nightly [--dry-run]` for every project
  with a repo; skipped when weekly usage ≥ 85% (same check as the memory job).
- State `${TC_STATE}/discover/<project>.json`: `{reported: {key: {first_reported, last_evidence_count}},
  dismissed: {key: {at, evidence_count}}, filed: {key: {at, idea_line}}}`.
- An item is shown when its key is not filed, and either not dismissed or its evidence count grew ≥ 50% since the
  dismissal. Items already shown on an earlier night and unchanged are not reposted (they stay listed in the
  report's footer as `still open: <n>`).
- `repeated_ruling` candidates that the memory job already turned into a proposal (its `report.json`, same key) are
  marked `also proposed by the memory run` instead of being reposted as new.
- One outbox `post` to the project's home channel, tier `progress` (no ping): a numbered list (title, why, value,
  effort, risk, evidence summary with deep links where they exist), and per item two buttons:
  `File as idea` (`ab:discover:file:<project>:<key>`: `tmux-ctl idea "<title>: <why> (evidence: …)"`, recorded in
  `filed`, audited) and `Dismiss` (`ab:discover:dismiss:<project>:<key>`, recorded with the current evidence count,
  audited). The post is edited to show each decision.
- Nothing new: no post.
- Each nightly run is recorded with `tmux-ctl metrics` as kind `discover`.
- `TC_DISCOVER=0` or `discover.off` turns the schedule off.

## Error handling

- Model run fails or times out (10 min): no post that night; the log records why; three failed nights in a row post a
  `critical` line.
- `gh` unauthenticated or rate-limited: the dependency signal is skipped and listed in `sources_skipped`.

## Testing

- Each signal on fixtures (run records with flips, timings, ledgers with similar rulings, a git repo with TODO
  additions, fake `gh`/`npm` outputs, an ideas file), with trigger and non-trigger cases and stable keys.
- Rank check: unknown key dropped, bad evidence index dropped.
- Dismissal and regrowth threshold; no repost of unchanged items; memory-job overlap marking.
- Post shape and buttons; File as idea files once; Dismiss records; edits after decisions; audit lines.
- The model step is a fake `claude` in tests; one real `discover nightly --dry-run` on this repo is the user-gate
  check.

## Out of scope

- Drafting specs or starting work from an item (the user starts a brainstorm).
- Cross-project ranking (each project gets its own report).
