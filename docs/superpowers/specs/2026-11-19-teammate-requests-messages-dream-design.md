# Teammate requests in the lead's window, late teammate messages, and the dream skip (regroup group 1)

Date: 2026-11-19 · Decided with the user over Discord, 2026-11-19 (regroup "Teammate permissions, messages and dream job"; ideas 7533265807, fdec51baf0, ff59393949, 42073aa338)

Builds on spec C (`2026-11-19-remote-discord-only-design.md`): `tmux-ctl dialog <win> show|press`, `board/discord_dialogs.py` scan and its Allow once / Deny posts. This spec runs after spec C is merged.

## Problem

1. In agent teams, a teammate's permission request can queue in the lead's own terminal. The teammate's pane shows only a "Waiting for team lead approval" box, and nothing reaches Discord. On 2026-11-19, c-t2 sat 7 h with no post. No capture of the lead-side dialog exists, so neither `dialog show` nor the board can read it.
2. The lead's queue is FIFO. A killed teammate's request (c-t2, killed by `wait-gone`) stays at its head and blocks the next teammate's request (c-t2b) until someone answers it at the terminal.
3. Teammate messages reach the lead late or not at all. c-rev2's verdict and c-t2c's done report never arrived. On 2026-11-19 22:28Z, c-t7's done report arrived about 15 min after its commit, after the lead had already read its report file. Nothing tells the lead that a teammate stopped.
4. The dream job reports `dream: francisco_ruiz skipped, no repo root` on every `--all` run. That context file (home-dir sessions) has no entries, and `~` is not a git repo (`board/dream.py:357-360`).

## Decisions (user, Discord, 2026-11-19)

- D1. A request in the lead's window from a teammate that is gone gets Deny pressed automatically and logged (Q1 answer "1"; the user confirmed "press deny automatically").
- D2. Late messages: a Stop hook in each teammate writes a status file, a lead hook reminds the lead when that file is newer than the teammate's last message, and `tmux-ctl teammates` lists them (Q2 answer "1").
- D3. Dream: `--all` silently passes over a project whose core has no entries. A project with entries and no root still reports `skipped, no repo root` (Q3 answer "1").
- D4. The design below was approved as sent ("Ok", 22:46Z).

## Design

### 1. Teammate requests in the lead's window (`tools/lib/dialog.zsh`, `board/discord_dialogs.py`, `board/paneclass.py`)

- **Capture first.** A scratch lead with one scratch teammate, on a scratch tmux server (`-f /dev/null`), in a temp repo whose settings deny one harmless command (e.g. `touch probe`) without a prompt rule for it. The teammate runs it, and the lead pane is captured while the request shows. Store it as `tools/tests/fixtures/dialogs/team-request.txt`, with the teammate pane's "Waiting for team lead approval" box as `team-waiting.txt`. Note in the fixtures README how the requesting teammate's name appears, and whether the lead must be idle for the request to render. If the request never renders in the lead pane under the scratch setup, the task stops and reports what it saw: the rest of this section depends on the capture.
- **`dialog show`** reads the lead-side request as `kind: permission`, with the same options and `--expect` lines as a teammate's own prompt, plus `from: <teammate name>`.
- **The scan** posts it as any permission dialog (spec C), headed `🔐 <project> · <name> (in the lead's window) wants to …`. Allow once / Deny press in the lead pane through `dialog press`, with the exact-text re-check.
- **The teammate's box.** `paneclass` classifies a teammate pane whose last rows are the "Waiting for team lead approval" box as `waiting-on-lead`: the board shows it as waiting, pointing at the lead window, and the scan posts nothing for the teammate pane itself (the lead pane's post covers it).

### 2. Stale requests are denied (`board/discord_dialogs.py`)

- On every scan, for each lead pane whose `show` is a permission request `from` a teammate: the teammate is **gone** when no `✦ <name>` window exists in the lead's session, on two scans at least 30 s apart (a window being respawned under the same name is not gone).
- A gone teammate's request gets `dialog press <lead pane> --option No --expect <its lines>`. If the re-check reads `changed`, nothing is pressed this tick.
- The scan repeats down the queue while the new head is also from a gone teammate, up to 10 presses per lead per tick.
- Each press: an audit line `dialog / stale-deny / <name>`, a line in the Activity feed `denied stale request from <name> (window gone)`, and, if the request had a Discord post, an edit to `→ denied: <name> is gone`.
- Never: a press on a request from a live teammate, a request with no `from`, or a request whose re-check fails. A worker (`tmux-ctl agent`) or a peer is never treated as a teammate here.

