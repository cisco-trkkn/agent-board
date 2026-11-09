source "${0:A:h}/lib.zsh"
# tmux-ctl approve <win> once|deny [--expect <text>]: presses the one-time Yes / the No of a permission prompt.
# Each case replays a real captured prompt (tools/tests/fixtures/approve/*.txt) in a window of the scratch server:
# `cat fixture; read -t 3 -k1 k; print GOT:$k` shows which key arrived (GOT:NONE = nothing was sent).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
FX="${0:A:h}/fixtures/approve"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttap.XXXXXX"):A}"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
# replay <win> <file>: a window showing the fixture, then waiting for one key
replay() { tt new-window -d -t '=tt:' -n "$1" -c "$TT_DIR" "zsh -c 'cat $2; read -t 3 -k1 k; print -r -- \"GOT:\${k:-NONE}\"; sleep 600'"; sleep 0.5 }
got() { local n=20 g; while (( n-- > 0 )); do g="$(tt capture-pane -p -J -t "=tt:$1" | grep -a -o 'GOT:[^ ]*' | tail -1)"; [[ -n "$g" ]] && { print -r -- "${g#GOT:}"; return }; sleep 0.25; done; print -r -- TIMEOUT }
ap() { out="$($C approve "$@" 2>&1)"; rc=$?; }

# --- variants built from real fixtures with sed (not hand-written prompts)
sed '/ 1\. Yes$/d' $FX/bash-git.txt > $S/no-plain-yes.txt                                      # bash-git.txt with the plain "1. Yes" row deleted
sed 's/ 1\. Yes$/ 1. Yes, and switch to accept edits/' $FX/write.txt > $S/only-yes-and.txt     # write.txt whose plain Yes row is a "Yes, and ..." row
sed '/ 3\. No$/d' $FX/write.txt > $S/no-no.txt                                                 # write.txt with the No row deleted

# --- once: Bash prompts (1 Yes / 2 ... don’t ask / 3 switch / 4 No)
for f in bash-touch bash-git; do
  replay w-$f $FX/$f.txt; ap w-$f once
  # mutation: pick the first "Yes…" row instead of exactly Yes → still 1 here; see the variant tests below
  check "once $f: message"        test "$out" = "approve: w-$f: chose \"Yes\""
  check "once $f: exit 0"         test $rc -eq 0
  check "once $f: key 1 arrived"  test "$(got w-$f)" = 1
done
replay w-write $FX/write.txt; ap w-write once
check "once write: key 1"         test "$(got w-write)" = 1
# --- deny
replay d-git $FX/bash-git.txt; ap d-git deny
check "deny bash-git: chose No"   test "$out" = "approve: d-git: chose \"No\""
check "deny bash-git: key 4"      test "$(got d-git)" = 4
replay d-write $FX/write.txt; ap d-write deny
check "deny write: key 3"         test "$(got d-write)" = 3
# --- refusals: no key sent
for f in no-prompt after-yes; do
  replay n-$f $FX/$f.txt; ap n-$f once
  # mutation: drop the no-prompt check → exit-1 test fails
  check "$f: exit 1 + message"    test $rc -eq 1 -a "$out" = "approve: no permission prompt in n-$f"
  check "$f: no key sent"         test "$(got n-$f)" = NONE
done
# --expect
replay e-ok $FX/bash-git.txt; ap e-ok once --expect "git config user.name probe-user"
check "expect match: chose"       test $rc -eq 0 -a "$(got e-ok)" = 1
replay e-bad $FX/bash-git.txt; ap e-bad once --expect "rm -rf /"
# mutation: drop the --expect check → changed-prompt test sends a key
check "expect mismatch: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in e-bad changed"
check "expect mismatch: no key"   test "$(got e-bad)" = NONE
# prompt swapped between the capture and the send (seam TC_APPROVE_BEFORE_SEND runs after the first capture)
replay c-swap $FX/bash-git.txt
cat > $S/swap.zsh <<SW
$TT_BIN respawn-pane -k -t '=tt:c-swap' "cat $FX/write.txt; read -t 3 -k1 k; print -r -- GOT:\\\${k:-NONE}; sleep 600"
sleep 0.5
SW
export TC_APPROVE_BEFORE_SEND="zsh $S/swap.zsh"
ap c-swap once; unset TC_APPROVE_BEFORE_SEND
# mutation: skip the re-capture compare → a key is sent to the new prompt
check "swap between capture and send: exit 1 + message"  test $rc -eq 1 -a "$out" = "approve: the prompt in c-swap changed"
check "swap: no key sent"         test "$(got c-swap)" = NONE
# --- never a "Yes, and ..." row
for v in no-plain-yes only-yes-and; do
  replay v-$v $S/$v.txt; ap v-$v once
  # mutation: match labels starting with Yes (blacklist always/don't ask) → this presses a "Yes, and ..." row
  check "$v: once refused"        test $rc -eq 1 -a "$out" = "approve: no one-time Yes in v-$v"
  check "$v: no key sent"         test "$(got v-$v)" = NONE
done
replay v-nono $S/no-no.txt; ap v-nono deny
check "no No row: deny refused"   test $rc -eq 1 -a "$out" = "approve: no No option in v-nono"
check "no No row: no key"         test "$(got v-nono)" = NONE
# --- worker window (@tc_agent) works, unlike keys
replay wk $FX/bash-touch.txt; tt set-option -w -t '=tt:wk' @tc_agent 1; ap wk once
check "worker window: chose + key 1"  test $rc -eq 0 -a "$(got wk)" = 1
# --- usage
ap; check "usage: exit 2"           test $rc -eq 2
ap w-write maybe; check "bad action: exit 2"  test $rc -eq 2
ap nosuchwin once; check "no such window: exit 2"  test $rc -eq 2
# --- help lists approve and still ends at the header
h="$($C help)"
check "help: approve line"        test -n "$(print -r -- "$h" | grep 'tmux-ctl approve')"
check "help: telegram line kept"  test -n "$(print -r -- "$h" | grep 'tmux-ctl telegram')"
check "help: nothing after the header"  test -z "$(print -r -- "$h" | grep 'send/run only type')"
tt_done
