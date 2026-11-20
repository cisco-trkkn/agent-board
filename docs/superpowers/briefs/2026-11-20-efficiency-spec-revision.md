# Brief: efficiency revision E1-E5 to the engine and improvement-loop specs

The user approved this on Discord (2026-11-20 15:04Z) as part A of the efficiency work. Source: `docs/superpowers/notes/2026-11-20-efficiency-learnings-for-pcee.md`, items 1-4 and 6. Part B is `docs/superpowers/specs/2026-11-20-efficiency-now-design.md`; read its §2, §4 and §5.

## Files (yours)

- `docs/superpowers/specs/2026-11-10-pcee-engine-design.md`
- `docs/superpowers/specs/2026-11-16-supervised-improvement-loop-design.md`

## Model to follow

This morning's revision R1-R5 of the loop spec (commit fb1fd2c, `git show fb1fd2c`). Follow its shape: a dated revision note near the top of each spec, listing the items, and each change made in place in the section it belongs to, marked `(E<n>, 2026-11-20)`.

## Changes

- **E1, loop spec, acceptance rule:** a proposal that shrinks what a worker reads (tool output, bounce text, context) is trialled and judged on tokens per task plus fix rounds and bounces per task, with failed tasks kept in the denominator. Reason: a cut that makes the agent re-read or re-run can raise the bill. PointFive measured 38.4% less tool output read and a 6.8% higher bill over about 3,000 runs. Point to ECC insight 8 in `docs/superpowers/notes/2026-11-20-ecc-insights-for-pcee.md` as the same rule.
- **E2, engine §3, green check and bounce** (about line 209: "the output"): the bounce text is the failing test names, their error lines and the runner's summary line, plus the path of the full log. A cap in lines comes from a constant in the strategy file. Add a `bounce_bytes` field to the bounce event's `detail`, so the cap can be measured.
- **E3, engine §1 events, job end:** write `context_tokens` (the job's final context, from the shared reader `board/ctxsize.py` that B builds) and the limits reading when one exists. Use null with a missing reason otherwise, the same rule as B §3.
- **E4, engine §3 job table:** add a "Pending (E4)" line. A per-kind `tools`/`mcp` column, allow-all by default, applies only if B's worker-context probe returns a go (MCP schemas ≥ 5% of a fresh worker's context). Name the probe note B §4 will write.
- **E5, loop spec variants:** add a "Pending (E5)" line. `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` becomes a trial variant for mechanical-tier implementers only if B's Code Mode hooks probe returns a go (our PreToolUse/PostToolUse gates fire under it).

## Do

1. Read both specs fully and `git show fb1fd2c`.
2. Make the edits. Don't change anything else, and keep each spec's existing wording style.
3. Check that each E item appears where it should: grep for `(E1`…`(E5` in both files, and give the counts.
4. Commit only the two spec paths, as `docs(spec): efficiency revision E1-E5 for the engine and improvement loop`, ending with the trailer `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit -- <two paths>`. This is the main checkout and the live install, but these are docs files only: commit nothing else, and run no other git command that changes state.
5. SendMessage team-lead with the commit and a one-line summary per E item, each with the section it landed in.

## Decided

- If a section the brief names doesn't exist under that number, put the change in the section that holds that content, and say where in your message.
- E4 and E5 are pending markers only. Don't write the full column or variant now.
