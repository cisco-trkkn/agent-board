source "${0:A:h}/lib.zsh"
# Telegram always-on fixes: part 2 (the launcher clears the stale MCP failure) and part 3 (the watchdog).
# Everything runs against scratch dirs: CLAUDE_CONFIG_DIR, TC_STATE and HOME are temp, `claude` is a stub.
tt_setup claude
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
HELPER="$TT_REPO/tools/telegram_cache.py"
KEY='plugin:telegram:telegram'
seed() { print -r -- '{"plugin:gitlab:gitlab":{"timestamp":1},"plugin:telegram:telegram":{"timestamp":2,"id":"abc"}}' > "$CACHE" }
haskey() { jq -e --arg k "$1" 'has($k)' "$CACHE" >/dev/null 2>&1 }

REAL_PLISTS="$(ls ~/Library/LaunchAgents 2>/dev/null | grep -c agent-board-telegram-watch.plist)"
# --- part 2a: the helper
seed
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: exit 0"                     test $rc = 0
check "helper: telegram key removed"       not haskey "$KEY"
check "helper: other key kept"             haskey plugin:gitlab:gitlab
check "helper: other key value intact"     test "$(jq -c '.["plugin:gitlab:gitlab"]' "$CACHE")" = '{"timestamp":1}'
check "helper: no temp file left"          test "$(ls -A $CFG | grep -c tmp)" = 0
rm -f "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: missing file: exit 0"       test $rc = 0
check "helper: missing file: not created"  not test -e "$CACHE"
print -r -- 'not json{' > "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: bad JSON: exit 0"           test $rc = 0
check "helper: bad JSON: file untouched"   test "$(<$CACHE)" = 'not json{'
print -r -- '[1,2]' > "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear; rc=$?
check "helper: non-object JSON: exit 0"    test $rc = 0
check "helper: non-object JSON untouched"  test "$(<$CACHE)" = '[1,2]'
print -r -- '{"plugin:gitlab:gitlab":{"timestamp":1}}' > "$CACHE"; touch -t 202001010000 "$CACHE"
CLAUDE_CONFIG_DIR="$CFG" python3 "$HELPER" clear
check "helper: key absent: file not rewritten" test "$(stat -c %Y "$CACHE" 2>/dev/null || stat -f %m "$CACHE")" -lt 1600000000
# default dir: HOME/.claude when CLAUDE_CONFIG_DIR is unset
mkdir -p "$RT/.claude"; print -r -- '{"plugin:telegram:telegram":{"timestamp":2}}' > "$RT/.claude/mcp-needs-auth-cache.json"
env -u CLAUDE_CONFIG_DIR HOME="$RT" python3 "$HELPER" clear
check "helper: default dir is HOME/.claude" test "$(<$RT/.claude/mcp-needs-auth-cache.json)" = '{}'

# --- part 2b: the launcher calls it, only for a lead with a token
TG="$TC_STATE/telegram/tt"
L="$TT_REPO/bin/claude-orchestrator"
run() { rm -f $S/argv; env HOME="$RT" CLAUDE_CONFIG_DIR="$CFG" PATH="$STUB:$ORIG_PATH" "$@" >/dev/null 2>&1 }
rm -rf "$TG"; seed
run "$L"
check "launcher: no token: cache untouched"  haskey "$KEY"
mkdir -p "$TG"; print -r -- "TELEGRAM_BOT_TOKEN=1:x" > "$TG/.env"; seed
run "$L"
check "launcher: token: claude still started" test -s $S/argv
check "launcher: token: telegram key cleared" not haskey "$KEY"
check "launcher: token: other key kept"       haskey plugin:gitlab:gitlab
seed; run TC_TELEGRAM=0 "$L"
check "launcher: TC_TELEGRAM=0: cache untouched" haskey "$KEY"
print -r -- 'garbage' > "$CACHE"; run "$L"
check "launcher: bad cache JSON: claude still starts" test -s $S/argv
rm -f "$CACHE"; run "$L"
check "launcher: missing cache: claude still starts" test -s $S/argv
# a failing helper never blocks the launch
mkdir -p "$TT_DIR/repo3/bin" "$TT_DIR/repo3/tools" "$TT_DIR/repo3/claude"; cp "$TT_REPO"/bin/{claude-orchestrator,_ab_claude.zsh,_tc_bins.zsh} "$TT_DIR/repo3/bin/"
print -r -- 'import sys; sys.exit(3)' > "$TT_DIR/repo3/tools/telegram_cache.py"
run "$TT_DIR/repo3/bin/claude-orchestrator"
check "launcher: failing helper: claude still starts" test -s $S/argv

