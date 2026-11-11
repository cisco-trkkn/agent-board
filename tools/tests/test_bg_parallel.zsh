source "${0:A:h}/bg_common.zsh"
# test_bg_parallel.zsh — concurrent runs on one window stay clean; no run record is left unfinished.
# concurrent runs on one idle window must not interleave their typed lines
tt_wait 5 tt_all_idle
bad=0
for i in 1 2 3 4 5 6 7 8; do
  $C run tests 'echo A' >"$TT_DIR/oa" 2>&1 & $C run tests 'echo B' >"$TT_DIR/ob" 2>&1 & wait
  grep -qE 'bad math|jq:|printf\]' "$TT_DIR/oa" "$TT_DIR/ob" && (( bad++ ))
  grep -qx A "$TT_DIR/oa" && grep -qx B "$TT_DIR/ob" || (( bad++ ))
done
check "parallel runs stay clean" test $bad -eq 0
check "no stuck records"         test "$(jq -sr '[group_by(.id)[]|select(last.exit==null)]|length' "$r")" = 0
tt_done
