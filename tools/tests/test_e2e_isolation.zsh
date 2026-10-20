# test_e2e_isolation.zsh — installing and using agent-board leaves a user's own Claude Code and tmux setup as it was.
# Isolation: a scratch HOME (everything agent-board writes lands there), two private tmux sockets (A = the user's own
# server, stands in for the default server; B = agent-board's server, stands in for -L agent-board), TC_STATE in the
# scratch dir. The trap kills only those two servers; the real default server, the real -L agent-board server, ~/.claude,
# ~/.tmux.conf and ~/.local are never started, written or (outside the leak check's hashes) read.
# TMUX_TMPDIR is a scratch dir before any tmux call: a plain `tmux` (no -L/-S) would land on a scratch "default" socket,
# not the real default server, and the check at the end fails the test if that socket exists.
ORIG_TMPDIR="${TMUX_TMPDIR:-/tmp}"   # where the REAL tmux sockets live, captured before the scratch export
TMX="$(mktemp -d /tmp/abx.XXXXXX)"; export TMUX_TMPDIR="$TMX"
source "${0:A:h}/lib.zsh"
R="$TT_REPO"; F="${0:A:h}/fixtures"
tt_setup claude shell
A_SOCK="$TT_SOCK_NAME"; B_SOCK="abe2e-$$-$RANDOM"
export AGENT_BOARD_TMUX_SOCKET="$B_SOCK"
A() { "$TT_BIN" -L "$A_SOCK" "$@" }
B() { "$TT_BIN" -L "$B_SOCK" "$@" }
kill_b() {
  local sp; sp="$("$TT_BIN" -L "$B_SOCK" display -p '#{socket_path}' 2>/dev/null)"
  "$TT_BIN" -L "$B_SOCK" kill-server 2>/dev/null; [[ -n "$sp" ]] && rm -f "$sp"
}
kill_x() { "$TT_BIN" -S "$TMX/tmux-$UID/default" kill-server 2>/dev/null; rm -rf "$TMX" }   # a stray plain tmux would have started a server here
trap 'kill_b; tt_teardown; kill_x' EXIT INT TERM
REALHOME="$HOME"
real_sum() { shasum -a 256 "$REALHOME/.claude/settings.json" "$REALHOME/.tmux.conf" 2>&1 }
real_sum > "$TT_DIR/real.before"
real_sock() { "$TT_BIN" -S "$ORIG_TMPDIR/tmux-$UID/agent-board" list-sessions -F x 2>/dev/null | wc -l | tr -d ' ' }
real_b0="$(real_sock)"

# --- the user's setup, in a scratch HOME
H="$TT_DIR/home"; PROJ="$TT_DIR/proj"
mkdir -p "$H/.claude/skills/x" "$H/.claude/agents" "$H/.local/bin" "$PROJ"; git -C "$PROJ" init -q
print -r -- '{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"echo user-probe >> /dev/null"}]}]},"theme":"dark"}' > "$H/.claude/settings.json"
print 'name: x' > "$H/.claude/skills/x/SKILL.md"; print 'my agent' > "$H/.claude/agents/y.md"
print "set-hook -g after-split-window 'display-message my-own-hook'" > "$H/.tmux.conf"
print 'export FOO=1' > "$H/.zshrc"; print '#!/bin/sh' > "$H/.local/bin/mytool"; chmod +x "$H/.local/bin/mytool"
A set-hook -g after-split-window 'display-message my-own-hook'; A bind-key U display-message mine
A show-hooks -g > "$TT_DIR/hooks.before"; A list-keys > "$TT_DIR/keys.before"
hashes() { ( cd "$H" && find .claude .tmux.conf .zshrc -type f | LC_ALL=C sort | xargs shasum -a 256 ) }
hashes > "$TT_DIR/files.before"
mkdir -p "$TT_DIR/stubs"; print -r -- '#!/bin/sh
echo stub-claude > "$STUB_MARK"; exec sleep 120' > "$TT_DIR/stubs/claude"; chmod +x "$TT_DIR/stubs/claude"
export STUB_MARK="$TT_DIR/stub.mark"

