#!/usr/bin/env bash
# PreToolUse(Agent): in a dev lead, deny an Agent call that has no name, or a fork, so every agent the lead starts opens
# in its own ✦ window where the user can watch it. The lead marker AGENT_BOARD_LEAD=1 is exported only by
# bin/claude-orchestrator into the lead's own process (never the tmux session environment), so teammates, tmux-ctl agent
# workers and the overseer are never checked. Kill switch: AGENT_NAME_GUARD=0. --scoped (the plugin registration) is
# accepted and changes nothing. Fail-open on any parse or runtime error.
[[ "$AGENT_NAME_GUARD" == 0 || "$AGENT_BOARD_LEAD" != 1 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
verdict=$(printf '%s' "$input" | python3 -I -c 'import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "Agent" or not isinstance(ti, dict):
        print("allow")
    else:
        n = ti.get("name")
        bad = not isinstance(n, str) or not n.strip() or ti.get("subagent_type") == "fork"
        print("deny" if bad else "allow")
except Exception:
    print("allow")' 2>/dev/null) || exit 0
[[ "$verdict" == deny ]] || exit 0
printf '%s\n' "Give this agent a name (the Agent tool's name parameter) so it opens in its own ✦ window where the user can watch it. Dev leads never run agents hidden in the background: read-only lookups (Explore, web-fetch, claude-code-guide) and reviewers included. A fork (subagent_type \"fork\") is never allowed, named or not, because it never opens a window. If the teammate's window fails to spawn, retry once, then tell the user the error and wait; never fall back to an unnamed agent. (Kill switch for the user: AGENT_NAME_GUARD=0.)" >&2
exit 2
