# Brief: public GitHub repos with a PCEE-like engine, ranked by stars

The user (on Discord) asked: "Can you find other public github repos with a pcee engine. Sort your ratings by stars."

"PCEE" is this project's own name (multi-plan execution engine), so no repo will use the word. Find repos that build the same thing.

## What PCEE is

Read only these, for the concept (do not edit them):
- `docs/superpowers/specs/2026-11-10-pcee-decomposition.md` (overview, stages, gates)
- `docs/superpowers/specs/2026-11-10-pcee-engine-design.md` (the engine itself), skim
- `docs/superpowers/notes/2026-11-20-ecc-insights-for-pcee.md` (one comparable repo already studied: Everything Claude Code)

In short: an orchestrator that runs a queue of specs/plans unattended, overnight, with coding agents (Claude Code or similar). Each spec goes through plan → per-task implement → review → fix loop → merge or branch, with tiered model routing, metrics per run, a morning report, and a human approving from a phone.

## Do

1. Search GitHub (web search, GitHub search pages, `gh search repos` if `gh` works without prompts) for public repos that run multiple plans/specs/tasks with coding agents unattended: Claude Code orchestrators, agent-team / multi-agent coding queues, "overnight" or "autonomous" coding pipelines, spec-driven agent runners, plan-execute-review loops. Include the obvious known ones if they fit.
2. For each candidate, get the current star count from the repo page or `gh api repos/<owner>/<repo> --jq .stargazers_count` (the real number, not a guess), the last commit date, and the licence.
3. Rate how close each is to PCEE, 1-5, against: queue of several plans, unattended runs, per-task review and fix loop, model tiering, metrics/reporting, remote human approval. One line saying what it has and lacks.
4. Keep 10-20 repos that score 2 or more. Sort by stars, descending.

## Output

Write `/Users/francisco.ruiz/agent-board/docs/superpowers/notes/2026-11-20-pcee-like-repos.md`: a table (rank, repo URL, stars, last commit, licence, closeness 1-5, one-line has/lacks), then the 3 repos most worth studying with two sentences each on what PCEE could take from them. State the date the star counts were read. Do not commit. Then SendMessage team-lead with the path and the top 5 rows.

## Decided

- Public repos only; skip forks and repos with fewer than 20 stars unless closeness is 5.
- No claims from memory: every star count comes from a fetch this session.
- Send nothing outside: no posts, issues, stars or comments on any repo. Do not put the user's name, email or this project's name in any search query.
