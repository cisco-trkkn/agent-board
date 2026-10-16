source "${0:A:h}/lib.zsh"
# Never runs a real pkill/killall: the hook only inspects `ps`; we feed it JSON on stdin.
H=~/.claude/hooks/kill-guard.sh
tmp="$(mktemp -d "${TMPDIR:-/tmp}/kg.XXXXXX")"; tmp="${tmp:A}"
pids=()
cleanup() { local p c; for p in $pids; do for c in $(pgrep -P "$p"); do kill "$c" 2>/dev/null; done; kill "$p" 2>/dev/null; done; rm -rf "$tmp"; }
trap 'cleanup; tt_teardown' EXIT INT TERM

mkdir -p "$tmp/claude/versions"
# fake Claude: copy of /bin/sh named 9.9.9 whose argv carries the pattern
cp /bin/sh "$tmp/claude/versions/9.9.9"
codesign --force -s - "$tmp/claude/versions/9.9.9" 2>/dev/null   # copied system binaries are killed (137) otherwise
"$tmp/claude/versions/9.9.9" -c 'sleep 300; :' "GUARDPAT-$$" </dev/null >/dev/null 2>&1 & pids+=($!)
# non-Claude decoy
/bin/sh -c 'sleep 300' "DECOYPAT-$$" </dev/null >/dev/null 2>&1 & pids+=($!)
sleep 0.5

json() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[2],"tool_input":{"command":sys.argv[1]}}))' "$1" "${2:-Bash}"; }
# run_hook <cmd> [tool] -> sets rc, out, err
run_hook() { json "$@" | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
blocked() { run_hook "$1"; [[ $rc == 2 && "$err" == *"kill by PID"* ]]; }
allowed() { run_hook "$@"; [[ $rc == 0 && -z "$out" ]]; }

check "pkill -f matching fake claude blocked"   blocked "pkill -f 'GUARDPAT-$$'"
check "pkill -f matching decoy allowed"         allowed "pkill -f 'DECOYPAT-$$'"
check "killall claude binary name blocked"      blocked "killall 9.9.9"
check "killall sleep allowed"                   allowed "killall sleep"
check "compound segment blocked"                blocked "echo hi; pkill -f GUARDPAT-$$ && true"
check "sudo pkill blocked"                      blocked "sudo pkill -f GUARDPAT-$$"
check "kill by pid allowed"                     allowed "kill 1234"
check "pkill without -f matches name only"      allowed "pkill GUARDPAT-$$"
check "single & separator blocked"             blocked "echo x & pkill -f GUARDPAT-$$"
check "bash -c nested blocked"                  blocked "bash -c \"pkill -f GUARDPAT-$$\""
check "VAR=1 prefix blocked"                    blocked "VAR=1 pkill -f GUARDPAT-$$"
check "xargs/env/subshell blocked"              blocked "echo | xargs pkill -f GUARDPAT-$$; (env pkill -f GUARDPAT-$$)"
check "quoted ; pattern blocked"                blocked "pkill -f \"GUARDPAT-$$|a;b\""
check "unbalanced quote falls back to regex"    blocked "pkill -f 'GUARDPAT-$$"
check "decoy via bash -c allowed"               allowed "bash -c 'pkill -f DECOYPAT-$$'"
check "non-Bash tool ignored"                   allowed "pkill -f GUARDPAT-$$" Edit
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
silent0() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
check "malformed json silent exit 0"            silent0
tt_done
