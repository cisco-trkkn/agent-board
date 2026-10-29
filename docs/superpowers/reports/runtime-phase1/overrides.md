# skillOverrides audit (Task 10, spec 1.1 plugin half)

Date: 2026-10-28. Window: 30 days to today (local midnight 29 days back). Scope: transcripts under `~/.claude/projects` whose cwd is `/Users/francisco.ruiz/master-gcp-repo` or `/Users/francisco.ruiz/agent-board` (and their `.claude/worktrees/`), the scope `tools/audit/run_baseline.sh` uses.

## Sources

- **Calls**: `session_metrics.py` does not emit per-skill counts (no `Skill` handling; `transcripts.py` events carry no `input.skill`). Counts were computed by a short script that reads the transcripts with `tools/audit/transcripts.py` helpers (`candidate_files`, `window_start`, `in_repo`, `_ts`): `tool_use` blocks named `Skill`, grouped by `input.skill`, main thread and sidechains, de-duplicated by `tool_use` id. Total: 738 calls over 38 distinct invoked names.
- **Listing**: `attachment` of type `skill_listing`, `isInitial`, from lead transcript `~/.claude/projects/-Users-francisco-ruiz/b396c327-8a97-4bd1-aca4-1ab1c220fc2f.jsonl` (started today, no agentName, 59 skills; later incremental listings of that kind add none to this one). **Listed skills: 59. Table rows: 59.** Description chars = length of the listing text after `name: `.
- **Current overrides**: `~/.claude/settings.json` `skillOverrides` (read-only): 17 entries, of which 1 are listed (the rest are `off` and absent from the listing).
- **Name aliases**: the bare invoked name `task-observer` (16 calls) is counted with `task-observer:task-observer` (31). `tmux-orchestrator` (5) and `agent-board:tmux-orchestrator` (2) are listed and counted separately (both repo-owned).
- **Invoked but not listed** (not rows): `abspike:abspike-probe` (1), `artifact-design` (2).

## Rule

`name-only` when calls = 0 and chars > 300; `off` only with a stated out-of-scope reason (none proposed: no unlisted-by-user-scope skill qualifies, and `interior-design-expert` stays `name-only` because the user has interiors projects); existing overrides kept; repo-owned skills are marked "shortened in Task 9".

## Table

