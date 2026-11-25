#!/usr/bin/env zsh
# test_run_watch_e2e.zsh — the run watch end to end on a scratch tmux server (lib.zsh, -f /dev/null). A stand-in lead (a
# binary named claude, ready per its agent-status file) and a `✦ fake` teammate (a binary named claude that runs
# `perl -e 'sleep 9999'` through a shell, as the Bash tool does) in a project whose temp task list holds a pending
# `Plan & run:` task with queue metadata (queue mode). A temp caps file gives `sleep 9999` a 1 s cap (TC_RUN_CAPS). The
# board's own build_overview and observe_overview run in-process with a clock seam: the run is alerted, found flat twice,
# killed by PID; the teammate pane shows the `[Watch] killed` line, the lead pane the nudge, kills.jsonl one line.
# Plus a read-only check of the real process tree and a leak check of the real watch files.
# Spec docs/superpowers/specs/2026-11-24-run-watch-design.md §b.
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
REAL_TC="${TMPDIR:-/tmp}"; REAL_TC="${REAL_TC%/}/tmux-ctl-$(id -u)"
REAL_AB="$HOME/.local/state/agent-board"
# leak check: compare content, not mtimes (the live board rewrites its watch files every overview): no real watch file
# (watch.json, watch/heartbeat, watch/kills.jsonl) may name this test's project. Prints how many real files it read.
leak() { local f n=0 hit=0; for f in "$REAL_TC"/watch*(N) "$REAL_TC"/watch/*(N) "$REAL_AB"/watch*(N) "$REAL_AB"/watch/*(N); do [[ -f $f ]] || continue; (( n++ )); grep -qF e2e-rw "$f" && (( hit++ )); done
  print -r -- "leak check: read $n real watch files, $hit name e2e-rw"; (( hit == 0 )) }
check "no real watch file names e2e-rw before the run" leak
REAL_HOME="$HOME"
tt_setup claude
E="$TT_DIR/e2e"; mkdir -p "$E/home/.claude/sessions" "$E/lead" "$E/mate" "$TC_STATE/discord/e2e-rw" "$TC_STATE/agent-status"
print -r -- '{"channel": "C1"}' > "$TC_STATE/discord/e2e-rw/bridge.json"
print -r -- '{"default_s": 900, "caps": [{"match": "sleep 9999", "cap_s": 1}]}' > "$E/caps.json"
# pane_current_command must read `claude` (a symlink reads as its target): two compiled stand-ins
printf '#include <unistd.h>\nint main(void){sleep(900);return 0;}\n' > "$E/lead.c"
printf '#include <stdlib.h>\n#include <unistd.h>\nint main(void){system("/bin/zsh -c '"'"'source /dev/null /Users/u/.claude/shell-snapshots/snapshot-zsh-1.sh; perl -e \\"sleep 9999\\"; :'"'"'");sleep(900);return 0;}\n' > "$E/mate.c"
cc -o "$E/lead/claude" "$E/lead.c" && cc -o "$E/mate/claude" "$E/mate.c" || { print "FAIL - cc"; exit 1 }
tt new-session -d -s e2e-rw -n claude -c "$E" "$E/lead/claude"
tt new-window -d -t '=e2e-rw:' -n '✦ fake' -c "$E" "$E/mate/claude"
LEAD="$(tt display -p -t '=e2e-rw:claude' '#{window_id}.#{pane_id}')"
SID=e2e0bbbb-0000-4000-8000-000000000002
print -r -- "{\"sessionId\": \"$SID\", \"tmux\": \"$LEAD\", \"updatedAt\": 1, \"pid\": 0, \"startedAt\": 0}" > "$E/home/.claude/sessions/1.json"
T="$E/home/.claude/tasks/session-${SID[1,8]}"; mkdir -p "$T"
print -r -- '{"id": "1", "subject": "Plan & run: docs/superpowers/specs/x.md", "status": "pending", "blockedBy": [], "metadata": {"queue": {"integration": "merge", "push": false, "answeredAt": "2026-11-24T00:00:00Z"}}}' > "$T/1.json"
cat > "$E/drive.py" <<'EOP'
import json, os, sys, time
board, lead_pane, mate_pane = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path.insert(0, board)
import server, watch, notify, tc_env  # noqa: E402
clock = [time.time()]
def fresh_status():   # the lead at its prompt, the teammate busy on its command (agent-status, preferred over pane text);
    t = clock[0]      # stamped with the seam clock so paneclass's 45 s STATUS_TTL keeps it
    for name, pane, st in (("lead", lead_pane, "ready"), ("mate", mate_pane, "working")):
        (tc_env.state_dir() / "agent-status" / f"{name}.json").write_text(json.dumps(
            {"pane": pane, "state": st, "since": t - 60, "updatedAt": t}))
(tc_env.state_dir() / "awake.json").write_text(json.dumps({"caffeinatePid": os.getpid(), "queue": True}))   # a live hold
server.NOTIFIER = notify.Notifier(runner=lambda a: None, enabled=False, now=lambda: clock[0])   # default sinks: the discord feed
server.WATCH = watch.Watch(now=lambda: clock[0], run=lambda argv: "ok", nudge=lambda p, line: server.COMMENTS.add_line(p, line),
                           alert=notify.discord_sink, tell=server.tell_pane)
watch.FLAT_KILL_S = 3   # the real floor is 120 s; the clock can't drive it: a jump past it reads as a new process (elapsed_s is real ps time)
def step(dt=None):   # dt None: the clock is real time (before the kill), else it jumps dt seconds
    clock[0] = time.time() if dt is None else clock[0] + dt
    fresh_status()
    server._state_cache["value"] = None
    ov = server.build_overview(clock[0])
    server.observe_overview(ov)
    return next(x for x in ov["projects"] if x["project"] == "e2e-rw")
time.sleep(2)   # the run is now past its 1 s cap
p = step()
print("runs", json.dumps([(r["window"], r["cmd"]) for r in p["runs"]], ensure_ascii=False))
pid = p["runs"][0]["pid"] if p["runs"] else 0
print("pid", pid)
time.sleep(1.5); step()   # flat once
time.sleep(1.5); step()   # flat twice, 1.5 s of flat time: under the floor, not killed
print("early_kill", os.path.exists(tc_env.state_dir() / "watch" / "kills.jsonl"))
time.sleep(2); step()     # flat 3.5 s: killed
time.sleep(1)
step(10)         # this build types the queued lead nudge
step(10)         # 10 s after the TERM: the KILL check
EOP
export TMUX_DASH_TOKEN=e2e TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME" TC_DISCORD_ALERTS=1 TC_RUN_CAPS="$E/caps.json"
MATE="$(tt display -p -t '=e2e-rw:✦ fake' '#{pane_id}')"
tt_wait 5 zsh -c 'pgrep -f "^perl -e sleep 9999$" >/dev/null' || print -u2 "perl slow to start"
OUT="$(HOME="$E/home" python3 -B "$E/drive.py" "$R/board" "$(tt display -p -t '=e2e-rw:claude' '#{pane_id}')" "$MATE" 2>"$E/drive.err")"
print -r -- "$OUT"
PID="$(print -r -- "$OUT" | sed -n 's/^pid //p')"
check "the run is the perl under the teammate's shell" grep -qxF 'runs [["✦ fake", "perl -e sleep 9999"]]' <<< "$OUT"
check "no kill under the flat-time floor" grep -qxF 'early_kill False' <<< "$OUT"
check "the run's process is gone" zsh -c '[[ $1 == <1-> ]] && ! kill -0 $1 2>/dev/null' _ "$PID"
FEED="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import tc_env; print(tc_env.feed_path("e2e-rw"))' "$R/board")"
check "discord feed: one run_overdue alert, critical" python3 -c '
import json, sys
ls = [json.loads(l) for l in open(sys.argv[1])]
hit = [l for l in ls if l["kind"] == "run_overdue"]
sys.exit(0 if len(hit) == 1 and hit[0]["tier"] == "critical" and "fake run past cap: perl -e sleep 9999 (0 min, cap 0 min)" in hit[0]["text"] else 1)' "$FEED"
check "teammate pane: the [Watch] killed line" tt_wait 5 zsh -c '"$1" -L "$2" capture-pane -p -J -t "=e2e-rw:✦ fake" | grep -qF "[Watch] killed perl -e sleep 9999 after 0 min, no progress: report to the lead"' _ "$TT_BIN" "$TT_SOCK_NAME"
check "lead pane: the nudge, once" tt_wait 5 zsh -c 'test "$("$1" -L "$2" capture-pane -p -J -t "=e2e-rw:claude" | grep -cF "[Watch] killed fake'"'"'s perl -e sleep 9999 after 0 min, no progress: read its report.")" -eq 1' _ "$TT_BIN" "$TT_SOCK_NAME"
check "kills.jsonl: one line for that pid" python3 -c '
import json, sys
ls = [json.loads(l) for l in open(sys.argv[1])]
sys.exit(0 if len(ls) == 1 and ls[0]["pid"] == int(sys.argv[2]) and ls[0]["project"] == "e2e-rw" and ls[0]["window"] == "✦ fake" and ls[0]["cap_s"] == 1 else 1)' "$TC_STATE/watch/kills.jsonl" "$PID"
# tell_pane against real panes (the run watch's hold rule): a pane whose input line holds typed text is held (False,
# nothing typed); a pane with an empty input line gets the line. Static `cat` panes draw Claude's rule + `❯` input frame.
RULE="$(printf '─%.0s' {1..20})"
tt new-window -d -t '=e2e-rw:' -n held -c "$E" sh -c "printf '%s\n❯ draft text\n' '$RULE'; cat"
tt new-window -d -t '=e2e-rw:' -n idle -c "$E" sh -c "printf '%s\n❯ \n' '$RULE'; cat"
sleep 1
HELD="$(tt display -p -t '=e2e-rw:held' '#{pane_id}')"; IDLE="$(tt display -p -t '=e2e-rw:idle' '#{pane_id}')"
TELL="$(python3 -B -c '
import sys; sys.path.insert(0, sys.argv[1]); import server
print("held", server.tell_pane(sys.argv[2], "[Watch] probe held"), "idle", server.tell_pane(sys.argv[3], "[Watch] probe idle"))' "$R/board" "$HELD" "$IDLE" 2>&1)"
print -r -- "tell_pane: $TELL"
check "tell_pane: held with text in the input, typed into an empty one" test "$TELL" = "held False idle True"
check "idle pane shows the line" tt_wait 5 zsh -c '"$1" -L "$2" capture-pane -p -J -t "=e2e-rw:idle" | grep -qF "[Watch] probe idle"' _ "$TT_BIN" "$TT_SOCK_NAME"
check "held pane never got the line" zsh -c '! "$1" -L "$2" capture-pane -p -J -t "=e2e-rw:held" | grep -qF "[Watch] probe held"' _ "$TT_BIN" "$TT_SOCK_NAME"
[[ -s "$E/drive.err" ]] && { print -r -- "--- driver stderr:"; cat "$E/drive.err" }

# read-only, real state: on this machine's own process tree, no direct non-shell child of a claude process (its MCP
# servers, caffeinate) is ever a run; prints how many claude processes it checked (skip only where none runs, e.g. CI)
check "real process tree: no MCP server or helper of a claude process is a run" python3 -B -c '
import subprocess, sys
sys.path.insert(0, sys.argv[1]); import overview
procs = overview.parse_ps(subprocess.run(list(overview.PS_ARGV), capture_output=True, text=True).stdout)
kids = {}
for pid in sorted(procs):
    if procs[pid]["ppid"] != pid:
        kids.setdefault(procs[pid]["ppid"], []).append(pid)
claudes = [p for p in procs if overview._is_claude(procs[p]["cmd"])]
if not claudes:
    print("skip: no claude process on this machine"); sys.exit(0)
bad = [r for c in claudes for r in overview.run_roots(c, procs, kids) if procs[r]["ppid"] == c and not overview._is_shell(procs[r]["cmd"])]
helpers = sum(1 for c in claudes for k in kids.get(c, []) if not overview._is_shell(procs[k]["cmd"]))
print(f"checked {len(claudes)} claude processes with {helpers} non-shell children: {len(bad)} counted as runs")
sys.exit(0 if not bad else 1)' "$R/board"
check "no leak into the real watch files" leak
tt_done
