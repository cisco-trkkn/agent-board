# pi-observational-memory: what it is and what pcee can take

Read 2026-11-24 from a shallow clone (files only, nothing run). Paths with no prefix are in the outside repo; `docs/how-it-works.md` is cited as HIW.

## What it is

A Pi extension that keeps a long session coherent by writing memory while the session runs, so compaction is a cheap fold of notes already made (README "The second problem"; HIW:5).

**Storage.** An append-only ledger inside the session itself, written with `pi.appendEntry(customType, data)` (`src/hooks/consolidation-trigger.ts:63-64`). Three entry types: `om.observations.recorded`, `om.reflections.recorded`, `om.observations.dropped` (HIW:83-143). Memory state is the fold of those entries on the current branch (HIW:5). Drops are tombstones; history stays (HIW:143).

**Data flow.**
- **Observer** runs on `turn_end` in the background. It runs when raw source tokens since its last watermark reach `observeAfterTokens` (HIW:161-177). It takes the oldest chunk, about 60k tokens, and a separate model call writes timestamped observations rated low to critical. Each carries `sourceEntryIds`, and invalid ids are rejected in code (HIW:174, 177; `src/agents/observer/prompts.ts:1-27`). The prompt says the records are the assistant's only memory once the raw text is gone, and keeps user assertions verbatim (prompts.ts:3, 40-50).
- **Reflector** also runs on `turn_end`, only when the observer is not due (HIW:60, 181-186). It crystallizes durable facts, each citing observation ids (HIW:131, 190-191).
- **Dropper** runs only after a same-run reflection, and only when the active pool exceeds `observationsPoolTargetTokens` (HIW:192-196). It drops observations the reflections cover.
- **Compaction trigger** runs on `agent_settled`. It calls `ctx.compact()` when idle and over `compactAfterTokens` (HIW:198-215; `src/hooks/compaction-trigger.ts:29`). It never waits for the workers.
- **Compaction hook** (`session_before_compact`, `src/hooks/compaction-hook.ts:292`) makes no model call. It folds the ledger and renders the summary from a fixed template (HIW:217-239, 255-283). An empty projection falls back to Pi's own summarizer.
- **recall tool** (`src/tools/recall-observation.ts:482`) takes an observation id and returns the exact source entries, even for dropped observations (HIW:285-296).
- **Progress clocks** are the `coversUpToId` watermark on every entry (HIW:72-81). Raw tokens after each worker's last watermark are what trigger it.

## What depends on the Pi harness

Hooks and APIs used (`src/index.ts:1,10`; consolidation-trigger.ts:303-323; compaction-hook.ts:292):
- `turn_end`, `agent_start` and `agent_settled` events.
- `session_before_compact`, which lets the extension return the summary itself, plus `ctx.compact()` to start a compaction.
- `pi.appendEntry`, a typed custom entry stored in the session tree.
- `registerTool` and `registerCommand`.
- The model registry and auth (`AGENTS.md` "Model auth"), to run the worker models.

The ledger works because Pi's session is a tree of entries that extensions can add to and read by branch. The harness exposes that tree, a compaction override and an idle event.

**Claude Code equivalents** (from my knowledge of Claude Code, not from these repos; check before building):

| Pi | Claude Code |
|---|---|
| `turn_end` / `agent_settled` | `Stop` hook, `PostToolUse`, `SubagentStop` |
| `session_before_compact` returns a summary | `PreCompact` runs before compaction and can add instructions. It cannot replace the summary, so I know of no equivalent. |
| `appendEntry` ledger in the session | None. A sidecar file is needed, keyed by `session_id`. |
| Read source entries | `transcript_path` in hook input gives the session JSONL on disk |
| Inject memory into context | `SessionStart` hook `additionalContext`; this repo already does it with `context-inject` (`claude/orchestrator.md:121`). `--append-system-prompt` at launch also works. |
| Worker model calls | Agent SDK `query()` or `claude -p` from a hook or engine process |
| `recall` tool | an MCP tool, or a skill that reads the sidecar and transcript |

## Learnings for pcee

pcee's durability is mostly by design: state in SQLite and a disposable worker per job (engine spec "Decisions", lines 102-130; section 10, lines 417+). Workers are short, so most are never compacted. The learnings below are for the long-lived pieces: the lead, the architect, and `awaiting_you` resumes.

