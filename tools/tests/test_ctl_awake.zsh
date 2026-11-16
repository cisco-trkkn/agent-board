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
mkdir -p "$S/real/lnk"; ln -s /bin/zsh "$S/real/lnk/claude"   # comm is claude, but on Linux the exe path (/proc) resolves to /bin/zsh
mkdir -p "$S/real/claude/versions"; cp /bin/zsh "$S/real/claude/versions/9.9.9"   # how Claude Code runs: basename is a version number
codesign -s - -f "$S/real/caffeinate" "$S/real/claude-fake" "$S/real/claude/versions/9.9.9" 2>/dev/null   # a copied platform binary is killed on macOS until re-signed
cat > "$S/bin/caffeinate" <<STUB
#!/bin/sh
echo "\$*" >> "$S/caffeinate.args"
exec "$S/real/caffeinate" 600
STUB
# pmset: $S/batt.cur (a fixture path) overrides the battery capture at call time (a running watchdog sees changes);
# $S/log.cur (a fixture path) overrides the `pmset -g log` capture the same way;
# $S/sleepdisabled present = `pmset -g` carries a SleepDisabled line (absent when 0, as on the real Mac).
cat > "$S/bin/pmset" <<STUB
#!/bin/sh
case "\$*" in
  "-g batt") if [ -f "$S/batt.cur" ]; then cat "\$(cat "$S/batt.cur")"; else cat "\${AWAKE_FIXTURE_BATT:-$FX/batt-ac.txt}"; fi ;;
  "-g log")  if [ -f "$S/log.cur" ]; then cat "\$(cat "$S/log.cur")"; else cat "$FX/log-sleeps.txt"; fi ;;
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
out="$("$S/real/claude/versions/9.9.9" -c "$C awake on; true")"
check "versioned claude ancestor (.../claude/versions/9.9.9) found"  zsh -c '[[ $1 == "awake: on (pid "*", watching "[0-9]*")" ]]' _ "$out"
check "versioned ancestor: pid is not the test shell"  test "$(jq -r .pid "$AF")" != "$W"
$C awake off >/dev/null
out="$("$S/real/lnk/claude" -c "$C awake on; true")"
check "claude by comm, exe elsewhere (symlink named claude) found"  zsh -c '[[ $1 == "awake: on (pid "*", watching "[0-9]*")" ]]' _ "$out"
$C awake off >/dev/null

