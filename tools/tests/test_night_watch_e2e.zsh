#!/usr/bin/env zsh
# test_night_watch_e2e.zsh — the night watch end to end on a scratch tmux server (lib.zsh, -f /dev/null): a stand-in lead
# (a binary named claude at its prompt: an agent-status file says ready) and a `✦ fake` teammate window owning task #2 of a
# temp task list that also holds a pending `Plan & run:` task with queue metadata. The board's own build_overview and
# observe_overview run in-process with a clock seam; the teammate pane is killed; the Discord feed line, the [Watch] line
# typed into the lead pane, and (clock moved 15 min) the re-alert are checked. Plus a read-only check of the real task
# lists (queue_mode against an independent count) and a leak check of the real watch files.
# Spec docs/superpowers/specs/2026-11-23-night-watch-design.md §7.
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
REAL_TC="${TMPDIR:-/tmp}"; REAL_TC="${REAL_TC%/}/tmux-ctl-$(id -u)"
REAL_AB="$HOME/.local/state/agent-board"
# leak check: after the live board runs this code it rewrites the real watch files every overview, so compare content, not
# mtimes: no real watch file may name this test's project (e2e-nw). Prints how many real files it read.
leak() { local f n=0 hit=0; for f in "$REAL_TC"/watch*(N) "$REAL_TC"/watch/*(N) "$REAL_AB"/watch*(N); do [[ -f $f ]] || continue; (( n++ )); grep -qF e2e-nw "$f" && (( hit++ )); done
  print -r -- "leak check: read $n real watch files, $hit name e2e-nw"; (( hit == 0 )) }
check "no real watch file names e2e-nw before the run" leak
REAL_HOME="$HOME"
tt_setup claude
E="$TT_DIR/e2e"; mkdir -p "$E/home/.claude/sessions" "$E/fake" "$TC_STATE/discord/e2e-nw" "$TC_STATE/agent-status"
print -r -- '{"channel": "C1"}' > "$TC_STATE/discord/e2e-nw/bridge.json"
printf '#include <unistd.h>\nint main(void){sleep(900);return 0;}\n' > "$E/c.c"
cc -o "$E/fake/claude" "$E/c.c" || { print "FAIL - cc"; exit 1 }   # pane_current_command must read `claude` (a symlink reads as its target)
tt new-session -d -s e2e-nw -n claude -c "$E" "$E/fake/claude"
tt new-window -d -t '=e2e-nw:' -n '✦ fake' -c "$E" "$E/fake/claude"
LEAD="$(tt display -p -t '=e2e-nw:claude' '#{window_id}.#{pane_id}')"
SID=e2e0aaaa-0000-4000-8000-000000000001
print -r -- "{\"sessionId\": \"$SID\", \"tmux\": \"$LEAD\", \"updatedAt\": 1, \"pid\": 0, \"startedAt\": 0}" > "$E/home/.claude/sessions/1.json"
T="$E/home/.claude/tasks/session-${SID[1,8]}"; mkdir -p "$T"
print -r -- '{"id": "1", "subject": "Plan & run: docs/superpowers/specs/x.md", "status": "pending", "blockedBy": [], "metadata": {"queue": {"integration": "merge", "push": false, "answeredAt": "2026-11-24T00:00:00Z"}}}' > "$T/1.json"
print -r -- '{"id": "2", "subject": "Task 2: x", "status": "in_progress", "owner": "fake", "blockedBy": []}' > "$T/2.json"
print -r -- '{"id": "3", "subject": "Task 3: y", "status": "pending", "blockedBy": ["2"]}' > "$T/3.json"
cat > "$E/drive.py" <<'EOP'
import json, os, sys, time
board, lead_pane = sys.argv[1], sys.argv[2]
sys.path.insert(0, board)
import server, watch, notify, tc_env  # noqa: E402
clock = [time.time()]
runs = []
def fresh_status():   # the lead at its prompt, per agent-status (the mod the board prefers over pane text); stamped with the seam clock so paneclass's 45 s TTL keeps it
    t = clock[0]
    (tc_env.state_dir() / "agent-status" / "lead.json").write_text(json.dumps(
        {"pane": lead_pane, "state": "ready", "since": t - 60, "updatedAt": t}))
(tc_env.state_dir() / "awake.json").write_text(json.dumps({"caffeinatePid": os.getpid(), "queue": True}))   # a live hold: only the teammate stalls
server.NOTIFIER = notify.Notifier(runner=lambda a: None, enabled=False, now=lambda: clock[0])   # default sinks: the discord feed
server.WATCH = watch.Watch(now=lambda: clock[0], run=lambda argv: runs.append(argv) or "ok",
                           nudge=lambda p, line: server.COMMENTS.add_line(p, line), alert=notify.discord_sink)
def step():
    fresh_status()
    server._state_cache["value"] = None
    ov = server.build_overview(clock[0])
    return ov, server.observe_overview(ov)
ov, _ = step()
p = next(x for x in ov["projects"] if x["project"] == "e2e-nw")
print("seed", json.dumps({"queue": p["queue"], "owned": p["owned"], "awake": p["awake"]}))
server.tmux("kill-pane", "-t", "=e2e-nw:✦ fake")
clock[0] += 30
ov, ev = step()
print("events", " ".join(e["kind"] for e in ev))
clock[0] += 30
step(); time.sleep(1)   # this build delivers the queued line into the lead pane
clock[0] += watch.REALERT_S
step()
print("runs", len(runs))
EOP
export TMUX_DASH_TOKEN=e2e TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME" TC_DISCORD_ALERTS=1
OUT="$(HOME="$E/home" python3 -B "$E/drive.py" "$R/board" "$(tt display -p -t '=e2e-nw:claude' '#{pane_id}')" 2>"$E/drive.err")"
print -r -- "$OUT"
check "seed: queue mode on, teammate window present, hold live" grep -qF 'seed {"queue": true, "owned": [{"owner": "fake", "task": "2", "window": true, "dead": false, "ready_s": null}], "awake": true}' <<< "$OUT"
check "kill: one teammate_gone event" grep -qx 'events teammate_gone' <<< "$OUT"
FEED="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import tc_env; print(tc_env.feed_path("e2e-nw"))' "$R/board")"
check "discord feed: the teammate_gone alert, critical" python3 -c '
import json, sys
ls = [json.loads(l) for l in open(sys.argv[1])]
sys.exit(0 if any(l["kind"] == "teammate_gone" and l["tier"] == "critical" and "teammate fake window is gone (task #2 in progress)" in l["text"] for l in ls) else 1)' "$FEED"
check "lead pane: the [Watch] line was typed" tt_wait 5 zsh -c 'tmux_bin="$1"; shift; "$tmux_bin" -L "$1" capture-pane -p -J -t "=e2e-nw:claude" | grep -qF "[Watch] teammate fake window is gone (task #2 in progress): respawn it."' _ "$TT_BIN" "$TT_SOCK_NAME"
check "lead pane: typed once" test "$(tt capture-pane -p -J -t '=e2e-nw:claude' | grep -cF '[Watch] teammate fake window is gone')" -eq 1
check "discord feed: one re-alert after 15 min" test "$(grep -cF 'teammate fake window is gone (task #2 in progress) — lead did not react (15 min)' "$FEED")" -eq 1
check "no awake fix ran (the hold was live)" grep -qx 'runs 0' <<< "$OUT"
check "heartbeat lists e2e-nw" python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1]))["queue"] == ["e2e-nw"] else 1)' "$TC_STATE/watch/heartbeat"
[[ -s "$E/drive.err" ]] && { print -r -- "--- driver stderr:"; cat "$E/drive.err" }

# read-only, real state (skipped where there is no ~/.claude/tasks, e.g. CI): queue_mode over every real task list agrees with an independent count of open Plan & run tasks with queue metadata
check "real task lists: queue_mode agrees with the raw files" python3 -B -c '
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1]); import overview, planview
root = Path(sys.argv[2]) / ".claude" / "tasks"
if not root.is_dir():   # a CI runner has no real task lists: say so, never a silent pass on mac
    print(f"skip: no {root}"); sys.exit(0)
n = on = bad = 0
for d in sorted(p for p in root.glob("*") if p.is_dir()):
    raw = []
    for f in d.glob("*.json"):
        try: raw.append(json.loads(f.read_text()))
        except (OSError, ValueError): pass
    raw = [t for t in raw if isinstance(t, dict)]
    want = any(str(t.get("subject", "")).startswith("Plan & run:") and t.get("status") in ("pending", "in_progress")
               and isinstance(t.get("metadata"), dict) and "queue" in t["metadata"] for t in raw)
    got = overview.queue_mode({"active": True, "tasks": planview._finish([planview._norm(t) for t in raw])})
    n += 1; on += got; bad += got != want
print(f"checked {n} real task lists, {on} in queue mode, {bad} disagree")
sys.exit(0 if n > 0 and bad == 0 else 1)' "$R/board" "$REAL_HOME"
check "no leak into the real watch files" leak
tt_done
