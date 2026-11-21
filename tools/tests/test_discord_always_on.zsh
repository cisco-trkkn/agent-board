source "${0:A:h}/lib.zsh"
# Discord always-on: part 2 (the launcher clears the stale MCP failure) and part 3 (the watchdog and its launchd job).
# Everything runs against scratch dirs: CLAUDE_CONFIG_DIR, TC_STATE and HOME are temp, `claude` is a stub.
export TC_TMUX="$TT_BIN"
tt_setup claude
REAL_PLISTS="$(ls ~/Library/LaunchAgents 2>/dev/null | grep -c agent-board-discord-watch.plist)"
RT="$TT_DIR/home"; mkdir -p "$RT"
CFG="$TT_DIR/cfg"; mkdir -p "$CFG"
STUB="$TT_DIR/stub"; S="$TT_DIR/out"; mkdir -p "$STUB" "$S"
cat > "$STUB/claude" <<STUBEOF
#!/bin/zsh
print -rl -- "\$@" > $S/argv
STUBEOF
chmod +x "$STUB/claude"
not() { ! "$@" }
ORIG_PATH="$PATH"
CACHE="$CFG/mcp-needs-auth-cache.json"
KEY='plugin:discord:discord'
seed() { print -r -- '{"plugin:gitlab:gitlab":{"timestamp":1},"plugin:discord:discord":{"timestamp":2,"id":"abc"}}' > "$CACHE" }
haskey() { jq -e --arg k "$1" 'has($k)' "$CACHE" >/dev/null 2>&1 }

# --- part 2b: the launcher calls it, only for a lead with a token
DCD="$TC_STATE/discord/tt"
L="$TT_REPO/bin/claude-orchestrator"
run() { rm -f $S/argv; env HOME="$RT" CLAUDE_CONFIG_DIR="$CFG" PATH="$STUB:$ORIG_PATH" "$@" >/dev/null 2>&1 }
rm -rf "$DCD"; seed
run "$L"
check "launcher: no token: cache untouched"  haskey "$KEY"
mkdir -p "$DCD"; print -r -- "DISCORD_BOT_TOKEN=1:x" > "$DCD/.env"; seed
run "$L"
check "launcher: token: claude still started" test -s $S/argv
check "launcher: token: discord key cleared" not haskey "$KEY"
check "launcher: token: other key kept"       haskey plugin:gitlab:gitlab
seed; run TC_DISCORD=0 "$L"
check "launcher: TC_DISCORD=0: cache untouched" haskey "$KEY"
print -r -- 'garbage' > "$CACHE"; run "$L"
check "launcher: bad cache JSON: claude still starts" test -s $S/argv
rm -f "$CACHE"; run "$L"
check "launcher: missing cache: claude still starts" test -s $S/argv
# a failing helper never blocks the launch
mkdir -p "$TT_DIR/repo3/bin" "$TT_DIR/repo3/tools" "$TT_DIR/repo3/claude"; cp "$TT_REPO"/bin/{claude-orchestrator,_ab_claude.zsh,_tc_bins.zsh} "$TT_DIR/repo3/bin/"
print -r -- 'import sys; sys.exit(3)' > "$TT_DIR/repo3/tools/discord_cache.py"
run "$TT_DIR/repo3/bin/claude-orchestrator"
check "launcher: failing helper: claude still starts" test -s $S/argv

