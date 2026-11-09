# e2e: lead named agents (real run and transcript check)

- Date: 2026-11-09
- Worktree: `/Users/francisco.ruiz/agent-board/.claude/worktrees/lead-named-agents` (branch `feat/lead-named-agents`)
- Plugin path used: `/Users/francisco.ruiz/agent-board/.claude/worktrees/lead-named-agents/claude/plugin` (loaded through this worktree's `bin/claude-orchestrator`; the pane's hook error names `…/lead-named-agents/claude/plugin/scripts/agent-name-guard.sh`)
- Scratch tmux: `~/.local/bin/tmux -L e2e10 -f /dev/null`, session `e2e`, temp `TC_STATE`. The live `dev` session was not touched.

## Denied unnamed call

Start (scratch window `e2e:lead`):

    cd <worktree> && TC_STATE=<tmp> bin/claude-orchestrator --model haiku

Prompt (send-keys text, 1 s, separate Enter):

    Use the Agent tool with subagent_type Explore and NO name parameter to list files in bin/. Do not retry with a name.

Captured pane (`capture-pane -p -t e2e:lead`), relevant lines:

    ⏺ Explore(List files in bin/)
      ⎿  Initializing…
      ⎿  Error: PreToolUse:Agent hook error: ["/Users/francisco.ruiz/agent-board/.claude/worktrees/lead-named-agents/claude/plugin/scripts/agent-name-guard.sh" --scoped]: Give this agent a name (the Agent
         tool's name parameter) so it opens in its own ✦ window where the user can watch it. Dev leads never run agents hidden in the background: read-only lookups (Explore, web-fetch, claude-code-guide)
         and reviewers included. A fork (subagent_type "fork") is never allowed, named or not, because it never opens a window. If the teammate's window fails to spawn, retry once, then tell the user the
         error and wait; never fall back to an unnamed agent. (Kill switch for the user: AGENT_NAME_GUARD=0.)
         This hook comes from the agent-board@inline plugin.

The call was denied before the agent ran, with the guard's reason shown. The lead's own reply then listed options and did not retry unnamed.

## Named call opens a window

Prompt:

    Use the Agent tool with name "probe1", subagent_type general-purpose, prompt "run env and reply with the AGENT_BOARD_LEAD line or NONE".

Form observed: **no `✦ probe1` window** (the `-f /dev/null` scratch server lacks the agent-board tmux hooks), so the pass condition from the brief applies: a teammate pane exists for `probe1` on the scratch server.

    $ tmux -L e2e10 list-windows -a
    e2e:0: lead* (2 panes) [200x50]
    $ tmux -L e2e10 list-panes -a -F '#{pane_id} pid=#{pane_pid} title=#{pane_title}'
    %0 pid=29732 title=✳ Agent Explore bin directory listing
    %1 pid=31383 title=✳ general-purpose

The lead's pane list in Claude Code showed `◯ probe1  Probe AGENT_BOARD_LEAD env line`; its own `env` answer: `AGENT_BOARD_LEAD` "is not set in this session's environment" (checked with `env | grep '^AGENT_BOARD_LEAD='`).

Process environments (`ps eww -o command= -p <pid>`, counting `^AGENT_BOARD_LEAD=` words; each env was readable: `TMUX=` present in both):

    lead     pid 29732 (claude --settings …/claude/session-settings.json --plugin-dir …): AGENT_BOARD_LEAD count = 1
    probe1   pid 31383 (--agent-id probe1@session-de2ab341 --agent-name probe1 …):       AGENT_BOARD_LEAD count = 0
    tmux -L e2e10 show-environment -g        | grep -c AGENT_BOARD_LEAD  -> 0
    tmux -L e2e10 show-environment -t e2e    | grep -c AGENT_BOARD_LEAD  -> 0

Result: the lead's process has the marker, the probe1 teammate process, its own `env` and the tmux global and session environments lack it.

## Real transcripts

Read-only. Globs: `~/.claude/projects/*/*.jsonl` and `~/.claude/projects/*/*/subagents/*.jsonl`. Scanner (scratchpad, run with `python3 -I`) takes every `tool_use` block named `Agent` in each line's `message.content`, feeds `{"tool_name":"Agent","tool_input":<input>}` to `claude/plugin/scripts/agent-name-guard.sh --scoped` with `AGENT_BOARD_LEAD=1` (exit 2 = deny), and compares with an independent predicate: `name` missing, non-string or blank, or `subagent_type == "fork"`.

    $ python3 -I scan.py x <worktree>/claude/plugin/scripts/agent-name-guard.sh
    files scanned: 2571
    Agent calls found: 1448
    guard denies: 182
    predicate count: 182
    mismatches: 0

Counts are uncapped. The transcripts include this run's own sessions, so the totals were taken at the time of this run and drift upward.

Cleanup: `tmux -L e2e10 kill-server`; afterwards `ps -axo pid,command | grep -a e2e10` shows only the e2e10 teammate's own process (pid 28789, the agent running this task); the scratch lead (29732) and probe1 (31383) are gone.
