# Relay launch check: the new lead must actually start

Project: /Users/francisco.ruiz/agent-board · commit to `docs/superpowers/specs/2026-11-09-relay-launch-check-design.md`

Idea (inbox, 2026-11-09 14:26): "auto handoff is broken again. i get an error that the directory doesnt exist or
has been deleted. i change the directory to '~' and re-run the last terminal command and it works".

## Evidence (gathered 2026-11-09 by a worker, read-only)

- Both agent-board relays today failed the same way: 14:24:39 EST (doc `2026-11-09-queue-spec9-remote-brainstorm.md`)
  and 15:05:17 (doc `2026-11-09-queue-spec10-plan.md`), pane `%8` (lineage `~/.local/state/agent-board/lineage/agent-board.jsonl`).
- `relay.py` reported success both times (`$TMPDIR/tmux-ctl-$UID/relay-agent-board.log`: "relayed agent-board:claude …").
  It cannot know better: it returns as soon as it has typed the launch line.
- No transcript was created in `~/.claude/projects/-Users-francisco-ruiz-agent-board/` after either relay, so the new
  `claude` exited at startup.
- `~/.zsh_history` holds the sequence: the relay's typed `…/bin/claude-orchestrator 'Read …spec9-remote-brainstorm.md …'`,
  then `cd ~`, then the same line again. In the 15:05 case the respawned zsh (pid 1724) started 15:05:17 and its `claude`
  child only at 15:05:49; both now sit in `/Users/francisco.ruiz`.
- The two leads the user restarted by hand (4474f02d, ada03471) run with cwd `~`, not the project. Their transcripts
  land in `-Users-francisco-ruiz`, and `tmux-ctl agent`/`claude -w` from that lead makes worktrees of the **home repo**:
  the worker that wrote this spec got `~/.claude/worktrees/begin-brainstorming-handoff`, a worktree of the ~ repo.
- Claude Code 2.1.321 prints, when `process.cwd()` throws ENOENT: "The current directory no longer exists (it was
  deleted or moved). Start Claude Code from an existing directory." Probed in a scratch tmux: `cd gone && rmdir gone &&
  claude` prints exactly that and returns to the shell. That matches the user's report and the `cd ~` workaround.
- Not reproduced: a scratch `respawn-pane -k -c ~/agent-board` plus the same launcher starts fine, and plain `claude` in
  `~/agent-board` starts fine. So *why* the respawned shell sat in a gone directory is still open (Task 1 of the plan).
  Side observation: `~/.claude.json` has a stale `activeWorktreeSession` for `/Users/francisco.ruiz/agent-board`
  (worktreePath `.claude/worktrees/spikeworker`, originalCwd `.claude/worktrees/mod-agent-status`, both gone). It did
  not stop a plain start, but it is the kind of state the repro should include.
- History: the same symptom was fixed once in f1677ef (relay starts in `session_root`, the main checkout).

## Decisions (made by the worker; the user was not available)

1. **The launch line cds explicitly.** The typed line becomes `cd -- <root> && <claude-orchestrator> '<prompt>'`.
   Whatever left the shell in a gone directory, `cd` to an existing path repairs it. If `<root>` is itself gone, the
   line fails loudly instead of starting claude somewhere else. Never fall back to `~` silently: a lead in `~` creates
   worktrees of the wrong repo.
2. **Relay verifies the start.** After typing, relay polls the pane (2 s apart, 30 s cap) until its foreground is not a
   shell on two polls in a row (`paneclass.pane_status` kind != `shell`). A claude that dies at startup falls back to
   the shell, so this catches it. The check is "not a shell", not "is claude": tmux reports a running claude as its
   version binary (probed: `2.1.321`), and test stubs cannot pose as `claude` (probed on macOS: a copy of `sleep` named
   `claude` is SIGKILLed; a symlink and `exec -a claude` are both reported as `sleep`). Limitation: a claude that dies
   more than about 4 s after starting is not caught.
3. **One retry, then fail loudly with the evidence.** On a failed start, relay captures the pane's last lines into its
   log, respawns once more and retries. A second failure raises: `relay.py` exits 1, and the existing `_relay_failed`
   path shows the notice to every client and writes `relay-failed-<session>.txt`. The notice's manual command includes
   the `cd -- <root> &&` part. Lineage is written only after a verified start.
4. **Root cause first.** Task 1 reproduces the real relay end to end on a scratch tmux server: a lead in a worktree,
   the worktree removed during the turn, the stale `activeWorktreeSession`, and `tmux-ctl relay` via `run-shell -b`.
   It records the cause. If it names a cause the later tasks do not cover, the lead adds a task for it.

## Out of scope

- Clearing Claude Code's `activeWorktreeSession` in `~/.claude.json` (not ours to edit; noted for the repro).
- Moving the current lead back to `~/agent-board`. The lead's next handoff does it once this fix is in.
- The 12:24 idea (after a forced restart, no projects are open): separate.