| skill | owner | Skill calls (window) | description chars | current override | proposed override | reason |
|---|---|---|---|---|---|---|
| **rule** | spec 1.1 | n/a | > 300 | existing kept | name-only if calls = 0 and chars > 300 | off only with an out-of-scope reason; repo-owned: shortened in Task 9 |
| docs-architecture | agent-board (repo) | 2 | 359 | (none) | shortened in Task 9 | repo-owned; description 359 chars |
| docs-compose | agent-board (repo) | 2 | 320 | (none) | shortened in Task 9 | repo-owned; description 320 chars |
| docs-explainer | agent-board (repo) | 0 | 402 | (none) | shortened in Task 9 | repo-owned; description 402 chars |
| docs-report | agent-board (repo) | 0 | 357 | (none) | shortened in Task 9 | repo-owned; description 357 chars |
| docs-runbook | agent-board (repo) | 0 | 351 | (none) | shortened in Task 9 | repo-owned; description 351 chars |
| fix-merge-conflicts | agent-board (repo) | 3 | 101 | (none) | none | repo-owned; description 101 chars, already ≤300 |
| frontend-design | user skill (.agents/skills) | 0 | 204 | (none) | none | 0 calls, 204 chars ≤ 300 |
| gitlab-ci-loop | agent-board (repo) | 22 | 466 | (none) | shortened in Task 9 | repo-owned; description 466 chars |
| interior-design-expert | user skill (.agents/skills) | 0 | 627 | (none) | name-only | 0 calls in window, 627 chars > 300 |
| requesting-code-review-extras | agent-board (repo) | 32 | 723 | (none) | shortened in Task 9 | repo-owned; description 723 chars |
| subagent-driven-development-extras | agent-board (repo) | 2 | 512 | (none) | shortened in Task 9 | repo-owned; description 512 chars |
| terraform-skill | user skill (~/.claude/skills) | 3 | 220 | (none) | none | 3 calls |
| test-driven-development-extras | agent-board (repo) | 92 | 816 | (none) | shortened in Task 9 | repo-owned; description 816 chars |
| tmux-orchestrator | agent-board (repo) | 5 | 434 | (none) | shortened in Task 9 | repo-owned; description 434 chars |
| writing-for-agents | agent-board (repo) | 8 | 103 | (none) | none | repo-owned; description 103 chars, already ≤300 |
| writing-plans-extras | agent-board (repo) | 21 | 1053 | (none) | shortened in Task 9 | repo-owned; description 1053 chars |
| superpowers-extended-cc:gate-check | superpowers-extended-cc | 0 | 227 | (none) | none | 0 calls, 227 chars ≤ 300 |
| superpowers-extended-cc:onboard | superpowers-extended-cc | 0 | 207 | (none) | none | 0 calls, 207 chars ≤ 300 |
| superpowers-extended-cc:specify-gate | superpowers-extended-cc | 0 | 241 | (none) | none | 0 calls, 241 chars ≤ 300 |
| claude-md-management:revise-claude-md | claude-md-management | 0 | 49 | (none) | none | 0 calls, 49 chars ≤ 300 |
| agent-board:tmux-orchestrator | agent-board (repo) | 2 | 434 | (none) | shortened in Task 9 | repo-owned; description 434 chars |
| superpowers-extended-cc:brainstorming | superpowers-extended-cc | 30 | 198 | (none) | none | 30 calls |
| superpowers-extended-cc:checking-gates | superpowers-extended-cc | 5 | 330 | (none) | none | 5 calls |
| superpowers-extended-cc:dispatching-parallel-agents | superpowers-extended-cc | 0 | 106 | (none) | none | 0 calls, 106 chars ≤ 300 |
| superpowers-extended-cc:executing-plans | superpowers-extended-cc | 0 | 104 | (none) | none | 0 calls, 104 chars ≤ 300 |
| superpowers-extended-cc:finishing-a-development-branch | superpowers-extended-cc | 18 | 101 | (none) | none | 18 calls |
| superpowers-extended-cc:receiving-code-review | superpowers-extended-cc | 7 | 234 | (none) | none | 7 calls |
| superpowers-extended-cc:requesting-code-review | superpowers-extended-cc | 35 | 107 | (none) | none | 35 calls |
| superpowers-extended-cc:specifying-gates | superpowers-extended-cc | 1 | 282 | (none) | none | 1 calls |
| superpowers-extended-cc:subagent-driven-development | superpowers-extended-cc | 33 | 85 | (none) | none | 33 calls |
| superpowers-extended-cc:systematic-debugging | superpowers-extended-cc | 42 | 91 | (none) | none | 42 calls |
| superpowers-extended-cc:test-driven-development | superpowers-extended-cc | 111 | 79 | (none) | none | 111 calls |
| superpowers-extended-cc:using-git-worktrees | superpowers-extended-cc | 3 | 196 | (none) | none | 3 calls |
| superpowers-extended-cc:using-superpowers | superpowers-extended-cc | 0 | 159 | (none) | none | 0 calls, 159 chars ≤ 300 |
| superpowers-extended-cc:verification-before-completion | superpowers-extended-cc | 123 | 225 | (none) | none | 123 calls |
| superpowers-extended-cc:writing-plans | superpowers-extended-cc | 27 | 84 | (none) | none | 27 calls |
| superpowers-extended-cc:writing-skills | superpowers-extended-cc | 3 | 97 | (none) | none | 3 calls |
| claude-md-management:claude-md-improver | claude-md-management | 2 | 338 | (none) | none | 2 calls |
| task-observer:task-observer | task-observer | 47 | 1017 | (none) | none | 47 calls |
| dataviz | Claude Code (built-in) | 1 | 1436 | (none) | none | 1 calls |
| update-config | Claude Code (built-in) | 1 | 690 | (none) | none | 1 calls |
| keybindings-help | Claude Code (built-in) | 0 | 228 | (none) | none | 0 calls, 228 chars ≤ 300 |
| code-review | Claude Code (built-in) | 0 | 1191 | (none) | name-only | 0 calls in window, 1191 chars > 300 |
| simplify | Claude Code (built-in) | 0 | 176 | (none) | none | 0 calls, 176 chars ≤ 300 |
| fewer-permission-prompts | Claude Code (built-in) | 1 | 163 | (none) | none | 1 calls |
| loop | Claude Code (built-in) | 0 | 336 | (none) | name-only | 0 calls in window, 336 chars > 300 |
| schedule | Claude Code (built-in) | 0 | 369 | (none) | name-only | 0 calls in window, 369 chars > 300 |
| claude-api | Claude Code (built-in) | 6 | 1068 | (none) | none | 6 calls |
| claude-in-chrome | Claude Code (built-in) | 8 | 527 | (none) | none | 8 calls |
| run | Claude Code (built-in) | 0 | 361 | (none) | name-only | 0 calls in window, 361 chars > 300 |
| init | Claude Code (built-in) | 0 | 59 | (none) | none | 0 calls, 59 chars ≤ 300 |
| security-review | Claude Code (built-in) | 0 | 71 | (none) | none | 0 calls, 71 chars ≤ 300 |
| anthropic-skills:chrome-browser | anthropic-skills | 5 | 751 | (none) | none | 5 calls |
| anthropic-skills:deep-research | anthropic-skills | 1 | 570 | (none) | none | 1 calls |
| anthropic-skills:docs | anthropic-skills | 31 | 1004 | (none) | none | 31 calls |
| anthropic-skills:find-skills | anthropic-skills | 0 | 303 | (none) | name-only | 0 calls in window, 303 chars > 300 |
| anthropic-skills:pdf | anthropic-skills | 0 | 437 | (none) | name-only | 0 calls in window, 437 chars > 300 |
| anthropic-skills:pptx | anthropic-skills | 0 | 0 | name-only | name-only | existing override kept |
| anthropic-skills:skill-creator | anthropic-skills | 0 | 319 | (none) | name-only | 0 calls in window, 319 chars > 300 |

## Proposed additions

8 skills: `interior-design-expert`, `code-review`, `loop`, `schedule`, `run`, `anthropic-skills:find-skills`, `anthropic-skills:pdf`, `anthropic-skills:skill-creator`.
See `overrides.json`.

Caveat: counts cover only the two audited repos; a skill used only in other projects (e.g. `interior-design-expert` in the interiors projects) shows 0. `name-only` keeps the skill invocable by name; only its description leaves the listing.
