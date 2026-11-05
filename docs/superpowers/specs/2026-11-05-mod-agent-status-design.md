# Mod: agent status from events

Date: 2026-11-05 · Status: approved design, awaiting spec review
Group 2a of the mods ideas (ideas file, 2026-11-04 23:23 "mod: agent status from events, not pane text").
Followed by: `2026-11-05-mod-team-band-design.md` (reads this mod's files).

## Problem

The board decides busy / ready / needs-you by scraping pane text (`board/paneclass.py`: `classify`,
`spinner_live` over the last 30 rows). A Claude Code wording change silently turns every pane ready
(2.1.316 dropped "esc to interrupt"). Claude Code mods see the real events, so a mod can write each
session's state and the board can read it.

## Mods facts this spec relies on

From https://code.claude.com/docs/en/plugins/mods/ (overview, interface, reference, events, api), read 2026-11-05 against Claude Code 2.1.318:
- A mod is a plugin's `hooks/hooks.json` `"modules": ["./<file>.js"]` entry; the module exports `register(on, options)` and runs in Claude Code's process as an ES module with no Node APIs or timer globals: files, processes and timers go through `$.fs`, `$.process.run([...])` (no shell) and `$.clock.every/after`.
- `--plugin-dir` loads a plugin's mods for that session; the agent-board plugin is loaded that way (`claude/plugin/.claude-plugin/plugin.json`). Whether `hooks.json` can hold `modules` beside the existing classic hooks is checked by the plan's first task.
- Limits: 10 s per hook (time inside `next` or `$` calls not counted); a hook that throws or times out is skipped, the session goes on. `claude plugin test` runs `*.test.ts(x)`, 5 s per test.
- `claude -p`: hooks run, nothing drawn. `--bg` and teammate sessions: not stated in the docs.
- Events used: `session.start`, `session.end`, `turn.start`, `turn.complete`, `tool.check` (Claude Code's allow / ask / deny decision, before any prompt), `tool.call` (before the tool; `await next(e)` returns after it, so for `AskUserQuestion` it returns once the user answered).
- There is no event for a permission dialog appearing or being answered.

## Design

### The mod (`claude/plugin/mods/agent-status.js`)

Writes one file per session: `<state dir>/agent-status/<session_id>.json` (state dir = `$TC_STATE`, else
`~/.local/state/agent-board`, as `tc_env.state_dir()` resolves it), holding
`{"session_id", "pane": $TMUX_PANE or null, "state", "since", "updatedAt"}` (times as epoch seconds).
One writer per file, so no lost writes; the shared `$.store` is not used (its get+set is not atomic and the
Python board would have to read the plugin store file). Writes go to `<file>.tmp` then a rename if `$.fs`
offers one, else a direct write (the reader tolerates a partial file by ignoring it).

States and transitions:
- `ready` on `session.start` and on `turn.complete`.
- `busy` on `turn.start`.
- `needs-you` when `tool.call` for `AskUserQuestion` starts; back to `busy` when its `next()` returns.
- `needs-you` when `tool.check` decides `ask`; back to `busy` when that tool's `tool.call` starts (the user
  allowed it) or `ready` at `turn.complete` (denied / aborted).
- A heartbeat (`$.clock.every(15000)`) rewrites `updatedAt` only.
- `session.end` deletes the file.

`$TMUX_PANE` and the state dir come from the environment (`$.process` env or a `printenv` run, whichever the
API offers; the plan's first task settles it). Every handler is wrapped so an error never blocks a tool.

### The board (`board/paneclass.py`)

Before scraping a pane, look for a status file whose `pane` equals the pane id and whose `updatedAt` is
under 45 s old; if found, its `state` maps to the board's existing classes (busy / ready / needs you).
Otherwise classify by pane text as today. The reading is cached per refresh (one directory listing per
board poll, not per pane). No board UI change.

### Spike first (plan Task 1)

Before the mod is built out: a minimal mod that writes one file on `session.start`, run for real in
(a) the `dev` lead, (b) a `tmux-ctl agent` worker, (c) a teammate window, (d) a `--bg` session if the
installed Claude Code has one. Record which load it, and whether `modules` and classic hooks coexist in
`claude/plugin/hooks/hooks.json`. A context where it does not load keeps the scraping fallback; the spec is
not failed for that. If mods load nowhere, the spec fails (Queue mode records `failed — mods do not load`).

## Files

- Create: `claude/plugin/mods/agent-status.js`, `claude/plugin/mods/agent-status.test.ts`
- Modify: `claude/plugin/hooks/hooks.json` (the `modules` entry), `board/paneclass.py`,
  `board/tests/` (a paneclass test file for file-first and fallback), the plugin manifest description.

## Testing

- `claude plugin test` on the mod: each transition above, the heartbeat, deletion on end, a throwing write
  not propagating.
- Python: paneclass uses a fresh file, ignores a stale (≥45 s), partial or other-pane file and falls back.
- One real run in a scratch tmux server (`-f /dev/null`, temp `TC_STATE`): a lead session goes busy → ready,
  and needs-you while an AskUserQuestion is open, read from the file and from the board's `/api/state`.
- Targeted runs only: `python3 -m unittest` on the new test file and `zsh tools/tests/test_plugin.zsh`.

## Not in scope

The team band (its own spec), usage gauges (own spec), moving the shell hooks in-process (parked).
