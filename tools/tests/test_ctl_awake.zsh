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
#!/bin/sh
case "\$*" in
  "-g batt") cat "\${AWAKE_FIXTURE_BATT:-$FX/batt-ac.txt}" ;;
  "-g log")  cat "$FX/log-sleeps.txt" ;;
esac
STUB
# pmset: $S/batt.cur (a fixture path) overrides the battery capture at call time (a running watchdog sees changes);
# $S/sleepdisabled present = `pmset -g` carries a SleepDisabled line (absent when 0, as on the real Mac).
cat > "$S/bin/pmset" <<STUB
#!/bin/sh
case "\$*" in
  "-g batt") if [ -f "$S/batt.cur" ]; then cat "\$(cat "$S/batt.cur")"; else cat "\${AWAKE_FIXTURE_BATT:-$FX/batt-ac.txt}"; fi ;;
  "-g log")  cat "$FX/log-sleeps.txt" ;;
  "-g")      printf 'System-wide power settings:\nCurrent Power Settings:\n standby 1\n'; [ -f "$S/sleepdisabled" ] && printf ' SleepDisabled\t\t1\n' ;;
esac
STUB
# sudo: logs argv; `-n -l <cmd>` answers from the fixture named in $S/sudo.mode (default: the Privilege Manager capture, exit 0);
# `-n /usr/bin/pmset -a disablesleep 1|0` sets or clears $S/sleepdisabled. Never the real sudo.
cat > "$S/bin/sudo" <<STUB
#!/bin/sh
echo "\$*" >> "$S/sudo.args"
if [ "\$1 \$2" = "-n -l" ]; then
  f="\$(cat "$S/sudo.mode" 2>/dev/null || echo "$FX/sudo-l-privmgr.txt")"
  for a; do last="\$a"; done
  sed "s/disablesleep 1\\$/disablesleep \$last/" "\$f"; exit 0
fi
[ "\$*" = "-n /usr/bin/pmset -a disablesleep 1" ] && { : > "$S/sleepdisabled"; exit 0; }
[ "\$*" = "-n /usr/bin/pmset -a disablesleep 0" ] && [ -f "$S/sudo.fail0" ] && exit 1
[ "\$*" = "-n /usr/bin/pmset -a disablesleep 0" ] && { rm -f "$S/sleepdisabled"; exit 0; }
exit 1
STUB
chmod +x "$S/bin/caffeinate" "$S/bin/pmset" "$S/bin/sudo"
export PATH="$S/bin:$PATH" TZ=America/New_York TC_AWAKE_TICK=1
AF="$TC_STATE/awake.json"
stubpids() { pgrep -f "$S/real/caffeinate" }
nstub() { stubpids | wc -l | tr -d ' ' }
WDS=()   # watchdog pids seen, killed at exit
cleanup() { local p; for p in $WDS; do kill $p 2>/dev/null; done; for p in ${(f)"$(pgrep -f "$S/real/" 2>/dev/null)"}; do kill $p 2>/dev/null; done; rm -rf "$S" }
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

# --- lid mode (sudo and pmset are stubs; TC_AWAKE_TICK=1 makes the watchdog tick every second)
waitfor() { local i; for i in {1..60}; do eval "$1" && return 0; sleep 0.1; done; return 1 }
ndis() { grep -c "^-n /usr/bin/pmset -a disablesleep $1\$" "$S/sudo.args" 2>/dev/null }   # grep -c prints 0 itself
wdalive() { [[ "$(ps -o args= -p "$1" 2>/dev/null)" == *"tmux-ctl awake _watchdog"* ]] }
allow() { print -r -- "$FX/sudo-l-allowed.txt" > "$S/sudo.mode" }
deny() { rm -f "$S/sudo.mode" }
lidfile() { jq -r "$1" "$AF" 2>/dev/null }
$C awake off >/dev/null; rm -f "$S/sudo.args" "$S/sleepdisabled" "$S/batt.cur" "$TC_STATE/awake.log"

out="$($C awake lid-setup)"; rc=$?
check "lid-setup: sudoers line"                zsh -c '[[ $1 == *"$2 ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1"* ]]' _ "$out" "$(id -un)"
check "lid-setup: visudo command"              zsh -c '[[ $1 == *"sudo visudo -f /etc/sudoers.d/agent-board-awake"* ]]' _ "$out"
check "lid-setup: exit 0"                      test $rc -eq 0
check "lid-setup: installs and runs nothing"   test ! -e "$S/sudo.args" -a ! -e "$AF" -a "$(nstub)" = 0

