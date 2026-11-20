#!/usr/bin/env bash
# Stop / PostToolUse (lead only): remind the lead once per teammate stop. A teammate's stop is the file
# <TC_STATE>/teammates/<lead sid>/<name>.json (teammate-stop.sh). It is due when its ts is newer than the last message
# from that teammate in the lead's transcript (a line holding <teammate-message teammate_id="<name>"; the automatic
# idle_notification does not count: it always follows the stop) and not yet reminded. A message sent up to
# GRACE (30) seconds before the stop counts as "messaged since the stop": a teammate's report precedes its Stop by ~1 s
# (Probe B). A stop so handled is recorded in .reminded too, so it is not re-checked. Each (name, ts) reminded is
# recorded in <name>.reminded, so a stop is announced once. UserPromptSubmit does not fire for teammate messages and no
# hook input names the sender, hence the transcript (docs/superpowers/notes/2026-11-19-teammate-probes.md, Probe B).
#   Stop:         {"decision":"block","reason":"<lines>"} once (never when stop_hook_active).
#   PostToolUse:  hookSpecificOutput.additionalContext, at most once a minute per lead session (<dir>/.last-remind).
# Lead = AGENT_BOARD_LEAD=1 and no --agent-name in the Claude process args; teammate and worker are silent.
# Cheap exits first, in shell, before ps and python: not a lead; no <state>/teammates/<sid>/ dir; no status file that is
# not strictly older than its .reminded; PostToolUse within a minute of .last-remind. Only then is the transcript read;
# PostToolUse writes .last-remind on every check that gets that far, not only on emit.
# Seam: TC_TEAMMATE_ARGS_FILE (args line instead of `ps -o args= -p $CLAUDE_PID`), TC_NOW (clock).
# Fail-open: any error exits 0 with nothing printed. --scoped is accepted and changes nothing.
[ "$AGENT_BOARD_LEAD" = 1 ] || exit 0   # before the input is read: bash 3.2 reads a pipe a byte at a time, and this runs on every tool call
input=$(cat)
GRACE=30
[[ $input =~ \"session_id\"[[:space:]]*:[[:space:]]*\"([A-Za-z0-9_-]+)\" ]] || exit 0
sid=${BASH_REMATCH[1]}
state=${TC_STATE:-${TMPDIR:-/tmp}}
[ -n "$TC_STATE" ] || state="${state%/}/tmux-ctl-$UID"
ddir="$state/teammates/$sid"
[ -d "$ddir" ] || exit 0
due=
for f in "$ddir"/*.json; do
  [ -e "$f" ] || continue
  [ "${f%.json}.reminded" -nt "$f" ] || { due=1; break; }
done
[ -n "$due" ] || exit 0
if [[ $input =~ \"hook_event_name\"[[:space:]]*:[[:space:]]*\"PostToolUse\" ]] && [ -r "$ddir/.last-remind" ]; then
  now=${TC_NOW:-$(date +%s)}
  lr=$(cat "$ddir/.last-remind" 2>/dev/null)
  case "$lr" in ''|*[!0-9]*) ;; *) [ $((now - lr)) -lt 60 ] && exit 0 ;; esac
fi
if [ -n "$TC_TEAMMATE_ARGS_FILE" ]; then
  args=$(cat "$TC_TEAMMATE_ARGS_FILE" 2>/dev/null)
elif [ -n "$CLAUDE_PID" ]; then
  args=$(ps -o args= -p "$CLAUDE_PID" 2>/dev/null)
fi
case " $args " in *" --agent-name "*) exit 0 ;; esac
printf '%s' "$input" | GRACE=$GRACE python3 -I -c 'import datetime, json, os, re, sys, time
try:
    GRACE = int(os.environ["GRACE"])
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
        with open(last_file, "w") as f:
            f.write(str(now))
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
        if sts <= done:
            continue
        if last.get(name, 0) >= sts - GRACE:
            with open(rf, "w") as f:
                f.write(str(sts))
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
    print(json.dumps(out, ensure_ascii=False))
except SystemExit:
    raise
except BaseException:
    pass' 2>/dev/null
exit 0