# --- part 3: `tmux-ctl telegram watch --once` against a fake claude TUI in a scratch tmux window
if (( ! $+commands[python3] )); then print "skip - no python3"; tt_done; exit 0; fi
MARK="tgfake-$$-$RANDOM"
ln -sf "${commands[zsh]:A}" "$STUB/claude"   # a process whose command line starts with claude (tmux still calls its command zsh)
FAKE="$TT_REPO/tools/tests/fixtures/fake_claude_tui.zsh"
tt new-window -d -n lead -c "$TT_DIR" "$STUB/claude -f $FAKE $MARK --channels plugin:telegram@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead' '#{pane_id}')"
sleep 1.5
watch() { env TC_NOTIFY=0 TC_TELEGRAM_WATCH_GRACE=0 TC_TELEGRAM_WATCH_QUIET=0 "$@" "$TT_REPO/bin/tmux-ctl" telegram watch --once }
nserv() { pgrep -f "telegram/server.ts $MARK" | wc -l | tr -d ' ' }
screen() { tt capture-pane -p -J -t "$LP" }
WLOG="$TC_STATE/telegram-watch.log"
# typed text in the input line: never typed over, the user is told instead
tt send-keys -t "$LP" -l 'half a sentence'; sleep 0.5
watch >/dev/null
check "typed text: no server started"      test "$(nserv)" = 0
check "typed text: input untouched"        grep -q 'half a sentence' =(screen)
check "typed text: logged as not typing"   grep -q 'not typing' "$WLOG"
tt send-keys -t "$LP" C-u; sleep 0.5
rm -f "$WLOG"
watch >/dev/null
check "idle: telegram server running after one pass" test "$(nserv)" = 1
check "idle: one reconnect line logged"    test "$(grep -c 'reconnect: ok' "$WLOG")" = 1
check "idle: pane back at the prompt"      grep -q '^❯' =(screen)
watch >/dev/null
# (a real lead on this machine may also be down: it has no pane in the scratch server and is logged as such, so count ours only)
check "healthy lead: second pass is a no-op" test "$(grep -c "pane $LP" "$WLOG")" = 1
for p in $(pgrep -f "telegram/server.ts $MARK"); do kill $p; done; sleep 0.5; rm -f "$WLOG"
watch TC_TELEGRAM_WATCH=0 >/dev/null
check "TC_TELEGRAM_WATCH=0: nothing happens" test "$(nserv)" = 0 -a ! -e "$WLOG"
touch "$TC_STATE/telegram-watch.off"; watch >/dev/null
check "flag file: nothing happens"         test "$(nserv)" = 0 -a ! -e "$WLOG"
rm -f "$TC_STATE/telegram-watch.off"
# copy mode: keys would start a search, so nothing is typed
tt copy-mode -t "$LP"
watch >/dev/null
check "copy mode: no server started"       test "$(nserv)" = 0
check "copy mode: logged"                  grep -q 'copy mode' "$WLOG"
tt send-keys -t "$LP" -X cancel
# a pane with output in the last 30 s is left alone (the default quiet time)
rm -f "$WLOG"
env TC_NOTIFY=0 TC_TELEGRAM_WATCH_GRACE=0 "$TT_REPO/bin/tmux-ctl" telegram watch --once >/dev/null
check "recent activity: no server started" test "$(nserv)" = 0
check "recent activity: logged"            grep -q 'active in the last 30 s' "$WLOG"
# a failed reconnect backs off: a lead whose server never appears is typed into once, not every pass
rm -f "$WLOG" "$TC_STATE/telegram-watch.json"
tt kill-window -t "$LP"; sleep 0.5
tt new-window -d -n lead2 -c "$TT_DIR" "$STUB/claude -f $TT_REPO/tools/tests/fixtures/fake_claude_tui_broken.zsh $MARK --channels plugin:telegram@claude-plugins-official"
LP="$(tt display -p -t '=tt:lead2' '#{pane_id}')"; sleep 1.5
watch >/dev/null; watch >/dev/null; watch >/dev/null
check "backoff: three passes, one reconnect attempt" test "$(grep -c "pane $LP.*reconnect:" "$WLOG")" = 1
check "backoff: one banner line"           test "$(grep -c "pane $LP.*notified" "$WLOG")" = 1
tt kill-window -t "$LP"; sleep 0.5; for p in $(pgrep -f "telegram/server.ts $MARK"); do kill $p; done
check "leak: no fake server left"          test "$(nserv)" = 0
check "leak: no fake lead left"            test "$(pgrep -f "fake_claude_tui.zsh $MARK" | wc -l | tr -d ' ')" = 0

# --- part 3: the launchd job through tmux-ctl, against a fake launchctl and a scratch HOME (never the real LaunchAgents)
LC="$TT_DIR/launchctl"; LCALLS="$TT_DIR/lcalls"
print -r -- "#!/bin/sh
echo \"\$@\" >> $LCALLS" > "$LC"; chmod +x "$LC"
mkdir -p "$RT/.local/bin"; ln -sf "$TT_REPO/bin/tmux-ctl" "$RT/.local/bin/tmux-ctl"
PL="$RT/Library/LaunchAgents/com.user.agent-board-telegram-watch.plist"
sched() { env TW_HOME="$RT" TW_LAUNCHCTL="$LC" "$TT_REPO/bin/tmux-ctl" telegram watch "$@" }
sched install >/dev/null; rc=$?
check "schedule install: exit 0"               test $rc = 0
check "schedule install: plist written"        test -f "$PL"
check "schedule install: StartInterval 60"     grep -q '<integer>60</integer>' "$PL"
check "schedule install: runs watch --once"    grep -q '<string>--once</string>' "$PL"
check "schedule install: bootout then bootstrap" test "$(sed 's/gui\/[0-9]*/gui\/UID/' $LCALLS | tr '\n' '|')" = "bootout gui/UID/com.user.agent-board-telegram-watch|bootstrap gui/UID $PL|"
sched uninstall >/dev/null
check "schedule uninstall: plist gone"         not test -e "$PL"
check "schedule: the real LaunchAgents plist untouched" test "$(ls ~/Library/LaunchAgents 2>/dev/null | grep -c agent-board-telegram-watch.plist)" = "${REAL_PLISTS:-0}"
tt_done
