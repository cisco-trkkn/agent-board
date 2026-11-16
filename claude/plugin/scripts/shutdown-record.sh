#!/usr/bin/env bash
# PostToolUse(SendMessage): when the message is a shutdown_request (an object, or a JSON string that parses to one),
# add its recipient to <TC_STATE>/shutdown-pending/<session_id>, one name per line, each name once. lead-stop-guard.sh
# reads that file at Stop (docs/superpowers/specs/2026-11-10-queue-reliability-design.md §3). Nothing else.
# Fail-open: any error exits 0 with nothing printed. --scoped (the plugin registration) is accepted and changes nothing.
# Delivery: hooks of one assistant message can run at once and a hook can run twice, so the read-check-append runs
# under flock: no name is lost or repeated. Order does not matter (the file is a set).
input=$(cat) || exit 0
printf '%s' "$input" | python3 -I -c 'import fcntl, json, os, re, sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "SendMessage" or not isinstance(ti, dict):
        sys.exit(0)
    m = ti.get("message")
    if isinstance(m, str):
        m = json.loads(m)
    if not isinstance(m, dict) or m.get("type") != "shutdown_request":
        sys.exit(0)
    to, sid = ti.get("to"), d.get("session_id")
    if not isinstance(to, str) or not to.strip() or "\n" in to or "\r" in to:
        sys.exit(0)
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    state = os.environ.get("TC_STATE") or os.path.join((os.environ.get("TMPDIR") or "/tmp").rstrip("/"), "tmux-ctl-%d" % os.getuid())
    pdir = os.path.join(state, "shutdown-pending")
    os.makedirs(pdir, exist_ok=True)
    with open(os.path.join(pdir, sid), "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        if to not in f.read().split("\n"):
            f.write(to + "\n")
except BaseException:
    pass' >/dev/null 2>&1
exit 0
