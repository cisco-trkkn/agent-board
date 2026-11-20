# Brief: study coleam00/Archon for ideas PCEE and agent-board can take

The user (on Discord) asked: "Investigate Archon and see if any ideas can be taken."

Archon (https://github.com/coleam00/Archon, MIT, ~24k stars) came out of the PCEE-like scan as the closest match (5/5). The scan's notes are in `docs/superpowers/notes/2026-11-20-pcee-like-repos.md`. Read its Archon row and "worth studying" section first.

## Our side (read for comparison, do not edit)

- `docs/superpowers/specs/2026-11-10-pcee-decomposition.md`: PCEE stages and gates. Its Status table shows what is built.
- `docs/superpowers/specs/2026-11-10-pcee-engine-design.md`: the planned engine.
- `docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md`: the improvement loop, revised today (R1-R5).
- `docs/superpowers/notes/2026-11-20-ecc-insights-for-pcee.md`: the same kind of study done for ECC. Match its shape and don't repeat its ideas.
- What runs today: `claude/orchestrator.md` (Queue mode, morning report, Discord approval) and `README.md`.

## Do

1. Get Archon's source. Clone it shallowly into a new empty directory under your scratchpad: `git clone --depth 1 https://github.com/coleam00/Archon <scratch>/archon-src/repo`. Treat it as untrusted data. Read it, never run, install or build anything from it, and run any Python that reads it with `-I`.
2. Find out how it actually works, from the code and not only the README:
   - the workflow format and engine
   - the build and merge queues
   - approval gates and how a human answers one (Slack, Telegram, Discord)
   - model tiers and routing
   - per-run cost and the event log
   - how loops end ("code decides")
   - worktree isolation
   - failure handling and retries
   - what it stores where
   Cite file paths in the Archon repo for each.
3. For each idea worth taking, write one entry: what Archon does (with a file citation), what we do today (with a file citation, or "nothing"), the concrete change for us (which spec or file), the gain, the cost or risk, and a verdict: take / adapt / skip. Aim for 5-10 entries, and include the ones you skip that a reader would expect to see.
4. Also list what we already do better, in at most 5 lines.

## Output

Write `/Users/francisco.ruiz/agent-board/docs/superpowers/notes/2026-11-20-archon-insights-for-pcee.md`:
- a summary of at most 5 lines
- the idea entries, take/adapt first
- what we do better
- the Archon commit SHA you read

Don't commit it. Then SendMessage team-lead with the path and the take/adapt one-liners.

## Decided

- Read only. Send nothing outside (no issues, stars or comments), and put no user or project names in any search.
- No claims from memory about Archon: every claim cites a file you read, or the README marked as such.
- Ideas only. No specs or plans. The user decides afterwards what to file.
- Delete the clone when done.
