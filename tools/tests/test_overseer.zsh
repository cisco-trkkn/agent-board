source "${0:A:h}/lib.zsh"
# Overseer lifecycle on a scratch server: created with the first project session, recreated after kill-session,
# stopped when the last project closes, never with TC_OVERSEER=0. The window runs TC_OVERSEER_CMD (a sleeper), not claude.
O="${TC_OVERSEER_BIN:-$TT_REPO/bin/tmux-overseer}"; L="${TC_LAYOUT:-$TT_REPO/bin/tmux-dev-layout}"
tt_setup shell                                  # tt_setup exports TC_OVERSEER=0; this test turns it on itself
export TC_OVERSEER_CMD='exec sleep 6007'
export XDG_STATE_HOME="$TT_DIR/xdg"        # the overseer's start dir lives under it: scratch, never the real ~/.local/state
running() { tt has-session -t '=overseer' 2>/dev/null }
# session tt has only a `shell` window: no project at all, and the server stays up (a restarted scratch server would load ~/.tmux.conf and its resurrect restore)
unset TC_OVERSEER
tt new-session -d -s lonely -n shell -c "$TT_DIR"
"$O" ensure
check "no project with a claude window: not created"   sh -c "! $TT_BIN has-session -t '=overseer' 2>/dev/null"
tt new-session -d -s p1 -n claude -c "$TT_DIR"
"$L" p1 "$TT_DIR"                                 # the dev layout is the session setup that ensures the overseer
check "created with the first project session"   running
check "tagged @tc_overseer"                       test "$(tt show-options -qv -t '=overseer:' @tc_overseer)" = 1
check "starts in its own state dir, not the repo"  test "$(tt display -p -t '=overseer:' '#{session_path}')" = "$XDG_STATE_HOME/agent-board/overseer"
check "window runs the seam command"              tt_wait 5 sh -c "$TT_BIN display -p -t '=overseer:claude' '#{pane_current_command}' | grep -qx sleep"
check "status says running"                       sh -c "$O status | grep -qx running"
check "ensure is idempotent (one session)"        sh -c "$O ensure; $TT_BIN list-sessions -F '#{session_name}' | grep -cx overseer | grep -qx 1"
tt kill-session -t '=overseer'
"$O" ensure
check "recreated after kill-session"              running
tt new-session -d -s p2 -n claude -c "$TT_DIR"
tt kill-session -t '=p1'; "$O" stop
check "stop keeps it while a project remains"     running
tt kill-session -t '=p2'; "$O" stop
check "stopped when the last project closes"      sh -c "! $TT_BIN has-session -t '=overseer' 2>/dev/null"
check "status says stopped, exit 1"               sh -c "! $O status >/dev/null"
# I2: Claude exits (or the trust dialog is refused) and leaves a shell: ensure retypes the command, at most once per TC_OVERSEER_RETRY_S (60)
tt new-session -d -s p5 -n claude -c "$TT_DIR"
tt kill-session -t '=overseer' 2>/dev/null; rm -f "$TT_DIR/runs"
export TC_OVERSEER_CMD="echo run >> $TT_DIR/runs"   # exits at once, the pane falls back to a shell
"$O" ensure
check "exiting command: first start typed once"   tt_wait 5 sh -c "[ \"\$(grep -c run '$TT_DIR/runs' 2>/dev/null)\" = 1 ]"
check "pane is back at a shell"                   tt_wait 5 sh -c "$TT_BIN display -p -t '=overseer:claude' '#{pane_current_command}' | grep -Eqx '(-?)(zsh|bash|sh|fish|dash)'"
"$O" ensure; sleep 1
check "ensure within 60s does not retype"         test "$(grep -c run "$TT_DIR/runs")" = 1
TC_OVERSEER_RETRY_S=0 "$O" ensure
check "ensure at a shell past the limit retypes"  tt_wait 5 sh -c "[ \"\$(grep -c run '$TT_DIR/runs')\" = 2 ]"
export TC_OVERSEER_CMD='exec sleep 6007'
tt kill-session -t '=overseer'; "$O" ensure
check "a running command is not retyped"          tt_wait 5 sh -c "$TT_BIN display -p -t '=overseer:claude' '#{pane_current_command}' | grep -qx sleep"
TC_OVERSEER_RETRY_S=0 "$O" ensure; sleep 1
check "still one sleeper after ensure"            sh -c "[ \"\$(pgrep -f 'sleep 6007' | wc -l | tr -d ' ')\" = 1 ]"
# I3: a browser view (grouped _web- session) must not keep the overseer's window alive after stop
tt new-session -d -t '=overseer' -s _web-9999
tt kill-session -t '=p5'
"$O" stop
check "stop with a grouped _web- view: overseer gone"   sh -c "! $TT_BIN has-session -t '=overseer' 2>/dev/null"
check "stop with a grouped _web- view: view gone too"   sh -c "! $TT_BIN has-session -t '=_web-9999' 2>/dev/null"
check "stop with a view: no sleeper left"               tt_wait 5 sh -c "! pgrep -f 'sleep 6007' >/dev/null"
tt new-session -d -s p3 -n claude -c "$TT_DIR"
TC_OVERSEER=0 "$O" ensure
check "not created with TC_OVERSEER=0"            sh -c "! $TT_BIN has-session -t '=overseer' 2>/dev/null"
# the session-closed hook path: register the real hook line and close the last project
grep '^set-hook -g session-closed' "${TC_CONF:-$TT_REPO/config/tmux.conf}" > "$TT_DIR/hook.conf"; tt source-file "$TT_DIR/hook.conf"
"$O" ensure; check "created again for p3" running
tt kill-session -t '=p3'
check "session-closed hook stops it"              tt_wait 5 sh -c "! $TT_BIN has-session -t '=overseer' 2>/dev/null"
check "leak check: no overseer process left"      sh -c "! pgrep -f 'sleep 6007' >/dev/null"
# tmux-ctl overview: no board reachable (empty token dir) -> the local build lists this scratch server's projects
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt new-session -d -s p4 -n claude -c "$TT_DIR"
out="$(cd "$TT_DIR" && TMUX_DASH_STATE="$TT_DIR/nodash" TC_SESSION=p4 $C overview --json 2>/dev/null)"
check "tmux-ctl overview --json lists the scratch project, source local" python3 -c 'import json,sys; d=json.loads(sys.argv[1]); assert d["source"]=="local" and "p4" in [p["project"] for p in d["projects"]] and "overseer" not in [p["project"] for p in d["projects"]], d' "$out"
check "tmux-ctl overview p4 prints one line"   test "$(cd "$TT_DIR" && TMUX_DASH_STATE="$TT_DIR/nodash" TC_SESSION=p4 $C overview p4 2>/dev/null | grep -c '^p4 ')" = 1
check "tmux-ctl overview rejects two projects"  sh -c "cd $TT_DIR && TC_SESSION=p4 $C overview a b 2>&1 | grep -q usage"
check "tmux-ctl overview of an unknown project exits 1" sh -c "cd $TT_DIR && TMUX_DASH_STATE=$TT_DIR/nodash TC_SESSION=p4 $C overview nope >/dev/null 2>&1; test \$? = 1"
check "tmux-ctl overview with two projects exits 2"     sh -c "cd $TT_DIR && TC_SESSION=p4 $C overview a b >/dev/null 2>&1; test \$? = 2"
check "help names overview"                     sh -c "TC_SESSION=p4 $C help | grep -q 'overview \[project\]'"
# the launcher itself, with a stub `claude` that records its argv and the child-session marker (no real Claude starts)
mkdir -p "$TT_DIR/stubbin"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" > "$TT_DIR/stub.argv"\nprintf "%%s\\n" "${CLAUDE_CODE_CHILD_SESSION-UNSET}" > "$TT_DIR/stub.child"\nenv | grep -E "^(CLAUDECODE|CLAUDE_CODE_SESSION_ID|CLAUDE_CODE_SSE_PORT|CLAUDE_CODE_MESSAGING_SOCKET|CLAUDE_CODE_MESSAGING_TOKEN)=" | cut -d= -f1 > "$TT_DIR/stub.leaked"\n' > "$TT_DIR/stubbin/claude"
chmod +x "$TT_DIR/stubbin/claude"
CLAUDECODE=1 CLAUDE_CODE_SESSION_ID=x CLAUDE_CODE_SSE_PORT=1 CLAUDE_CODE_MESSAGING_SOCKET=x CLAUDE_CODE_MESSAGING_TOKEN=x CLAUDE_CODE_CHILD_SESSION=1 PATH="$TT_DIR/stubbin:$PATH" TT_DIR="$TT_DIR" "$TT_REPO/bin/claude-overseer" >/dev/null 2>&1
check "launcher excludes the user settings source"   grep -q -- '--setting-sources project,local' "$TT_DIR/stub.argv"
check "launcher keeps the overseer settings file"    grep -q -- "--settings $TT_REPO/claude/overseer-settings.json" "$TT_DIR/stub.argv"
check "launcher unsets CLAUDE_CODE_CHILD_SESSION"    test "$(cat "$TT_DIR/stub.child")" = UNSET
check "launcher unsets the session-scoped CLAUDECODE/CLAUDE_CODE_* variables (leaked names: $(tr '\n' ' ' < "$TT_DIR/stub.leaked"))"  test ! -s "$TT_DIR/stub.leaked"
tt_done
