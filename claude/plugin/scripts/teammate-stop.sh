#!/usr/bin/env bash
# Stop (teammate only): write <TC_STATE>/teammates/<lead session id>/<name>.json =
# {"ts", "name", "first_line", "text": last_assistant_message[:2000]}, atomically (temp in the same dir + rename).
# teammate-remind.sh reads it in the lead. Who is a teammate: the Claude process's args hold --agent-name <name> and
# --parent-session-id <lead sid> (docs/superpowers/notes/2026-11-19-teammate-probes.md, Probe A). The args also hold
# --lead-verify-key: only the two values are cut out, the line is never written or logged.
# Seam: TC_TEAMMATE_ARGS_FILE names a file holding the args line instead of `ps -o args= -p $CLAUDE_PID`; TC_NOW fixes the clock.
# Fail-open: any error exits 0 with nothing printed and nothing partial. --scoped is accepted and changes nothing.
input=$(cat) || exit 0
if [ -n "$TC_TEAMMATE_ARGS_FILE" ]; then
  args=$(cat "$TC_TEAMMATE_ARGS_FILE" 2>/dev/null)
elif [ -n "$CLAUDE_PID" ]; then
  args=$(ps -o args= -p "$CLAUDE_PID" 2>/dev/null)
fi
case " $args " in *" --agent-name "*) ;; *) exit 0 ;; esac
printf '%s' "$input" | ARGS="$args" python3 -I -c 'import json, os, re, sys, tempfile, time
try:
    toks = os.environ.get("ARGS", "").split()
    def after(flag):
        return toks[toks.index(flag) + 1] if flag in toks[:-1] else None
    name, lead = after("--agent-name"), after("--parent-session-id")
    if not name or not lead or not re.fullmatch(r"[A-Za-z0-9_.@-]+", name) or not re.fullmatch(r"[A-Za-z0-9_-]+", lead):
        sys.exit(0)
    d = json.load(sys.stdin)
    text = d.get("last_assistant_message")
    text = text[:2000] if isinstance(text, str) else ""
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")[:200]
    state = os.environ.get("TC_STATE") or os.path.join((os.environ.get("TMPDIR") or "/tmp").rstrip("/"), "tmux-ctl-%d" % os.getuid())
    ddir = os.path.join(state, "teammates", lead)
    os.makedirs(ddir, exist_ok=True)
    ts = int(os.environ.get("TC_NOW") or time.time())
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=ddir)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump({"ts": ts, "name": name, "first_line": first, "text": text}, f)
        os.replace(tmp, os.path.join(ddir, name + ".json"))
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
except BaseException:
    pass' >/dev/null 2>&1
exit 0
