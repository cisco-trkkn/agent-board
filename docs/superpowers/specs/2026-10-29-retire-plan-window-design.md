# Retire the `plan` window

Status: approved by the user, 2026-10-29.

## Why

The user finds the `plan` window adds nothing: the orchestrator chat already shows the lead's task list. The board's "Needs you" already flags waiting prompts. Three open ideas go away with it:
- blocked tasks render as ✗, which reads as failed;
- teammate windows land between `claude` and `plan`;
- "the plan window is useless".

## Scope

### 1. Layout

- `bin/dev` and `bin/tmux-dev-layout` no longer create a `plan` window.
- When the layout runs on a session that still has a `plan` window, it closes that window, but only if its pane runs `tmux-plan`: check the pane's start command (`#{pane_start_command}`) or its current command. A window the user created and happened to name `plan` is never touched.
- A dev session's visible windows become `claude` plus any teammate windows `✦ <name>`.

### 2. Code removed

- Delete `bin/tmux-plan`.
- `board/planview.py`:
  - Remove `render()`, `watch()`, the `GLYPHS` table and the `watch` choice of `main()`.
  - Keep `view()` and its `view` CLI subcommand unchanged. The queued overseer and night-mode plans read `view()` (`active`, `name`, `tasks`).
  - Update the module docstring: it no longer serves a tmux window.
- Tests:
  - delete `tools/tests/e2e-plan-window.zsh`;
  - in `tools/tests/test_layout.zsh`, replace the `plan` window checks with the three cases under Testing;
  - in `board/tests/test_planview.py`, drop the render and watch cases and keep every `view()` case.
  - `board/tests/fixtures/planview/` stays wherever a `view()` case uses it.

### 3. Docs and rules

Remove the `plan` window from:
- `claude/orchestrator.md`, the live lead rules: the "session's windows" table row, and any other mention of the plan window;
- `claude/skills/tmux-orchestrator/SKILL.md` and `claude/plugin/skills/tmux-orchestrator/SKILL.md`;
- `claude/skills/docs-runbook/SKILL.md`, where it mentions the window;
- `docs/ARCHITECTURE.md`;
- the comment at the top of `bin/dev`, and the `tmux-dev-layout` header comment.

Historical specs, plans, reports and ledgers dated before this spec are left as they are.

### 4. Amendment to the queued teams plan

`docs/superpowers/plans/2026-10-28-teams-in-one-project.md`, Task 5 (0 of 13 tasks done, nothing in flight):
- drop "ensure `<t>·plan` next to each `<t>·claude`" from the `bin/tmux-dev-layout` file entry and from its acceptance criteria;
- drop the `bin/tmux-plan` file entry;
- fix its `json:metadata` `files` list and the `.tasks.json` description to match.

Add one line under the plan's header saying the plan window was retired by this spec.

### 5. Ideas

Mark these as `- [x] … → docs/superpowers/specs/2026-10-29-retire-plan-window-design.md`:
- the plan-window ✗ glyph idea;
- teammate windows before `plan`;
- "the plan window is also useless".

## Out of scope

- The board and its "Needs you".
- `tmux-teammate-window`: it does no `plan`-relative placement, so it needs no change.
- The `tests`/`shell` windows of the `<project>-bg` session.

## Testing

`tools/tests/test_layout.zsh`, on a scratch tmux server started with `-f /dev/null`:
1. A fresh `dev` session has no `plan` window.
2. Re-layout of a session that has a `plan` window running `tmux-plan` closes it, and `claude` stays at index 1.
3. Re-layout of a session with a user window named `plan` running a plain shell leaves that window alone.

Also run:
- `python3 -m unittest board.tests.test_planview`: the `view()` cases pass;
- `grep -rn "tmux-plan\|plan window" bin claude board tools docs/ARCHITECTURE.md`: no hits outside dated history files;
- the full `zsh tools/tests/run-all.zsh`, with its exit code read alone, plus `python3 -m unittest discover -s board/tests`.

## Risks

- **A live session keeps its old `plan` window until its layout runs again.** That is harmless: `tmux-plan` stays deleted, so the pane shows "command not found" if its process is ever restarted. Re-running `dev` closes the window.
- **The overseer spec reads `planview` for "the active plan's title and done/total".** It still works, because `view()` is kept.
