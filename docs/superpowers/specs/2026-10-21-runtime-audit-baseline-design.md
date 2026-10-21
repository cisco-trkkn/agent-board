# Runtime audit and baseline — design

Sub-project 1 of the "Claude Code Runtime Optimization" brief (`~/Desktop/ff.rtf`).
The brief asks for eight deliverables across six subsystems. It is split into four
sub-projects, each with its own spec, plan and execution:

1. **Audit + baseline** (this spec): read-only. Current-state architecture, efficiency
   audit, measured baseline, draft roadmap.
2. Instrumentation: per-task outcome records, routing/observer/handoff telemetry.
3. Policy changes chosen from the audit's evidence: model-routing policy (brief D4),
   context and handoff design (brief D5), hook/observer/skill slimming.
4. Autonomy: queue, background scheduling, dashboard views — only what 1–3 justify.

Sub-projects 2–4 are not designed here; this audit's roadmap section is their input.

## Goal

Produce an evidence-based picture of how the current setup actually behaves and where
its avoidable overhead is, so later changes are chosen by measurement, not impression.
Primary metric from the brief: verified useful work per unit of subscription usage,
elapsed time and human attention, with quality as a constraint.

## Decisions (settled with the user, 2026-10-21)

| Decision | Choice |
| --- | --- |
| Scope | Sub-project 1 only |
| Data | Transcripts of `master-gcp-repo` and `agent-board` (+ its worktrees), last 30 days; full content may be quoted as evidence, secrets and credentials always redacted |
| Budget | Lean, script-first: deterministic scripts mine the transcripts; agents read code and script output |
| Approach | Script toolkit → three parallel read-only discovery areas → one synthesis owner |
| Report | A Claude Doc |

## Constraints

- No change to live behaviour. Nothing under `~/.claude`, `~/.local/bin` or the live
  `~/agent-board` checkout is edited; this repo is the live install, so all work runs in
  a worktree under `.claude/worktrees/` on branch `audit/runtime-baseline`.
- Read-only probes only (e.g. timing a hook with dummy input). Scratch tmux servers start
  with `-f /dev/null`.
- Nothing is pushed. Commits on the audit branch: `tools/audit/` and the area reports.
- Every claim is labelled **Verified** (code, logs, reproducible test), **Measured**
  (observed metric), **Hypothesis** or **Recommendation**. Estimated savings are never
  presented as measured.
- No secrets or credentials in any committed file or in the doc.

## Component 1 — metrics toolkit (`tools/audit/`)

Python 3 standard library only. Each script reads JSONL or JSON and writes JSON, and runs
on its own.

| Unit | Responsibility |
| --- | --- |
| `transcripts.py` | The only module that knows the transcript format. Iterates sessions of a project directory within a date window, follows subagent/sidechain files, yields normalised events: message usage (input, output, cache_read, cache_creation), model, tool_use (name + hashed args key), tool_result size, hook and system-reminder injections, timestamps. |
| `session_metrics.py` | Per session: totals by model, by agent, orchestrator vs teammates; peak context; turns; wall-clock; agents spawned and their lifetimes. |
| `waste_signals.py` | Deterministic duplication and stagnation signals: same file read N times, same command with same result, repeated identical test failures, tool-output share of context, teammate idle time between last useful output and shutdown. |
| `injection_costs.py` | Size and frequency of always-on text: CLAUDE.md files, SessionStart hook output, skill bodies as loaded, system-reminders. |
| `handoff_trace.py` | Handoff and compaction events, context size at the event, the next session's time and tokens to its first new edit, signs of redone work. |
| `run_baseline.sh` | Runs all of the above over the agreed scope into `audit-out/<date>/` (gitignored: it may hold transcript content). |

Output rules:

- Every metric carries `source: measured | derived`.
- A field the transcripts do not expose is `null` with a `reason`, never an estimate.
- Subscription quota is out of scope unless the board's existing usage code already
  reads it; then it is reported with that code as the source.

Testing (TDD):

