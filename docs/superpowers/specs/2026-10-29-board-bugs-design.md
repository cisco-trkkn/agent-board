# Board bugs: session root, Show dropped, Usage tab, test_bg flake

Status: approved by the user, 2026-10-29.

Four independent fixes in one plan. Their files don't overlap, so (a), (b) and (d) can run in parallel.

## (a) `session_path()` returns the session root

**Problem.** `board/server.py` `session_path(sess)` returns the active pane's `#{pane_current_path}`. Claude Code follows the lead's `cd`, so this is wherever the lead last went, often a worktree. Its three callers all want the project's main checkout:
- `:500` names a board-spawned agent from the repo's `claude/*` branches and `.claude/worktrees`;
- `:539` is the cwd for `tmux-ctl agent`, which creates the agent's worktree from there. From a worktree, the agent branches off that worktree's branch, and its worktree nests;
- `:807` lists the worktrees.

This is the same root cause as the relay start-dir bug fixed in e978a70.

**Fix.** `session_path(sess)` delegates to `relay.session_root(tmux, sess)`: the session's start path, then its main checkout, then `$HOME`. It raises `RuntimeError(f"no session '{sess}'")` when the session doesn't exist, as today.

**Accepted cost.** A board-spawned agent branches from the main checkout's HEAD, never from the branch the lead happens to be on.

**Tests** (`board/tests/`, scratch tmux server with `-f /dev/null`): a session whose start path is a repo and whose active pane sits in one of its worktrees. Each of the three call sites gets the main checkout. A missing session still raises.

## (b) "Show dropped" re-renders at once

**Problem.** `board/index.html` `pollIdeas` returns early on an unchanged poll (304, `ideasShown === s.name`). Ticking "Show dropped" therefore changes nothing until the data changes or the page reloads. This exists on main; uicheck found it on 2026-10-28.

**Fix.** The checkbox handler re-renders from the last data received. If that is not possible, it clears the early-return guard so the next poll re-renders. The toggle must not cost an extra fetch when the cached data is enough.

**Test.** Extend the `board/tests/test_ideas_gitlab_ui.py` pattern, which extracts the page's own functions. With an unchanged poll, toggling shows the dropped rows; toggling back hides them.

## (c) A trustworthy Usage tab: probe, then tap

**Problem.** Every column of the Activity drawer's Usage tab is re-derived from transcripts:
- **Context %:** the last call's tokens divided by a window from `board/prices.json`, which assumes 1M for every model but Haiku 4.5;
- **Model and Effort:** the newest transcript line;
- **Last hour and Total:** API-equivalent dollars;
- **Rows:** sessions with a call in the last `live_s` (1800 s).

The user sees all four disagree with Claude Code's own figures (its status line, `/context`, `/usage`). No `statusLine` is configured, so those figures never reach the board.

**1. Probe (frontier tier, read-only).**
- Capture the JSON Claude Code passes to a statusLine command, in a real interactive session. Use a temporary statusLine set by a session-local or scratch setting, never the user's `~/.claude/settings.json`.
- Record which fields exist: context-window size, used tokens and %, model id and display name, effort, session id, cost, and any plan-limit windows (5-hour or weekly).
- Output: `docs/superpowers/plans/2026-10-29-statusline-probe.md`, with the field table and one real sample. Scrub the sample of paths under `/Users/` and of anything secret-shaped. The sample becomes the test fixture.

**2. Tap.**
- New script: `claude/statusline/agent-board-statusline`. It reads the JSON on stdin and writes it atomically (temp file + rename) to `<state_dir>/statusline/<session_id>.json` with a `received_at` epoch. It prints a one-line status: model, context %, and the plan-limit figure if one exists.
- It never fails Claude Code: on any error it prints a fallback line and exits 0. It never writes outside `<state_dir>/statusline/`.
- Install: `statusLine` in `~/.claude/settings.json` pointing at the script. It is a user-global config change, so the install step is a user gate: the lead asks before writing. Back the file up first, as the user's tooling rules require.

**3. Board.**
- `board/usage.py`: a live row takes Context %, Model and Effort from the tap when its file is fresh, and from the transcripts otherwise.
- Liveness: a session is live when its tap file was written within `live_s`, or when it had a transcript call within `live_s` and has no tap file at all.
- Plan-limit windows: if the probe finds them, the tab shows them in their own block. If not, the probe report says "not exposed locally", and the money columns are labelled "API-equivalent $" so they no longer read as `/usage`.
- `board/prices.json` context windows stay as the transcript fallback.

**Acceptance.**
- For every live interactive session, the board's Context % is within ±1 point of the value in that session's tap file, and Model and Effort match it exactly. Check this on the real board against real sessions, as an e2e step with uncapped output.
- A session with a stale or missing tap file still shows a row, from transcripts.
- The tap script's tests cover valid JSON, invalid JSON (fallback line, exit 0), and a write failure (exit 0).

## (d) `tools/tests/test_bg.zsh` flakes under CPU load

**Evidence (2026-10-28).**
- Three assertions fail together: `interrupted exit 143`, `interrupted summary`, `no stuck records`.
- With 2×ncpu `yes` load the failure reproduced in 1 of 2 runs. The test passes unloaded, and through `tmux-ctl run`.
- The code under test is unchanged between `a59ffc7` and `9c06adc`.
- The test waits 5 s (`tt_wait 5`) for the `sleep 30` start record, then sends `kill -TERM`, then waits 5 s for `exit: 143`.

**Approach.** Use `superpowers-extended-cc:systematic-debugging` to decide between two causes:
- If a TERM landing before the run's trap or record is in place leaves an `exit: null` record, that is a real bug: a stuck run in the Activity drawer. Fix it in `bin/tmux-ctl` so an early TERM still finalises the record, and add a test that sends TERM at once.
- Otherwise the test waits on conditions, not fixed 5 s windows, and the conditions are failure-checked: a `tt_wait` that times out fails the step loudly.

**Acceptance.** 5 of 5 runs of `zsh tools/tests/test_bg.zsh` under 2×ncpu load pass, with the load processes started and stopped by PID. `run-all.zsh` exits 0.

## Out of scope

- Plan-limit enforcement or alerts.
- Changing the board's cost model.
- Any change to how `tmux-ctl` records runs, beyond what (d)'s root cause needs.

## Ideas closed by this spec

Mark these `- [x] … → docs/superpowers/specs/2026-10-29-board-bugs-design.md`:
- session_path;
- Show dropped;
- the activity panel vs usage and context;
- the test_bg flake.
