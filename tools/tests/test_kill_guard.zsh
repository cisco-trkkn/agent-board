source "${0:A:h}/lib.zsh"
# Never runs a real pkill/killall: the hook only inspects `ps`; we feed it JSON on stdin.
H="${TC_KILLGUARD:-$TT_REPO/claude/hooks/kill-guard.sh}"
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
# npm-style Claude: the executable is not named claude (node), but the process calls itself claude: argv[0] "claude"
# everywhere, and on Linux also comm "claude" (node's process.title). Its /proc/<pid>/exe is .../node.
mkdir -p "$tmp/npm"; cp /bin/sh "$tmp/npm/node"; codesign --force -s - "$tmp/npm/node" 2>/dev/null
( exec -a claude "$tmp/npm/node" -c '[ -w /proc/self/comm ] && echo claude > /proc/$$/comm 2>/dev/null; sleep 300; :' "NPMPAT-$$" ) </dev/null >/dev/null 2>&1 & pids+=($!)
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
check "npm-style claude (exe is node, name claude) blocked" blocked "pkill -f 'NPMPAT-$$'"
# /proc unreadable (macOS has none; here an empty root): the comm and argv checks alone still guard
run_hook_noproc() { json "$1" | KILL_GUARD_PROC_ROOT="$tmp/noproc" "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; err="$(<$tmp/e)"; }
mkdir -p "$tmp/noproc"
run_hook_noproc "pkill -f 'GUARDPAT-$$'"; check "no /proc: versions-path claude still blocked (comm/argv fallback)" test $rc -eq 2 -a -n "$err"
run_hook_noproc "pkill -f 'NPMPAT-$$'";   check "no /proc: npm-style claude still blocked" test $rc -eq 2 -a -n "$err"
run_hook_noproc "pkill -f 'DECOYPAT-$$'"; check "no /proc: decoy still allowed" test $rc -eq 0
# Linux npm install, simulated on any OS with a fake /proc: comm and args say claude, but exe is /usr/bin/node
# (a real Linux CI run also gets the genuine case from the npm-style process above)
npmpid="$(pgrep -f "NPMPAT-$$" | head -1)"; mkdir -p "$tmp/fakeproc/$npmpid"; ln -s /usr/bin/node "$tmp/fakeproc/$npmpid/exe"
run_hook_fakeproc() { json "$1" | KILL_GUARD_PROC_ROOT="$tmp/fakeproc" "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; err="$(<$tmp/e)"; }
run_hook_fakeproc "pkill -f 'NPMPAT-$$'"; check "exe is node but comm/args say claude: still blocked (fail closed)" test $rc -eq 2 -a -n "$err"
check "non-Bash tool ignored"                   allowed "pkill -f GUARDPAT-$$" Edit
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
silent0() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
check "malformed json silent exit 0"            silent0
tt_done
