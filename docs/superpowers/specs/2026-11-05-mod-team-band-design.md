# Mod: team band in the lead's terminal

Date: 2026-11-05 · Status: approved design, awaiting spec review
Group 2b of the mods ideas (ideas file, 2026-11-04 23:23 "mod: team band in the lead's terminal").
Depends on: `2026-11-05-mod-agent-status-design.md` (its `agent-status/*.json` files). Queued after it.

## Problem

To see which teammate needs an answer, the user opens the board in a browser. The lead's own terminal could
show it.

## Mods facts this spec relies on

Same source and limits as the agent-status spec. In addition: the `AbovePrompt` render site draws a band
above the prompt (terminal and Desktop only, shared by all mods, collapsible by the user); `$.clock.every`
polls; `$.fs` reads files; `$.process.run(["tmux", …])` runs tmux without a shell.

## Design

`claude/plugin/mods/team-band.js`:
- **Who draws it:** only the lead, the session whose tmux window is named `claude`
  (`tmux display -p -t $TMUX_PANE '#{window_name}'`, checked once at `session.start`). Other sessions
  register nothing visible.
- **What it reads:** every 2 s, `<state dir>/agent-status/*.json` (written by the agent-status mod), kept to
  panes of the lead's tmux session group (`tmux list-panes -s -F '#{pane_id} #{window_name}'` over the
  group, refreshed every 10 s), and named by window name (`✦ qrev`, `tests`).
- **What it shows:** one line, needs-you first: `Needs you: ✦ qrev · busy 2 · ready 1`. With nobody waiting:
  `busy 2 · ready 1`. With no other agents: nothing (no band). A pane whose file is missing or older than
  45 s counts as `?` (`? 1`), never as ready.
- The lead's own pane is left out.
- Errors (tmux missing, unreadable dir) leave the last good band, or none; never a thrown hook.

## Files

- Create: `claude/plugin/mods/team-band.js`, `claude/plugin/mods/team-band.test.ts`
- Modify: `claude/plugin/hooks/hooks.json` (add the module), the plugin manifest description.

## Testing

- `claude plugin test`: line built from fixture files (needs-you first, `?` for stale, own pane excluded,
  empty → no band), non-lead session draws nothing.
- One real run in a scratch tmux server (`-f /dev/null`, temp `TC_STATE`): a lead window `claude` and one
  teammate-like window whose status file says needs-you; the band text read from the lead's pane capture.
- Targeted runs only: the mod tests and `zsh tools/tests/test_plugin.zsh`.

## Failure rule

If the agent-status spec failed or its spike found mods do not load in the lead, this spec fails with that
reason (Queue mode outcome `failed — agent-status mod unavailable`).
