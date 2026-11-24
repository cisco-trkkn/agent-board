#!/bin/zsh
# tmux-ctl engine start: one engine in a window `engine` of <project>-bg, through a stub `node` first on PATH
# (scratch tmux server, nothing real is started). Exit codes: 1 preflight said no work, 2 refused (TC_ENGINE=0, usage),
# 4 an engine already runs (the window exists, or the preflight found the lock held).
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"
tt_setup
work="$(mktemp -d)"; work="${work:A}"; trap 'rm -rf "$work"; tt_teardown' EXIT INT TERM
repo="$work/repo"; mkdir -p "$repo" "$work/bin" "$work/eng"; git -C "$repo" init -q
git -C "$repo" -c user.email=t@e -c user.name=T commit -q --allow-empty -m init
nodelog="$work/node.log"
# the stub: logs its argv and the two variables; `--preflight` exits by the code in pre_rc (default 0) with a reason line
cat > "$work/bin/node" <<STUB
#!/bin/sh
echo "ARGV \$*" >> "$nodelog"
for a in "\$@"; do echo "ARG [\$a]" >> "$nodelog"; done
echo "ENV TC_PROJECT=\$TC_PROJECT TC_SESSION=\$TC_SESSION TC_ENGINE_DIR=\$TC_ENGINE_DIR" >> "$nodelog"
case "\$*" in
  *--preflight*) rc=\$(cat "$work/pre_rc" 2>/dev/null || echo 0); [ "\$rc" = 0 ] || echo "nothing to do: stub reason"; exit "\$rc" ;;
  *) [ -f "$work/die_now" ] && { echo "engine died: stub"; exit 3; }; echo "engine output line"; sleep 30 ;;
esac
STUB
chmod +x "$work/bin/node"
export PATH="$work/bin:$PATH" TC_ENGINE_DIR="$work/eng"
ctl="$R/bin/tmux-ctl"
run() { ( cd "$repo" && env -u AGENT_BOARD_LEAD "$ctl" "$@" ) }
wins() { tt list-windows -t "=$1:" -F '#{window_name}' 2>/dev/null; }
nwin() { local n; n="$(tt list-windows -t "=$1:" 2>/dev/null | wc -l)"; print -r -- "${n// /}"; }
has_engine_win() { wins "$1" | grep -qx engine }
log_has() { grep -qF -- "$1" "$nodelog" 2>/dev/null }

# preflight says no work (exit 1): no window, no bg session, rc 1 with the engine's reason line
print -r -- 1 > "$work/pre_rc"
out="$(run engine start 2>&1)"; rc=$?
check "preflight 1: returns 1" test $rc -eq 1
check "preflight 1: the reason line is passed on" grep -q 'stub reason' <<< "$out"
check "preflight 1: no -bg session, so no engine window" test -z "$(tt list-sessions -F '#{session_name}' | grep -x tt-bg)"
print "  (looked at $(tt list-sessions | wc -l | tr -d ' ') sessions)"
check "preflight 1: stub never ran --here" test -z "$(grep -- '--here' "$nodelog")"

# TC_ENGINE=0: refused, node never runs
: > "$nodelog"
out="$(TC_ENGINE=0 run engine start 2>&1)"; rc=$?
check "TC_ENGINE=0: returns 2" test $rc -eq 2
check "TC_ENGINE=0: says so" grep -q 'engine start: TC_ENGINE=0' <<< "$out"
check "TC_ENGINE=0: no node ran" test ! -s "$nodelog"
check "TC_ENGINE=0: no -bg session" test -z "$(tt list-sessions -F '#{session_name}' | grep -x tt-bg)"

# a preflight that finds the lock held (exit 4) makes the wrapper exit 4 too
print -r -- 4 > "$work/pre_rc"
run engine start >/dev/null 2>&1; rc=$?
check "preflight 4: returns 4" test $rc -eq 4

# work to do: the window appears
print -r -- 0 > "$work/pre_rc"; : > "$nodelog"
out="$(run engine start --backend fake 2>&1)"; rc=$?
check "start: returns 0" test $rc -eq 0
print -r -- "  (start printed: $out)"
check "start: prints where it started" test "$out" = "engine started in tt-bg:engine"
check "start: window engine in tt-bg" has_engine_win tt-bg
tt_wait 5 log_has "engine.js start --here --backend fake"
check "start: node ran start --here with the engine flags" log_has "engine.js start --here --backend fake"
check "start: the preflight ran first, with the same flags" log_has "engine.js start --preflight --backend fake"
check "start: TC_PROJECT and TC_SESSION in the engine's environment" log_has "ENV TC_PROJECT=tt TC_SESSION=tt TC_ENGINE_DIR=$work/eng"
check "start: output also appended to <engine dir>/<project>.log" tt_wait 5 grep -q 'engine output line' "$work/eng/tt.log"
check "start: the shells window of the bg session is untouched" wins tt-bg | grep -qx shell
print "  (tt-bg has $(nwin tt-bg) windows)"

# a second start while the window exists
run engine start >/dev/null 2>"$work/err"; rc=$?
check "second start: returns 4 (an engine already runs)" test $rc -eq 4
check "second start: names the window" grep -q 'window engine already exists in tt-bg' "$work/err"
check "second start: still one engine window" test "$(wins tt-bg | grep -cx engine)" -eq 1

