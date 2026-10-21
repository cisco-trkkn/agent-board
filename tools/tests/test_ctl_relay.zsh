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
tt_zdot "$STUB/zdot"   # panes read no user rc, so the stub stays first on PATH (never start a real claude)
tt_setup claude worker
export AGENT_BOARD_REPO="$STUB/repo"; tt set-environment -g AGENT_BOARD_REPO "$STUB/repo"     # run-shell jobs get the server's env; the relay types <repo>/bin/claude-orchestrator by absolute path (bin/ is not on PATH on a fresh install)
doc="$TT_DIR/h.md"; print "# handoff" > "$doc"
$C artifact "$doc" --kind handoff >/dev/null
check "artifact registered" test "$(jq -r .kind "$TC_STATE/artifacts-tt.jsonl" | tail -1)" = handoff
$C idea "try X" >/dev/null
check "idea filed"          grep -q '^- \[ \] .* · try X$' "$STUB/ideas/tt.md"
# relay is lead-only: from any window but the session's claude window it refuses and the lead pane is left alone
lead="$TMUX_PANE"; worker="$(tt display -p -t '=tt:worker' '#{pane_id}')"
lead_pid0="$(tt display -p -t "$lead" '#{pane_pid}')"
tt set-option -w -t '=tt:worker' @tc_agent 1
for who in worker teammate; do
  [[ $who == teammate ]] && tt set-option -w -t '=tt:worker' -u @tc_agent
  out="$(TMUX_PANE=$worker $C relay "$doc" --old-session OLD1 2>&1)"; rc=$?
  check "relay from $who window refuses"     test $rc -ne 0
  check "$who refusal says lead-only"        zsh -c 'print -r -- "$1" | grep -qi "lead"' x "$out"
  check "$who refusal prints manual start"   zsh -c 'print -r -- "$1" | grep -qF "claude-orchestrator '"'"'Read $2 and continue from where the previous session left off.'"'"'"' x "$out" "$doc"
  check "$who refusal schedules nothing"     zsh -c '! print -r -- "$1" | grep -q "relay scheduled"' x "$out"
done
sleep 6   # relay.py would have polled twice (2s apart) and respawned the lead by now
check "lead pane untouched"  test "$(tt display -p -t "$lead" '#{pane_pid}')" = "$lead_pid0"
check "no orchestrator started" test ! -e "$STUB/args"
check "no lineage written"   test ! -e "$TC_STATE/lineage-tt.jsonl"
out="$($C relay "$doc" --old-session OLD1)"
check "relay scheduled"     zsh -c 'print -r -- "$1" | grep -q "relay scheduled"' x "$out"
check "orchestrator started" tt_wait 30 test -s "$STUB/args"
check "prompt names doc"    grep -qF "Read $doc and continue from where the previous session left off." "$STUB/args"
check "lineage written"     tt_wait 10 sh -c "test \"\$(jq -r .old_session_id $TC_STATE/lineage-tt.jsonl 2>/dev/null)\" = OLD1"
tt_wait 10 test -n "$(tt list-panes -t '=tt:claude' -F '#{pane_current_command}' | grep -x sleep)"
tt send-keys -t '=tt:claude' C-c 2>/dev/null
tt respawn-pane -k -t '=tt:claude'       # no command: a fresh interactive shell, as relay.respawn does
tt_wait 5 tt_all_idle
# a failed detached relay is surfaced, not silent (relay now refuses before scheduling unless the caller is the lead,
# so the failure notice is driven the way run-shell drives it: relay.py's error text in the log, then _relay_failed)
tt new-session -d -s nc -n other -c "$TT_DIR"
flog="$TT_DIR/failed.log"
python3 -I "$TT_REPO/board/relay.py" --session nc --doc "$doc" --state "$TC_STATE" --socket "$(tt display -p '#{socket_path}')" > "$flog" 2>&1
check "relay.py fails without a claude window" test $? -eq 1
$C _relay_failed "$flog" "$doc" nc
check "failed relay reported" grep -q 'relay failed' "$TC_STATE/relay-failed-nc.txt"
check "notice prefix not doubled" test "$(grep -o 'relay failed:' $TC_STATE/relay-failed-nc.txt | wc -l | tr -d ' ')" = 1
# '#' in the doc path must survive tmux format expansion (relay from the lead; the lineage records the doc as relay.py received it)
hd="$TT_DIR/h#H.md"; print x > "$hd"
$C relay "$hd" >/dev/null
check "hash in path kept"     tt_wait 15 sh -c "grep -q 'h#H.md' $TC_STATE/lineage-tt.jsonl"
$C relay /nope-$$.md 2>/dev/null; rc=$?
check "missing doc refused" test $rc -eq 2
check "help lists relay"    sh -c "$C help | grep -q 'tmux-ctl relay'"
rm -rf "$STUB"
tt_done
