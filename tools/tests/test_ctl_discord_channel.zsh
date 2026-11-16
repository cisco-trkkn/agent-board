source "${0:A:h}/lib.zsh"
# tmux-ctl discord channel|bridge install|start|stop|audit and the channel/bridge lines of status.
# Scratch tmux server from lib.zsh; HOME and TC_STATE are temp; node and npm are fakes on PATH; the bridge dir is a scratch copy (TC_DISCORD_BRIDGE_DIR).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_TMUX="$TT_BIN"
tt_setup claude
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdcc.XXXXXX"):A}"
mkdir -p "$S/bin" "$S/home" "$S/cfg" "$S/bridge"
export HOME="$S/home" CLAUDE_CONFIG_DIR="$S/cfg" TC_DISCORD_BRIDGE_DIR="$S/bridge"
cat > "$S/bin/node" <<STUB
#!/bin/sh
echo "\$@" > "$S/node.args"
exec sleep 300
STUB
cat > "$S/bin/npm" <<STUB
#!/bin/sh
echo "\$PWD \$*" >> "$S/npm.log"
STUB
cat > "$S/bridge.js" <<'STUB'
#!/bin/sh
trap 'kill $!; exit 0' TERM
sleep 300 &
wait
STUB
chmod +x "$S/bin/node" "$S/bin/npm" "$S/bridge.js"
export PATH="$S/bin:$PATH"
tt set-environment -g PATH "$PATH"      # windows the bridge start creates inherit the fakes
D="$TC_STATE/discord/tt"
A="$D/access.json"; B="$D/bridge.json"
N=0; PIDS=()
cleanup() { (( ${#PIDS} )) && kill $PIDS 2>/dev/null; rm -rf "$S" }
trap 'cleanup; tt_teardown' EXIT INT TERM
run() { (( N++ )); "$@" > "$S/out.$N" 2>&1; rc=$?; out="$(<$S/out.$N)" }
mt() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" }
mkdir -p "$D"; chmod 700 "$D"
seed() { print -r -- '{"dmPolicy":"allowlist","allowFrom":["11","22"],"groups":{"g":{"x":1}},"pending":{"p":{"a":1}},"ackReaction":"👀"}' > $A; chmod 600 $A; rm -f $B }

# --- channel
seed
run $C discord channel abc
check "channel: non-numeric id exits 2 (usage)" test $rc -eq 2 -a -n "$(grep -i usage $S/out.$N)"
print -r -- '{"dmPolicy":"pairing","allowFrom":[],"groups":{}}' > $A
run $C discord channel 555
check "channel: no allowFrom exits 1 with the message" test $rc -eq 1 -a "$out" = "discord: pair or allow a user first" -a ! -e $B
seed
run $C discord channel 555
check "channel: exit 0 and message" test $rc -eq 0 -a "$out" = "channel: 555"
check "channel: groups entry" test "$(jq -cS '.groups["555"]' $A)" = '{"allowFrom":["11","22"],"requireMention":false}'
check "channel: other keys kept" test "$(jq -cS '[.dmPolicy,.groups.g,.pending,.ackReaction]' $A)" = '["allowlist",{"x":1},{"p":{"a":1}},"👀"]'
check "channel: bridge.json content" test "$(jq -cS . $B)" = '{"channel":"555","user":"11"}'
check "channel: modes 600" test "$(mode $A)" = 600 -a "$(mode $B)" = 600
check "channel: no .next left" test ! -e $A.next -a ! -e $B.next
m1="$(mt $A)"; m2="$(mt $B)"; cp $A $S/a.before; cp $B $S/b.before; sleep 1.2
run $C discord channel 555
check "channel unchanged: message and exit 0" test $rc -eq 0 -a "$out" = "channel: 555 (unchanged)"
check "channel unchanged: files byte-identical" cmp -s $A $S/a.before && cmp -s $B $S/b.before
check "channel unchanged: mtimes unchanged" test "$(mt $A)" = "$m1" -a "$(mt $B)" = "$m2"
run $C discord channel 777
check "channel: a new id adds a second group, keeps the first" test "$(jq -c '.groups|keys' $A)" = '["555","777","g"]' -a "$(jq -r .channel $B)" = 777

# --- status
rm -f $B; rmdir $S/bridge 2>/dev/null; rm -rf $S/bridge
run $C discord status
check "status: channel none, bridge no channel" test -n "$(grep -x 'channel: none' $S/out.$N)" -a -n "$(grep -x 'bridge: no channel' $S/out.$N)"
check "status: new lines come after the watch line" test "$(grep -n '^watch:' $S/out.$N | cut -d: -f1)" -lt "$(grep -n '^channel:' $S/out.$N | cut -d: -f1)" -a "$(grep -n '^channel:' $S/out.$N | cut -d: -f1)" -lt "$(grep -n '^bridge:' $S/out.$N | cut -d: -f1)"
print -r -- '{"channel":"555","user":"11"}' > $B
run $C discord status
check "status: channel id, deps missing" test -n "$(grep -x 'channel: 555' $S/out.$N)" -a -n "$(grep -x 'bridge: deps missing' $S/out.$N)"
mkdir -p $S/bridge/node_modules
run $C discord status
check "status: stopped" test -n "$(grep -x 'bridge: stopped' $S/out.$N)"
"$S/bridge.js" >/dev/null 2>&1 & PIDS+=($!); LP=$!
print -r -- $LP > $D/bridge.pid
run $C discord status
check "status: running with a live bridge.js pid" test -n "$(grep -x "bridge: running (pid $LP)" $S/out.$N)"
sleep 300 >/dev/null 2>&1 & PIDS+=($!); OP=$!
print -r -- $OP > $D/bridge.pid
run $C discord status
check "status: a live pid that is not bridge.js is stopped" test -n "$(grep -x 'bridge: stopped' $S/out.$N)"
kill $OP; rm -f $D/bridge.pid

# --- bridge start
print -r -- 'DISCORD_BOT_TOKEN=x.y' > $D/.env
rm -f $B
run $C discord bridge start --project tt
check "start: no channel refuses, exit 1, one line" test $rc -eq 1 -a "$(wc -l < $S/out.$N | tr -d ' ')" = 1 -a -n "$(grep -i channel $S/out.$N)"
print -r -- '{"channel":"555","user":"11"}' > $B
rm -rf $S/bridge/node_modules
run $C discord bridge start --project tt
check "start: deps missing refuses, exit 1" test $rc -eq 1 -a -n "$(grep -i 'node_modules\|install' $S/out.$N)"
mv $D/.env $D/.env.off
mkdir -p $S/bridge/node_modules
run $C discord bridge start --project tt
check "start: token missing refuses, exit 1" test $rc -eq 1 -a -n "$(grep -i token $S/out.$N)"
mv $D/.env.off $D/.env
run env TC_DISCORD_BRIDGE=0 $C discord bridge start --project tt
check "start: TC_DISCORD_BRIDGE=0 starts nothing" test $rc -eq 0 -a -z "$(tt list-windows -a -F '#{session_name}:#{window_name}' | grep -x 'tt-bg:discord')"
check "start: refusals created no tt-bg session" test -z "$(tt list-sessions -F '#{session_name}' | grep -x tt-bg)"
run env -u TMUX -u TMUX_PANE AGENT_BOARD_TMUX_SOCKET="$TT_SOCK_NAME" $C discord bridge start --project tt
check "start: creates tt-bg with window discord" test $rc -eq 0 -a -n "$(tt list-windows -t '=tt-bg:' -F '#{window_name}' | grep -x discord)"
check "start: tt-bg got tests and shell windows and @tc_bg" test -n "$(tt list-windows -t '=tt-bg:' -F '#{window_name}' | grep -x tests)" -a -n "$(tt list-windows -t '=tt-bg:' -F '#{window_name}' | grep -x shell)" -a -n "$(tt show-options -qv -t '=tt-bg:' @tc_bg)"
for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do [[ -s $S/node.args ]] && break; sleep 0.2; done
check "start: node ran bridge.js <dir>" test "$(<$S/node.args)" = "$TT_REPO/tools/discord-bridge/bridge.js $D"
W1="$(tt list-windows -t '=tt-bg:' -F '#{window_name} #{window_id}' | grep '^discord ')"
run $C discord bridge start --project tt
W2="$(tt list-windows -t '=tt-bg:' -F '#{window_name} #{window_id}' | grep '^discord ')"
check "start: a stale discord window is replaced by a fresh one" test $rc -eq 0 -a -n "$W2" -a "$W1" != "$W2" -a "$(tt list-windows -t '=tt-bg:' -F '#{window_name}' | grep -cx discord)" = 1
"$S/bridge.js" >/dev/null 2>&1 & PIDS+=($!); LP2=$!
print -r -- $LP2 > $D/bridge.pid
tt kill-window -t '=tt-bg:=discord'
run $C discord bridge start --project tt
check "start: live bridge pid is a no-op" test $rc -eq 0 -a "$out" = "bridge: running (pid $LP2)" -a -z "$(tt list-windows -t '=tt-bg:' -F '#{window_name}' | grep -x discord)"

# --- bridge stop / install
run $C discord bridge stop --project tt
check "stop: TERM sent to the live pid" test $rc -eq 0
for i in 1 2 3 4 5 6 7 8 9 10; do kill -0 $LP2 2>/dev/null || break; sleep 0.2; done
check "stop: process gone" test ! "$(kill -0 $LP2 2>/dev/null && echo up)"
print -r -- 999999 > $D/bridge.pid
run $C discord bridge stop --project tt
check "stop: stale pid file removed" test $rc -eq 0 -a ! -e $D/bridge.pid
run $C discord bridge install --project tt
check "install: npm ci --omit=dev in the bridge dir" test $rc -eq 0 -a "$(<$S/npm.log)" = "$S/bridge ci --omit=dev"

# --- audit
rm -f $D/audit.jsonl
run $C discord audit --project tt
check "audit: missing file prints audit: none" test $rc -eq 0 -a "$out" = "audit: none"
cat > $D/audit.jsonl <<'J'
{"ts":"2026-11-15T10:00:00Z","user":"11","action":"pause","target":"queue","result":"ok"}
{"ts":"2026-11-16T09:30:00Z","user":"22","action":"resume","target":"queue","result":"ignored"}
J
run $C discord audit --project tt
check "audit: lines formatted" test "$out" = "2026-11-15T10:00:00Z 11 pause queue ok
2026-11-16T09:30:00Z 22 resume queue ignored"
run $C discord audit --since 2026-11-16T00:00:00Z --project tt
check "audit --since filters older lines" test "$out" = "2026-11-16T09:30:00Z 22 resume queue ignored"

# --- usage / leaks
h="$($C help)"
check "help: lists channel, bridge and audit" test -n "$(print -r -- "$h" | grep 'discord channel')" -a -n "$(print -r -- "$h" | grep 'bridge install|start|stop')" -a -n "$(print -r -- "$h" | grep 'audit \[--since')"
check "leak: no stray discord window in the main session" test -z "$(tt list-windows -t '=tt:' -F '#{window_name}' | grep -x discord)"
tt_done
