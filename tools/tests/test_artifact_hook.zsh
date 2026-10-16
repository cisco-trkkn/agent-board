source "${0:A:h}/lib.zsh"
H="${TC_HOOK:-$HOME/.claude/hooks/artifact-register.sh}"
tt_setup claude
tt rename-window -t '=tt:claude' '✦ impl'
mkdir -p "$TT_DIR/r/docs/superpowers/plans" "$TT_DIR/sp/scratchpad"
plan="$TT_DIR/r/docs/superpowers/plans/p.md"; print "# P" > "$plan"
m="$TC_STATE/artifacts-tt.jsonl"
hook() { print -r -- "$1" | "$H" }
hook "{\"tool_name\":\"Write\",\"session_id\":\"S1\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "plan recorded"       test "$(jq -r .kind "$m" | tail -1)" = plan
check "agent from window"   test "$(jq -r .agent "$m" | tail -1)" = impl
check "hash present"        test "$(jq -r .hash "$m" | tail -1 | tr -d '\n' | wc -c | tr -d ' ')" = 64
check "session id"          test "$(jq -r .session_id "$m" | tail -1)" = S1
check "epoch 0"             test "$(jq -r .epoch "$m" | tail -1)" = 0
other="$TT_DIR/r/notes.md"; print x > "$other"
n0=$(wc -l < "$m")
hook "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$other\"}}"
check "unmatched ignored"   test "$(wc -l < "$m")" -eq "$n0"
print '{}' > "$TC_STATE/lineage-tt.jsonl"
hook "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "epoch from lineage"  test "$(jq -r .epoch "$m" | tail -1)" = 1
rep="$TT_DIR/sp/scratchpad/e2e-report.md"; print r > "$rep"
hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$rep\"}}"
check "report kind"         test "$(jq -r .kind "$m" | tail -1)" = report
ho="${TMPDIR:-/tmp}/tt-handoff-$$.md"; print h > "$ho"
hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$ho\"}}"
check "tmp handoff kind"    test "$(jq -r .kind "$m" | tail -1)" = handoff
rm -f "$ho"
hook '{"tool_name":"Artifact","tool_input":{"file_path":"/x/page.html"},"tool_response":"Published https://claude.ai/code/artifact/abc-123 ok"}'
check "published url"       test "$(jq -r .url "$m" | tail -1)" = "https://claude.ai/code/artifact/abc-123"
( unset TMUX TMUX_PANE; "$H" --path "$other" --kind other --agent you --project tt )
check "manual mode"         test "$(jq -r '.agent+" "+.kind' "$m" | tail -1)" = "you other"
hook 'not json'; rc=$?
check "bad input exit 0"    test $rc -eq 0
out="$( unset TMUX TMUX_PANE; print -r -- "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$plan\"}}" | "$H"; print rc=$? )"
check "outside tmux silent" test "$out" = "rc=0"
tt_done
