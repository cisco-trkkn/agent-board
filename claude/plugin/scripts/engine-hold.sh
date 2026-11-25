#!/usr/bin/env bash
# PreToolUse(*): approval holds for engine workers (engine spec section 13). Outside an engine worker it does nothing.
# Inside one it runs engine/bin/hold.js, which denies a stop-class call until the user approves it once.
# --scoped (the plugin registration) is accepted and changes nothing.
[[ -n "$ENGINE_JOB" ]] || exit 0
deny() { printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"engine hold unavailable: %s; report status blocked"}}\n' "$1"; exit 0; }
repo="$AGENT_BOARD_REPO"
if [[ -z "$repo" ]]; then
  self="$(python3 -I -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "${BASH_SOURCE[0]}" 2>/dev/null)" || deny "cannot resolve the script path"
  repo="$(cd "$(dirname "$self")/../../.." && pwd)"
fi
[[ -f "$repo/engine/bin/hold.js" ]] || deny "no $repo/engine/bin/hold.js"
command -v node >/dev/null 2>&1 || deny "no node on PATH"
exec node --no-warnings "$repo/engine/bin/hold.js"
