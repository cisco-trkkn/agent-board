# lib.zsh — isolated tmux server for tmux-tools tests. Source it, then call tt_setup.
TT_BIN="${TC_TMUX:-$([[ -x $HOME/.local/bin/tmux ]] && print -r -- $HOME/.local/bin/tmux || print -r -- ${commands[tmux]:-$HOME/.local/bin/tmux})}"
TT_REPO="${${(%):-%x}:A:h:h:h}"          # the checkout under test (file scope: inside a function $0 is the function name)
TT_FAILS=0
# A board-opened shell exports AGENT_BOARD=1, which makes the legacy global hooks (kill-guard, bash-mirror) defer and exit 0.
# Tests that run those hooks directly never call tt_setup, so clear it at source time.
unset AGENT_BOARD

# tt_zdot <dir>: a ZDOTDIR for pane shells. No global rcs either: Ubuntu's /etc/zsh/zshrc runs compinit, which asks
# "insecure directories, continue [y/n]?" on a runner and eats the first typed line.
tt_zdot() { mkdir -p "$1"; print -r -- 'unsetopt GLOBAL_RCS' > "$1/.zshenv"; : > "$1/.zshrc"; export ZDOTDIR="$1" }

tt_setup() {   # tt_setup [windows...]  (default: claude shell tests)
  local wins=("${@:-claude}"); (( $# )) || wins=(claude shell tests)
  TT_SOCK_NAME="tctest-$$-$RANDOM"
  TT_DIR="$(mktemp -d "${TMPDIR:-/tmp}/tctest.XXXXXX")"
  TT_DIR="${TT_DIR:A}"
  export TC_STATE="$TT_DIR/state"; mkdir -p "$TC_STATE"
  export TC_LINEAGE="$TC_STATE/lineage"   # handoff lineage lives outside the state dir in production; tests keep it in the temp dir
  # pane shells are interactive zsh: without a .zshrc in $ZDOTDIR/$HOME they open the zsh-newuser-install menu and eat the typed line (fresh CI runners)
  [[ -n "$ZDOTDIR" ]] || tt_zdot "$TT_DIR/zdot"
  unset TMUX TMUX_PANE TC_SESSION TMUX_DASH_TMUX_ARGS DEV_NO_ATTACH DEV_CLIENT DEV_CLAUDE_CMD AGENT_BOARD   # a board-opened shell exports some of these (AGENT_BOARD=1 makes the legacy global hooks defer, so they record nothing)
  # the private socket stands in for agent-board's own server (-L agent-board), and this checkout for the live one
  export SHELL="${commands[zsh]:-/bin/zsh}"   # pane shells run zsh syntax; tmux takes default-shell from $SHELL (CI runners have bash)
  export AGENT_BOARD_TMUX_SOCKET="$TT_SOCK_NAME" AGENT_BOARD_REPO="$TT_REPO"
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
