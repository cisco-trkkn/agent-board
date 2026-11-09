# Dev leads never run agents hidden in the background

Date: 2026-11-09 · Status: approved design (user, 2026-11-09)
Source: the user, relayed by the interiors lead: "agents should not be run in the background, why has this been
happening" and "send this to the agent board lead and tell it to queue the spec". Queued (regroup-style) after
`2026-11-05-queue-keep-awake-design.md`.

## Problem

In a `dev` session the lead is meant to start every agent as a named teammate in its own `✦` window, where the user
can watch it. Two things in the interiors project broke that:

1. The lead made an Agent call with no `name` (an Explore lookup). The harness ran it as a hidden background
   subagent.
2. After two teammate spawns failed ("respawn pane failed: fork failed: Device not configured"), the lead ran its
   reviews as background agents on its own, without retrying or telling the user.

`claude/orchestrator.md` only says plan seats are "teammates in named windows, not background subagents"; it says
nothing about agents outside a plan or about a failed spawn. The PreToolUse `Agent` hook
(`claude/plugin/scripts/sdd-call-guard.sh`) only checks the subagent-driven-development Skill call.

## User decisions (2026-11-09)

- No exemptions: every Agent call a dev lead makes must carry a `name`, read-only helpers (Explore, web-fetch,
  claude-code-guide) included.
- Integration: merge to `main` locally, no push.

## Design

### 1. Lead marker

`bin/claude-orchestrator` exports `AGENT_BOARD_LEAD=1` into its own environment before `exec claude`. It does NOT
set it in the tmux session environment (`tc_tmux set-environment`), so teammates (which inherit the tmux session
environment), `tmux-ctl agent` workers and the overseer (`bin/claude-overseer`) never see it. Hooks of the lead
process inherit it.

### 2. Guard: `claude/plugin/scripts/agent-name-guard.sh`

Registered in `claude/plugin/hooks/hooks.json` under the existing `PreToolUse` `"matcher": "Agent"` entry, after
`sdd-call-guard.sh`, with `--scoped` and `"timeout": 10` like its neighbours.

- `AGENT_NAME_GUARD=0` → allow (kill switch). `AGENT_BOARD_LEAD` not `1` → allow.
- Reads the hook JSON from stdin. `tool_name` not `Agent` → allow.
- Deny (exit 2, reason on stderr) when `tool_input.name` is missing, not a string, or blank after trimming, or when
  `tool_input.subagent_type == "fork"` (a fork never opens a window, named or not).
- Any parse or runtime error → allow (fail-open, like the other guards).
- Reason text (one paragraph): give the agent a `name` so it opens in its own `✦` window; dev leads never run agents
  hidden in the background, read-only lookups and reviewers included; a fork is never allowed; if the window spawn
  fails, retry once, then tell the user and wait — never fall back to an unnamed agent. Ends with
  `(Kill switch for the user: AGENT_NAME_GUARD=0.)`.

### 3. Rules: `claude/orchestrator.md`

In "Default: use an agent team", two bullets:

- Every agent you start gets a `name`, so it opens in a `✦` window: read-only lookups (Explore, web-fetch,
  claude-code-guide) and reviewers included. Never start a fork. The `agent-name-guard` hook enforces this.
- If a teammate's window fails to spawn, retry once; if it fails again, tell the user with the error and wait. Never
  fall back to an unnamed background agent.

The live checkout holds an uncommitted user edit of `claude/orchestrator.md`: carry it across the merge as a
dry-run-checked patch (as earlier queue items did).

## Testing

- Unit tests for the script, in the style of the existing guard tests (`tools/tests/test_sdd_call_guard.zsh` or
  `claude/hooks/tests/`): marker unset → allow; marker set: name present → allow; name missing / `""` / `"  "` /
  non-string → deny with the reason; `subagent_type: "fork"` with a name → deny; kill switch → allow; malformed JSON →
  allow; `tool_name` other than Agent → allow. `tools/tests/test_plugin.zsh` asserts the hooks.json registration.
- `bin/claude-orchestrator`: a test that the exec'd environment carries `AGENT_BOARD_LEAD=1` and that the tmux
  session environment does not.
- One real run (scratch tmux `-L <sock> -f /dev/null`, temp state): a lead started through `claude-orchestrator`
  with this worktree's plugin makes an unnamed Agent call → denied with the reason in the pane; a named one → a
  `✦ <name>` window opens; that teammate's environment has no `AGENT_BOARD_LEAD`
  (`tmux show-environment` and the teammate's own `env`). Recorded in `tools/tests/e2e-lead-named-agents.md`.
- Targeted runs only; never the full suites.

## Not in scope

Teammates or workers dispatching agents (`claude/worker.md` already forbids it); the overseer; the cause of the
"fork failed: Device not configured" spawn error.
