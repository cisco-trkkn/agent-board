#!/usr/bin/env bash
# PostToolUse(TaskUpdate): at a spec boundary in queue mode, tell the lead to hand off before the next spec
# (docs/superpowers/specs/2026-11-20-efficiency-now-design.md §1). It speaks only when the update sets status
# "completed" on a task whose subject starts "Plan & run:" and the session's task folder
# (${SPEC_NUDGE_TASKS_DIR:-~/.claude/tasks}/session-<first 8 of session_id>/) still holds a pending "Plan & run:" task.
# Read-only, never blocks. Fail-open: any error, a missing folder or a malformed payload exits 0 with nothing printed.
# Delivery: stateless, so a repeated or concurrent delivery prints the same advice again; order does not matter.
# --scoped (the plugin registration) is accepted and changes nothing.
input=$(cat) || exit 0
printf '%s' "$input" | python3 -I -c 'import glob, json, os, re, sys
PREFIX = "Plan & run:"
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "TaskUpdate" or not isinstance(ti, dict) or ti.get("status") != "completed":
        sys.exit(0)
    sid, tid = d.get("session_id"), str(ti.get("taskId") or "")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid) or not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
        sys.exit(0)
    root = os.environ.get("SPEC_NUDGE_TASKS_DIR") or os.path.join(os.path.expanduser("~"), ".claude", "tasks")
    folder = os.path.join(root, "session-" + sid[:8])

    def task(path):
        try:
            with open(path) as f:
                t = json.load(f)
            return t if isinstance(t, dict) else {}
        except (OSError, ValueError):
            return {}
    if not str(task(os.path.join(folder, tid + ".json")).get("subject") or "").startswith(PREFIX):
        sys.exit(0)
    pending = False
    for p in glob.glob(os.path.join(folder, "*.json")):
        t = task(p)
        if str(t.get("id")) != tid and t.get("status") == "pending" and str(t.get("subject") or "").startswith(PREFIX):
            pending = True
            break
    if pending:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
              "Spec boundary: hand off now (agent-board:handoff) before the next Plan & run task."}}))
except Exception:
    pass
' 2>/dev/null
exit 0