# rule absent: the real Privilege Manager capture exits 0 and lists no command
out="$($C awake on --lid --pid $W)"; rc=$?
check "no rule (Privilege Manager rc 0): unavailable message"  zsh -c '[[ $1 == *"awake: lid hold unavailable (run tmux-ctl awake lid-setup)"* ]]' _ "$out"
check "no rule: exit 0"                        test $rc -eq 0
check "no rule: plain hold kept"               test "$(nstub)" = 1 -a "$(lidfile .pid)" = "$W"
check "no rule: no lid fields"                 test "$(lidfile '[has("lid"),has("watchdogPid")]|any')" = false
check "no rule: disablesleep never called"     test "$(ndis 1)" = 0 -a ! -e "$S/sleepdisabled"
check "no rule: the rule was asked with sudo -n -l"  grep -qx -- '-n -l /usr/bin/pmset -a disablesleep 1' "$S/sudo.args"
$C awake off >/dev/null

# rule present
allow; rm -f "$S/sudo.args"
out="$($C awake on --lid --pid $W)"; rc=$?
wd1="$(lidfile .watchdogPid)"; WDS+=($wd1)
check "lid on: ventilation message"            zsh -c '[[ $1 == *"awake: lid hold on: the Mac stays awake with the lid shut; keep it ventilated (not in a closed bag on battery for long)"* ]]' _ "$out"
check "lid on: exit 0"                         test $rc -eq 0
check "lid on: disablesleep 1 called once"     test "$(ndis 1)" = 1
check "lid on: awake.json lid true"            test "$(lidfile .lid)" = true
check "lid on: awake.json watchdogPid is a watchdog"  wdalive "$wd1"
check "lid on: file keeps the base fields"     test "$(lidfile '[.pid,.caffeinatePid,.since]|map(type)|join(",")')" = "number,number,string"
check "lid on: SleepDisabled set"              test -e "$S/sleepdisabled"
out="$($C awake on --lid --pid $W)"
check "lid on twice: already on"               zsh -c '[[ $1 == "awake: already on"* ]]' _ "$out"
check "lid on twice: disablesleep 1 still once"  test "$(ndis 1)" = 1
check "lid on twice: same watchdog"            test "$(lidfile .watchdogPid)" = "$wd1"
out="$($C awake status)"
check "status: lid on"                         zsh -c '[[ $1 == *"lid: on"* ]]' _ "$out"
check "status: no stale warning when owned"    zsh -c '[[ $1 != *"stale lid hold"* ]]' _ "$out"

# off releases and kills only the recorded watchdog
sleep 300 & bystander=$!
$C awake off >/dev/null
check "off: disablesleep 0 called once"        test "$(ndis 0)" = 1
check "off: SleepDisabled cleared"             test ! -e "$S/sleepdisabled"
check "off: watchdog killed"                   waitfor '! kill -0 '$wd1' 2>/dev/null'
check "off: file removed"                      test ! -e "$AF"
out="$($C awake status)"
check "status after off: lid off"              zsh -c '[[ $1 == *"lid: off"* ]]' _ "$out"
print -r -- "{\"pid\": $W, \"caffeinatePid\": $bystander, \"since\": \"2020-01-01T00:00:00Z\", \"lid\": true, \"watchdogPid\": $bystander}" > "$AF"
$C awake off >/dev/null
check "off: a recorded pid that is not the watchdog is left alone"  kill -0 $bystander
kill $bystander
rm -f "$S/sudo.args"

# battery 25%: no lid hold
print -r -- "$FX/batt-battery-25.txt" > "$S/batt.cur"
out="$($C awake on --lid --pid $W)"; rc=$?
check "battery 25%: message"                   zsh -c '[[ $1 == *"awake: battery 25%: no lid hold below 30%"* ]]' _ "$out"
check "battery 25%: exit 0, plain hold, no lid"  test $rc -eq 0 -a "$(nstub)" = 1 -a "$(lidfile 'has("lid")')" = false
check "battery 25%: disablesleep 1 not called"   test "$(ndis 1)" = 0
$C awake off >/dev/null
print -r -- "$FX/batt-battery.txt" > "$S/batt.cur"
out="$($C awake on --lid --pid $W)"; WDS+=("$(lidfile .watchdogPid)")
check "battery 80%: lid hold on"               zsh -c '[[ $1 == *"lid hold on"* ]]' _ "$out"
$C awake off >/dev/null
rm -f "$S/batt.cur"

# watchdog: the lead dies
sleep 300 & lead=$!
$C awake on --lid --pid $lead >/dev/null; wd2="$(lidfile .watchdogPid)"; WDS+=($wd2); rm -f "$S/sudo.args"
check "watchdog (lead): running"               wdalive "$wd2"
kill $lead
check "watchdog (lead): releases within a few ticks"  waitfor '[[ ! -e "$S/sleepdisabled" ]]'
check "watchdog (lead): disablesleep 0 called"  test "$(ndis 0)" -ge 1
check "watchdog (lead): lid fields removed"     waitfor 'test "$(lidfile "[has(\"lid\"),has(\"watchdogPid\")]|any")" = false'
check "watchdog (lead): watchdog exited"        waitfor '! kill -0 '$wd2' 2>/dev/null'
$C awake off >/dev/null

