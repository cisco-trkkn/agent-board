# Brief: a relay re-runs the pane's old start command (stale handoff on every relay)

## Rules

1. Role: implementer for one bug. Deliverable: a failing test, the fix, the verdict lines, a report, on branch
   `fix/relay-respawn-command` in worktree `/Users/francisco.ruiz/agent-board/.claude/worktrees/relay-respawn-command`
   (create it: `git -C /Users/francisco.ruiz/agent-board worktree add -b fix/relay-respawn-command .claude/worktrees/relay-respawn-command main`).
   You own `board/relay.py`, the relay tests under `board/tests/` (`test_relay.py`, `test_orchestrator_path.py`, or a new
   test file) and the report file. Stage only your own paths (`git add <paths>`, never `-A` or `.`) and run no
   whole-tree git operation (`stash`, `reset`, `checkout`, `clean`, `rebase`). Never touch the main checkout
   (`/Users/francisco.ruiz/agent-board`): it is the live install. Never restart bridges, the board or any lead, never
   run a real relay, and never respawn or send keys to a real tmux pane (reading `%138` is fine).
2. Skills, by full name: `superpowers-extended-cc:systematic-debugging` (confirm the cause below), then
   `superpowers-extended-cc:test-driven-development` with `test-driven-development-extras`, and
   `superpowers-extended-cc:verification-before-completion` before reporting. The design is settled: do not run
   `brainstorming` and do not ask the user anything.
3. Questions and decisions go to the lead (`team-lead`) as a message. If an answer can't wait, make the reasonable
   choice, note the assumption, and keep going. The exception: when the question is about a failed acceptance
   criterion, a spec constraint your option cannot meet, a gate, or a step that changes shared state or removes
   something (a worktree, a published doc), wait for the lead's answer before that step. A user-confirm step that a
   loaded skill names is such a gate: it goes to the lead to relay, and a spec or plan never stands in for the user's
   answer. Only reversible, local work continues meanwhile. "My plan unless you say otherwise" is for choices you can
   still undo.
4. Decided: see the Decided block below.
5. Read `~/agent-board/claude/worker.md`; its common rules and teammate section apply to you.

## The bug

`board/relay.py` `respawn()` (line ~128) runs `tmux respawn-pane -k -t <pane> -c <root>` with no command, commented
"no command: fresh default shell". But tmux re-runs the pane's ORIGINAL start command when respawn-pane gets none.
The live lead pane `%138` shows it: `tmux display -p -t %138 '#{pane_start_command}'` prints
`".../bin/claude-orchestrator 'Read .../handoffs/2026-11-19-spec-c-task2-fix.md and continue …'"`. So every relay
(and every board restart_orchestrator, `board/server.py:1072,1079`, which call the same `respawn()`) starts a lead on
that stale 11-19 handoff; the launch line typed afterwards by send-keys lands as a queued message or is lost.

## Decided

- Fix in `respawn()` only: pass an explicit command to `respawn-pane` so the stored start command is replaced. The
  command is a login shell: the tmux global `default-shell` (`tmux show -gv default-shell`, through the same `tmux`
  callable), falling back to `$SHELL`, then `/bin/sh`, started with `-l` (what tmux runs for a new window when
  `default-command` is empty). Keep the existing send-keys of `launch_line(root, prompt)` + Enter after it, so
  `wait_started` ("not a shell") semantics stay the same.
- Tests (unit, with the existing fake tmux recorders): respawn-pane's argv ends with a command after `-c <root>`;
  that command is the login shell; the send-keys order is unchanged. Update `test_relay.py:195`'s exact-argv
  assertion to the new argv.
- One real check (test-driven-development-extras' "one real run"): on a scratch tmux server
  (`~/.local/bin/tmux -L relayprobe -f /dev/null`), create a window whose start command is e.g. `sleep 1000`,
  call `relay.respawn` against it with a recorder that runs the real tmux on that socket, and show
  `#{pane_start_command}` no longer says `sleep 1000` and `#{pane_current_command}` is the shell. Kill that server
  afterwards. Never launch claude there: monkeypatch `launch_line` to return `true` for the real check, so nothing
  real starts.
- Verdicts: `python3 -m unittest discover -s board/tests` (its summary line) and `zsh tools/tests/all.zsh` (its
  verdict line and rc; rc 4 = time budget only is acceptable, say so).
- Commit: `fix(board): relay respawns the pane with an explicit login shell, not its stale start command`.
- Report: `docs/superpowers/briefs/2026-11-20-relay-respawn-command.report.md` in your worktree, committed: cause
  evidence, test names, the real-check output, both verdict lines, commit SHAs. Then message `team-lead`.
