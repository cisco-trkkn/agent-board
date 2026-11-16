#!/usr/bin/env zsh
# check_real_queue_reliability.zsh — real-state check for spec 2026-11-10-queue-reliability (not a test_*.zsh: run by hand).
# Runs wait-gone and the Stop guard against the REAL tmux server this shell is in, awake sleeps against this Mac's real
# `pmset -g log` (read-only), and the Stop guard inside one live `claude -p` session loaded with this checkout's plugin.
# It touches only its own scratch session (named *-bg: the board and the session-closed hook skip those) and a temp state
# dir; no real window, hold or state file is changed. Prints one line per check and ends with REAL CHECK PASS, or exits 1.
emulate -L zsh
REPO="${0:A:h:h:h}"
[[ -n "$TMUX" ]] || { print "FAIL - not inside tmux (run it from a pane of the real server)"; exit 1 }
source "$REPO/bin/_tc_bins.zsh"
FAILS=0
ok()    { print -r -- "ok   - $1" }
fail()  { print -r -- "FAIL - $1"; (( FAILS++ )) }
check() { local name="$1"; shift; if "$@"; then ok "$name"; else fail "$name"; fi }
SC="qrel-check-$$-bg"; ST="$(mktemp -d "${TMPDIR:-/tmp}/qrel.XXXXXX")"; ST="${ST:A}"
cleanup() { tc_tmux kill-session -t "=$SC" 2>/dev/null; rm -rf "$ST" }
trap cleanup EXIT INT TERM
snap() { tc_tmux list-windows -a -F '#{session_name} #{window_id} #{window_name}' | grep -v "^$SC " | sort }

print -r -- "## wait-gone and Stop guard on the real tmux server"
before="$(snap)"
print -r -- "server: $(tc_tmux display -p '#{socket_path}'), pid $(tc_tmux display -p '#{pid}'), $(print -r -- "$before" | wc -l | tr -d ' ') windows outside the scratch session"
tc_tmux new-session -d -s "$SC" -n base -c "$HOME" 'sleep 600'
tc_tmux new-window -d -t "=${SC}:" -n '✦ qrel-probe' 'sleep 600'
tc_tmux new-window -d -t "=${SC}:" -n '✦ qrel-probe-2' 'sleep 600'
pane="$(tc_tmux display -p -t "=${SC}:base" '#{pane_id}')"
SID="00000000-0000-4000-8000-$(printf '%012d' $$)"
guard() { print -r -- '{"session_id":"'"$SID"'","hook_event_name":"Stop","stop_hook_active":false}' | TC_STATE="$ST" AGENT_BOARD_LEAD=1 TMUX_PANE="$pane" "$REPO/claude/plugin/scripts/lead-stop-guard.sh" --scoped }
mkdir -p "$ST/shutdown-pending"; print -r -- qrel-probe > "$ST/shutdown-pending/$SID"
g="$(guard)"; print -r -- "guard: $g"
check "guard blocks while the real window exists"      test "$(print -r -- "$g" | jq -r .decision 2>/dev/null)" = block
out="$(TC_STATE="$ST" TC_SESSION="$SC" "$REPO/bin/tmux-ctl" wait-gone qrel-probe --timeout 4)"; rc=$?
print -r -- "wait-gone: $out (exit $rc)"
check "wait-gone kills the window at the timeout, exit 3"  test $rc -eq 3 -a "$out" = "wait-gone: killed qrel-probe after 4s"
check "the longer-named window and the base window are left"  test "$(tc_tmux list-windows -t "=$SC" -F '#{window_name}' | tr '\n' ',')" = "base,✦ qrel-probe-2,"
g="$(guard)"
check "guard allows once the window is gone, pending file deleted"  test -z "$g" -a ! -e "$ST/shutdown-pending/$SID"
after="$(snap)"
check "no real window changed ($(print -r -- "$after" | wc -l | tr -d ' ') compared)"  test "$before" = "$after"

print -r -- "## awake sleeps on the real pmset log"
if (( $+commands[pmset] )); then
  real="$(TC_STATE="$ST" "$REPO/bin/tmux-ctl" awake sleeps '2000-01-01 00:00')"
  nall="$(TC_STATE="$ST" "$REPO/bin/tmux-ctl" awake sleeps '2000-01-01 00:00' --all | wc -l | tr -d ' ')"
  nreal="$(print -rn -- "$real" | grep -c '')"
  # independent count of real periods: first Sleep line with a reason off the deny-list, until the next Wake line
  want="$(pmset -g log | awk '($4=="Sleep"||$4=="Wake") && $5!="Requests"' | awk -F"'" '
    $0 ~ /^[0-9-]+ [0-9:]+ [-+][0-9]+ Sleep / { if ($2=="Maintenance Sleep"||$2=="Sleep Service Back to Sleep"||$2=="Notification Wake Back to Sleep") next; if (!o) { p++; o=1 } next }
    { o=0 } END { print p+0 }')"
  print -r -- "$real"
  print -r -- "real periods: $nreal; --all lines: $nall"
  check "the real log has Sleep/Wake lines to filter ($nall)"  test "$nall" -gt 0
  check "default output = the independent count of real periods ($want)"  test "$nreal" = "$want"
  check "every line is '<start> – <end or …> <reason>'"  zsh -c '[[ -z $1 ]] || ! print -r -- "$1" | grep -qvE "^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8} – ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9:]{8}|…) .+"' _ "$real"
  check "no noise reason in the default output"          zsh -c '! print -r -- "$1" | grep -qE "Maintenance Sleep|Back to Sleep|DarkWake"' _ "$real"
else
  print -r -- "skip - no pmset on this machine"
fi

print -r -- "## Stop guard in a live Claude session"
if (( $+commands[claude] )); then
  LS="$(uuidgen | tr 'A-Z' 'a-z')"; mkdir -p "$ST/handoff-pending" "$ST/work"; : > "$ST/handoff-pending/$LS"
  ( cd "$ST/work" && git init -q && AGENT_BOARD_LEAD=1 TC_STATE="$ST" claude -p --model haiku --plugin-dir "$REPO/claude/plugin" --session-id "$LS" \
      "Reply with the single word ok. Use no tool at all, whatever a hook message says: each time, just reply ok again." </dev/null >"$ST/claude.out" 2>&1 )
  print -r -- "log: $(sed "s/$LS/<session id>/g" "$ST/stop-guard.log" 2>/dev/null)"
  check "the live session's stop was blocked three times, then allowed and logged once"  test "$(grep -c "$LS allowed after 3 blocks: a self-started handoff has not relayed" "$ST/stop-guard.log" 2>/dev/null)" = 1
  check "the counter was reset"                          test ! -e "$ST/stop-guard/$LS"
else
  print -r -- "skip - no claude CLI"
fi
if (( FAILS == 0 )); then print "REAL CHECK PASS"; else print "$FAILS FAILED"; exit 1; fi
