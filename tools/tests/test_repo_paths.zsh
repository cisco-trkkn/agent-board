# test_repo_paths.zsh — scripts find their files relative to the repo, with an empty HOME (no ~/.local, no ~/.claude).
# HOME is a scratch dir; the real tmux and ttyd are named by absolute path (TC_TMUX, TTYD_BIN). Any board server started
# here uses scratch ports and a scratch state dir (under the scratch HOME) and is killed by PID in the trap.
source "${0:A:h}/lib.zsh"
R="$TT_REPO"; BIN="$R/bin"
REAL_TTYD="${commands[ttyd]:-$HOME/.local/bin/ttyd}"
export TC_TMUX="$TT_BIN"
RP_HOME="$(mktemp -d "${TMPDIR:-/tmp}/rphome.XXXXXX")"; RP_HOME="${RP_HOME:A}"
rp_cleanup() {
  local p f
  for f in "$RP_HOME"/.local/state/tmux-dash/*.pid(N); do p="$(<$f)"; kill "$p" 2>/dev/null; done
  rm -rf "$RP_HOME"
  tt_teardown
}
trap rp_cleanup EXIT INT TERM
tt_setup shell
HOME_REAL="$HOME"; export HOME="$RP_HOME"
export PATH="$BIN:$PATH"
check "scratch HOME has no .local and no .claude" test ! -e "$HOME/.local" -a ! -e "$HOME/.claude"

# 1. tmux-ctl run works with an empty HOME
out="$(tmux-ctl run shell "echo hi" 2>&1)"
check "tmux-ctl run: hi on its own line" test -n "$(print -r -- "$out" | grep -x hi)"
check "tmux-ctl run: [exit 0]" test -n "$(print -r -- "$out" | grep -F '[exit 0]')"

# 2. the worker rules come from the repo; a user override wins
dry="$(TC_AGENT_DRYRUN=1 tmux-ctl agent w --force "a b" 2>&1)"
check "agent line names the repo's worker.md" test -n "$(print -r -- "$dry" | grep -F "$R/claude/worker.md")"
mkdir -p "$HOME/.config/agent-board"; print x > "$HOME/.config/agent-board/worker.md"
dry="$(TC_AGENT_DRYRUN=1 tmux-ctl agent w --force "a b" 2>&1)"
check "agent line names the user's worker.md override" test -n "$(print -r -- "$dry" | grep -F "$HOME/.config/agent-board/worker.md")"
check "override replaces the repo rules" test -z "$(print -r -- "$dry" | grep -F "$R/claude/worker.md")"
rm -rf "$HOME/.config"

# 3. idea / artifact use the repo's files
f="$TT_DIR/doc.md"; print '# Doc' > "$f"
out="$(tmux-ctl idea "empty-home idea" 2>&1)"
check "tmux-ctl idea works" test -n "$(print -r -- "$out" | grep -v -i -E 'no such|error|traceback')"
check "tmux-ctl idea wrote under the scratch HOME or state, not a missing script" test -z "$(print -r -- "$out" | grep -iE 'can.t open file|No such file')"
out="$(tmux-ctl artifact "$f" 2>&1)"
check "tmux-ctl artifact registers" test -n "$(print -r -- "$out" | grep -F 'registered')"
check "tmux-ctl artifact wrote its manifest line" test -n "$(cat "$TC_STATE"/artifacts-*.jsonl 2>/dev/null)"

# 4. agent-board dispatcher
out="$(agent-board help 2>&1)"
for c in dev ctl dash jump cleanup; do check "agent-board help lists $c" test -n "$(print -r -- "$out" | grep -w $c)"; done
check "agent-board ctl help runs tmux-ctl" test -n "$(agent-board ctl help 2>&1 | grep -F 'tmux-ctl list')"
check "agent-board dev --help runs dev" test -n "$(agent-board dev --help 2>&1 | grep -iF 'dev')"
check "agent-board with no command exits 2" sh -c "! '$BIN/agent-board' >/dev/null 2>&1"

# 5. dash: scratch ports, scratch state (HOME), killed by PID in the trap
export TMUX_DASH_PORT=$(( 20000 + RANDOM % 20000 )) TMUX_DASH_TTYD_PORT=$(( 40000 + RANDOM % 20000 )) TTYD_BIN="$REAL_TTYD"
out="$(agent-board dash status 2>&1)"
check "agent-board dash status: server stopped" test -n "$(print -r -- "$out" | grep -F 'server: stopped')"
check "agent-board dash status: ttyd stopped" test -n "$(print -r -- "$out" | grep -F 'ttyd: stopped')"
if [[ -x "$REAL_TTYD" ]]; then
  out="$(agent-board dash start 2>&1)"
  check "agent-board dash start prints a scratch-port url" test -n "$(print -r -- "$out" | grep -F "127.0.0.1:$TMUX_DASH_PORT/")"
  out="$(agent-board dash status 2>&1)"
  check "dash status: server running" test -n "$(print -r -- "$out" | grep -F 'server: running')"
  check "dash status: ttyd running" test -n "$(print -r -- "$out" | grep -F 'ttyd: running')"
  agent-board dash stop >/dev/null 2>&1
  check "dash stop: server stopped" test -n "$(agent-board dash status 2>&1 | grep -F 'server: stopped')"
fi
check "dash wrote state only under the scratch HOME" test -d "$HOME/.local/state/tmux-dash"

# 6. ttyd's command is the repo's tmux-web-attach, wherever dash was started from (a stub ttyd records its argv)
stub="$TT_DIR/ttyd-stub"; argv_out="$TT_DIR/ttyd-argv"
print -r -- "#!/bin/sh
for a in \"\$@\"; do printf '%s\n' \"\$a\"; done > '$argv_out'
exec sleep 300" > "$stub"; chmod +x "$stub"
(cd / && TTYD_BIN="$stub" agent-board dash start >/dev/null 2>&1)
check "dash started from / gives ttyd the repo's tmux-web-attach" test "$(tail -n 1 "$argv_out" 2>/dev/null)" = "$BIN/tmux-web-attach"
agent-board dash stop >/dev/null 2>&1
tt_done
