# test_dedicated_server.zsh — agent-board runs on its own tmux server, chosen by one resolver (bin/_tc_bins.zsh).
# Two scratch servers stand in for the real ones; neither is the user's default server nor the real -L agent-board:
#   A = the harness server from lib.zsh (-f /dev/null) ........ "the user's own server"; $TMUX points at it
#   B = a fresh socket named by AGENT_BOARD_TMUX_SOCKET ......... "-L agent-board"; dev starts it with config/tmux.conf
# lib.zsh kills A on exit; the trap below kills B and the scratch board.
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"; RES="$R/bin/_tc_bins.zsh"; F="${0:A:h}/fixtures"
tt_setup claude shell
A_SOCK="$TT_SOCK_NAME"
B_SOCK="ab-test-$$-$RANDOM"
export AGENT_BOARD_TMUX_SOCKET="$B_SOCK"      # lib.zsh pointed it at A; here A plays the user's server
A() { "$TT_BIN" -L "$A_SOCK" "$@" }
B() { "$TT_BIN" -L "$B_SOCK" "$@" }
SRV_PID=
C_SOCK="ab-test-$$-$RANDOM"
NEVER="ab-test-$$-never"                      # an agent-board socket nothing should ever start (the legacy checks)
cleanup() {
  [[ -n "$SRV_PID" ]] && kill "$SRV_PID" 2>/dev/null
  local s sp; for s in "$B_SOCK" "$C_SOCK" "$NEVER"; do      # NEVER too: a failing legacy check would have started it
    sp="$("$TT_BIN" -L "$s" display -p '#{socket_path}' 2>/dev/null)"
    "$TT_BIN" -L "$s" kill-server 2>/dev/null
    rm -f "${sp:-${TMUX_TMPDIR:-/tmp}/tmux-$UID/$s}"      # kill-server leaves the socket file behind
  done
  tt_teardown
}
trap cleanup EXIT INT TERM
A_TMUX="$TMUX"                                 # a pane on A, as lib.zsh set it
SH="$TT_DIR/home"; mkdir -p "$SH/.config/agent-board" "$TT_DIR/usage" "$TT_DIR/ideas"
print 'set -g @ab_local 1' > "$SH/.config/agent-board/tmux.local.conf"
# an unmigrated install: ~/.tmux.conf still carries the hook lines INSTALL.md §5 used to add (install.sh --migrate removes them)
LH="$TT_DIR/legacyhome"; mkdir -p "$LH"
print "set-hook -g after-split-window 'run-shell -b \"~/.local/bin/tmux-teammate-window\"'" > "$LH/.tmux.conf"
for p in proj proj2 lg; do mkdir -p "$TT_DIR/$p"; git -C "$TT_DIR/$p" init -q; done
A show-hooks -g > "$TT_DIR/hooks.before"; A list-keys > "$TT_DIR/keys.before"
TEAMMATE_CMD="cd /tmp && env CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 sh -c 'sleep 60; :' --agent-id NAME@tt --agent-name NAME --team-name tt --agent-color green --parent-session-id 00000000-0000-0000-0000-000000000000 --agent-type general-purpose --permission-mode auto --model sonnet"
win_of() { "$TT_BIN" -L "$1" list-windows -t "=$2" -F '#{window_name}' 2>/dev/null | grep -qxF -- "✦ $3" }
not() { ! "$@" }