### 3. Late teammate messages (`claude/hooks/`, `claude/plugin/hooks/hooks.json`, `bin/tmux-ctl`, `claude/orchestrator.md`, `claude/worker.md`)

- **Teammate Stop hook.** It runs only inside a teammate. The plan's first step probes which environment marks a teammate and its name inside a hook (spec C's Task 11 carries the same probe; reuse its result if it has run). It writes `<state>/teammates/<lead session id>/<name>.json`: `{"ts": <epoch>, "name": …, "first_line": …, "text": <last assistant message, first 2000 chars>}`, atomically (temp file, then rename). It never blocks the Stop and never fails it: any error exits 0.
- **Lead reminder.** A lead-only hook, on the events that wake the lead (the plan probes whether `UserPromptSubmit` fires for teammate messages; `PostToolUse` otherwise, at most once a minute), compares each status file's `ts` with the time of the last message from that teammate. The time comes from a `<state>/teammates/<lead session id>/<name>.seen` file that the same hook touches when a message from that name arrives. When the status file is newer, it adds context once per stop: `<name> stopped at HH:MM: <first line> — read its report file.`
- **`tmux-ctl teammates`** lists, per teammate of the calling lead's session: name, window alive (yes/no), busy/idle (from the pane class), last stop time, and first line. It prints `no teammates` when there are none.
- **Rules.** `claude/worker.md` (teammate section): write the report file before sending the done message, and name it in the message. `claude/orchestrator.md`: when a teammate looks idle, or the reminder fires, read its report file before waiting longer; act once on a report that arrives twice.

### 4. Dream skips empty projects (`board/dream.py`)

- `run --all` passes over a project whose core has no entry lines (only the title, the `Last curated` line and the four headings), with no result line and no message.
- A project with entries and no root still yields `dream: <p> skipped, no repo root`.
- `run <project>` on an empty project still runs the usual path. It names the project explicitly, so the user sees what happens.

## Error handling

- A capture that never shows the lead-side request stops section 1 and section 2 (they depend on it). Sections 3 and 4 still ship.
- `dialog press` failures in section 2 (changed, no prompt, copy mode) are logged and retried on the next tick, never forced.
- The Stop hook and the lead hook exit 0 on any error and write nothing partial.

## Testing

- `tools/tests/test_ctl_dialog_show.zsh`: `team-request.txt` reads as `kind: permission` with `from: <name>`, with options and `--expect` lines as the capture shows.
- `board/tests/test_discord_dialogs.py`: a lead-side request posts once with the `(in the lead's window)` header; a fake lead pane whose request comes from a teammate with no `✦` window on two scans 30 s apart gets exactly one Deny press with its lines as `--expect`; a live teammate's request, a request on the first scan only, and a request with no `from` get no press; a `changed` re-check presses nothing; a queue of three stale requests gets three presses in one tick, and the 11th is left for the next tick.
- `board/tests/test_paneclass.py`: `team-waiting.txt` classifies as `waiting-on-lead`.
- `claude/hooks/tests/`: the Stop hook writes the status file only in a teammate env, atomically, and exits 0 when the state dir is unwritable; the lead hook reminds once per stop, not when `.seen` is newer, and not in a teammate or worker.
- `tools/tests/`: `tmux-ctl teammates` on a scratch server with one live and one dead teammate; `no teammates` when there are none.
- `board/tests/test_dream.py`: `--all` with an empty core and no root yields no result for it; with entries and no root, it yields `skipped, no repo root`.
- One real check after the merge (user gate): a real teammate's request in the lead's window answered from Discord; a teammate killed while its request waits gets Deny pressed within a minute; the reminder line appears in the lead when a teammate stops.

## Out of scope

- Answering a live teammate's request without the user (only gone teammates get Deny).
- Changing how Claude Code delivers teammate messages.
- Dreaming projects without a repo (Q3 option 2).