# --session with TMUX unset (the restore job's launchd run), for another project on the same server
tt new-session -d -s pj -c "$repo" -x 200 -y 50
: > "$nodelog"
out="$(cd "$repo" && env -u TMUX -u TMUX_PANE -u TC_SESSION -u AGENT_BOARD_LEAD "$ctl" engine start --session pj 2>&1)"; rc=$?
check "--session without TMUX: returns 0" test $rc -eq 0
check "--session without TMUX: engine window in pj-bg" has_engine_win pj-bg
tt_wait 5 log_has "ENV TC_PROJECT=pj TC_SESSION=pj"
check "--session without TMUX: environment carries the named session" log_has "ENV TC_PROJECT=pj TC_SESSION=pj"
out="$(cd "$repo" && env -u TMUX -u TMUX_PANE -u TC_SESSION -u AGENT_BOARD_LEAD "$ctl" engine start 2>&1)"; rc=$?
check "no TMUX and no --session: usage, returns 2" test $rc -eq 2
check "no TMUX and no --session: the usage line" grep -q 'usage: tmux-ctl engine start --session' <<< "$out"

# every other subcommand and `start --here` go to node as before
: > "$nodelog"
run engine status --project x >/dev/null 2>&1
check "engine status: passed to node as is" log_has "engine.js status --project x"
: > "$nodelog"
run engine start --here --backend fake >/dev/null 2>&1
check "engine start --here: passed to node, no preflight, no window made" test "$(grep -c -- '--preflight' "$nodelog")" -eq 0 -a "$(grep -c 'engine.js start --here --backend fake' "$nodelog")" -eq 1


# a flag value with a space and a quote reaches node as one argument, in the preflight and in the window
: > "$nodelog"
tt kill-window -t '=tt-bg:engine'
odd="$work/a b/it's.json"
run engine start --script "$odd" >/dev/null 2>&1
tt_wait 5 log_has "engine.js start --here --script"
check "quoting: preflight got the odd value as one argument" test "$(grep -cxF "ARG [$odd]" "$nodelog")" -ge 1
tt_wait 5 test "$(grep -cxF "ARG [$odd]" "$nodelog")" -ge 2
check "quoting: the window's node got it as one argument too" test "$(grep -cxF "ARG [$odd]" "$nodelog")" -eq 2

# called from a window of <project>-bg: TC_SESSION is the main session, not tt-bg
tt kill-window -t '=tt-bg:engine'
: > "$nodelog"
bgpane="$(tt display -p -t '=tt-bg:shell' '#{pane_id}')"
( cd "$repo" && env -u AGENT_BOARD_LEAD TMUX_PANE="$bgpane" "$ctl" engine start ) >/dev/null 2>&1; rc=$?
check "from a -bg pane: returns 0" test $rc -eq 0
tt_wait 5 log_has "ENV TC_PROJECT=tt TC_SESSION=tt "
check "from a -bg pane: TC_PROJECT=tt, TC_SESSION=tt (not tt-bg)" log_has "ENV TC_PROJECT=tt TC_SESSION=tt "
check "from a -bg pane: never TC_SESSION=tt-bg" test -z "$(grep 'TC_SESSION=tt-bg' "$nodelog")"

# an engine that dies at once: no "started", rc 1, the log's last lines shown, "engine exited rc=" in the log
tt kill-window -t '=tt-bg:engine'
: > "$work/eng/tt.log"; touch "$work/die_now"
out="$(run engine start 2>&1)"; rc=$?
check "engine dies at once: returns 1" test $rc -eq 1
check "engine dies at once: no 'engine started'" test -z "$(grep 'engine started' <<< "$out")"
check "engine dies at once: the log's last lines are printed" grep -q 'engine died: stub' <<< "$out"
check "engine dies at once: the log ends with its exit status" tt_wait 10 grep -q 'engine exited rc=3' "$work/eng/tt.log"
print "  (tt-bg has $(nwin tt-bg) windows)"
rm -f "$work/die_now"

# TMUX unset: the cwd must be inside a git checkout
mkdir -p "$work/plain"
out="$(cd "$work/plain" && env -u TMUX -u TMUX_PANE -u TC_SESSION -u AGENT_BOARD_LEAD "$ctl" engine start --session pj 2>&1)"; rc=$?
check "TMUX unset, cwd outside a git checkout: returns 2" test $rc -eq 2
check "TMUX unset, cwd outside a git checkout: the usage names the problem" grep -q 'not in one' <<< "$out"

# TMUX unset, cwd in ANOTHER git checkout than the session's (a launchd run with cwd $HOME, itself a repo): refused, both paths named
other="$work/other"; mkdir -p "$other"; git -C "$other" init -q
out="$(cd "$other" && env -u TMUX -u TMUX_PANE -u TC_SESSION -u AGENT_BOARD_LEAD "$ctl" engine start --session pj 2>&1)"; rc=$?
check "TMUX unset, cwd in another checkout: returns 2" test $rc -eq 2
check "TMUX unset, cwd in another checkout: both paths named" test -n "$(grep -F "${other:A}" <<< "$out" | grep -F "${repo:A}")"
# a session whose first pane is in no git checkout: refused
tt new-session -d -s np -c "$work/plain" -x 200 -y 50
out="$(cd "$repo" && env -u TMUX -u TMUX_PANE -u TC_SESSION -u AGENT_BOARD_LEAD "$ctl" engine start --session np 2>&1)"; rc=$?
check "TMUX unset, session pane outside git: returns 2" test $rc -eq 2
check "TMUX unset, session pane outside git: says so" grep -q 'has no git pane path' <<< "$out"

tt_done
