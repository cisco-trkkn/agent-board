# Handoff relay, artifacts panel, ideas inbox and Activity drawer: design

Date: 2026-10-16. Status: approved in brainstorming, awaiting spec review.

## Goal

Make long orchestrator sessions continuous and visible to the user:

1. **Handoff relay.** When a session is handed off, a fresh orchestrator takes over in place with the handoff doc, and the agent team comes with it. The user confirms every switch.
2. **Artifacts panel.** A hideable left sidebar in the Agent Board shows the session's artifacts, with the plan doc live, editable, commentable and showing what changed and who changed it.
3. **Ideas inbox.** The user can drop ideas for future work at any time without changing the current work. When the plan is done, the lead turns them into a Next steps round.
4. **Activity drawer.** The `shell`/`tests` windows and their feed/watch panes, which are of no use to the user, are replaced by a hidden agent session and an Activity drawer in the board.

## Scope and locations

All code lives outside this repo. Only this spec and its plan are committed here.

| Component | Location |
| --- | --- |
| Handoff skill | `~/.claude/skills/handoff/SKILL.md` |
| Orchestrator and worker prompts | `~/.claude/orchestrator.md`, `~/.claude/worker.md` |
| tmux tooling | `~/.local/bin/{dev,tmux-dev-layout,tmux-ctl}`, tests in `~/.local/share/tmux-tools/tests/` |
| tmux-orchestrator skill | `~/.claude/skills/tmux-orchestrator/SKILL.md` (window table) |
| Agent Board | `~/.local/share/tmux-dash/{server.py,index.html}`, tests in `~/.local/share/tmux-dash/tests/` |
| Hooks | `~/.claude/hooks/artifact-register.sh`, registered in `~/.claude/settings.json` |
| Ideas | `~/.claude/ideas/<project>.md` |
| Runtime state | the tmux-ctl state dir, `$STATE = ${TC_STATE:-$TMPDIR/tmux-ctl-$UID}` |

`<project>` is the tmux session name that `dev` derives from the git top level.

Every modified file gets a `.bak` copy before its first edit, as in the 2026-10-15 reliability work.

## 1. Handoff relay

### Flow

1. The context guard (`~/.claude/hooks/context-size-guard.sh`) still warns at 300k tokens and recommends `/handoff`. It is unchanged.
2. The user runs `/handoff "<focus>"`. It stays user-only (`disable-model-invocation: true`). The skill gains these steps:
   1. **Checkpoint.** Send each teammate a checkpoint request. Each finishes or pauses its current step and replies with a state note: name, role, model tier, current task, files owned, progress, next step, assumptions.
   2. **Timeout.** A teammate with no reply after 2 minutes is recorded as `no checkpoint`, with the last 40 lines of its window (`tmux-ctl read`).
   3. **Write the doc** to `~/.claude/handoffs/YYYY-MM-DD-<slug>.md`. Beyond today's content, it contains:
      - a **Team** section, one entry per teammate built from the notes;
      - the old session id;
      - a link to the ideas file (never its contents).
   4. **Register** the doc as an artifact (kind `handoff`).
   5. **Shut down** each teammate with a `shutdown_request` that carries the ToolSearch schema hint.
   6. **Ask the user** with AskUserQuestion: "Switch to a fresh orchestrator now?" (Yes / Not yet). This step is never skipped. On "Not yet", it prints the doc path and the `tmux-ctl relay` command and stops.
   7. On Yes, run `tmux-ctl relay <doc>`.
3. **`tmux-ctl relay <doc>`**:
   1. It detaches (`tmux run-shell -b`) and polls the `claude` pane every 2 seconds, with a 120-second cap. The turn has ended once the board's `classify` reports `idle` or `ready` for two polls in a row. `classify` moves into a small shared module so the board and `tmux-ctl` use the same logic.
   2. It respawns the pane in place (`respawn-pane -k`) running `claude-orchestrator "Read <doc> and continue from where the previous session left off."`.
   3. It appends `{ts, old_session_id, doc, pane}` to `$STATE/lineage-<project>.jsonl`. The new session id is filled in by the artifact hook on the new lead's first tool call.
   4. The restart logic is shared with the board's `restart_orchestrator`: one implementation, called from both places.
4. **New lead.** A new rule in `orchestrator.md`: when the first prompt names a handoff doc that has a Team section, the lead respawns each teammate with:
   - the same name, role and tier;
   - its state note at the top of its prompt;
   - the standard teammate rules.

   It then continues with the plan. A teammate marked `no checkpoint` is respawned with its last output and told to re-check its files before going on.

### Failure handling