# --- aged state: yesterday's run and a feed log of two agents spanning midnight, already in TC_STATE
zmodload zsh/datetime
mid="$(date -j -f '%Y-%m-%d %H:%M:%S' "$(date +%Y-%m-%d) 00:00:00" +%s)"
e1=$(( mid - 600 )); e2=$(( mid - 60 )); e3=$(( mid + 60 ))
mkdir -p "$TC_STATE/logs/proj"; print 'old output' > "$TC_STATE/logs/proj/old.log"
print -r -- "{\"id\":\"old-1\",\"ts\":$e1,\"agent\":\"agent-a\",\"win\":\"tests\",\"session\":\"proj\",\"cmd\":\"pytest yesterday\",\"cwd\":\"$PROJ\",\"exit\":0,\"duration\":3,\"log\":\"$TC_STATE/logs/proj/old.log\",\"summary\":\"4 passed\"}" > "$TC_STATE/runs-proj.jsonl"
{ for spec in "agent-a $e1 0 first" "agent-b $e2 1 second" "agent-a $e3 0 third"; do
    set -- ${=spec}; print -r -- "── $(strftime %H:%M:%S $2) · $1 · ~/proj · exit $3 · @$2"; print -r -- "\$ pytest $4"; print
  done; } > "$TC_STATE/feed-proj-tests.log"

# --- install.sh, agent-board dev (stub claude), tmux-ctl run, a teammate split
out="$(HOME="$H" zsh "$R/install.sh" 2>&1)"; rc=$?
check "install: exit 0"                       test $rc -eq 0
check "install: one link to this checkout"    test "$(readlink "$H/.local/bin/agent-board")" = "$R/bin/agent-board"
AB="$H/.local/bin/agent-board"
out="$(env -u TMUX -u TMUX_PANE HOME="$H" TC_TMUX="$TT_BIN" DEV_NO_ATTACH=1 DEV_CLAUDE_CMD="$TT_DIR/stubs/claude" "$AB" dev "$PROJ" 2>&1)"; rc=$?
check "dev: exit 0, ready"                    test $rc -eq 0 -a "$out" = "session 'proj' ready"
check "dev: session on agent-board's server"  B has-session -t '=proj'
check "dev: not on the user's server"         sh -c "! $TT_BIN -L $A_SOCK has-session -t '=proj' 2>/dev/null"
check "dev: stub claude ran in the claude window" tt_wait 10 test -f "$STUB_MARK"
bsock="$(B display -p -t '=proj:claude' '#{socket_path}')"; bpane="$(B display -p -t '=proj:claude' '#{pane_id}')"
inB() { env HOME="$H" TC_TMUX="$TT_BIN" TMUX="$bsock,1,0" TMUX_PANE="$bpane" "$@" }
out="$(cd "$PROJ" && inB "$AB" ctl run tests 'echo ok' 2>&1)"
check "run: printed ok"                       test "${out%%$'\n'*}" = ok
check "run: [exit 0]"                         test "${out##*$'\n'}" = "[exit 0]"
# the mirror hook records a call, as the plugin's PostToolUse hook would
sed "s|__HOME__|$H|" "$F/ok.json" | inB AGENT_BOARD=1 "$R/claude/hooks/bash-mirror.sh" --scoped
TEAMMATE_CMD="cd /tmp && env CLAUDECODE=1 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 sh -c 'sleep 60; :' --agent-id NAME@proj --agent-name NAME --team-name proj --agent-color green --parent-session-id 00000000-0000-0000-0000-000000000000 --agent-type general-purpose --permission-mode auto --model sonnet"
B split-window -d -t '=proj:claude' "${TEAMMATE_CMD//NAME/probe-e}"
win_of() { B list-windows -t '=proj' -F '#{window_name}' 2>/dev/null | grep -qxF -- "✦ probe-e" }
check "teammate split → ✦ window on B"        tt_wait 12 win_of
check "teammate split: user's server has no such window" sh -c "! $TT_BIN -L $A_SOCK list-windows -a -F '#{window_name}' | grep -q probe-e"

