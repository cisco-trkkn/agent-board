source "${0:A:h}/lib.zsh"
# tmux-ctl awake on|off|status|sleeps: the queue's keep-awake hold. caffeinate and pmset are stubs on a temp PATH dir
# (never the real ones): the caffeinate stub execs a copy of /bin/sleep named caffeinate, so `ps -o comm=` says caffeinate.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
FX="${0:A:h}/fixtures/awake"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttawake.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/real"
cp /bin/sleep "$S/real/caffeinate"
cp /bin/zsh "$S/real/claude-fake"
codesign -s - -f "$S/real/caffeinate" "$S/real/claude-fake" 2>/dev/null   # a copied platform binary is killed on macOS until re-signed
cat > "$S/bin/caffeinate" <<STUB
#!/bin/sh
echo "\$*" >> "$S/caffeinate.args"
exec "$S/real/caffeinate" 600
STUB
cat > "$S/bin/pmset" <<STUB
#!/bin/sh
case "\$*" in
  "-g batt") cat "\${AWAKE_FIXTURE_BATT:-$FX/batt-ac.txt}" ;;
  "-g log")  cat "$FX/log-sleeps.txt" ;;
esac
STUB
chmod +x "$S/bin/caffeinate" "$S/bin/pmset"
export PATH="$S/bin:$PATH" TZ=America/New_York
AF="$TC_STATE/awake.json"
stubpids() { pgrep -f "$S/real/caffeinate" }
nstub() { stubpids | wc -l | tr -d ' ' }
cleanup() { local p; for p in ${(f)"$(pgrep -f "$S/real/" 2>/dev/null)"}; do kill $p 2>/dev/null; done; rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
W=$$   # a live pid to watch

# --- on
out="$($C awake on --pid $W)"; rc=$?
cp1="$(jq -r .caffeinatePid "$AF" 2>/dev/null)"
check "on: prints on (pid, watching)"          test "$out" = "awake: on (pid $cp1, watching $W)"
check "on: exit 0"                             test $rc -eq 0
check "on: awake.json has the three fields"    test "$(jq -r '[.pid,.caffeinatePid,.since]|map(type)|join(",")' "$AF")" = "number,number,string"
check "on: since is ISO UTC"                   zsh -c '[[ $1 == [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z ]]' _ "$(jq -r .since "$AF")"
check "on: caffeinate -i -s -w <pid>"          test "$(<$S/caffeinate.args)" = "-i -s -w $W"
check "on: one caffeinate running"             test "$(nstub)" = 1
check "on: the recorded pid is the caffeinate" test "$(basename "$(ps -o comm= -p $cp1)")" = caffeinate
since1="$(jq -r .since "$AF")"
out="$($C awake on --pid $W)"
check "on twice: already on message"           test "$out" = "awake: already on (pid $cp1, since $since1)"
check "on twice: still one caffeinate"         test "$(nstub)" = 1
out="$(AWAKE_FIXTURE_BATT=$FX/batt-battery.txt $C awake on --pid $W)"
check "on twice on battery: only already-on"   test "$out" = "awake: already on (pid $cp1, since $since1)"

# --- status
out="$($C awake status)"
check "status on: line"                        zsh -c '[[ $1 == *"on (pid $2, watching $3, since $4)"* ]]' _ "$out" $cp1 $W $since1
check "status on: power line (AC)"             zsh -c '[[ $1 == *"AC Power"*"100%"* ]]' _ "$out"
out="$(AWAKE_FIXTURE_BATT=$FX/batt-battery.txt $C awake status)"
check "status: power line (battery)"           zsh -c '[[ $1 == *"Battery Power"*"80%"* ]]' _ "$out"

# --- dead pid is replaced
kill $cp1; sleep 0.3
out="$($C awake status)"
check "status with dead pid: off"              zsh -c '[[ $1 == off* ]]' _ "$out"
check "status removes the stale file"          test ! -e "$AF"
print -r -- "{\"pid\": $W, \"caffeinatePid\": $cp1, \"since\": \"2020-01-01T00:00:00Z\"}" > "$AF"
$C awake on --pid $W >/dev/null
cp2="$(jq -r .caffeinatePid "$AF")"
check "on with a dead recorded pid: new pid"   test "$cp2" != "$cp1" -a -n "$cp2"
check "on with a dead recorded pid: new since" test "$(jq -r .since "$AF")" != "2020-01-01T00:00:00Z"
check "on with a dead recorded pid: one caffeinate"  test "$(nstub)" = 1

# --- battery warning
$C awake off >/dev/null
out="$(AWAKE_FIXTURE_BATT=$FX/batt-battery.txt $C awake on --pid $W)"
check "on battery: warns"                      zsh -c '[[ $1 == *"awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night"* ]]' _ "$out"
$C awake off >/dev/null
out="$($C awake on --pid $W)"
check "on AC: no warning"                      zsh -c '[[ $1 != *"on battery"* ]]' _ "$out"

# --- off
out="$($C awake off)"; rc=$?
check "off: prints off"                        test "$out" = "awake: off"
check "off: exit 0"                            test $rc -eq 0
check "off: file removed"                      test ! -e "$AF"
check "off: caffeinate killed"                 test "$(nstub)" = 0
out="$($C awake off)"; rc=$?
check "off with no file: awake: off, exit 0"   test "$out" = "awake: off" -a $rc -eq 0
# a reused pid (alive, not caffeinate) is left alone
sleep 300 & other=$!
print -r -- "{\"pid\": $W, \"caffeinatePid\": $other, \"since\": \"2020-01-01T00:00:00Z\"}" > "$AF"
out="$($C awake status)"
check "status: reused pid counts as off"       zsh -c '[[ $1 == off* ]]' _ "$out"
print -r -- "{\"pid\": $W, \"caffeinatePid\": $other, \"since\": \"2020-01-01T00:00:00Z\"}" > "$AF"
out="$($C awake off)"
check "off: reused pid not killed"             kill -0 $other
check "off: reused pid still prints off"       test "$out" = "awake: off"
check "off: reused pid file removed"           test ! -e "$AF"
kill $other

# --- ancestor
out="$(TC_AWAKE_ANCESTOR=zz-no-such-name $C awake on 2>&1)"; rc=$?
check "no claude ancestor: message"            test "$out" = "awake: no claude ancestor; pass --pid"
check "no claude ancestor: non-zero"           test $rc -ne 0
check "no claude ancestor: nothing started"    test "$(nstub)" = 0
out="$("$S/real/claude-fake" -c "$C awake on; true")"
check "claude ancestor found"                  zsh -c '[[ $1 == "awake: on (pid "*", watching "[0-9]*")" ]]' _ "$out"
check "ancestor pid is not the test shell"     test "$(jq -r .pid "$AF")" != "$W"
$C awake off >/dev/null

# --- sleeps
out="$($C awake sleeps '2026-11-07 10:28')"
check "sleeps local: first line"               test "$(print -r -- "$out" | head -1)" = "2026-11-07 10:28:22 DarkWake Deep Idle"
check "sleeps local: sleep reason"             sh -c "printf %s '$out' | grep -qx '2026-11-07 10:28:24 Sleep Sleep Service Back to Sleep'"
check "sleeps local: nothing before the cutoff"  test -z "$(print -r -- "$out" | grep '10:12:')"
check "sleeps: Wake Requests excluded"         test -z "$(print -r -- "$out" | grep -i 'request')"
iso="$($C awake sleeps '2026-11-07T15:28:00Z')"
check "sleeps ISO UTC == local equivalent"     test "$iso" = "$out"
all="$($C awake sleeps '2000-01-01 00:00')"
check "sleeps: a real Wake line is listed"     test "$(print -r -- "$all" | awk '$3=="Wake"' | wc -l | tr -d ' ')" -ge 1
check "sleeps: only three types"               test -z "$(print -r -- "$all" | awk '$3!="Sleep"&&$3!="Wake"&&$3!="DarkWake"')"
check "sleeps: line count = fixture minus Wake Requests"  test "$(print -r -- "$all" | wc -l | tr -d ' ')" = "$(grep -vc 'Wake Requests' "$FX/log-sleeps.txt")"
out="$($C awake sleeps '2099-01-01 00:00')"; rc=$?
check "sleeps: none prints nothing, exit 0"    test -z "$out" -a $rc -eq 0

# --- unsupported: a PATH without caffeinate (resp. pmset)
mkdir -p "$S/nocaff" "$S/nopm"
for tool in zsh sh env jq tmux python3 git ps date sed awk grep cat kill mkdir rm dirname basename xargs tr sort head tail wc sleep readlink uname id ls; do
  p="$(command -v $tool 2>/dev/null)"; [[ -n "$p" && "$p" == /* ]] || continue
  ln -sf "$p" "$S/nocaff/$tool"; ln -sf "$p" "$S/nopm/$tool"
done
ln -sf "$S/bin/pmset" "$S/nocaff/pmset"; ln -sf "$S/bin/caffeinate" "$S/nopm/caffeinate"
for sub in on status off "sleeps 2026-11-07"; do
  out="$(PATH="$S/nocaff" $C awake ${=sub} 2>&1)"; rc=$?
  check "no caffeinate: '$sub' unsupported, exit 0"  test "$out" = "awake: unsupported here" -a $rc -eq 0
done
out="$(PATH="$S/nopm" $C awake status 2>&1)"; rc=$?
check "no pmset: unsupported, exit 0"          test "$out" = "awake: unsupported here" -a $rc -eq 0
check "unsupported started nothing"            test "$(nstub)" = 0
check "help lists awake"                       sh -c "$C help | grep -q 'tmux-ctl awake'"
check "help still ends at the blank line"      test "$($C help | tail -1)" = ""

# --- leak check
$C awake off >/dev/null
check "leak: no stub process left"             test "$(nstub)" = 0
tt_done
