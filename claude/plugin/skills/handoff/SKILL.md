---
name: handoff
description: "Two uses. (1) The lead hands its session to a fresh orchestrator: checkpoint the team, write a handoff doc, relay in place (asks first when the user typed /handoff). (2) `teammate <name>` replaces one teammate with a fresh one under the same name, from its checkpoint."
argument-hint: "What will the next session be used for? Or: teammate <name>"
---

Lead only. A teammate or worker never runs this skill in either mode: tell the lead.

Hand the work in this session to a fresh orchestrator. If the user passed arguments, they describe what the next session should focus on; tailor the doc to that.

## Teammate mode

Arguments that start with `teammate <name>` replace that one teammate; the rest of this skill does not run. No doc, no AskUserQuestion.

1. Send `<name>` the checkpoint message from step 1.
2. Wait up to 2 minutes for the reply. With no reply, record `no checkpoint` and the last 40 lines of its window: `tmux-ctl read "✦ <name>" 40`, or `tmux-ctl read <name> 40` if the window has no ✦ prefix.
3. Send `<name>` a `shutdown_request` whose `reason` ends with the suffix from step 3, and wait for the termination notice. A teammate idle at its prompt is not gone.
4. Respawn it with the same `name`, role and tier: the tier map in `claude/orchestrator.md` "Models and effort" gives the `subagent_type` and `model` (mechanical → effort-low + haiku, standard → effort-medium + sonnet, frontier → general-purpose + fable). The prompt is teammate rules 1–5 from `claude/orchestrator.md`, then the checkpoint note (task, files owned, progress, next step, assumptions, risks). For `no checkpoint`, give the captured output and "re-check the state of your files before continuing".
5. Check the new pane is alive: `tmux list-panes -a -F '#{window_name} #{pane_dead}'`. Respawn again if it is dead.
6. Report one line to the user: `respawned <name> from checkpoint`, or `respawned <name> from captured output`.

Brief first, owner second: re-set the teammate's task `owner` only after the new brief is sent.

Do the steps in order. **Inside tmux** (`$TMUX` set) do all five. **Outside tmux** (`$TMUX` unset) there is no board, no window to read and no relay: do steps 1–3 without any `tmux-ctl` command, skip step 4, and end with the fallback in step 5.

## 1. Checkpoint the team (skip if you have no teammates)

Send every teammate this message with SendMessage:

> Handoff checkpoint. Finish or pause your current step at a safe point (don't leave a file half-edited), then reply to me with exactly these fields: name, role, model tier, current task (id and subject), files you own, progress so far, next step, assumptions made, anything unfinished or risky. Then stop and wait; a shutdown request follows.

Wait up to 2 minutes for the replies. For a teammate that has not answered, record `no checkpoint`. Inside tmux, add the last 40 lines of its window from `tmux-ctl read "✦ <name>" 40`, or from `tmux-ctl read <name> 40` if the window has no ✦ prefix (`tmux-ctl list` shows the names). Outside tmux, record `no checkpoint` with no captured output.

## 2. Write the handoff doc

Save it with the Write tool to `~/.local/state/agent-board/handoffs/YYYY-MM-DD-<short-slug>.md` (today's date; `mkdir -p ~/.local/state/agent-board/handoffs` first). Include:

Older handoffs may still be in `~/.claude/handoffs/`; read them from there if the user points to one.

To find "the recent handoff for this project", filter by the `Project:` line first (`grep -lx "Project: <toplevel>"` over both directories), then take the newest match. Never take the newest file across all projects. If nothing matches (older docs have no `Project:` line), list the candidates with their Focus lines and ask.

- **Project**: the doc's first line is `Project: <path>`, where the path is `git rev-parse --show-toplevel` of the main checkout (for a worktree, the repo it belongs to), or the cwd outside git. Every project's handoffs share one directory, so this line is how the next session finds its own.
- **Focus**: what the next session is for (the arguments, or your best summary).
- **State of the work**: what is done, in progress and next. Reference the plan, spec, branch, MR and commits by path or URL instead of copying them. If the doc names a merge strategy or branch relationship ("merging into main is a fast-forward"), record the SHAs it was computed against (`git rev-parse <base> <branch>`), so the next lead can re-check it before acting.
- **Team**: one entry per teammate, built from its checkpoint, so the next lead can respawn it as is. Lead with name, role and model tier, then the checkpoint note: task, files owned, progress, next step, assumptions, risks. Mark teammates without a reply as `no checkpoint` and include their captured output, if any.
- **Previous session**: its id, so it stays resumable with `claude --resume <id>`. Write a placeholder first and fill it in as below.
- **Ideas**: one line: `Ideas inbox: ${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md (do not read until the plan is done)`, with `TC_IDEAS_DIR` resolved from your environment when it is set. `<project>` is the tmux session name: `tmux display -p '#{?session_group,#{session_group},#{session_name}}'`. Never copy ideas into the doc. Outside tmux, leave this line out.
- **Shared context**: first merge any unmerged `Context learned` items from teammate reports and checkpoints with `tmux-ctl context add <section> "<entry>"` (inside tmux). Then one line: `Shared context: ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md`, with `TC_CONTEXT_DIR` resolved from your environment when it is set and `<project>` as for Ideas. Never copy entries into the doc: the next orchestrator gets them from the SessionStart hook. Outside tmux, leave this line out.
- **Suggested skills**: the skills the next lead should invoke with the Skill tool.

Redact secrets and personal data.

**Find the previous session id.** The Write tool's hook records the doc together with this session's id. Read it back, retrying for up to about 5 seconds because the hook runs async:

```bash
jq -r --arg p "<doc absolute realpath>" 'select(.path==$p and .session_id) | .session_id' \
  "${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}/artifacts-<project>.jsonl" | tail -1
```

Only if that is still empty (always the case outside tmux), fall back to the basename (without `.jsonl`) of the newest `.jsonl` file in `~/.claude/projects/<cwd with every / and . replaced by ->/`, and say in the doc that the id came from this fallback and may be a teammate's transcript. Don't use "newest .jsonl" first: teammate transcripts share that directory. Put the id into the doc with Edit.

**Register it** only if the doc is saved somewhere other than `~/.local/state/agent-board/handoffs/`: `tmux-ctl artifact <doc> --kind handoff`. A doc under `~/.local/state/agent-board/handoffs/` is already registered by the hook.

## 3. Shut the team down

Send each teammate a `shutdown_request`. End its `reason` with: "To approve: first load SendMessage's schema with ToolSearch query \"select:SendMessage\", then send `message` as a JSON object, not a string." Confirm each one is gone.

## 4. Ask before switching

**Self-started** means the user did not type `/handoff` in the message that started this turn (you chose to hand off, for example after a context-guard warning). Self-started: skip the question, print `Handing off to a fresh orchestrator: <doc>` and take step 5's **On Yes** path. A Not yet earlier in this session makes every later handoff user-started: ask.

**User-started:** ask with AskUserQuestion: "Switch to a fresh orchestrator now?"

- **Yes**: "This window restarts as a new orchestrator that starts from the doc and respawns the team. This session stays resumable."
- **Not yet**: "Keep this session. I'll print the doc path and the command to switch later."

When the user started the handoff, never run the relay without a Yes from this question.

## 5. Relay

- Relay is lead-only: `tmux-ctl relay` refuses from any window but the session's `claude` window (workers, teammates, lanes, shell) and prints the manual start command. If you are not the lead, give the user that printed command instead of relaying.
- **On Yes:** run `tmux-ctl relay <doc> --old-session <id>`. Then end your turn with:

  ```
  Switching once this turn ends; the new orchestrator starts from <doc>.
  If it doesn't switch, start it by hand in a new shell (e.g. a new tmux window): claude-orchestrator 'Read <doc> and continue from where the previous session left off.'
  ```

  The relay waits for your turn to end, then replaces this window. Do nothing else after it. If no switch happens within about 2 minutes, a tmux message ("relay failed: …") says why (full reason in `$STATE/relay-<project>.log`), and the doc stays where it is for a manual start.
- **On Not yet:** end with

  ```
  Handoff saved: <absolute path>

  Switch later: tmux-ctl relay <absolute path> --old-session <id>
  Or start a session by hand: Read <absolute path> and continue from where the previous session left off.
  ```
- **Outside tmux (`$TMUX` unset), self-started or not:** end with

  ```
  Handoff saved: <absolute path>

  Next session prompt:
  Read <absolute path> and continue from where the previous session left off.
  ```