# --- the user's setup is as it was
hashes > "$TT_DIR/files.after"
check "files: ~/.claude, ~/.tmux.conf, ~/.zshrc hashes unchanged" diff "$TT_DIR/files.before" "$TT_DIR/files.after"
check "~/.local/bin: agent-board + the seeded tool only" test "$(ls -A "$H/.local/bin" | tr '\n' ' ')" = "agent-board mytool "
check "~/.claude: nothing new"                test "$(cd "$H" && find .claude | LC_ALL=C sort | tr '\n' ' ')" = ".claude .claude/agents .claude/agents/y.md .claude/settings.json .claude/skills .claude/skills/x .claude/skills/x/SKILL.md "
A show-hooks -g > "$TT_DIR/hooks.after"; A list-keys > "$TT_DIR/keys.after"
check "user server: show-hooks -g unchanged"  diff "$TT_DIR/hooks.before" "$TT_DIR/hooks.after"
check "user server: list-keys unchanged"      diff "$TT_DIR/keys.before" "$TT_DIR/keys.after"

# --- aged: yesterday's run and the midnight-spanning feed read back in order next to the new ones
runs="$(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import activity; print(" ".join(r["cmd"].replace(" ","_") for r in activity.runs("proj")))' "$R/board")"
check "aged: runs() = new run, then yesterday's" test "$runs" = "echo_ok pytest_yesterday"
feed="$(inB "$AB" ctl feed tests 100 | grep '^── ' | awk -F' · ' '{print $2}' | tr '\n' ' ')"
check "aged: feed keeps agent-a, agent-b, agent-a across midnight, then the new entry" test "$feed" = "agent-a agent-b agent-a claude "
eps="$(inB "$AB" ctl feed tests 100 | grep '^── ' | sed 's/.*@//' | tr '\n' ' ')"
check "aged: feed epochs ascend"              test "$eps" = "$(print -r -- ${(n)=eps}) "

# --- plain session unaffected: a real `claude -p` in the scratch repo, the user's probe hook only
if (( $+commands[claude] )); then
  PR="$TT_DIR/plain"; mkdir -p "$PR/state"; git -C "$PR" init -q
  print -r -- "{\"hooks\":{\"UserPromptSubmit\":[{\"hooks\":[{\"type\":\"command\",\"command\":\"echo user-hook >> $PR/probe\"}]}]}}" > "$PR/settings.json"
  ( cd "$PR" && exec env -u TMUX -u TMUX_PANE -u AGENT_BOARD TC_STATE="$PR/state" claude -p --model haiku --no-session-persistence --settings "$PR/settings.json" 'Reply with the single word ok.' > "$PR/out" 2>&1 ) &
  cpid=$!; ( sleep 60; kill $cpid ) >/dev/null 2>&1 </dev/null & kpid=$!   # 60s cap; output closed so it can't hold a pipe open
  wait $cpid; crc=$?; kill $kpid 2>/dev/null
  if grep -qx user-hook "$PR/probe" 2>/dev/null; then
    check "plain claude: the user's hook fired" true
    check "plain claude: no agent-board marker" test -z "$(ls -A "$PR/state")" -a "$(sort -u "$PR/probe")" = user-hook
  else
    print -r -- "skip - claude -p did not reach the prompt hook (exit $crc: timeout, auth or network): $(head -c 200 "$PR/out")"
  fi
else
  print -r -- "skip - no claude"
fi

# --- leak check
real_sum > "$TT_DIR/real.after"
check "leak: real settings.json and .tmux.conf unchanged" diff "$TT_DIR/real.before" "$TT_DIR/real.after"
check "leak: real -L agent-board server untouched" test "$(real_sock)" = "$real_b0"
check "leak: nothing talked to the default tmux socket" test ! -e "$TMX/tmux-$UID/default"
kill_b
check "leak: the stand-in agent-board server is gone" sh -c "! $TT_BIN -L $B_SOCK list-sessions >/dev/null 2>&1"
tt_done