# --- part 3: `tmux-ctl discord watch --once` against a fake claude TUI in a scratch tmux window
if (( ! $+commands[python3] )); then print "skip - no python3"; tt_done; exit 0; fi
MARK="dcfake-$$-$RANDOM"
# a failure anywhere below must not leave the stub or its fake server running: reap by this run's own mark only
dc_reap() {
  local p
  for p in $(pgrep -f "$MARK"); do kill $p 2>/dev/null; done
  [[ -n "$(pgrep -f "$MARK")" ]] && { sleep 1; for p in $(pgrep -f "$MARK"); do kill -9 $p 2>/dev/null; done }
  return 0
}
trap 'dc_reap; tt_teardown' EXIT INT TERM
ln -sf "${commands[zsh]:A}" "$STUB/claude"   # a process whose command line starts with claude (tmux still calls its command zsh)
FAKE="$TT_REPO/tools/tests/fixtures/fake_claude_tui.zsh"
tt new-window -d -n lead -c "$TT_DIR" "$STUB/claude -f $FAKE $MARK --channels plugin:discord@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead' '#{pane_id}')"
# drawn: the fake TUI has painted its input line (a fixed sleep was too short on a loaded machine, so the ghost / refresh checks read a blank pane)
drawn() { tt capture-pane -p -J -t "$LP" | grep -q '❯' }
tt_wait 20 drawn
watch() { env TC_NOTIFY=0 TC_DISCORD_WATCH_GRACE=0 TC_DISCORD_WATCH_QUIET=0 "$@" "$TT_REPO/bin/tmux-ctl" discord watch --once }
nserv() { pgrep -f "discord/server.ts $MARK" | wc -l | tr -d ' ' }
screen() { tt capture-pane -p -J -t "$LP" }
WLOG="$TC_STATE/discord-watch.log"
# typed text in the input line: never typed over, the user is told instead
tt send-keys -t "$LP" -l 'half a sentence'; sleep 0.5
watch >/dev/null
check "typed text: no server started"      test "$(nserv)" = 0
check "typed text: input untouched"        grep -q 'half a sentence' =(screen)
check "typed text: logged as not typing"   grep -q 'not typing' "$WLOG"
tt send-keys -t "$LP" C-u; sleep 0.5
rm -f "$WLOG"
watch >/dev/null
check "idle: discord server running after one pass" test "$(nserv)" = 1
check "idle: one reconnect line logged"    test "$(grep -c 'reconnect: ok' "$WLOG")" = 1
check "idle: pane back at the prompt"      grep -q '^❯' =(screen)
watch >/dev/null
# (a real lead on this machine may also be down: it has no pane in the scratch server and is logged as such, so count ours only)
check "healthy lead: second pass is a no-op" test "$(grep -c "pane $LP" "$WLOG")" = 1
for p in $(pgrep -f "discord/server.ts $MARK"); do kill $p; done; sleep 0.5; rm -f "$WLOG"
watch TC_DISCORD_WATCH=0 >/dev/null
check "TC_DISCORD_WATCH=0: nothing happens" test "$(nserv)" = 0 -a ! -e "$WLOG"
touch "$TC_STATE/discord-watch.off"; watch >/dev/null
check "flag file: nothing happens"         test "$(nserv)" = 0 -a ! -e "$WLOG"
rm -f "$TC_STATE/discord-watch.off"
# copy mode: keys would start a search, so nothing is typed
tt copy-mode -t "$LP"
watch >/dev/null
check "copy mode: no server started"       test "$(nserv)" = 0
check "copy mode: logged"                  grep -q 'copy mode' "$WLOG"
tt send-keys -t "$LP" -X cancel
# a lead that keeps redrawing (window activity always fresh) is still reconnected: quiet means an untouched empty input line, not no output
rm -f "$WLOG"
tt kill-window -t "$LP"; sleep 0.5
tt new-window -d -n lead3 -c "$TT_DIR" "env FAKE_TICK=1 $STUB/claude -f $FAKE $MARK --channels plugin:discord@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead3' '#{pane_id}')"; tt_wait 20 drawn
check "refreshing: window activity is fresh" test "$(( $(date +%s) - $(tt display -p -t "$LP" '#{window_activity}') ))" -le 2
watch TC_DISCORD_WATCH_QUIET=1 >/dev/null
check "refreshing: discord server running" test "$(nserv)" = 1
check "refreshing: reconnect ok logged"    grep -q "pane $LP.*reconnect: ok" "$WLOG"
for p in $(pgrep -f "discord/server.ts $MARK"); do kill $p; done; sleep 0.5
# text typed between the two captures: nothing is typed, the user's text stays
rm -f "$WLOG" "$TC_STATE/discord-watch.json"
# the text must land between the watch's two captures: the first one comes after the watch's own startup (seconds on a loaded machine), so
# the gap is 8 s and the text is typed 4 s after the start (1 s / 3 s typed it before the first capture under load)
( sleep 4; tt send-keys -t "$LP" -l 'mid-gap' ) &
watch TC_DISCORD_WATCH_QUIET=8 >/dev/null; wait
check "typed in the gap: no server started" test "$(nserv)" = 0
check "typed in the gap: logged as not quiet" grep -q "pane $LP.*input line not quiet" "$WLOG"
check "typed in the gap: the user's text is untouched" grep -q '^❯ mid-gap$' =(screen)
# a dim prompt suggestion on the input line (Claude's greyed "auto prompt") is not typed text: the lead is reconnected
rm -f "$WLOG" "$TC_STATE/discord-watch.json"
tt kill-window -t "$LP"; sleep 0.5
tt new-window -d -n lead4 -c "$TT_DIR" "env FAKE_GHOST=1 $STUB/claude -f $FAKE $MARK --channels plugin:discord@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead4' '#{pane_id}')"; tt_wait 20 drawn
check "ghost: the pane draws a dim suggestion" grep -q $'\e\\[2mrun it' =(tt capture-pane -p -e -J -t "$LP")
watch >/dev/null
check "ghost: discord server running"     test "$(nserv)" = 1
check "ghost: reconnect ok logged"         grep -q "pane $LP.*reconnect: ok" "$WLOG"
for p in $(pgrep -f "discord/server.ts $MARK"); do kill $p; done; sleep 0.5
# a failed reconnect backs off: a lead whose server never appears is typed into once, not every pass
rm -f "$WLOG" "$TC_STATE/discord-watch.json"
tt kill-window -t "$LP"; sleep 0.5
tt new-window -d -n lead2 -c "$TT_DIR" "$STUB/claude -f $TT_REPO/tools/tests/fixtures/fake_claude_tui_broken.zsh $MARK --channels plugin:discord@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead2' '#{pane_id}')"; tt_wait 20 drawn
watch >/dev/null; watch >/dev/null; watch >/dev/null
check "backoff: three passes, one reconnect attempt" test "$(grep -c "pane $LP.*reconnect:" "$WLOG")" = 1
check "backoff: one banner line"           test "$(grep -c "pane $LP.*notified" "$WLOG")" = 1
tt kill-window -t "$LP"; sleep 0.5; for p in $(pgrep -f "discord/server.ts $MARK"); do kill $p; done
check "leak: no fake server left"          test "$(nserv)" = 0
check "leak: no fake lead left"            test "$(pgrep -f "fake_claude_tui.zsh $MARK" | wc -l | tr -d ' ')" = 0
check "leak: nothing with the test's mark left" test -z "$(pgrep -f "$MARK")"

