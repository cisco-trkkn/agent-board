source "${0:A:h}/lib.zsh"
H="${TC_HOOK:-$TT_REPO/claude/hooks/artifact-register.sh}"
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
# handoffs: the plugin skill writes under ~/.local/state/agent-board/handoffs, the old skill under ~/.claude/handoffs (scratch HOME)
SH="$TT_DIR/home"; mkdir -p "$SH/.local/state/agent-board/handoffs" "$SH/.claude/handoffs"
print h > "$SH/.local/state/agent-board/handoffs/new.md"; print h > "$SH/.claude/handoffs/old.md"
TC_TMUX="$TT_BIN" HOME="$SH" hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$SH/.local/state/agent-board/handoffs/new.md\"}}"
check "state handoff kind"  test "$(jq -r .kind "$m" | tail -1)" = handoff
check "state handoff path"  test "$(jq -r .path "$m" | tail -1)" = "$SH/.local/state/agent-board/handoffs/new.md"
TC_TMUX="$TT_BIN" HOME="$SH" hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$SH/.claude/handoffs/old.md\"}}"
check "legacy handoff kind" test "$(jq -r .path "$m" | tail -1)" = "$SH/.claude/handoffs/old.md" -a "$(jq -r .kind "$m" | tail -1)" = handoff
hook '{"tool_name":"Artifact","tool_input":{"file_path":"/x/page.html"},"tool_response":"Published https://claude.ai/code/artifact/abc-123 ok"}'
check "published url"       test "$(jq -r .url "$m" | tail -1)" = "https://claude.ai/code/artifact/abc-123"
( unset TMUX TMUX_PANE; "$H" --path "$other" --kind other --agent you --project tt )
check "manual mode"         test "$(jq -r '.agent+" "+.kind' "$m" | tail -1)" = "you other"
hook 'not json'; rc=$?
check "bad input exit 0"    test $rc -eq 0
out="$( unset TMUX TMUX_PANE; print -r -- "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$plan\"}}" | "$H"; print rc=$? )"
check "outside tmux silent" test "$out" = "rc=0"
FX="$TT_REPO/tools/tests/fixtures/docs-hook"
want_url="$(jq -r '.tool_response[0].text|split("\n")[0]|fromjson|.frame.url' "$FX/create.json")"
want_slug="$(jq -r '.tool_input.container.id' "$FX/update.json")"
n0=$(wc -l < "$m")
hook "$(<"$FX/create.json")"
check "doc create recorded"  test "$(jq -r .kind "$m" | tail -1)" = doc -a "$(wc -l < "$m")" -eq $(( n0 + 1 ))
check "doc url and path"     test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(jq -r .path "$m" | tail -1)" = "$want_url"
check "doc title"            test "$(jq -r .title "$m" | tail -1)" = "agent-board hook fixture (delete me)"
check "doc slug"             test "$(jq -r .slug "$m" | tail -1)" = "$want_slug"
hook "$(<"$FX/update.json")"
check "doc edit recorded"    test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(wc -l < "$m")" -eq $(( n0 + 2 ))
check "doc edit kind slug"   test "$(jq -r '.kind+" "+.slug+" ["+.title+"]"' "$m" | tail -1)" = "doc $want_slug []"
n1=$(wc -l < "$m")
hook "$(<"$FX/read.json")"
check "doc read ignored"     test "$(wc -l < "$m")" -eq "$n1"
hook '{"tool_name":"mcp__claude_ai_Claude_Docs__batch","tool_input":{},"tool_response":"no link here"}'
check "doc without url"      test "$(wc -l < "$m")" -eq "$n1"
hook "$(jq -c '.tool_input.container.id="00000000-unknown"' "$FX/update.json")"
check "update unknown slug"  test "$(wc -l < "$m")" -eq "$n1"
hook '{"tool_name":"mcp__other__create","tool_input":{},"tool_response":"https://claude.ai/x/y"}'
check "other mcp ignored"    test "$(wc -l < "$m")" -eq "$n1"
hook "{\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "file lines have title" test "$(jq -r 'select(.kind=="plan") | has("title")' "$m" | tail -1)" = true
# stray claude.ai links never win over frame.url (create) or the manifest URL (edit by slug)
n2=$(wc -l < "$m")
hook "$(jq -c '.tool_response[0].text += "\n\nsee https://claude.ai/artifact/PROSE-LINK."' "$FX/create.json")"
check "prose link after frame"  test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(wc -l < "$m")" -eq $(( n2 + 1 ))
hook "$(jq -c '.tool_response = [{"type":"text","text":"https://claude.ai/artifact/STRAY-FIRST"}] + .tool_response' "$FX/create.json")"
check "stray item before frame" test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(wc -l < "$m")" -eq $(( n2 + 2 ))
n3=$(wc -l < "$m")
hook "{\"tool_name\":\"mcp__claude_ai_Claude_Docs__batch\",\"tool_input\":{\"container\":{\"kind\":\"project\",\"id\":\"$want_slug\"},\"batch\":[]},\"tool_response\":[{\"type\":\"text\",\"text\":\"done, see https://claude.ai/artifact/STRAY-EDIT.\"}]}"
check "edit stray link -> manifest url" test "$(jq -r .url "$m" | tail -1)" = "$want_url" -a "$(wc -l < "$m")" -eq $(( n3 + 1 ))
# fallback regex (no parsable frame, no container id) drops a sentence-ending dot
hook '{"tool_name":"mcp__claude_ai_Claude_Docs__batch","tool_input":{},"tool_response":"Made it: https://claude.ai/artifact/FALLBACK-1."}'
check "fallback url trims dot"  test "$(jq -r .url "$m" | tail -1)" = "https://claude.ai/artifact/FALLBACK-1"
# a frame url off claude.ai is never recorded: every claude.ai link in the fixture becomes javascript:, so the frame falls
# through to the container id (none in create.json) and the regex (no claude.ai link left): nothing is appended
n4=$(wc -l < "$m")
hook "$(jq -c '.tool_response[0].text |= gsub("https://claude\\.ai/[^\\s\"]+"; "javascript:alert(1)")' "$FX/create.json")"
check "off-claude frame url dropped" test "$(wc -l < "$m")" -eq "$n4" -a "$(grep -c javascript "$m")" -eq 0
# manifest missing / garbled: nothing appended, rc 0 (scratch manifest only)
cp "$m" "$m.keep"; rm -f "$m"
hook "$(<"$FX/update.json")"; rc=$?
check "update, manifest missing" test $rc -eq 0 -a ! -e "$m"
print 'garbage{' > "$m"
hook "$(<"$FX/update.json")"; rc=$?
check "update, manifest garbled" test $rc -eq 0 -a "$(wc -l < "$m")" -eq 1
mv "$m.keep" "$m"
tt_done
