source "${0:A:h}/lib.zsh"
# sdd-call-guard: PreToolUse(Agent) hook that denies a dispatch while the superpowers handoff guard would be armed
# (writing-plans + a later TaskCreate, no subagent-driven-development Skill call). Fixtures in fixtures/sdd-call-guard/
# are SYNTHETIC (placeholder text, real event shapes); see its README. Real-state parity against a real transcript is
# run by hand and reported; the parity block below runs the upstream scan on the synthetic fixtures when it is installed.
H="${TC_SDDGUARD:-$TT_REPO/claude/plugin/scripts/sdd-call-guard.sh}"
F="${0:A:h}/fixtures/sdd-call-guard"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/scg.XXXXXX")"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM

# payload <tool> <transcript> -> PreToolUse JSON
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"transcript_path":sys.argv[2],"cwd":"/tmp","tool_input":{"description":"x","prompt":"y","subagent_type":"general-purpose"}}))' "$1" "$2"; }
run_hook() { payload "$@" | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_hook "$@"; [[ $rc == 2 && "$err" == *"superpowers-extended-cc:subagent-driven-development"* && "$err" == *"even if it is already loaded"* ]]; }
allowed() { run_hook "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }

check "round-2 shape (plan + TaskCreate, no SDD call): Agent denied" denied Agent "$F/round2-armed.jsonl"
check "round-1 shape (SDD Skill call after TaskCreate): allowed"     allowed Agent "$F/round1-disarmed.jsonl"
check "no writing-plans: allowed"                                    allowed Agent "$F/no-plan.jsonl"
check "second plan after a disarmed first cycle: denied again"       denied Agent "$F/second-cycle-armed.jsonl"
check "second cycle then a new SDD call: allowed"                    allowed Agent "$F/second-cycle-redisarmed.jsonl"
check "non-Agent tool ignored even when armed"                       allowed Bash "$F/round2-armed.jsonl"
check "missing transcript: allowed"                                  allowed Agent "$tmp/nope.jsonl"
check "empty transcript path: allowed"                               allowed Agent ""
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: silent exit 0"                                test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
print -r -- '{"tool_name":"Agent"}' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "Agent with no transcript_path: silent exit 0"                 test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
printf '{bad json line\n' >"$tmp/bad.jsonl"; cat "$F/round2-armed.jsonl" >>"$tmp/bad.jsonl"
check "invalid line in transcript poisons only itself (still armed)" denied Agent "$tmp/bad.jsonl"
payload Agent "$F/round2-armed.jsonl" | SDD_CALL_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "SDD_CALL_GUARD=0 lets the dispatch through"                   test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent "$F/round2-armed.jsonl" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?
check "--scoped registration denies the same way"                    test $rc -eq 2
check "deny text names the kill switch"                              zsh -c '[[ $1 == *SDD_CALL_GUARD=0* ]]' _ "$(run_hook Agent "$F/round2-armed.jsonl"; print -r -- $err)"

# Parity with the superpowers guard's own PY_SCAN (needs the plugin installed; skipped otherwise).
UP=(~/.claude/plugins/cache/superpowers-extended-cc-marketplace/superpowers-extended-cc/*/hooks/pre-askuser-handoff-guard(N))
if (( $#UP )); then
  python3 - "${UP[-1]}" >"$tmp/upscan.py" <<'PY'
import re, sys
s = open(sys.argv[1]).read()
print(re.search(r"PY_SCAN='\n(.*?)\n'\n", s, re.S).group(1))
PY
  parity() { local up mine; up="$(python3 "$tmp/upscan.py" "$1" | head -1)"; run_hook Agent "$1"; [[ $rc == 2 ]] && mine=true || mine=false; [[ "$up" == "$mine" ]]; }
  for f in round1-disarmed round2-armed no-plan second-cycle-armed second-cycle-redisarmed; do
    check "parity with upstream scan: $f" parity "$F/$f.jsonl"
  done
else
  print -r -- "skip: upstream pre-askuser-handoff-guard not installed, parity not run"
fi
tt_done
