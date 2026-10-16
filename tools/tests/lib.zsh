# lib.zsh — isolated tmux server for tmux-tools tests. Source it, then call tt_setup.
TT_BIN="${TC_TMUX:-$HOME/.local/bin/tmux}"
TT_FAILS=0

tt_setup() {   # tt_setup [windows...]  (default: claude shell tests)
  local wins=("${@:-claude}"); (( $# )) || wins=(claude shell tests)
  TT_SOCK_NAME="tctest-$$-$RANDOM"
  TT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tctest.XXXXXX")"
  TT_DIR="${TT_DIR:A}"
  export TC_STATE="$TT_DIR/state"; mkdir -p "$TC_STATE"
  unset TMUX TMUX_PANE TC_SESSION
  # TC_STATE is exported before the server starts, so pane shells inherit it
  "$TT_BIN" -L "$TT_SOCK_NAME" -f /dev/null new-session -d -s tt -n "$wins[1]" -c "$TT_DIR" -x 200 -y 50
  local w; for w in "${wins[@]:1}"; do
    "$TT_BIN" -L "$TT_SOCK_NAME" new-window -d -t '=tt:' -n "$w" -c "$TT_DIR"
  done
  local sock="$("$TT_BIN" -L "$TT_SOCK_NAME" display -p -t "=tt:$wins[1]" '#{socket_path}')"
  export TMUX="$sock,$$,0"
  export TMUX_PANE="$(tt display -p -t "=tt:$wins[1]" '#{pane_id}')"
  tt_wait 5 tt_all_idle || print -u2 "tt_setup: shells slow to start"
}
tt_teardown() {
  if [[ -n "$TT_SOCK_NAME" ]]; then
    local sp="$("$TT_BIN" -L "$TT_SOCK_NAME" display -p '#{socket_path}' 2>/dev/null)"
    "$TT_BIN" -L "$TT_SOCK_NAME" kill-server 2>/dev/null
    [[ -n "$sp" ]] && rm -f "$sp"          # kill-server leaves the socket file behind
  fi
  [[ -n "$TT_DIR" ]] && rm -rf "$TT_DIR"
  TT_SOCK_NAME=; TT_DIR=
}
# top level on purpose: an EXIT trap set inside tt_setup would fire when tt_setup returns
trap tt_teardown EXIT INT TERM
tt() { "$TT_BIN" "$@" }                       # talks to the test server through $TMUX
tt_all_idle() { ! tt list-panes -s -t '=tt' -F '#{pane_current_command}' | grep -qvE '^-?(zsh|bash|sh)$' }
tt_wait() { local n=$(( $1 * 4 )); shift; while (( n-- > 0 )); do "$@" && return 0; sleep 0.25; done; return 1 }
ok()    { print -r -- "ok   - $1" }
fail()  { print -r -- "FAIL - $1"; (( TT_FAILS++ )) }
check() { local name="$1"; shift; if "$@"; then ok "$name"; else fail "$name"; fi }
tt_done() { if (( TT_FAILS == 0 )); then print "ALL PASS"; else print "$TT_FAILS FAILED"; exit 1; fi }
