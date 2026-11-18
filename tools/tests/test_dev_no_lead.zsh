source "${0:A:h}/lib.zsh"
# test_dev_no_lead.zsh — dev: DEV_NO_LEAD creates the session without typing a lead; DEV_CLAUDE_CMD is still typed; agent-board restore dispatch.
tt_setup claude
D="$TT_REPO/bin/dev"
export TC_LAYOUT=/usr/bin/true DEV_NO_ATTACH=1
unset TMUX TMUX_PANE
d1="$TT_DIR/nolead"; d2="$TT_DIR/withcmd"; mkdir -p "$d1" "$d2"
DEV_NO_LEAD=1 DEV_CLAUDE_CMD='echo should-not-type' "$D" "$d1" >/dev/null 2>&1
DEV_CLAUDE_CMD='echo restored-lead' "$D" "$d2" >/dev/null 2>&1
sleep 1
pane() { "$TT_BIN" -L "$TT_SOCK_NAME" capture-pane -p -t "=${1}:claude" }
check "no-lead session exists"       "$TT_BIN" -L "$TT_SOCK_NAME" has-session -t "=nolead"
check "no-lead types nothing"        sh -c "! { $TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=nolead:claude' | grep -qE 'claude-orchestrator|should-not-type'; }"
check "DEV_CLAUDE_CMD typed"         sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=withcmd:claude' | grep -q restored-lead"
check "agent-board dispatches restore" grep -q 'restore) shift; exec python3' "$TT_REPO/bin/agent-board"
check "agent-board help lists restore" sh -c "'$TT_REPO/bin/agent-board' help | grep -q 'agent-board restore'"
tt_done