# watchdog: battery below 15% on battery
$C awake on --lid --pid $W >/dev/null; wd3="$(lidfile .watchdogPid)"; WDS+=($wd3)
print -r -- "$FX/batt-ac-10.txt" > "$S/batt.cur"
sleep 2.5
check "watchdog: 10% on AC does not release"    test -e "$S/sleepdisabled" -a "$(lidfile .lid)" = true
print -r -- "$FX/batt-battery-10.txt" > "$S/batt.cur"
check "watchdog (battery): releases within a few ticks"  waitfor '[[ ! -e "$S/sleepdisabled" ]]'
check "watchdog (battery): lid fields removed"  waitfor 'test "$(lidfile "[has(\"lid\"),has(\"watchdogPid\")]|any")" = false'
check "watchdog (battery): logged"              grep -qx 'awake: lid hold released: battery 10%' "$TC_STATE/awake.log"
check "watchdog (battery): watchdog exited"     waitfor '! kill -0 '$wd3' 2>/dev/null'
check "watchdog (battery): plain hold stays"    test "$(nstub)" = 1
$C awake off >/dev/null
rm -f "$S/batt.cur"

# release fails (sudo refuses disablesleep 0): the record stays, the failure is said, never a silent "off"
RF="awake: lid hold release failed (run: sudo pmset -a disablesleep 0)"
allow; $C awake on --lid --pid $W >/dev/null; wd4="$(lidfile .watchdogPid)"; WDS+=($wd4); : > "$S/sudo.fail0"
err="$($C awake off 2>&1 >/dev/null)"; rc=$?
check "off, release fails: stderr message"     test "$err" = "$RF"
check "off, release fails: exit 1"             test $rc -eq 1
check "off, release fails: lid fields kept"    test "$(lidfile .lid)" = true -a "$(lidfile .watchdogPid)" = "$wd4"
check "off, release fails: SleepDisabled still set"  test -e "$S/sleepdisabled"
check "off, release fails: caffeinate stopped" test "$(nstub)" = 0
check "off, release fails: watchdog kept for the retry"  wdalive "$wd4"
out="$($C awake status)"
check "status after failed off: lid on, no stale warning"  zsh -c '[[ $1 == *"lid: on"* && $1 != *"stale lid hold"* ]]' _ "$out"
rm -f "$S/sudo.fail0"
out="$($C awake off 2>&1)"; rc=$?
check "off retry: succeeds"                    test "$out" = "awake: off" -a $rc -eq 0
check "off retry: released and record gone"    test ! -e "$S/sleepdisabled" -a ! -e "$AF"
check "off retry: watchdog killed"             waitfor '! kill -0 '$wd4' 2>/dev/null'
# the watchdog path: lead dies while sudo refuses, then sudo recovers on a later tick
sleep 300 & lead=$!
$C awake on --lid --pid $lead >/dev/null; wd5="$(lidfile .watchdogPid)"; WDS+=($wd5); : > "$S/sudo.fail0"; rm -f "$TC_STATE/awake.log"
kill $lead
check "watchdog, release fails: logs it"       waitfor 'grep -qxF "$RF" "$TC_STATE/awake.log"'
check "watchdog, release fails: keeps lid fields and keeps running"  test "$(lidfile .lid)" = true -a "$(lidfile .watchdogPid)" = "$wd5" && wdalive "$wd5"
check "watchdog, release fails: SleepDisabled still set"  test -e "$S/sleepdisabled"
rm -f "$S/sudo.fail0"
check "watchdog: retries and releases on a later tick"  waitfor '[[ ! -e "$S/sleepdisabled" ]]'
check "watchdog: lid fields removed after the retry"    waitfor 'test "$(lidfile "[has(\"lid\"),has(\"watchdogPid\")]|any")" = false'
$C awake off >/dev/null
deny

# stale: SleepDisabled 1 with no lid record
deny; : > "$S/sleepdisabled"; rm -f "$S/sudo.args"
STALE="awake: stale lid hold: SleepDisabled is 1 with no owner; run tmux-ctl awake off"
out="$($C awake status)"
check "stale: status warns"                    zsh -c '[[ $1 == *"$2"* ]]' _ "$out" "$STALE"
out="$($C awake on --pid $W)"
check "stale: on warns"                        zsh -c '[[ $1 == *"$2"* ]]' _ "$out" "$STALE"
$C awake off >/dev/null
check "stale, no rule: off leaves it and says so"  test -e "$S/sleepdisabled"
allow
$C awake off >/dev/null
check "stale, rule present: off clears it"     test ! -e "$S/sleepdisabled"
check "stale: off called disablesleep 0"       test "$(ndis 0)" -ge 1
out="$($C awake status)"
check "stale cleared: no warning"              zsh -c '[[ $1 != *"stale lid hold"* ]]' _ "$out"
deny

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
check "leak: no watchdog left"                 test "$(pgrep -f "tmux-ctl awake _watchdog" | wc -l | tr -d " ")" = 0
tt_done
