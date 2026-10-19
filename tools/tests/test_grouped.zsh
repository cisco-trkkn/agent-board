# Grouped (web-attach) view sessions: feed logs must be keyed by the session GROUP, not the view name.
source "${0:A:h}/lib.zsh"
H="${TC_MIRROR:-$HOME/.claude/hooks/bash-mirror.sh}"; F="${0:A:h}/fixtures"
LAYOUT="${TC_LAYOUT:-$HOME/.local/bin/tmux-dev-layout}"; CTL="${TC_CTL:-$HOME/.local/bin/tmux-ctl}"
tt_setup
tt new-session -d -t '=tt' -s _web-1       # newest session in the group: TMUX_PANE now resolves to it
check "precondition: pane resolves to view" test "$(tt display -p -t $TMUX_PANE '#{session_name}')" = _web-1
check "precondition: view is grouped"       test "$(tt display -p -t $TMUX_PANE '#{session_group}')" = tt

"$LAYOUT" _web-1 "$TT_DIR"                 # called with the view name, as a grouped caller would
check "layout made the group's bg session"  tt has-session -t '=tt-bg'
check "no view-keyed bg session"            sh -c "! $TT_BIN has-session -t '=_web-1-bg' 2>/dev/null"

sed "s|__HOME__|$HOME|" "$F/ok.json" | "$H"
check "hook entry in feed-<group>-tests.log" grep -qxF '$ pytest -q tests/unit' "$TC_STATE/feed-tt-tests.log"
check "no feed-<view> log created"          test -z "$(ls $TC_STATE | grep -F -- _web-1)"
check "tmux-ctl feed reads it from the view" test "$("$CTL" feed tests 2>&1 | grep -cxF '$ pytest -q tests/unit')" -ge 1
tt_done
