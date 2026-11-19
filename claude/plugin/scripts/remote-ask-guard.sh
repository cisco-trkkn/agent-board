#!/usr/bin/env bash
# PreToolUse(AskUserQuestion): deny the dialog where the user cannot answer it at a terminal
# (spec docs/superpowers/specs/2026-11-19-remote-discord-only-design.md §3; plan Task 8). Checked in this order:
#   1. payload agent_id, TC_ROLE=worker, or a teammate (the Claude process argv holds --agent-id, or the pane's @tc_teammate is 1)
#        -> deny, "ask the lead with SendMessage; the user is not at your window"
#   2. AGENT_BOARD_LEAD=1 with its own marker <state>/remote/<session id>
#        -> deny, "the user is remote: ask in Discord as a numbered list with the reply tool"
#   3. no role and any marker under <state>/remote/ with mtime within 43200 s (12 h)
#        -> deny, "the user is remote: write the question as plain text and end your turn; it reaches Discord as a Needs you item"
# Otherwise exit 0, no output. Deny = exit 2 with the text on stderr. Any error fails open.
#
# Transcript branch (lead decision; the active writer of the marker until remote-marker.sh is registered, lead ruling F13): for a lead the
# guard reads payload.transcript_path and takes the last non-sidechain, non-meta-without-origin "user" row that is not a tool result.
# origin {kind: channel, server: plugin:discord:discord} -> the lead is remote: write/touch the marker. origin.kind "human" (a prompt
# typed at the terminal; real rows: {"origin": {"kind": "human"}, "promptSource": "typed", "turnOrigin": "human"}) -> remove the marker.
# Every other user row leaves it: teammate messages are rows with no origin whose text starts "Another Claude session sent a message:\n
# <teammate-message" (17 of 17 in the real lead transcript 78659598), task notifications carry origin.kind "task-notification". Unreadable
# transcript: change nothing, the marker file decides. (Deviation from spec §3's letter, F14: teammate/task/cross-session prompts keep
# the marker.) Cost: the marker is only refreshed when a dialog is attempted.
# Kill switch: REMOTE_ASK_GUARD=0. --scoped (the plugin registration) is accepted and changes nothing.
# Test seam: REMOTE_GUARD_ARGS, when set (even empty), stands in for `ps -o args=` of the Claude process.
#
# Hook-process probe (2026-11-19): scratch `claude -p "run the bash command: echo hi" --settings <tmp>` whose PreToolUse(Bash) hook
# ran `env | cut -d= -f1`, `ps -o args= -p $PPID` and `cat` of its stdin. In the hook process: CLAUDE_PID, CLAUDECODE and TMUX are set;
# TMUX_PANE, AGENT_BOARD_LEAD and TC_ROLE are not (the probe unset CLAUDE_PID and TMUX_PANE in the parent, so CLAUDE_PID is set by claude
# itself; TMUX_PANE absent only because it was unset). $PPID args: `claude -p run the bash command: echo hi --settings …`.
# Payload keys: cwd, effort, hook_event_name, permission_mode, prompt_id, session_id, tool_input, tool_name, tool_use_id, transcript_path
# (no agent_id: a top-level session). A teammate cannot be reproduced in a scratch session: teammate detection rests on the payload's
# agent_id and the Claude argv `--agent-id` (seen with `ps` from a teammate's Bash tool: …/2.1.328 --agent-id c-t8@session-78659598 …) and @tc_teammate.
[[ "$REMOTE_ASK_GUARD" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
HOOK_PAYLOAD="$input" exec python3 -I - <<'PY'
import json, os, re, subprocess, sys, time
TM = "ask the lead with SendMessage; the user is not at your window"
LEAD = "the user is remote: ask in Discord as a numbered list with the reply tool"
PEER = "the user is remote: write the question as plain text and end your turn; it reaches Discord as a Needs you item"
env = os.environ

def deny(text):
    sys.stderr.write(text + "\n")
    sys.exit(2)

def is_teammate():
    if "REMOTE_GUARD_ARGS" in env:
        args = env["REMOTE_GUARD_ARGS"]
    else:
        try:
            pid = env.get("CLAUDE_PID") or str(os.getppid())
            args = subprocess.run(["ps", "-o", "args=", "-p", pid], capture_output=True, text=True, timeout=3).stdout
        except Exception:
            args = ""
    if "--agent-id" in args:
        return True
    pane, tmux = env.get("TMUX_PANE"), env.get("TMUX")
    if pane and tmux:
        tb = env.get("TC_TMUX") or os.path.join(env.get("HOME", ""), ".local/bin/tmux")
        if not os.access(tb, os.X_OK):
            tb = "tmux"
        try:
            r = subprocess.run([tb, "-S", tmux.split(",")[0], "display", "-p", "-t", pane, "#{@tc_teammate}"],
                               capture_output=True, text=True, timeout=3)
            return r.stdout.strip() == "1"
        except Exception:
            return False
    return False

def last_user_row(path):
    """The last non-sidechain user row that is not a tool result (and not a meta row without an origin), or None."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4 * 1024 * 1024))
        data = f.read().decode("utf-8", "replace")
    for line in reversed(data.splitlines()):
        try:
            r = json.loads(line)
        except Exception:
            continue
        if not isinstance(r, dict) or r.get("type") != "user" or r.get("isSidechain"):
            continue
        c = (r.get("message") or {}).get("content")
        if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        if r.get("isMeta") and not r.get("origin"):
            continue
        return r
    return None

try:
    d = json.loads(env["HOOK_PAYLOAD"])
    if d.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    sid = d.get("session_id")
    sid = sid if isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9_-]+", sid) else None
    state = env.get("TC_STATE") or "%s/tmux-ctl-%d" % ((env.get("TMPDIR") or "/tmp").rstrip("/") or "/tmp", os.getuid())
    rdir = os.path.join(state, "remote")
    marker = os.path.join(rdir, sid) if sid else None
    role = False
    if d.get("agent_id") or env.get("TC_ROLE") == "worker" or is_teammate():
        deny(TM)
    if env.get("AGENT_BOARD_LEAD") == "1":
        role = True
        tp = d.get("transcript_path")
        if marker and isinstance(tp, str) and tp:
            try:
                r = last_user_row(tp)
            except Exception:
                r = None
            if r is not None:
                o = r.get("origin") or {}
                if o.get("kind") == "channel" and o.get("server") == "plugin:discord:discord":
                    os.makedirs(rdir, exist_ok=True)
                    with open(marker, "a"):
                        pass
                    os.utime(marker, None)
                elif o.get("kind") == "human":   # positive evidence of a typed prompt; every other row leaves the marker
                    try:
                        os.remove(marker)
                    except FileNotFoundError:
                        pass
        if marker and os.path.exists(marker):
            deny(LEAD)
        sys.exit(0)
    now = time.time()
    try:
        for n in os.listdir(rdir):
            try:
                if now - os.path.getmtime(os.path.join(rdir, n)) <= 43200:
                    deny(PEER)
            except OSError:
                continue
    except OSError:
        pass
except SystemExit:
    raise
except Exception:
    sys.exit(0)
sys.exit(0)
PY
