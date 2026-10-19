# Run records: truthful exit through a pipe, a summary for every suite flavour, and a 500-record cap.
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-${0:A:h:h:h}/bin/tmux-ctl}"      # the checkout under test, not the live install
tt_setup
cd "$TT_DIR"
runs() { print -r -- $TC_STATE/runs-*.jsonl(N[1]) }
last() { jq -r "$1" "$(runs)" | tail -1 }
rec() {   # rec <cmd>: run it, print the final record's exit and summary
  $C run -t 60 -C "$TT_DIR" tests "$1" >/dev/null 2>&1
  print -r -- "$(last .exit)|$(last .summary)"
}

r="$(rec 'false | tail -1')"
check "pipe whose first stage fails -> rc not 0" test "${r%%|*}" != 0
r="$(rec 'true | tail -1')"
check "pipe that succeeds -> rc 0"               test "${r%%|*}" = 0

r="$(rec "printf 'Ran 5 tests in 0.1s\n\nOK\n'")"
check "unittest ok summary"       test "${r#*|}" = "5 tests, OK"
r="$(rec "printf 'Ran 1 test in 0.1s\n\nFAILED (failures=1, errors=2)\n'; false")"
check "unittest failed summary"   test "${r#*|}" = "1 test, FAILED (failures=1, errors=2)"
r="$(rec "printf '2 passed, 1 failed in 0.3s\n'")"
check "pytest summary unchanged"  test "${r#*|}" = "2 passed, 1 failed"
r="$(rec "printf '### a.zsh\nok   - x\nALL PASS\n'")"
check "zsh suite pass summary"    test "${r#*|}" = "ALL PASS"
r="$(rec "printf '### a.zsh\nFAIL - x\n3 FAILED\n'")"
check "zsh suite fail summary"    test "${r#*|}" = "3 FAILED"

# cap: pad to 501 records, one more run must leave exactly 500, newest kept
f="$(runs)"
for i in {1..501}; do print -r -- "{\"id\":\"old-$i\",\"exit\":0,\"summary\":\"\"}"; done > "$TT_DIR/pad"
cat "$TT_DIR/pad" > "$f"
$C run -t 60 -C "$TT_DIR" tests 'echo newest' >/dev/null 2>&1
check "records capped at 500"     test "$(wc -l < "$f" | tr -d ' ')" = 500
check "newest record kept"        test "$(last .cmd)" = "echo newest"
check "oldest records dropped"    test "$(head -1 "$f" | jq -r .id)" != "old-1"
check "no temp file left"         test -z "$(print -l $TC_STATE/runs-*.tmp*(N))"

# concurrent finishers at the cap: a `tail -n 500` stub that stalls after reading widens the race window
mkdir -p "$TT_DIR/stub"
cat > "$TT_DIR/stub/tail" <<'STUB'
#!/bin/sh
/usr/bin/tail "$@"; rc=$?
if [ "$1" = "-n" ] && [ "$2" = "500" ] && mkdir "$TC_STATE/stalled" 2>/dev/null; then sleep 2; fi   # only the first trimmer stalls      # trimmed copy is read; the mv comes late
exit $rc
STUB
chmod +x "$TT_DIR/stub/tail"
rm -rf "$TC_STATE/stalled"; head -500 "$TT_DIR/pad" > "$f"
PATH="$TT_DIR/stub:$PATH" $C _append "$f" '{"id":"A"}' &
sleep 0.7      # A is inside its stalled trim when B appends
PATH="$TT_DIR/stub:$PATH" $C _append "$f" '{"id":"B"}' &
wait
check "concurrent: exactly 500 remain"    test "$(wc -l < "$f" | tr -d ' ')" = 500
check "concurrent: both appends kept"    test "$(jq -r 'select(.id=="A" or .id=="B") | .id' "$f" | sort | paste -sd, -)" = "A,B"
check "no lock left behind"               test -z "$(print -l $TC_STATE/runs-*.lock(N))"

# a unittest line followed by the zsh suite's own FAILED line: the suite line wins
r="$(rec "printf 'Ran 5 tests in 0.1s\n\nOK\n2 FAILED\n'")"
check "zsh FAILED line beats unittest OK" test "${r#*|}" = "2 FAILED"
# leftover temp file from a killed trim is removed by the next cap
print x > "$f.tmp.99999"; cat "$TT_DIR/pad" > "$f"
$C run -t 60 -C "$TT_DIR" tests 'echo C' >/dev/null 2>&1
check "orphan temp file removed"          test -z "$(print -l $f.tmp.*(N))"
tt_done
