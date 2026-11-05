# Mod: usage and context gauges in-session

Date: 2026-11-05 · Status: approved design, awaiting spec review
Group 2c of the mods ideas (ideas file, 2026-11-04 23:23 "mod: usage and context gauges in-session").
Independent of the other mod specs.

## Problem

Plan limits (5h / 7d), context fill and session cost are only on the board. The session itself could show
them in one line.

## Mods facts this spec relies on

Same source and limits as the agent-status spec (`2026-11-05-mod-agent-status-design.md`). In addition:
`$.ui.status(text)` shows one line under the prompt, prefixed with the mod's name; `$.clock.every` polls;
`$.fs.read` reads a file (up to 4 MiB).

## Data

The agent-board statusLine tap (`claude/statusline/agent-board-statusline`) writes each session's latest
statusLine payload to `<state dir>/statusline/<session_id>.json` with `received_at`. `board/usage.py` reads
the same files (`plan_limits`: `five_hour`, `seven_day` from the payload's `rate_limits`). The mod reads only
its own session's file.

## Design

`claude/plugin/mods/usage-gauges.js`:
- Every 10 s, read `<state dir>/statusline/<own session_id>.json`.
- Show `5h 42% · 7d 18% · ctx 61% · $3.20` via `$.ui.status`: 5h / 7d from `rate_limits` used percentages,
  ctx from the payload's context window fill, $ from its session cost. Field paths are read from a real tap
  file in the plan's first step and pinned in a fixture copied from it.
- A part whose data is missing is left out; no data at all, or a file older than 5 minutes → clear the status
  line.
- Never shows another session's numbers; never throws out of a hook.

## Files

- Create: `claude/plugin/mods/usage-gauges.js`, `claude/plugin/mods/usage-gauges.test.ts`
  (fixture copied from a real tap file, with any identifiers replaced)
- Modify: `claude/plugin/hooks/hooks.json` (add the module), the plugin manifest description.

## Testing

- `claude plugin test`: full line from the fixture, missing parts dropped, stale or absent file clears it.
- One real run: a session with the statusLine tap installed shows the line (pane capture).
- Targeted runs only: the mod tests and `zsh tools/tests/test_plugin.zsh`.

## Failure rule

If mods do not load in an interactive `--plugin-dir` session (the agent-status spike's finding, if it ran
first), this spec fails with `failed — mods do not load`.
