#!/usr/bin/env bash
# PostToolUse(Agent) hook, async: one line per teammate/subagent spawn in spawns.jsonl
# {ts, lead_session, name, subagent_type, model, tier, reason}. Fails open.
out="${AGENT_BOARD_SPAWNS:-$HOME/.local/state/agent-board/spawns.jsonl}"
payload=$(cat)
src=$(cat <<'PY'
import json, os, re, sys, time
try:
    d = json.loads(sys.stdin.read())
    if d.get("tool_name") != "Agent":
        sys.exit(0)
    i = d.get("tool_input") or {}
    model = i.get("model") or "inherit"
    tier = None
    try:
        with open(os.path.join(d.get("cwd") or ".", "docs/superpowers/model-routing.json")) as f:
            rm = json.load(f)
        tier = next((k for k, v in rm.items() if v == model), None)
    except Exception:
        pass
    m = re.search(r"^Reason:\s*(.+)$", i.get("prompt") or "", re.M)
    rec = {"ts": int(time.time()), "lead_session": d.get("session_id"), "name": i.get("name"),
           "subagent_type": i.get("subagent_type"), "model": model, "tier": tier,
           "reason": m.group(1).strip() if m else None}
    os.makedirs(os.path.dirname(sys.argv[1]), exist_ok=True)
    with open(sys.argv[1], "a") as f:
        f.write(json.dumps(rec) + "\n")
except Exception:
    pass
PY
)
printf '%s' "$payload" | python3 -I -c "$src" "$out" 2>/dev/null
exit 0
