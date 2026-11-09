# Remote access: every dev lead joins Remote Control

Date: 2026-11-09 · Status: approved design (user, 2026-11-09)
Source: the user: "how can I leave my computer lid open at my office and still access agent board remotely… avoid
ssh'ing", then "i need to be able to guide the agents in different projects not just get an overview". Queued
(regroup-style) after `2026-11-09-lead-named-agents-design.md`.

## Problem

The board binds `127.0.0.1` with a token in the path and a Host allowlist (`board/server.py`), so it is reachable
only from the Mac. The earlier remote spec (branch `docs/remote-ipad-spec`,
`docs/superpowers/specs/2026-11-02-remote-ipad-control-design.md`) chose Tailscale Serve; the user cannot use
Tailscale. The user wants to guide each project's agents from a phone or another computer while the Mac sits at the
office with the lid open, without ssh.

## User decisions (2026-11-09)

- Claude Code Remote Control is allowed on the user's login (checked: `/remote-control` connects).
- Only dev leads join Remote Control: one entry per project in the Claude app. Teammates, `tmux-ctl agent` workers
  and the overseer stay off; the user guides teammates through their lead.
- No cross-project overview page: the Claude app's session list is the overview.
- Out of scope: Tailscale, tunnels, exposing the board, teammates in the app.
- Integration: queue default (merge to `main` locally, no push).

## Remote Control facts this design relies on

From https://code.claude.com/docs/en/remote-control.md (researched 2026-11-09):

- `claude --remote-control "<name>"` (`--rc`) starts a session already connected; the remote title is `<name>`.
- The remote side (claude.ai/code, Claude iOS/Android) can send messages, answer permission prompts and
  AskUserQuestion (both wait until answered), stop subagents, run `/compact`, `/clear`, `/context`, `/usage`.
- Outbound HTTPS only. The Mac and the process must stay up; it reconnects after sleep or a network drop, but about
  30 min of failed heartbeats disconnects it until `/remote-control` is run again in that session.
- `--continue` / `--resume` reconnect; `/clear` keeps the connection.
- Blocked by: an off org toggle (Team/Enterprise Owner), managed `disableRemoteControl`, API-key/Bedrock/Vertex
  auth, a custom base URL, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.
- No documented way for a script to read whether a session is connected right now.

## Design

### 1. `bin/claude-orchestrator` adds `--rc "<project>"`

- `<project>` is the same key the ideas and context files use: the tmux session group, else the session name
  (`#{?session_group,#{session_group},#{session_name}}`, as `bin/tmux-ctl` computes `FEEDKEY`). Outside tmux, the
  basename of the current directory (`${PWD:t}`).
- Added unless: `TC_REMOTE_CONTROL=0`; or the caller already passed `--rc`, `--remote-control` or
  `--remote-control=*` (the caller's wins, no duplicate flag).
- Placed before `"$@"` in both `exec claude` lines, so `claude-orchestrator --continue` reconnects under the same
  name.
- Teammates, workers and the overseer do not start through `claude-orchestrator`, so they stay off; nothing is
  written to `~/.claude/settings.json` (`remoteControlAtStartup` stays unset).
- Spec 10 (`AGENT_BOARD_LEAD=1`) also edits this file; this spec's plan is written after spec 10 merges and builds on
  its version.

### 2. Board badge `rc`

The pane the board shows as a session's lead (the claude pane in its `claude` window) shows `rc` when the lead's claude process command line contains `--rc` or
`--remote-control` (read with `ps -o args= -p <pid>` for the pane's process, inside the existing per-pane
classification pass; one `ps` call per refresh for all lead panes, not one per pane). Tooltip: "started with Remote
Control (connection state not visible to the board)". No badge for any other pane.

### 3. Docs: `docs/INSTALL.md` section "Remote access"

- One-time setup: the org toggle (Owner, claude.ai/admin-settings/claude-code) if refused; the first
  "Enable Remote Control" confirmation, done once at the Mac.
- At the office: lid open, Mac on mains power, keep-awake via `tmux-ctl awake on` (spec 9); on battery the Mac
  will eventually sleep.
- Find each project as `<project>` in claude.ai/code or the Claude app.
- Known limits: a lead disconnected for ~30 min needs `/remote-control` in that session (from another connected
  lead: `tmux-ctl` can type it into that lead's window); a message sent while the session shows "Connecting" may
  sit in the app until it connects; `TC_REMOTE_CONTROL=0` turns it off.

## Error handling

- `claude` refuses `--rc` (org toggle off, policy): Claude Code prints its own message and the session still starts
  locally; `claude-orchestrator` adds nothing on top. The INSTALL section names the cause.
- Session name collisions (two dev sessions in one project): both are titled `<project>`; acceptable, the app
  lists both.

## Testing

- `tools/tests/test_claude_orchestrator_rc.zsh` (stub `claude` on a temp PATH that prints its argv; scratch tmux
  server started with `-f /dev/null`): `--rc <group>` inside a grouped session, `<session>` in an ungrouped one,
  `${PWD:t}` outside tmux; absent with `TC_REMOTE_CONTROL=0`; not duplicated when the caller passes `--rc x` or
  `--remote-control=x`; `--continue` keeps it; `--model` handling and `--append-system-prompt-file` unchanged.
- Board: a unit test for the badge on a lead pane whose args contain `--rc`, none without, none on a teammate pane;
  `ps` called once per refresh.
- Only these targeted tests run (user rule: never the full suites).
- User gate (unchecked checklist in `tools/tests/e2e-remote-access.md`, not run by agents): start a `dev` session;
  see `<project>` in the Claude app; send a message after it shows connected and see it arrive; answer a permission
  prompt from the phone; `/clear` remotely and confirm it stays connected; restart with `claude-orchestrator
  --continue` and see the same name reconnect.