# --- part 3: the launchd job through tmux-ctl, against a fake launchctl and a scratch HOME (never the real LaunchAgents)
LC="$TT_DIR/launchctl"; LCALLS="$TT_DIR/lcalls"
print -r -- "#!/bin/sh
echo \"\$@\" >> $LCALLS" > "$LC"; chmod +x "$LC"
mkdir -p "$RT/.local/bin"; ln -sf "$TT_REPO/bin/tmux-ctl" "$RT/.local/bin/tmux-ctl"
PL="$RT/Library/LaunchAgents/com.user.agent-board-discord-watch.plist"
sched() { env TW_HOME="$RT" TW_LAUNCHCTL="$LC" "$TT_REPO/bin/tmux-ctl" discord watch "$@" }
sched install >/dev/null; rc=$?
check "schedule install: exit 0"               test $rc = 0
check "schedule install: plist written"        test -f "$PL"
check "schedule install: StartInterval 60"     grep -q '<integer>60</integer>' "$PL"
check "schedule install: runs watch --once"    grep -q '<string>--once</string>' "$PL"
check "schedule install: bootout then bootstrap" test "$(sed 's/gui\/[0-9]*/gui\/UID/' $LCALLS | tr '\n' '|')" = "bootout gui/UID/com.user.agent-board-discord-watch|bootstrap gui/UID $PL|"
sched uninstall >/dev/null
check "schedule uninstall: plist gone"         not test -e "$PL"
check "schedule: the real LaunchAgents plist untouched" test "$(ls ~/Library/LaunchAgents 2>/dev/null | grep -c agent-board-discord-watch.plist)" = "${REAL_PLISTS:-0}"
tt_done