# --- sleeps
out="$($C awake sleeps '2026-11-07 10:28' --all)"
check "sleeps --all local: first line"         test "$(print -r -- "$out" | head -1)" = "2026-11-07 10:28:22 DarkWake Deep Idle"
check "sleeps --all local: sleep reason"       sh -c "printf %s '$out' | grep -qx '2026-11-07 10:28:24 Sleep Sleep Service Back to Sleep'"
check "sleeps --all local: nothing before the cutoff"  test -z "$(print -r -- "$out" | grep '10:12:')"
check "sleeps --all: Wake Requests excluded"   test -z "$(print -r -- "$out" | grep -i 'request')"
iso="$($C awake sleeps '2026-11-07T15:28:00Z' --all)"
check "sleeps --all ISO UTC == local equivalent"  test "$iso" = "$out"
all="$($C awake sleeps --all '2000-01-01 00:00')"
check "sleeps --all: a real Wake line is listed"  test "$(print -r -- "$all" | awk '$3=="Wake"' | wc -l | tr -d ' ')" -ge 1
check "sleeps --all: only three types"         test -z "$(print -r -- "$all" | awk '$3!="Sleep"&&$3!="Wake"&&$3!="DarkWake"')"
check "sleeps --all: line count = fixture minus Wake Requests"  test "$(print -r -- "$all" | wc -l | tr -d ' ')" = "$(grep -vc 'Wake Requests' "$FX/log-sleeps.txt")"
out="$($C awake sleeps '2099-01-01 00:00' --all)"; rc=$?
check "sleeps --all: none prints nothing, exit 0"  test -z "$out" -a $rc -eq 0
# default: one line per real sleep period (spec 2026-11-10-queue-reliability §5)
out="$($C awake sleeps '2000-01-01 00:00')"
check "sleeps: the real capture has one real period (Low Power Sleep, ended by the next Wake)"  test "$out" = "2026-11-07 11:52:58 – 2026-11-09 10:30:32 Low Power Sleep"
print -r -- "$FX/log-sleeps-kinds.txt" > "$S/log.cur"   # one of every Sleep reason kind
KINDS=(
  "2026-11-10 20:31:19 – 2026-11-10 21:03:05 Idle Sleep"
  "2026-11-11 08:46:33 – 2026-11-11 08:59:20 Clamshell Sleep"
  "2026-11-11 09:30:00 – 2026-11-11 09:45:00 Low Power Sleep"
  "2026-11-11 10:00:00 – 2026-11-11 10:05:00 Software Sleep"
  "2026-11-11 23:00:00 – … Idle Sleep"
)
out="$($C awake sleeps '2000-01-01 00:00')"; rc=$?
check "sleeps: only real periods, each ended by the next Wake, the open one by …"  test "$out" = "${(F)KINDS}" -a $rc -eq 0
check "sleeps: no Maintenance, Sleep Service, Notification Wake or DarkWake line"  test -z "$(print -r -- "$out" | grep -E 'Maintenance|Sleep Service|Notification|DarkWake')"
check "sleeps: a reason not on the deny-list shows (Software Sleep)"  zsh -c '[[ $1 == *"Software Sleep"* ]]' _ "$out"
out="$($C awake sleeps '2026-11-11 09:00')"
check "sleeps: periods that start before the cutoff are left out"  test "$out" = "${(F)KINDS[3,5]}"
iso="$($C awake sleeps '2026-11-11T14:00:00Z')"
check "sleeps ISO UTC == local equivalent"     test "$iso" = "$out"
all="$($C awake sleeps '2000-01-01 00:00' --all)"
check "sleeps --all on the same log: every Sleep, Wake and DarkWake line"  test "$(print -r -- "$all" | wc -l | tr -d ' ')" = "$(grep -vc 'Wake Requests' "$FX/log-sleeps-kinds.txt")"
check "sleeps --all keeps the old line format"  test "$(print -r -- "$all" | sed -n 2p)" = "2026-11-10 20:45:00 DarkWake Deep Idle"
out="$($C awake sleeps '2099-01-01 00:00')"; rc=$?
check "sleeps: none prints nothing, exit 0"    test -z "$out" -a $rc -eq 0
$C awake sleeps >/dev/null 2>&1; check "sleeps without a time: exit 2"  test $? -eq 2
$C awake sleeps --all >/dev/null 2>&1; check "sleeps --all without a time: exit 2"  test $? -eq 2
$C awake sleeps '2026-11-11 09:00' extra >/dev/null 2>&1; check "sleeps with two times: exit 2"  test $? -eq 2
rm -f "$S/log.cur"

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

# --- queue holds (spec 2026-11-10-queue-reliability §4): bound to the tmux server, so a relay does not end them
allow; $C awake off >/dev/null; rm -f "$S/caffeinate.args" "$S/sudo.args"
SRV="$(tt display -p '#{pid}')"   # the scratch tmux server: what `tmux display -p '#{pid}'` prints (probed on tmux 3.8)
out="$($C awake on --queue)"; rc=$?
cpq="$(lidfile .caffeinatePid)"
check "queue on: watches the tmux server pid"   test "$out" = "awake: on (pid $cpq, watching $SRV)" -a $rc -eq 0
check "queue on: caffeinate -i -s -w <server pid>"  test "$(<$S/caffeinate.args)" = "-i -s -w $SRV"
check "queue on: awake.json has queue true and the server pid"  test "$(lidfile .queue)" = true -a "$(lidfile .pid)" = "$SRV"
out="$($C awake status)"
check "status: queue line for a queue hold"     zsh -c '[[ $1 == "on (pid $2, watching $3, since "*$'"'"'\nqueue: on\nlid: off\n'"'"'* ]]' _ "$out" $cpq $SRV
out="$($C awake on --pid $W)"
check "non-queue on over a queue hold: already on (queue)"  test "$out" = "awake: already on (queue)"
out="$("$S/real/claude-fake" -c "$C awake on; true")"
check "a claude's own on over a queue hold: already on (queue)"  test "$out" = "awake: already on (queue)"
out="$($C awake on --queue)"
check "queue on twice: already on (queue)"      test "$out" = "awake: already on (queue)"
check "queue hold unchanged by all three"       test "$(lidfile .pid)" = "$SRV" -a "$(lidfile .caffeinatePid)" = "$cpq" -a "$(nstub)" = 1
out="$($C awake on --queue --pid $W 2>&1)"; rc=$?
check "--queue with --pid: usage, exit 2"       test $rc -eq 2 -a "$out" = "usage: tmux-ctl awake on [--queue | --pid N] [--lid]"
check "--queue with --pid: hold unchanged"      test "$(lidfile .caffeinatePid)" = "$cpq"
$C awake off >/dev/null
out="$(TMUX="$S/no-such-socket,1,0" $C awake on --queue 2>/dev/null)"; rc=$?
check "--queue with no tmux server: message, exit 1"  test "$out" = "awake: no tmux server; run on without --queue" -a $rc -eq 1
check "--queue with no tmux server: nothing started"  test "$(nstub)" = 0 -a ! -e "$AF"

