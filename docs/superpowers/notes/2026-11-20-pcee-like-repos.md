# Public GitHub repos with a PCEE-like engine, ranked by stars

Date: 2026-11-20 · Author: scout (research teammate) · Not committed.

Star counts, last-push dates and licences were read on **2026-11-20** with `gh api repos/<owner>/<repo>` (the real value at read time). "Last push" is the repo's `pushed_at`, which is the closest the API gives to the last commit date. Forks and repos under 20 stars were skipped. Nothing was posted, starred or filed on any repo.

How I rated: I found candidates with `gh search repos` (about 25 queries on orchestrator, ralph loop, software factory, spec-driven, overnight and similar terms) plus known names I checked directly. I read the README of the ones marked "README" in the evidence column and scored against the six PCEE traits: queue of several plans, unattended runs, per-task review and fix loop, model tiering, metrics or reporting, remote human approval. Ratings are my judgement from README text, not from running the tools. A "lacks" entry means I did not find it in the README, not that it is proven absent.

| Rank | Repo | Stars | Last push | Licence | Closeness (1-5) | Has / lacks | Evidence |
|---|---|---|---|---|---|---|---|
| 1 | https://github.com/affaan-m/ECC | 307,595 | 2026-11-20 | MIT | 2 | Has hooks, skills, model-route heuristic, worktree lifecycle. Lacks a plan queue, unattended scheduler, run metrics per spec. Already studied in `2026-11-20-ecc-insights-for-pcee.md`. | existing note |
| 2 | https://github.com/ruvnet/ruflo | 82,144 | 2026-11-20 | MIT | 2 | Has multi-agent swarms, some model routing and cost mentions. Lacks a clear spec queue with a review/fix loop; very broad harness. | README keyword scan only |
| 3 | https://github.com/BloopAI/vibe-kanban | 28,754 | 2026-11-15 | Apache-2.0 | 2 | Has a kanban board that runs several coding agents in worktrees, with diff review. Lacks unattended overnight runs, model tiering, metrics. | README |
| 4 | https://github.com/openai/symphony | 28,108 | 2026-09-15 | Apache-2.0 | 4 | Has a Linear-board watcher that spawns an isolated agent per task, with CI status, PR review feedback and safe landing as proof of work. Lacks model tiering and metrics in the README (spec in `SPEC.md`, not read); built around Codex. | README (short) |
| 5 | https://github.com/coleam00/Archon | 23,964 | 2026-11-20 | MIT | 5 | Has YAML workflows (plan, loop until tests pass, approve, PR), build and merge queues, schedules and triggers, approval gates, per-run cost and event log, model tiers and aliases, Slack/Telegram/Discord adapters, runs Claude Code or Codex. Lacks a morning report that I found. | README |
| 6 | https://github.com/snarktank/ralph | 22,307 | 2026-02-02 | MIT | 2 | Has the loop that runs until every PRD item is done. Lacks a plan queue, a separate review step, tiers, metrics, remote approval. | README |
| 7 | https://github.com/gastownhall/gastown | 18,851 | 2026-11-14 | MIT | 3 | Has many agents with persistent work state, a bisecting merge queue with verification gates, watchdogs, a live feed. Lacks model tiering and a spec-to-plan pipeline in the README; far more complex than PCEE. | README |
| 8 | https://github.com/AndyMik90/Aperant | 14,622 | 2026-06-14 | AGPL-3.0 | 3 | Has a kanban of autonomous multi-session builds that plan, build and validate. Lacks recent commits (2.x in maintenance, 3.0 built elsewhere), tiers, remote approval; AGPL. | README |
| 9 | https://github.com/frankbria/ralph-claude-code | 9,738 | 2026-11-14 | MIT | 2 | Has an autonomous Claude Code loop with exit detection, rate limits, cost and metrics mentions. Lacks a queue of several specs, a review/fix loop, remote approval. | README |
| 10 | https://github.com/mikeyobrien/ralph-orchestrator | 3,205 | 2026-11-13 | MIT | 3 | Has role "hats", backpressure gates (tests, lint), Telegram where agents ask and block until answered. Lacks a plan queue, tiering, per-run reports. | README |
| 11 | https://github.com/umputun/ralphex | 1,519 | 2026-11-19 | MIT | 4 | Has plan files run task by task, each in a fresh Claude Code or codex session, a multi-phase review (5 agents, then codex, then 2 agents) with stalemate detection, worktrees to run several plans in parallel, completed plans moved aside, Telegram/Email/Slack/webhook alerts. Lacks model tiering by task, per-run metrics, and phone approval (alerts only). | README |
| 12 | https://github.com/AnandChowdhary/continuous-claude | 1,389 | 2026-10-29 | MIT | 3 | Has Claude in a loop that opens a PR, waits for CI and review, merges or discards, with cost and budget limits and worktrees. Lacks a multi-spec queue, tiering, remote approval. | README |
| 13 | https://github.com/coleam00/ai-software-factory | 549 | 2026-11-13 | MIT | 4 | Has a PRD split into linked issues, parallelism worked out, an agent that builds each issue and two reviewers that did not write it, scheduling, approvals, model tiers in config, runs on Archon. Lacks its own metrics or morning report that I found; staging test is manual. | README |
| 14 | https://github.com/finna/Finn-loop | 325 | 2026-07-23 | MIT | 3 | Has three Claude Code skills (spec, build, review) run under `/loop`, an `agent-ready` label as the approval, humans merge, Slack mentions. Lacks tiering, metrics, overnight orchestration beyond `/loop`. | README |
| 15 | https://github.com/looptroop-ai/LoopTroop | 179 | 2026-11-18 | MIT | 3 | Has tickets that go from interview to PRD to small beads, Ralph loops that test and fix, worktrees, approvals, final verification. Lacks a multi-spec overnight queue and a report in the README; uses OpenCode. | README |
| 16 | https://github.com/nearform/lastlight | 48 | 2026-11-16 | MIT | 3 | Has an Architect, Executor, Reviewer cycle, cron and webhooks, Slack, approvals, some cost and metrics. Lacks Claude Code as the executor (own harness) and a plan queue. | README |

