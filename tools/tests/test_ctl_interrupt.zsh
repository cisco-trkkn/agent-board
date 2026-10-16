source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
export TC_IDEAS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ttideas.XXXXXX")"
mkdir -p "$TMPDIR/zd.$$"; export ZDOTDIR="$TMPDIR/zd.$$"
tt_setup
last_log() { jq -rs 'map(select(.log))|last|.log' "$TC_STATE/runs-tt.jsonl" }
# M2 + M1: a timeout leaves a log and no stale .rc once the late _done arrives
( cd "$TT_DIR" && $C run -t 1 tests 'sleep 3; echo late' >/dev/null 2>&1 ); rc=$?
check "timeout exits 124"        test $rc -eq 124
check "timeout leaves a log"     test -f "$(last_log)"
sleep 5
check "no stale .rc after a late _done" test -z "$(print -l $TC_STATE/*.rc(N))"
tt_wait 8 tt_all_idle
# INT/TERM: the pane is captured into the log
( cd "$TT_DIR" && $C run tests 'echo started-ok; sleep 20' >/dev/null 2>&1 ) &
pid=$!
tt_wait 8 sh -c "$TT_BIN capture-pane -p -t '=tt-bg:tests' | grep -q started-ok"
kill -TERM $pid; wait $pid 2>/dev/null
check "interrupted run leaves a log" test -f "$(last_log)"
check "log has the output so far"    grep -q started-ok "$(last_log)"
tt send-keys -t '=tt-bg:tests' C-c
# M6: from a -bg pane the key is the project, never <project>-bg-bg
tt_wait 5 sh -c "$TT_BIN has-session -t '=tt-bg'"
TC_SESSION=tt-bg $C idea "from the bg pane" >/dev/null 2>&1
check "key strips -bg"           test -s "$TC_IDEAS_DIR/tt.md"
check "no -bg-bg key"            test ! -e "$TC_IDEAS_DIR/tt-bg.md"
# M4: a _web-* key warns
tt new-session -d -s _web-9 -c "$TT_DIR"
doc="$TT_DIR/h.md"; print x > "$doc"
err="$(TC_SESSION=_web-9 $C artifact "$doc" 2>&1 >/dev/null)"
warns() { [[ "${1:l}" == *"browser view"* ]] }
check "artifact warns on _web- key" warns "$err"
err="$(TC_SESSION=_web-9 $C relay "$doc" 2>&1 >/dev/null)"
check "relay warns on _web- key"    warns "$err"
rm -rf "$TC_IDEAS_DIR" "$TMPDIR/zd.$$"
tt_done
