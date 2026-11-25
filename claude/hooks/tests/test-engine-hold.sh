#!/bin/bash
# Test for engine-hold.sh. Isolation: stub node on PATH for the guard tests; the end-to-end cases build their
# database in a temp ENGINE_DIR and run in a `git init` temp worktree; the real engine directory is leak-checked.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
H="${HOOK:-$HERE/../engine-hold.sh}"
ROOT="$(cd "$HERE/../../.." && pwd)"
T=$(mktemp -d)
pass=0; fail=0
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1: expected '$3', got '$2'"; fail=$((fail+1)); fi; }
REAL_ENGINE="$HOME/.local/state/agent-board/engine"
before="$(ls -la "$REAL_ENGINE" 2>/dev/null | md5 -q 2>/dev/null || ls -la "$REAL_ENGINE" 2>/dev/null | cksum)"

# stub node: marks its call, logs argv and stdin
mkdir -p "$T/stub"
cat > "$T/stub/node" <<STUB
#!/bin/sh
touch "$T/marker"
printf '%s\n' "\$*" > "$T/argv"
cat > "$T/stdin"
STUB
chmod +x "$T/stub/node"

out=$(printf '{}' | env -u ENGINE_JOB PATH="$T/stub:$PATH" AGENT_BOARD_REPO="$ROOT" bash "$H" --scoped 2>&1); rc=$?
check "no ENGINE_JOB: exit 0" "$rc" "0"
check "no ENGINE_JOB: no output" "$out" ""
check "no ENGINE_JOB: node not spawned" "$([ -e "$T/marker" ] && echo yes || echo no)" "no"

out=$(printf '{"a":1}' | ENGINE_JOB=J PATH="$T/stub:$PATH" AGENT_BOARD_REPO="$ROOT" bash "$H" --scoped 2>&1); rc=$?
check "ENGINE_JOB set: exit 0" "$rc" "0"
check "ENGINE_JOB set: node gets --no-warnings and hold.js" "$(cat "$T/argv" 2>/dev/null)" "--no-warnings $ROOT/engine/bin/hold.js"
check "ENGINE_JOB set: node gets stdin" "$(cat "$T/stdin" 2>/dev/null)" '{"a":1}'

# repo resolved from the script's real path when AGENT_BOARD_REPO is unset
rm -f "$T/argv"
printf '{}' | env -u AGENT_BOARD_REPO ENGINE_JOB=J PATH="$T/stub:$PATH" bash "$H" >/dev/null 2>&1
check "no AGENT_BOARD_REPO: repo is three dirs above the real script" "$(cat "$T/argv" 2>/dev/null)" "--no-warnings $ROOT/engine/bin/hold.js"

# fail closed inside an engine worker
out=$(printf '{}' | ENGINE_JOB=J AGENT_BOARD_REPO="$T/nowhere" bash "$H" 2>&1)
check "missing hold.js: deny with reason" "$(printf '%s' "$out" | python3 -I -c 'import json,sys; d=json.load(sys.stdin)["hookSpecificOutput"]; print(d["permissionDecision"], d["permissionDecisionReason"].startswith("engine hold unavailable: "), d["permissionDecisionReason"].endswith("; report status blocked"))')" "deny True True"
mkdir -p "$T/nonode"
NODE_DIR="$(dirname "$(command -v node)")"
out=$(printf '{}' | ENGINE_JOB=J AGENT_BOARD_REPO="$ROOT" PATH="/usr/bin:/bin" bash "$H" 2>&1)
if PATH="/usr/bin:/bin" command -v node >/dev/null 2>&1; then echo "SKIP missing node (node lives in /usr/bin)"; else
check "missing node: deny" "$(printf '%s' "$out" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"])')" "deny"; fi

# end to end with the real node
EDIR="$T/engine"; WT="$T/wt"; mkdir -p "$EDIR" "$WT"; git init -q "$WT"
TC_ENGINE_DIR="$EDIR" node --no-warnings -e '
const db=require(process.argv[1]+"/engine/lib/engine/db");
const d=db.open("p");
const seed=(table,row,spec)=>db.tx(d,()=>{db.put(d,table,row);db.event(d,{spec,kind:"seed_"+table,rows:[{table,row}]});});
seed("specs",{id:"S",state:"running",worktree:process.argv[2]},"S");
seed("jobs",{id:"J",spec:"S",kind:"implement",state:"running"},"S");
d.close();' "$ROOT" "$WT"
e2e() { printf '{"tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"%s","session_id":"s1"}' "$1" "$WT" |
  ENGINE_JOB=J ENGINE_PROJECT=p ENGINE_DIR="$EDIR" ENGINE_WORKTREE="$WT" AGENT_BOARD_REPO="$ROOT" bash "$H" --scoped 2>&1; }
out="$(e2e 'git push')"
check "e2e git push: permissionDecision deny" "$(printf '%s' "$out" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecision"])')" "deny"
check "e2e git push: reason starts with 'held for approval '" "$(printf '%s' "$out" | python3 -I -c 'import json,sys; print(json.load(sys.stdin)["hookSpecificOutput"]["permissionDecisionReason"].startswith("held for approval "))')" "True"
out="$(e2e 'git status')"
check "e2e git status: empty stdout" "$out" ""

after="$(ls -la "$REAL_ENGINE" 2>/dev/null | md5 -q 2>/dev/null || ls -la "$REAL_ENGINE" 2>/dev/null | cksum)"
check "leak check: real engine directory listing unchanged" "$after" "$before"
rm -rf "$T"
echo "pass=$pass fail=$fail"
[ "$fail" -eq 0 ]
