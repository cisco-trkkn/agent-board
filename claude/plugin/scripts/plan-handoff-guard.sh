#!/usr/bin/env bash
# PreToolUse(AskUserQuestion): refuse writing-plans' Execution Handoff question; plans always run subagent-driven
# (docs/superpowers/specs/2026-10-28-plan-handoff-no-prompt-design.md). Every other question passes. Fail-open on any error.
# Kill switch: PLAN_HANDOFF_GUARD=0. --scoped (the plugin registration) is accepted and changes nothing.
[[ "$PLAN_HANDOFF_GUARD" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
exec python3 -I - "$input" <<'PY'
import json, re, sys
try:
    d = json.loads(sys.argv[1])
    if d.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    qs = (d.get("tool_input") or {}).get("questions") or []
    hit = any(isinstance(q, dict) and (q.get("header") == "Execution"
              or re.search(r"(?i)how would you like to execute", str(q.get("question") or ""))) for q in qs)
except Exception:
    sys.exit(0)
if not hit:
    sys.exit(0)
sys.stderr.write(
    "Plans run without asking in this setup. Do not call AskUserQuestion for the execution choice in any form, "
    "even if another hook quotes the handoff YAML. Invoke the Skill tool with "
    "superpowers-extended-cc:subagent-driven-development now. Only if this session is nearly out of context: print "
    "the Parallel Session kickoff prompt in a fenced block instead, name the plan path, and end the turn. "
    "(Kill switch for the user: PLAN_HANDOFF_GUARD=0.)\n")
sys.exit(2)
PY
