#!/usr/bin/env bash
# Stop / PostToolUse (lead only): remind the lead once per teammate stop. A teammate's stop is the file
# <TC_STATE>/teammates/<lead sid>/<name>.json (teammate-stop.sh). It is due when its ts is newer than the last message
# from that teammate in the lead's transcript (a line holding <teammate-message teammate_id="<name>"; the automatic
# idle_notification does not count: it always follows the stop) and not yet reminded. Each (name, ts) reminded is
# recorded in <name>.reminded, so a stop is announced once. UserPromptSubmit does not fire for teammate messages and no
# hook input names the sender, hence the transcript (docs/superpowers/notes/2026-11-19-teammate-probes.md, Probe B).
#   Stop:         {"decision":"block","reason":"<lines>"} once (never when stop_hook_active).
#   PostToolUse:  hookSpecificOutput.additionalContext, at most once a minute per lead session (<dir>/.last-remind).
# Lead = AGENT_BOARD_LEAD=1 and no --agent-name in the Claude process args; teammate and worker are silent.
# Seam: TC_TEAMMATE_ARGS_FILE (args line instead of `ps -o args= -p $CLAUDE_PID`), TC_NOW (clock).
# Fail-open: any error exits 0 with nothing printed. --scoped is accepted and changes nothing.
input=$(cat) || exit 0
[ "$AGENT_BOARD_LEAD" = 1 ] || exit 0
if [ -n "$TC_TEAMMATE_ARGS_FILE" ]; then
  args=$(cat "$TC_TEAMMATE_ARGS_FILE" 2>/dev/null)
elif [ -n "$CLAUDE_PID" ]; then
  args=$(ps -o args= -p "$CLAUDE_PID" 2>/dev/null)
fi
case " $args " in *" --agent-name "*) exit 0 ;; esac
printf '%s' "$input" | python3 -I -c 'import datetime, json, os, re, sys, time
try:
    d = json.load(sys.stdin)
    sid, event = d.get("session_id"), d.get("hook_event_name")
    if event not in ("Stop", "PostToolUse") or not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    if event == "Stop" and d.get("stop_hook_active"):
        sys.exit(0)
    state = os.environ.get("TC_STATE") or os.path.join((os.environ.get("TMPDIR") or "/tmp").rstrip("/"), "tmux-ctl-%d" % os.getuid())
    ddir = os.path.join(state, "teammates", sid)
    if not os.path.isdir(ddir):
        sys.exit(0)
    now = int(os.environ.get("TC_NOW") or time.time())
    last_file = os.path.join(ddir, ".last-remind")
    if event == "PostToolUse":
        try:
            if now - int(open(last_file).read().strip()) < 60:
                sys.exit(0)
        except (OSError, ValueError):
            pass
    # last message per teammate from the transcript
    last = {}
    tp = d.get("transcript_path")
    if isinstance(tp, str) and os.path.isfile(tp):
        pat = re.compile(r"<teammate-message teammate_id=\\\\?\"([^\"\\\\]+)\\\\?\"")
        with open(tp, errors="replace") as f:
            for line in f:
                if "<teammate-message" not in line or "idle_notification" in line:
                    continue
                try:
                    ts = datetime.datetime.fromisoformat(json.loads(line)["timestamp"].replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
                for n in pat.findall(line):
                    last[n] = max(last.get(n, 0), ts)
    lines = []
    for fn in sorted(os.listdir(ddir)):
        if not fn.endswith(".json"):
            continue
        try:
            st = json.load(open(os.path.join(ddir, fn)))
            name, sts = st["name"], int(st["ts"])
        except Exception:
            continue
        rf = os.path.join(ddir, fn[:-5] + ".reminded")
        try:
            done = int(open(rf).read().strip())
        except (OSError, ValueError):
            done = 0
        if sts <= done or sts <= last.get(name, 0):
            continue
        hhmm = datetime.datetime.fromtimestamp(sts).strftime("%H:%M")
        first = " ".join(str(st.get("first_line") or "").split())
        lines.append("%s stopped at %s: %s — read its report file." % (name, hhmm, first))
        with open(rf, "w") as f:
            f.write(str(sts))
    if not lines:
        sys.exit(0)
    msg = "\n".join(lines)
    if event == "Stop":
        out = {"decision": "block", "reason": msg}
    else:
        out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}
        with open(last_file, "w") as f:
            f.write(str(now))
    print(json.dumps(out, ensure_ascii=False))
except SystemExit:
    raise
except BaseException:
    pass' 2>/dev/null
exit 0
