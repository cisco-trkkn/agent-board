source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
m="$TC_STATE/artifacts-tt.jsonl"
kind_of() { jq -r --arg p "$1" 'select(.path==$p)|.kind' "$m" | tail -1 }
mkdir -p "$TT_DIR/r/docs/superpowers/plans" "$TT_DIR/r/docs/superpowers/specs"
plan="$TT_DIR/r/docs/superpowers/plans/x.md"; print "# X" > "$plan"
spec="$TT_DIR/r/docs/superpowers/specs/y.md"; print "# Y" > "$spec"
note="$TT_DIR/r/notes.md"; print "# N" > "$note"
$C artifact "$plan" >/dev/null
check "plan auto kind"      test "$(kind_of "$plan")" = plan
$C artifact "$spec" >/dev/null
check "spec auto kind"      test "$(kind_of "$spec")" = spec
$C artifact "$note" >/dev/null
check "other fallback"      test "$(kind_of "$note")" = other
print "# Y2" > "$spec"
$C artifact "$spec" --kind other >/dev/null
check "explicit kind wins"  test "$(kind_of "$spec")" = other
check "prints the kind"     sh -c "$C artifact ${(q)plan} | grep -q '(plan)\$'"
# a board dismiss/restore line (no kind, no session_id) is the manifest's last line for the path: the readers' jq filters must skip it
filter_of() { grep -o 'select(\.path==\$p[^'"'"']*' "$1" | head -1 }
mk="$TT_DIR/marked.jsonl"
print -r -- '{"ts":1,"path":"/h.md","kind":"handoff","session_id":"SID1"}' > "$mk"
print -r -- '{"ts":2,"path":"/h.md","dismissed":true,"agent":"you"}' >> "$mk"
check "tmux-ctl artifact's kind filter skips marks" test "$(jq -r --arg p /h.md "$(filter_of "$C")" "$mk" | tail -1)" = handoff
check "handoff skill's session-id filter skips marks" test "$(jq -r --arg p /h.md "$(filter_of "$TT_REPO/claude/plugin/skills/handoff/SKILL.md")" "$mk" | tail -1)" = SID1
tt_done
