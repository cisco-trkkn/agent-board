source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
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
tt_done