# --- the resolver: TC_TMUX picks the binary; TMUX_DASH_TMUX_ARGS → $TMUX's socket → -L <dedicated> -f config
# Each helper starts from a fixed environment (a pane on A, scratch HOME = a fresh install, no override) and the caller's
# assignments come last, so they win. TMUX= (empty) means "outside tmux": the resolver tests -n.
ENV0=(HOME="$SH" TC_TMUX="$TT_BIN" TMUX="$A_TMUX" TMUX_DASH_TMUX_ARGS=)
ZRES='source "$1"; print -r -- "${TC_TMUX_CMD[@]}"'
ZDED='source "$1"; tc_tmux_resolve dedicated; print -r -- "${TC_TMUX_CMD[@]}"'
res()  { env "${ENV0[@]}" "$@" zsh -f -c "$ZRES" _ "$RES" }
resd() { env "${ENV0[@]}" "$@" zsh -f -c "$ZDED" _ "$RES" }
resl() { env "${ENV0[@]}" HOME="$LH" AGENT_BOARD_TMUX_SOCKET="$NEVER" "$@" zsh -f -c "$ZDED" _ "$RES" }   # unmigrated install, no agent-board server
py()   { env "${ENV0[@]}" "$@" python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import paneclass; print(" ".join(paneclass.tmux_cmd()))' "$R/board" }
sock="${A_TMUX%%,*}"
DED="$TT_BIN -L $B_SOCK -f $R/config/tmux.conf"
check "resolver: override wins over \$TMUX"   test "$(res TMUX_DASH_TMUX_ARGS='-L work')" = "$TT_BIN -L work"
check "resolver: inside tmux → that socket"   test "$(res)" = "$TT_BIN -S $sock"
check "resolver: outside → dedicated+config"  test "$(res TMUX=)" = "$DED"
check "resolver: TC_TMUX picks the binary"    test "$(res TC_TMUX=/x/tmux)" = "/x/tmux -S $sock"
check "resolver: dedicated ignores \$TMUX"    test "$(resd)" = "$DED"
check "resolver: dedicated keeps override"    test "$(resd TMUX_DASH_TMUX_ARGS='-L work')" = "$TT_BIN -L work"
# unmigrated install, no agent-board server yet: entry points stay on the user's server
check "legacy: dedicated inside tmux → that socket"   test "$(resl)" = "$TT_BIN -S $sock"
check "legacy: dedicated outside → default server"    test "$(resl TMUX=)" = "$TT_BIN -L default"
check "legacy: override still wins"                   test "$(resl TMUX_DASH_TMUX_ARGS='-L work')" = "$TT_BIN -L work"
check "legacy: non-entry commands unaffected"         test "$(res HOME="$LH" AGENT_BOARD_TMUX_SOCKET="$NEVER")" = "$TT_BIN -S $sock"
check "python = zsh: override"                test "$(py TMUX_DASH_TMUX_ARGS='-L work')" = "$(res TMUX_DASH_TMUX_ARGS='-L work')"
check "python = zsh: inside"                  test "$(py)" = "$(res)"
check "python = zsh: outside"                 test "$(py TMUX=)" = "$(res TMUX=)"
check "python = zsh: TC_TMUX"                 test "$(py TC_TMUX=/x/tmux)" = "$(res TC_TMUX=/x/tmux)"
check "config never sources ~/.tmux.conf"     test -z "$(grep -E 'source-file' "$R/config/tmux.conf" | grep -vF 'agent-board/tmux.local.conf')"
check "tmux-dash resolves the dedicated server for both processes" \
  sh -c "grep -q 'tc_tmux_resolve dedicated' '$R/bin/tmux-dash' && grep -q 'export TMUX_DASH_TMUX_ARGS=' '$R/bin/tmux-dash'"

# --- dev from a pane on another server (A): the session lands on B, nothing is nested, the attach command is printed
DEV="$R/bin/dev"
# scratch HOME: B must not read the real ~/.config or ~/.tmux.conf. A wrong AGENT_BOARD_REPO in the env must not reach the server.
devx() { HOME="$SH" AGENT_BOARD_REPO=/not/this/checkout TC_TMUX="$TT_BIN" TC_LAYOUT="$R/bin/tmux-dev-layout" DEV_CLAUDE_CMD=true "$DEV" "$@" }
out="$(devx "$TT_DIR/proj" 2>&1)"; rc=$?
check "nesting: dev exits 0"                  test $rc -eq 0
check "nesting: prints the attach command"    grep -qF "tmux -L $B_SOCK attach -t proj" <<< "$out"
check "dev: session on the agent-board server" B has-session -t '=proj'
check "dev: nothing created on the user's server" sh -c "! $TT_BIN -L $A_SOCK has-session -t '=proj' 2>/dev/null"
check "dev: layout ran on B too (proj-bg)"    B has-session -t '=proj-bg'
check "dev: windows"                          test "$(B list-windows -t '=proj' -F '#{window_name}' | sort | tr '\n' ' ')" = "claude shell "
out="$(devx "$TT_DIR/proj" 2>&1)"
check "nesting: second dev reattaches (hint again, no error)" grep -qF "attach -t proj" <<< "$out"
check "dev: DEV_NO_ATTACH still prints ready" sh -c "DEV_NO_ATTACH=1 HOME='$SH' TC_TMUX='$TT_BIN' TC_LAYOUT='$R/bin/tmux-dev-layout' '$DEV' '$TT_DIR/proj' | grep -q ready"

# --- B loaded config/tmux.conf: hooks, options, bindings, the personal tmux.local.conf; never ~/.tmux.conf
check "B: after-split-window hook"            sh -c "$TT_BIN -L $B_SOCK show-hooks -g after-split-window | grep -qF '$R/bin/tmux-teammate-window'"
check "B: session-closed hook"                sh -c "$TT_BIN -L $B_SOCK show-hooks -g session-closed | grep -qF '$R/bin/tmux-session-closed'"
check "B: hook passes the session name"       sh -c "$TT_BIN -L $B_SOCK show-hooks -g session-closed | grep -qF '#{q:hook_session_name}'"
check "B: AGENT_BOARD_REPO in server env"     test "$(B show-environment -g AGENT_BOARD_REPO 2>&1)" = "AGENT_BOARD_REPO=$R"
check "B: monitor-bell on"                    test "$(B show -gv monitor-bell)" = on
check "B: bell-action other"                  test "$(B show -gv bell-action)" = other
check "B: allow-passthrough on"               test "$(B show -gv allow-passthrough)" = on
check "B: extended-keys on"                   test "$(B show -sv extended-keys)" = on
check "B: prefix D opens a project"           sh -c "$TT_BIN -L $B_SOCK list-keys -T prefix D | grep -qF '$R/bin/dev'"
check "B: prefix f jumps"                     sh -c "$TT_BIN -L $B_SOCK list-keys -T prefix f | grep -qF 'tmux-jump'"
check "B: prefix W cleans worktrees"          sh -c "$TT_BIN -L $B_SOCK list-keys -T prefix W | grep -qF '$R/bin/tmux-agent-cleanup'"
check "B: tmux.local.conf sourced"            test "$(B show -gv @ab_local 2>/dev/null)" = 1
# legacy lines in ~/.tmux.conf no longer matter once the agent-board server (here B) is running: the user has migrated
check "legacy lines + agent-board server running → dedicated" test "$(resd HOME="$LH")" = "$DED"
# without a personal file, and started by hand, the config still loads silently and falls back to ~/agent-board
mkdir -p "$TT_DIR/emptyhome"
err="$(HOME="$TT_DIR/emptyhome" env -u AGENT_BOARD_REPO -u TMUX "$TT_BIN" -L "$C_SOCK" -f "$R/config/tmux.conf" new-session -d -s c 2>&1)"
check "config loads without tmux.local.conf"  test -z "$err"
check "config falls back to ~/agent-board"    sh -c "$TT_BIN -L $C_SOCK show-hooks -g session-closed | grep -qF '$TT_DIR/emptyhome/agent-board/bin/'"
# a teammate split on B is moved to its own window by B's hook (the shape test_teammate_window.zsh uses)
B split-window -d -t '=proj:claude' "${TEAMMATE_CMD//NAME/probe-b}"
check "B: teammate split → ✦ window"         tt_wait 12 win_of "$B_SOCK" proj probe-b
check "A: no teammate window appeared"        sh -c "! $TT_BIN -L $A_SOCK list-windows -a -F '#{window_name}' | grep -q probe-b"

# --- legacy: commands run from a pane on A act on A (their $TMUX), never on B
CTL="$R/bin/tmux-ctl"
out="$(cd "$TT_DIR" && "$CTL" run tests 'echo ok' 2>/dev/null)"
check "legacy: tmux-ctl run prints ok"        test "$(print -r -- "$out" | head -1)" = ok
check "legacy: tmux-ctl made tt-bg on A"      A has-session -t '=tt-bg'
check "legacy: no tt-bg on B"                 sh -c "! $TT_BIN -L $B_SOCK has-session -t '=tt-bg' 2>/dev/null"
sed "s|__HOME__|$HOME|" "$F/ok.json" | "$R/claude/hooks/bash-mirror.sh"
check "legacy: bash-mirror fed A's project"   grep -qxF '$ pytest -q tests/unit' "$TC_STATE/feed-tt-tests.log"
A split-window -d -t '=tt:claude' "${TEAMMATE_CMD//NAME/probe-l}"
sleep 0.5; "$R/bin/tmux-teammate-window"       # as A's hook would run it; A has no such hook, so its hooks stay pristine
check "legacy: teammate window on A"          tt_wait 12 win_of "$A_SOCK" tt probe-l
check "legacy: not on B"                      sh -c "! $TT_BIN -L $B_SOCK list-windows -a -F '#{window_name}' | grep -q probe-l"

# --- the board: lists B's sessions and its terminals attach to them (TMUX_DASH_TMUX_ARGS, as tmux-dash passes it)
PORT=$(( 20000 + RANDOM % 20000 ))
TMUX_DASH_TOKEN=t TMUX_DASH_PORT=$PORT TMUX_DASH_TMUX_ARGS="-L $B_SOCK" USAGE_ROOT="$TT_DIR/usage" TC_IDEAS_DIR="$TT_DIR/ideas" \
  python3 "$R/board/server.py" > "$TT_DIR/server.log" 2>&1 & SRV_PID=$!
up() { curl -s -o /dev/null "http://127.0.0.1:$PORT/t/" }
tt_wait 10 up || print -u2 "board slow to start: $(tail -3 "$TT_DIR/server.log")"
state="$(curl -s "http://127.0.0.1:$PORT/t/api/state")"
names="$(print -r -- "$state" | python3 -I -c 'import json,sys; print(" ".join(sorted(s["name"] for s in json.load(sys.stdin)["sessions"])))' 2>/dev/null)"
has_word() { grep -qw -- "$1" <<< "$2" }
check "board: lists B's project"              has_word proj "$names"
check "board: not A's sessions"               not has_word tt "$names"
A send-keys -t '=tt:shell' "TMUX_DASH_TMUX_ARGS='-L $B_SOCK' $R/bin/tmux-web-attach proj" Enter
view_on_b() { B list-sessions -F '#{session_name} #{session_group}' 2>/dev/null | grep -q '^_web-[0-9]* proj$' }
check "board terminal: grouped view on B"     tt_wait 10 view_on_b
check "board terminal: no view on A"          sh -c "! $TT_BIN -L $A_SOCK list-sessions -F '#{session_name}' | grep -q '^_web-'"
for v in ${(f)"$(B list-sessions -F '#{session_name}' | grep '^_web-')"}; do B kill-session -t "=$v"; done
tt_wait 5 sh -c "$TT_BIN -L $A_SOCK display -p -t '=tt:shell' '#{pane_current_command}' | grep -qE '^-?(zsh|bash|sh)$'"

# --- nesting: dev from a pane on B switches the client (a client attaches to B from a pane on A, as the printed command does)
A send-keys -t '=tt:shell' "env -u TMUX -u TMUX_PANE $TT_BIN -L $B_SOCK attach -t proj" Enter
check "attach from inside A's pane works"     tt_wait 10 sh -c "test -n \"\$($TT_BIN -L $B_SOCK list-clients -F '#{client_session}')\""
B send-keys -t '=proj:shell' "TC_TMUX=$TT_BIN TC_LAYOUT=$R/bin/tmux-dev-layout DEV_CLAUDE_CMD=true $DEV $TT_DIR/proj2 > $TT_DIR/dev2.out 2>&1; echo DEVRC=\$? >> $TT_DIR/dev2.out" Enter
check "same server: dev finished"             tt_wait 20 grep -q 'DEVRC=' "$TT_DIR/dev2.out"
check "same server: exit 0"                   grep -qx 'DEVRC=0' "$TT_DIR/dev2.out"
check "same server: no attach hint"           sh -c "! grep -q 'attach -t' '$TT_DIR/dev2.out'"
check "same server: client switched to proj2" tt_wait 5 sh -c "$TT_BIN -L $B_SOCK list-clients -F '#{client_session}' | grep -qx proj2"
B detach-client 2>/dev/null

# --- unmigrated install, Ctrl-a D shape: ~/.tmux.conf still binds `DEV_CLIENT=… dev` on the user's server (A), and no
# agent-board server exists for that install. dev must open the project on A and switch that client, not print the hint.
B send-keys -t '=proj:shell' "env -u TMUX -u TMUX_PANE $TT_BIN -L $A_SOCK attach -t tt" Enter   # a client on A, as the user would have
check "legacy: a client is attached to A"     tt_wait 10 sh -c "test -n \"\$($TT_BIN -L $A_SOCK list-clients -F '#{client_name}')\""
cl="$(A list-clients -F '#{client_name}' | head -1)"
out="$(HOME="$LH" AGENT_BOARD_TMUX_SOCKET="$NEVER" DEV_CLIENT="$cl" TC_TMUX="$TT_BIN" TC_LAYOUT="$R/bin/tmux-dev-layout" DEV_CLAUDE_CMD=true "$DEV" "$TT_DIR/lg" 2>&1)"; rc=$?
check "legacy Ctrl-a D: exit 0"               test $rc -eq 0
check "legacy Ctrl-a D: no attach hint"       not grep -q 'attach -t' <<< "$out"
check "legacy Ctrl-a D: session on the user's server" A has-session -t '=lg'
check "legacy Ctrl-a D: layout there too"     A has-session -t '=lg-bg'
check "legacy Ctrl-a D: no agent-board server started" not "$TT_BIN" -L "$NEVER" list-sessions 2>/dev/null
check "legacy Ctrl-a D: client switched"      tt_wait 5 sh -c "$TT_BIN -L $A_SOCK list-clients -F '#{client_session}' | grep -qx lg"
A detach-client 2>/dev/null

# --- the plugin copied away from its repo: the hooks fall back to the server they run in, with TC_TMUX honoured
cp -R "$R/claude/plugin" "$TT_DIR/plugin-copy"
n0="$(grep -c '^── ' "$TC_STATE/feed-tt-tests.log")"
sed "s|__HOME__|$HOME|" "$F/ok.json" | AGENT_BOARD=1 "$TT_DIR/plugin-copy/scripts/bash-mirror.sh" --scoped
check "copied plugin: hook still mirrors"     test "$(grep -c '^── ' "$TC_STATE/feed-tt-tests.log")" = $(( n0 + 1 ))
sed "s|__HOME__|$HOME|" "$F/ok.json" | AGENT_BOARD=1 TC_TMUX=/usr/bin/false "$TT_DIR/plugin-copy/scripts/bash-mirror.sh" --scoped
check "copied plugin: TC_TMUX honoured"       test "$(grep -c '^── ' "$TC_STATE/feed-tt-tests.log")" = $(( n0 + 1 ))

# --- the user's server is untouched: same hooks and keys as before everything above
A show-hooks -g > "$TT_DIR/hooks.after"; A list-keys > "$TT_DIR/keys.after"
check "A: hooks unchanged"                    diff -q "$TT_DIR/hooks.before" "$TT_DIR/hooks.after"
check "A: keys unchanged"                     diff -q "$TT_DIR/keys.before" "$TT_DIR/keys.after"
tt_done