- If the relay can't respawn the pane, the old session is still alive and the relay prints the doc path and a manual `claude-orchestrator` command.
- If the turn-end poll times out, the relay doesn't respawn. It reports that the lead is still busy.
- The previous session stays resumable with `claude --resume <old_session_id>`. The doc records that id.

## 2. Artifacts panel

### Registration

- A new PostToolUse hook, `~/.claude/hooks/artifact-register.sh`, matches `Write|Edit|Artifact`. For a file whose path matches a rule below, it appends an entry to `$STATE/artifacts-<project>.jsonl`:

  `{ts, path, kind, agent, hash, session_id}`

  - `agent` is the tmux window name of `$TMUX_PANE`, e.g. `claude` or `✦ impl`.
  - `hash` is the sha256 of the file after the write.
  - For an Artifact publish, the entry has `url` in place of `hash`.

- Path rules:

  | Kind | Paths |
  | --- | --- |
  | `plan` | `docs/superpowers/plans/**` |
  | `spec` | `docs/superpowers/specs/**` |
  | `handoff` | `~/.claude/handoffs/**`, `$TMPDIR/**handoff*.md` |
  | `report` | scratchpad `**/*report*.md` |
  | `published` | Artifact tool publishes |
  | `other` | registered by hand with `tmux-ctl artifact <path> [--kind K]` |

- The hook never blocks and always exits 0. It does nothing outside tmux.
- Manifests are deleted when the tmux session ends (a `session-closed` tmux hook).

### Server (`server.py`)

- `GET /artifacts?session=<project>` returns manifest entries grouped by path (latest entry plus change history) and the lineage chain.
- `GET /artifact?session=<project>&path=<p>` returns `{text, hash}`.
  - It serves **only** paths present in that session's manifest. Anything else is a 404.
  - `published` entries are links, not served.
- `POST /action {action: "save", session, path, base_hash, text}`:
  - It writes the file only if its current hash equals `base_hash`, and returns 409 with the current text otherwise.
  - A successful save adds a manifest entry with `agent: "you"`.
- `POST /action {action: "comment", session, path, anchor, quote, note}`:
  - It queues the comment in server memory, per session.
  - It delivers it with `send-keys` to the `claude` pane as one line: `[Plan comment] <file> § <anchor>: "<quote>" — <note>`.
  - It delivers only when the lead's status (from `classify`) is not `waiting`. A pending prompt must never receive typed keys.
  - Queued comments are retried each `/state` poll and shown as pending in the page.
- All of these use the existing token and `Host` guard.

### Page (`index.html`)

- **Layout:** a left sidebar with a ◀/▶ toggle. The collapsed state is kept in `localStorage`, wrapped in try/catch.
- **Pinned at the top:**
  - **Plan**: the newest `plan` entry in the current chain.
  - **Ideas**: section 3.
- **Below:** artifacts grouped by session along the lineage chain, newest session first. Each item has a kind icon, an agent badge and an "updated" dot.
- **Viewer:** markdown rendered by a vendored library served from the board's own directory (no CDN at runtime).
- **What changed:**
  - The page keeps the text you last viewed in memory and highlights added and changed lines against it.
  - Each changed block is tagged with the agent from the manifest entry that produced it.
- **Edit:**
  - Inline editing. Saving sends `base_hash`.
  - On a 409 it shows the agent's version beside yours, with **Reload**, **Overwrite** (resend with the new hash) and **Copy mine**.
- **Comment:** select text, add a note and send. Pending comments show until they're delivered.
- **Lifetime:**
  - The artifact list lives in page memory and keeps growing across handoffs for as long as the page is open.
  - On load or refresh it is seeded with only the current lead's artifacts: its plan, its spec, and the handoff doc it started from.
  - Closing the browser or refreshing drops older sessions' items.
  - Ideas are always read from their file.

## 3. Ideas inbox

### Capture

- **Board:** the pinned Ideas box has a one-line input and an optional detail field, sent with `POST /action {action: "idea", session, text, detail}`.
- **CLI:** `tmux-ctl idea "<text>"`.
- **Chat:** a user message to the lead starting with `idea:`. The lead appends it with `tmux-ctl idea`, replies "noted for later" in one line, and does not act on it.
- **Storage:** `~/.claude/ideas/<project>.md`.
  - Each idea is `- [ ] YYYY-MM-DD HH:MM · <text>`, with detail as indented lines below.
  - All writers append under an exclusive lock (`flock` or `fcntl.lockf`) on `<file>.lock`.

### Isolation

- No hook, message or prompt injects ideas into any agent's context.
- `orchestrator.md` says the lead does not read the ideas file while a plan is in progress. Teammate prompts never mention it.
- The handoff doc links to the file and does not copy it.