1. **Typed ledger with source ids (provenance).** Facts carry the ids of the evidence they came from, and a `recall` call returns the evidence. Where it would land: `engine/lib/engine/ledger.js` already renders the progress ledger from events, and shared context entries carry `(files: …)`. Add event ids to context entries and a `tmux-ctl context recall <id>`. Cost: low to medium. Covered: partly; file paths and dates give a weaker form of provenance.
2. **Watermark-driven background consolidation.** The observer fires on raw tokens since the last watermark, off the critical path. Where: an `engine` tick step (spec section 10 loop) or the nightly condense of the context file (`orchestrator.md:119-126`, over 8 KB). It would watch the lead's transcript and propose `Context learned` entries without waiting for a teammate report. Cost: medium (one model call per chunk). Covered: the lead curates by hand at each deliverable, so entries depend on lead discipline.
3. **Compaction does no model call.** Pi renders the summary from the ledger, deterministically. The same idea fits `agent-board:handoff`: write the handoff doc from the state the engine already holds (Queue state, task metadata, ledger) and not from the lead's memory. Where: handoff skill step 2 plus `ledger.js`. Cost: low. Covered: in part; the handoff already pulls from tasks and checkpoints.
4. **Never wait for the workers.** Compaction and handoff must not block on background consolidation, and they fold whatever exists. pcee's tick drains the inbox without waiting on jobs, which is the same shape (section 10 loop). Cost: none. Covered.
5. **Observation rules worth copying into brief or reflection prompts.** Keep user assertions verbatim, mark questions as questions, quote unusual terms, and prefer precise verbs (prompts.ts:40-50). Cost: low, text only. Covered: none. Target `worker.md` or the architect prompt.
6. **Tombstones, not deletes.** Dropped observations stay recallable (HIW:143, 292). The context file's archive (`<project>.archive.md`) already does this at coarse grain. Covered.
7. **Chunk caps and backoff for empty runs.** A fixed chunk size avoids stalls and an empty result backs off (HIW:177). Relevant if learning 2 is built.

## Is this only possible in Pi?

No. The mechanism is not Pi-specific; only this implementation is.

Two parts transfer to Claude Code. First, a background process can read the session's transcript on disk and write structured notes. Second, `SessionStart` can inject a rendered summary. The structure is a watermark, a typed note with source ids, and a tombstone.

What Claude Code lacks is Pi's tight integration. There is no `appendEntry` into the session tree and no hook that swaps in the compaction summary. In Claude Code, memory would sit in a sidecar, enter context only at `SessionStart` and `PreCompact` (a PreCompact hook cannot replace the summary), and need its own recall tool. After a compaction, Claude's own summary still wins, with the memory injected beside it. That is weaker than Pi's single visible summary, but it works.

For pcee the practical route is the engine process: it already reads agent-status files and reports, so it could read transcripts and make the observer call itself. The planned SDK backend (spec lines 37-47) gives it typed messages and session ids, a cleaner source than panes.

## Sources

Outside repo (`/tmp/claude-503/pimem/repo`): `README.md` (1-60), `docs/how-it-works.md` (all), `src/agents/observer/prompts.ts` (1-50), `src/index.ts`, `src/hooks/consolidation-trigger.ts` (grep of lines 63, 303-323, 570, 632, 730), `src/hooks/compaction-hook.ts:292`, `src/hooks/compaction-trigger.ts:29`, `src/tools/recall-observation.ts:482`, `AGENTS.md` (1-40), `package.json` (grep). Not read: `docs/concepts.md`, `docs/configuration.md`, dropper and reflector prompts, tests.

This repo: `docs/superpowers/specs/2026-11-10-pcee-engine-design.md` (lines 1-60, 88-132, 188-200, 417-445; Parts 2-3, sections 11-14 skimmed by heading only), `engine/lib/engine/` (module list), `engine/lib/engine/backend/claude_tmux.js` (1-30), `claude/orchestrator.md` (49-60, 119-126), `claude/plugin/skills/handoff/SKILL.md` (1-40). `claude/worker.md` was not read in full.

Not verified: the Claude Code hook behaviours in the table (from my knowledge, not tested here).
