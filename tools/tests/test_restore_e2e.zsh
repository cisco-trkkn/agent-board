# test_restore_e2e.zsh — `agent-board restore tick` after a (faked) reboot recreates two projects on a scratch tmux server.
# Isolation: a scratch tmux server (lib.zsh, -f /dev/null), TC_STATE in the scratch dir, TMUX_DASH_TMUX_ARGS pointing every
# tmux call at the scratch socket, stub scripts for the orchestrator and for tmux-ctl/agent-board (they log argv), the
# layout child and `route` replaced by /usr/bin/true. The user's own tmux server, ~/.local/state and claude are never touched.
source "${0:A:h}/lib.zsh"
tt_setup claude
R="$TT_REPO"
export TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME"
unset TMUX TMUX_PANE
S() { "$TT_BIN" -L "$TT_SOCK_NAME" "$@" }   # the scratch server by socket name ($TMUX is unset: the restore must not rely on it)
export TC_LAYOUT=/usr/bin/true TC_RESTORE_ROUTE=/usr/bin/true
STUBS="$TT_DIR/stubs"; mkdir -p "$STUBS"
export ORCH_ARGV="$TT_DIR/orch.argv" CTL_LOG="$TT_DIR/ctl.log"
# the paths are written into the stubs: the scratch server (and its pane shells) started before these exports
print -r -- "#!/bin/zsh
print -rl -- \"\$@\" > ${(q)ORCH_ARGV}; sleep 60" > "$STUBS/orch-stub"
print -r -- "#!/bin/zsh
print -r -- \"\$*\" >> ${(q)CTL_LOG}" > "$STUBS/ctl-stub"
chmod +x "$STUBS"/*
export TC_RESTORE_ORCH="$STUBS/orch-stub" TC_RESTORE_CTL="$STUBS/ctl-stub"
mkdir -p "$TT_DIR/projA" "$TT_DIR/projB" "$TC_STATE/restore" "$TC_STATE/discord/projA"
print -r -- $$ > "$TC_STATE/discord/projA/bridge.pid"    # a live pid: the bridge counts as up
python3 - "$TT_DIR" "$TC_STATE/restore/snapshot.json" <<'PY'
import json, sys
d, out = sys.argv[1:3]
json.dump({"boot": 1, "saved_at": 1.0, "restored": False, "awake": None, "projects": [
    {"name": "projA", "path": f"{d}/projA", "bridge": True,
     "lead": {"session_id": "11112222-aaaa-bbbb-cccc-ddddeeeeffff", "model": "opus", "discord": True}},
    {"name": "projB", "path": f"{d}/projB", "bridge": False, "lead": None}]}, open(out, "w"))
PY

python3 "$R/board/restore.py" tick; rc=$?
check "tick exits 0" test $rc -eq 0
check "session projA exists" S has-session -t "=projA"
check "session projB exists" S has-session -t "=projB"
tt_wait 8 test -s "$ORCH_ARGV"
argv="$(tr '\n' ' ' < "$ORCH_ARGV" 2>/dev/null)"
check "lead A: model, channels and resume sid" grep -qF -- "--model opus --channels plugin:discord@claude-plugins-official --resume 11112222-aaaa-bbbb-cccc-ddddeeeeffff The Mac was rebooted" <<<"$argv"
pane_a="$(S capture-pane -J -p -t "=projA:claude" | tr -d "\n")"   # zsh wraps the long line itself: tmux cannot join it
check "pane A shows the typed lead command" grep -qF -- "orch-stub --model opus --channels plugin:discord@claude-plugins-official --resume 11112222-aaaa-bbbb-cccc-ddddeeeeffff" <<<"$pane_a"
pane_b="$(S capture-pane -J -p -t "=projB:claude")"; rc_b=$?
check "pane B is readable and has no typed command" test $rc_b -eq 0 -a -z "$(grep -F orch-stub <<<"$pane_b")"
check "ctl log: dash start" grep -qx 'dash start' "$CTL_LOG"
check "ctl log: bridge start for A" grep -qx 'discord bridge start --project projA' "$CTL_LOG"
check "ctl log: send -m for A" grep -q '^discord send --project projA -m Mac restarted at .*lead resumed (11112222) · bridge · keep-awake none' "$CTL_LOG"
check "ctl log: nothing for B" test -z "$(grep -F projB "$CTL_LOG")"
check "snapshot marked restored with results" python3 -c '
import json, sys
s = json.load(open(sys.argv[1]))
assert s["restored"] is True and "restored_at" in s and s["results"]["projA"]["status"] == "restored", s' "$TC_STATE/restore/snapshot.json"

n_before="$(wc -l < "$CTL_LOG" | tr -d ' ')"
python3 "$R/board/restore.py" tick
check "second tick: no new ctl calls (no second restore)" test "$(wc -l < "$CTL_LOG" | tr -d ' ')" = "$n_before"
check "second tick: one dash start in total" test "$(grep -cx 'dash start' "$CTL_LOG")" = 1
tt_done