### Next steps round

- **Trigger:** all plan tasks are completed and `finishing-a-development-branch` has run. The lead then reads the open (`[ ]`) ideas.
- **Round:**
  1. The lead groups related ideas and notes which ones overlap with the work just finished.
  2. It proposes *brainstorm now*, *park* or *drop* for each group, using AskUserQuestion.
  3. Each group the user picks goes through `brainstorming`, one at a time.
- **Markers:**
  - Ideas taken up become `- [x] … → <spec path>`.
  - Dropped ideas become `- [-] …`.
  - Ideas are never deleted.

### Board cues

- The Ideas header shows the number of open ideas.
- When every task in the current plan is checked (`- [x]` checkboxes in the plan file), the Plan item reads **"Plan done · N ideas ready for next steps"**.

## 4. Hidden agent session and Activity drawer

### tmux layout

- **New sessions:** `dev` creates only `claude` and a plain `shell` window for the user. No feed pane, watch pane or `@tc_label`.
- **Agent windows:** these live in a detached session, `<project>-bg`, created on demand by `tmux-ctl`. It holds `tests`, `shell` and their lane windows.
- **Migration:** `tmux-dev-layout` migrates an existing session idempotently:
  - it moves `tests` to `-bg` (`move-window`);
  - it kills feed/watch panes (`@tc_role` feed/watch) in the user's `shell`.

  Running it again changes nothing.
- **`.dev/windows`:** watch commands, if present, run in `-bg`'s `tests` window.
- **Board:** it lists `-bg` sessions nowhere (filtered like `_web-*`), except through Activity.

### tmux-ctl

- `run` and `send` targets `tests` and `shell` resolve to `<project>-bg`. Lanes are created there with today's naming. The interface and output for agents are unchanged.
- Each `run` appends to `$STATE/runs-<project>.jsonl`:

  `{id, ts, agent, cmd, cwd, exit, duration, log, summary}`

  - `log` is `$STATE/logs/<project>/<id>.log` (full output).
  - `summary` is parsed best-effort from pytest (`N passed, M failed`) and the zsh test runner, and is empty otherwise.
  - A record with `exit: null` is written at start, then replaced by the final one.
- Feed logs keep being written as today.
- `tmux-ctl list` and `read` accept `-bg` windows by their plain names.

### Board

- **New endpoints:**
  - `GET /runs?session=<project>` returns run records.
  - `GET /log?session=<project>&id=<id>` returns a log by run id only, never by path.
  - `GET /feed?session=<project>` returns the tail of the feed logs.
- **Activity drawer:** a collapsible drawer under the terminals, with two tabs.
  - **Runs:** a card per run with agent, command, time, a spinner while running, then ✔/✘ with the summary. Click for the log. **Open live** attaches a ttyd terminal to the `-bg` window while the run is going.
  - **Commands:** feed lines, filterable by agent.
- **Failures:** a failed run adds to a red count on the drawer header until the drawer is opened.
- **Lifetime:** same rule as artifacts.

### Prompt and doc updates

The window tables and rule 5 in `orchestrator.md`, `worker.md` and the tmux-orchestrator skill:
- describe `claude` + `shell` for the user and `-bg` for agents;
- say that `tmux-ctl run tests` is still the way to run suites;
- say the user sees runs in the board's Activity drawer.

## Testing

| Area | Tests |
| --- | --- |
| Relay | zsh tests for `tmux-ctl relay` in a scratch tmux server (`-L`): waits for turn end, respawns in place, writes lineage, leaves the old pane alone on failure; a live dry run with a stub `claude-orchestrator` |
| Handoff skill | a live run in a scratch session with two haiku teammates: checkpoint notes, doc Team section, confirmation asked, team respawned by the new lead |
| Artifact hook | zsh tests for the path rules, agent naming from `$TMUX_PANE`, exit 0 on every input |
| Server | Python tests: artifact path allowlist, 409 on hash mismatch, comment held while `waiting` and sent otherwise, idea lock with two concurrent writers, `/log` by id only, `-bg` hidden from sessions |
| Layout | updated `~/.local/share/tmux-tools/tests` (incl. `test_ctl_panes`), migration idempotence, run records |
| Page | a live check in Chrome against a scratch session: sidebar toggle, seed on load, accumulation across a relay, diff highlight with agent badge, edit conflict, comment delivery, Ideas box, Activity runs |

## Out of scope

- Keeping teammate processes alive across a handoff. They are checkpointed and respawned.
- Multi-user or remote access to the board. It stays 127.0.0.1 with a token.
- Ticking or reordering plan tasks from the panel.
- A tmux-side artifacts view.
