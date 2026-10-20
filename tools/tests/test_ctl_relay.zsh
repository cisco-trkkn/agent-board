source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
STUB="$(mktemp -d "${TMPDIR:-/tmp}/ttstub.XXXXXX")"
mkdir -p "$STUB/repo/bin"
cat > "$STUB/repo/bin/claude-orchestrator" <<'EOF'
#!/bin/sh
printf '%s\n' "$@" > "$RELAY_OUT"
exec sleep 600
EOF
chmod +x "$STUB/repo/bin/claude-orchestrator"
export PATH="$STUB:$PATH" RELAY_OUT="$STUB/args" TC_IDEAS_DIR="$STUB/ideas"
mkdir -p "$STUB/zdot"; : > "$STUB/zdot/.zshrc"; export ZDOTDIR="$STUB/zdot"   # panes read no user rc, so the stub stays first on PATH (never start a real claude)
tt_setup claude
export AGENT_BOARD_REPO="$STUB/repo"; tt set-environment -g AGENT_BOARD_REPO "$STUB/repo"     # run-shell jobs get the server's env; the relay types <repo>/bin/claude-orchestrator by absolute path (bin/ is not on PATH on a fresh install)
doc="$TT_DIR/h.md"; print "# handoff" > "$doc"
$C artifact "$doc" --kind handoff >/dev/null
check "artifact registered" test "$(jq -r .kind "$TC_STATE/artifacts-tt.jsonl" | tail -1)" = handoff
$C idea "try X" >/dev/null
check "idea filed"          grep -q '^- \[ \] .* · try X$' "$STUB/ideas/tt.md"
out="$($C relay "$doc" --old-session OLD1)"
check "relay scheduled"     zsh -c 'print -r -- "$1" | grep -q "relay scheduled"' x "$out"
check "orchestrator started" tt_wait 30 test -s "$STUB/args"
check "prompt names doc"    grep -qF "Read $doc and continue from where the previous session left off." "$STUB/args"
check "lineage written"     tt_wait 10 sh -c "test \"\$(jq -r .old_session_id $TC_STATE/lineage-tt.jsonl 2>/dev/null)\" = OLD1"
tt_wait 10 test -n "$(tt list-panes -t '=tt:claude' -F '#{pane_current_command}' | grep -x sleep)"
tt send-keys -t '=tt:claude' C-c 2>/dev/null
tt respawn-pane -k -t '=tt:claude'       # no command: a fresh interactive shell, as relay.respawn does
tt_wait 5 tt_all_idle
# failing relay (no claude window): the failure is surfaced, not silent
tt new-session -d -s nc -n other -c "$TT_DIR"
TC_SESSION=nc $C relay "$doc" >/dev/null
check "failed relay reported" tt_wait 15 sh -c "grep -q 'relay failed' $TC_STATE/relay-failed-nc.txt 2>/dev/null"
check "notice prefix not doubled" test "$(grep -o 'relay failed:' $TC_STATE/relay-failed-nc.txt | wc -l | tr -d ' ')" = 1
# '#' in the doc path must survive tmux format expansion
hd="$TT_DIR/h#H.md"; print x > "$hd"
TC_SESSION=nc $C relay "$hd" >/dev/null
check "hash in path kept"     tt_wait 15 sh -c "grep -q 'h#H.md' $TC_STATE/relay-nc.log"
$C relay /nope-$$.md 2>/dev/null; rc=$?
check "missing doc refused" test $rc -eq 2
check "help lists relay"    sh -c "$C help | grep -q 'tmux-ctl relay'"
rm -rf "$STUB"
tt_done