## The 3 most worth studying

1. **Archon (coleam00/Archon, closeness 5).** It is the nearest to PCEE: queues that take an issue through plan, implement, review lenses, fix and CI, an attention queue where a paused run asks one question with a recommendation, and a stored cost and event log per run. PCEE could take the "one attention item" shape for phone approvals (what, why it matters, recommendation, choices) and the rule that code, not the model, decides when a loop is done (`until_bash`).

2. **ralphex (umputun/ralphex, closeness 4).** It does what a single PCEE spec job does: a plan file, one fresh session per task, and a staged review with different reviewers. PCEE could take the stalemate rule (`--review-patience`: stop after N rounds with no commits) for the fix loop, and the way it runs several plans in parallel in worktrees and moves finished plans to `completed/`.

3. **ai-software-factory (coleam00/ai-software-factory, closeness 4).** It shows a whole release flow: PRD to linked issues, parallel lanes worked out up front, and two reviewers that did not write the code deciding the merge, with the human only at "what to build" and "is it right". PCEE could take the rule that reviewers must be different from the author before a merge, and the habit of turning anything wrong found afterwards into a new queued item. (Symphony, rank 4, is the runner-up; its `SPEC.md` is worth reading next, but I did not read it.)

## Limits

- Star counts are from 2026-11-20 and move daily.
- I did not clone or run any repo. Closeness is from READMEs; ruflo and ECC are scored from a keyword scan or an earlier note, so they are the least certain.
- The search found many `ralph loop` repos; I kept only the highest-starred and the ones with review, queue or approval features. Others (for example `umputun/revmux`, `gastownhall/gascity`, `smtg-ai/claude-squad` at 8,839 stars) were seen but not scored, or judged under 2.
- Spec tools with large star counts (`github/spec-kit` 150,782, `Fission-AI/OpenSpec` 75,329, BMAD-METHOD 55,575) produce specs and plans but do not run them unattended, so they score 1 and are left out.
