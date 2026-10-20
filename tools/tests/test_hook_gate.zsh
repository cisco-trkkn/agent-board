# test_hook_gate.zsh — each hook acts exactly once whether registered scoped (--scoped, AGENT_BOARD=1),
# legacy-global (no flag), or both. Hooks under test are the repo's own copies.
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"; H="$R/claude/hooks"; F="${0:A:h}/fixtures"
tt_setup
mlog="$TC_STATE/feed-tt-tests.log"; alog="$TC_STATE/artifacts-tt.jsonl"
unset AGENT_BOARD

# --- bash-mirror: entries in the tests feed
mirror() { sed "s|__HOME__|$HOME|" "$F/ok.json" | "$H/bash-mirror.sh" "$@"; }
entries() { [[ -f "$1" ]] && grep -c '^── ' "$1" || print 0 }
rm -f $mlog; AGENT_BOARD=1 mirror --scoped
check "mirror: scoped, AGENT_BOARD=1 -> 1 entry"     test "$(entries $mlog)" = 1
rm -f $mlog; mirror
check "mirror: legacy, no AGENT_BOARD -> 1 entry"    test "$(entries $mlog)" = 1
rm -f $mlog; AGENT_BOARD=1 mirror; AGENT_BOARD=1 mirror --scoped
check "mirror: both registrations -> 1 entry"        test "$(entries $mlog)" = 1
rm -f $mlog; sed "s|__HOME__|$HOME|" "$F/tmuxctl.json" | AGENT_BOARD=1 "$H/bash-mirror.sh" --scoped
check "mirror: tmuxctl fixture still skipped"        test "$(entries $mlog)" = 0

# --- artifact-register: manifest lines
mkdir -p "$TT_DIR/docs/superpowers/plans"; plan="$TT_DIR/docs/superpowers/plans/p.md"; print x > $plan
write_json() { python3 -I -c 'import json,sys; print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"Write","session_id":"s","tool_input":{"file_path":sys.argv[1]}}))' "$plan" 2>/dev/null }
areg() { write_json | "$H/artifact-register.sh" "$@" }
lines() { [[ -f "$alog" ]] && wc -l < "$alog" | tr -d ' ' || print 0 }
rm -f $alog; AGENT_BOARD=1 areg --scoped
check "artifact: scoped, AGENT_BOARD=1 -> 1 line"    test "$(lines)" = 1
rm -f $alog; areg
check "artifact: legacy, no AGENT_BOARD -> 1 line"   test "$(lines)" = 1
rm -f $alog; AGENT_BOARD=1 areg; AGENT_BOARD=1 areg --scoped
check "artifact: both registrations -> 1 line"       test "$(lines)" = 1
rm -f $alog; AGENT_BOARD=1 "$H/artifact-register.sh" --path "$plan" --kind plan --project tt
check "artifact: --path records under AGENT_BOARD=1" test "$(lines)" = 1
rm -f $alog; "$H/artifact-register.sh" --path "$plan" --kind plan --project tt
check "artifact: --path records without AGENT_BOARD" test "$(lines)" = 1

# --- kill-guard: blocks (exit 2) exactly once
tmp="$TT_DIR/kg"; mkdir -p "$tmp/claude/versions"; pids=()
cp /bin/sh "$tmp/claude/versions/9.9.9"; codesign --force -s - "$tmp/claude/versions/9.9.9" 2>/dev/null
"$tmp/claude/versions/9.9.9" -c 'sleep 300; :' "GATEPAT-$$" </dev/null >/dev/null 2>&1 & pids+=($!)
trap 'for p in $pids; do kill $p 2>/dev/null; done; tt_teardown' EXIT INT TERM
sleep 0.5
kg_json() { python3 -I -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]}}))' "pkill -f GATEPAT-$$" 2>/dev/null }
kg() { kg_json | "$H/kill-guard.sh" "$@" >/dev/null 2>&1; print $? }
check "kill-guard: scoped, AGENT_BOARD=1 blocks"     test "$(AGENT_BOARD=1 kg --scoped)" = 2
check "kill-guard: legacy, no AGENT_BOARD blocks"    test "$(kg)" = 2
check "kill-guard: legacy under AGENT_BOARD=1 defers" test "$(AGENT_BOARD=1 kg)" = 0
n=0; for a in "" --scoped; do [[ "$(AGENT_BOARD=1 kg $a)" == 2 ]] && (( n++ )); done
check "kill-guard: both registrations -> 1 block"    test $n = 1

# --- settings.json: scoped registration, no absolute paths
S="$R/claude/session-settings.json"
check "settings.json exists"                         test -f "$S"
check "settings.json has no absolute path"           test -z "$(grep -E '/(Users|home)/' "$S" 2>/dev/null)"
HJ="$R/claude/plugin/hooks/hooks.json"   # hook registration lives in the plugin now
check "hooks.json hooks pass --scoped"               test "$(grep -c -- '--scoped' "$HJ" 2>/dev/null)" -ge 4
check "hooks.json has no absolute path"              test -z "$(grep -E '/(Users|home)/' "$HJ" 2>/dev/null)"
tt_done
