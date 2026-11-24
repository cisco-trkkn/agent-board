# test_restore_e2e.zsh — `agent-board restore tick` after a (faked) reboot recreates two projects on a scratch tmux server.
# Isolation: a scratch tmux server (lib.zsh, -f /dev/null), TC_STATE in the scratch dir, TMUX_DASH_TMUX_ARGS pointing every
# tmux call at the scratch socket, stub scripts for the orchestrator and for tmux-ctl/agent-board (they log argv), the
# layout child and `route` replaced by /usr/bin/true. The user's own tmux server, ~/.local/state and claude are never touched.
source "${0:A:h}/lib.zsh"
# reboot auto-restore reads kern.boottime (sysctl) and runs from a LaunchAgent: macOS only, board/restore.py has no Linux boot time
[[ "$OSTYPE" == darwin* ]] || { print -r -- "skip - restore e2e: macOS only (kern.boottime, launchd)"; print "ALL PASS"; exit 0 }
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
# `engine status --unfinished` is a question, not an action: it is not logged, and answers 1 (no unfinished queue) unless the
# file $TT_DIR/unfinished-<project> exists (then 0, as the real command does for an unfinished queue). Every other call is logged.
print -r -- "#!/bin/zsh
if [[ \"\$1 \$2 \$3\" == 'engine status --unfinished' ]]; then
  [[ -e ${(q)TT_DIR}/unfinished-\${@[-1]} ]] && exit 0
  exit 1
fi
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
cp "$TC_STATE/restore/snapshot.json" "$TT_DIR/seed.json"

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

# --- the same restore under the LaunchAgent's environment: nothing but HOME, the plist PATH and the seams, /usr/bin/python3
# (3.9 on this Mac). Real /sbin/route, no TC_RESTORE_ROUTE: it proves sysctl and route resolve there. Skipped where there is no
# default route to find (a runner without network would sit in the 300 s wait).
if [[ "$OSTYPE" == darwin* ]] && /sbin/route -n get default >/dev/null 2>&1; then
  S kill-session -t "=projA"; S kill-session -t "=projB"
  rm -f "$ORCH_ARGV" "$CTL_LOG"
  : > "$TT_DIR/unfinished-projA"   # projA has an unfinished engine queue: the restore starts its engine (spec section 11)
  cp "$TT_DIR/seed.json" "$TC_STATE/restore/snapshot.json"   # the seeded older-boot snapshot again (the second tick above replaced it)
  check "launchd env: snapshot reset has two projects" test "$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["projects"]))' "$TC_STATE/restore/snapshot.json")" = 2
  # TMUX_TMPDIR (and the real one all.zsh records) must survive env -i, and every tmux call names the scratch socket by path
  # with -f /dev/null: a server started by mistake would otherwise load ~/.tmux.conf (continuum, resurrect) and outlive the run.
  scratch_sock="$(S display -p '#{socket_path}')"
  env -i HOME="$HOME" PATH="$HOME/.local/bin:/opt/homebrew/bin:$HOME/.bun/bin:/usr/bin:/bin" TC_STATE="$TC_STATE" \
    ${TMUX_TMPDIR:+TMUX_TMPDIR=$TMUX_TMPDIR} ${TC_REAL_TMUX_TMPDIR:+TC_REAL_TMUX_TMPDIR=$TC_REAL_TMUX_TMPDIR} \
    TMUX_DASH_TMUX_ARGS="-S $scratch_sock -f /dev/null" TC_RESTORE_ORCH="$TC_RESTORE_ORCH" TC_RESTORE_CTL="$TC_RESTORE_CTL" \
    TC_LAYOUT=/usr/bin/true /usr/bin/python3 "$R/board/restore.py" tick
  check "launchd env: tick exits 0" test $? -eq 0
  check "launchd env: both sessions recreated" test "$(S has-session -t "=projA" 2>&1 && S has-session -t "=projB" 2>&1; print $?)" = 0
  check "launchd env: ctl log has dash start and bridge start" test "$(grep -cE '^(dash start|discord bridge start --project projA)$' "$CTL_LOG")" = 2
  check "launchd env: unfinished engine queue of A: engine start, none for B" test "$(grep -cE '^engine start --session projA$' "$CTL_LOG")" = 1 -a -z "$(grep -F projB "$CTL_LOG")"
  check "launchd env: snapshot marked restored" python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["restored"] is True' "$TC_STATE/restore/snapshot.json"
else
  print -r -- "skip - launchd env case: needs macOS and a default route"
fi
tt_done