- Fixture JSONL cut from real transcripts and redacted, including one session with
  subagents and one with a compaction.
- A smoke test runs the whole pipeline on one real session and checks that the token
  totals equal the sums of the raw `usage` fields, so the parser cannot drop events
  silently.

## Component 2 — discovery areas

Three read-only teammates in parallel, each owning one output file
`docs/superpowers/reports/runtime-audit/<area>.<agent-name>.md`; the lead promotes one
per area to `<area>.md`. They read code and the toolkit output, and open a raw
transcript only to check a session a metric points at.

| Area | Tier | Covers | Delivers |
| --- | --- | --- | --- |
| atlas | standard | board frontend and backend, project switching, tmux session lifecycle, `dev` / `tmux-ctl`, Claude launch, task queue and ideas, logs and telemetry | component diagram (mermaid); source of truth per state type (project, task, agent, terminal, usage); every place state lives only in tmux output or conversation history |
| sieve | standard | every hook (settings and plugins), always-on instructions (CLAUDE.md files, orchestrator prompt, using-superpowers injection), the `-extras` companion skills, task-observer | the brief's §5.4 table per mechanism (trigger, frequency, implementation, context cost, purpose, outcome, failure behaviour, overlap) filled from `injection_costs.json`; an overlap matrix (rule × enforcement places); observer value judged from its logged observations and the reviews that acted on them |
| relay | frontier | model-routing gates, effort agents, teammate spawn and shutdown, how the ~300K handoff trigger is measured, handoff skill and docs, worktrees and recovery | one representative real task traced intake → completion (§5.2); routing correctness; orchestrator share of usage; parallel-agent payoff; handoff failure modes |

Common findings format:

```
### F-<area>-<n>: <title>
Label: Verified | Measured | Hypothesis
Evidence: file:line / metric key + value / session id
Component · Root cause · Impact (measured, or "unmeasured — needs <instrument>")
Confidence: high | med | low · Candidate change · How to validate
```

A finding without evidence is a Hypothesis, never Verified.

## Component 3 — synthesis and report

**lens** (frontier) is the single owner of the doc. It works from the three area files
and `audit-out/`, does not redo discovery, and resolves a conflict between findings with
a targeted probe or shows both sides.

Claude Doc "Claude Code Runtime Audit — Baseline 2026-10":

1. Summary — five lines and the 3–5 next actions (brief D8).
2. Current-state architecture (D1) — layered diagrams, component table, state sources
   of truth, verified vs assumed.
3. Baseline measurements (D6, part) — what is measured now (usage by model and agent,
   orchestrator share, injection costs, waste signals, handoff statistics), charts from
   the JSON rows; what is not observable, and the instrument each gap needs.
4. Efficiency audit (D2) — findings ranked by expected benefit.
5. Hypotheses H1–H6 — confirmed, refuted or unmeasured, with evidence.
6. Expanded ideas (D3) — shortlist with problem, mechanism, complexity, downside,
   success metric; ideas not pursued, one line each.
7. Roadmap draft (D7) — phases 1–4 with benefit, effort, risk, dependencies,
   validation, rollback; the input to sub-projects 2–4.
8. Measurement plan (D6) — first instrumentation to add; a benchmark suite of 8–10 real
   tasks drawn from these transcripts.

D4 (routing policy) and D5 (context and handoff design) are deferred to sub-project 3;
the doc records only what the evidence implies for each.

## Verification

- Toolkit: tests pass; totals reconcile with the raw usage sums.
- **probe** (standard), independent of the authors, samples at least 10 findings,
  including every Verified one in the top 5, and re-checks each cited file:line, metric
  or session id. A failed check relabels or drops the finding before the user sees the
  doc. Output: `docs/superpowers/reports/runtime-audit/probe-review.md`.
- A redaction grep (keys, tokens, private-key headers, passwords) over the area files
  and the doc text returns nothing before publishing.

## Out of scope

Any change to routing, hooks, skills, the observer, handoff or the board; new
instrumentation in the live setup; subscription-limit workarounds.