# --- re-point: a live non-queue hold watching another pid moves to the caller
sleep 300 & foreign=$!
$C awake on --pid $foreign >/dev/null; cpf="$(lidfile .caffeinatePid)"
out="$($C awake status)"
check "status: no queue line for a plain hold"  zsh -c '[[ $1 != *queue* ]]' _ "$out"
out="$(TC_AWAKE_ANCESTOR=zz-no-such-name $C awake on)"
check "caller with no claude ancestor: the foreign hold is kept"  zsh -c '[[ $1 == "awake: already on (pid $2, since "*")" ]]' _ "$out" $cpf
out="$("$S/real/claude-fake" -c "$C awake on; true")"
me="$(lidfile .pid)"
check "re-point: message names old and new pid" test "$out" = "awake: on (re-pointed from $foreign to $me)"
check "re-point: the new pid is the caller's claude ancestor, not the foreign pid"  test -n "$me" -a "$me" != "$foreign" -a "$me" != "$W"
check "re-point: old caffeinate killed, one running"  zsh -c '! kill -0 $1 2>/dev/null && [[ $2 == 1 ]]' _ $cpf "$(nstub)"
check "re-point: awake.json points at the new caffeinate, no queue"  test "$(lidfile .caffeinatePid)" != "$cpf" -a "$(lidfile '.queue // false')" = false
check "re-point: the recorded pid is a caffeinate"  test "$(basename "$(ps -o comm= -p "$(lidfile .caffeinatePid)")")" = caffeinate
out="$($C awake on --pid $W)"
check "re-point with --pid: to that pid"        test "$out" = "awake: on (re-pointed from $me to $W)" -a "$(lidfile .pid)" = "$W"
out="$($C awake on --pid $W)"
check "same owner again: already on, no re-point"  zsh -c '[[ $1 == "awake: already on (pid "* ]]' _ "$out"
before="$(<"$AF")"; cpb="$(lidfile .caffeinatePid)"
out="$($C awake on --pid abc 2>&1 >/dev/null)"; rc=$?
check "on --pid abc over a live hold: usage on stderr, exit 2"  test "$out" = "usage: tmux-ctl awake on [--queue | --pid N] [--lid]" -a $rc -eq 2
check "on --pid abc: awake.json byte-identical"  test "$(<"$AF")" = "$before"
check "on --pid abc: the live caffeinate is not killed"  kill -0 $cpb
$C awake off >/dev/null

# --- re-point keeps lid and watchdogPid; the watchdog follows the re-pointed pid
rm -f "$S/sudo.args"
$C awake on --lid --pid $foreign >/dev/null; wdr="$(lidfile .watchdogPid)"; WDS+=($wdr)
out="$($C awake on --queue --lid)"
check "queue on over a plain hold: re-pointed to the tmux server"  test "$(print -r -- "$out" | head -1)" = "awake: on (re-pointed from $foreign to $SRV)"
check "queue re-point: queue true"              test "$(lidfile .queue)" = true -a "$(lidfile .pid)" = "$SRV"
check "queue re-point: lid and watchdogPid kept"  test "$(lidfile .lid)" = true -a "$(lidfile .watchdogPid)" = "$wdr"
check "queue re-point: disablesleep 1 not called again"  test "$(ndis 1)" = 1
kill $foreign; sleep 2.5   # two watchdog ticks after the first owner died
check "watchdog follows the re-pointed pid: lid hold still on"  test -e "$S/sleepdisabled" -a "$(lidfile .lid)" = true
check "watchdog follows the re-pointed pid: still running"  wdalive "$wdr"
$C awake off >/dev/null
check "off ends a queue hold"                   test ! -e "$AF" -a "$(nstub)" = 0 -a ! -e "$S/sleepdisabled"
$C awake on --queue --lid >/dev/null; wdq="$(lidfile .watchdogPid)"; WDS+=($wdq)
check "queue + lid: the watchdog's lead pid is the tmux server"  zsh -c '[[ "$(ps -o args= -p $1)" == *"awake _watchdog $2" ]]' _ "$wdq" "$SRV"
$C awake off >/dev/null
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
alivewd=0; for p in $WDS; do [[ -n "$p" ]] && wdalive $p && (( alivewd++ )); done   # only the watchdogs this test started
check "leak: no watchdog of this test left"    test $alivewd = 0
tt_done
