#!/usr/bin/env bash
# UserPromptSubmit: keep <state>/remote/<session id> in step with where the last user prompt came from
# (spec docs/superpowers/specs/2026-11-19-remote-discord-only-design.md §3; plan Task 8).
#   - a prompt holding <channel source="plugin:discord:discord" ... user_id="N"> with N in the allowFrom of any
#     <agent_base>/discord/*/access.json creates or touches the marker;
#   - a prompt with no "<channel " tag that does not start with <teammate-message, <task-notification or
#     <cross-session-message removes it (a prompt typed at the terminal); any other prompt changes nothing.
# Any error: exit 0, no output. --scoped (the plugin registration) is accepted and changes nothing.
#
# NOT REGISTERED in claude/plugin/hooks/hooks.json yet (lead ruling F13): whether UserPromptSubmit fires for a Discord channel
# message (transcript row: isMeta true, promptSource "system", origin.kind "channel") was not probed. remote-ask-guard.sh holds the
# transcript branch that writes and clears the same marker. Register this script after the post-merge probe (plan Task 11 item 1),
# if the hook fires with the channel tag.
#
# Hook-environment probe (this task, run inside a teammate, 2026-11-19):
#   $ ps -o args= -p $PPID | cut -c1-90
#   …/versions/2.1.328 --agent-id c-t8@session-78659598 --agent-name c-t8 --team-name session-78659598 …
#   $ env | cut -d= -f1 | grep -E 'CLAUDE_PID|TMUX_PANE|AGENT_BOARD_LEAD|TC_ROLE'      -> CLAUDE_PID, TMUX_PANE (no AGENT_BOARD_LEAD, no TC_ROLE)
#   $ tmux display -p -t "$TMUX_PANE" '#{@tc_teammate}|#{@tc_agent}'                    -> 1|
# Whether UserPromptSubmit fired for a <teammate-message prompt: not probed (F14: such prompts keep the marker either way).
input=$(cat) || exit 0
HOOK_PAYLOAD="$input" exec python3 -I - <<'PY' 2>/dev/null
import glob, json, os, re, sys
try:
    d = json.loads(os.environ["HOOK_PAYLOAD"])
    prompt, sid = d["prompt"], d["session_id"]
    if not (isinstance(prompt, str) and isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9_-]+", sid)):
        sys.exit(0)
    env = os.environ
    state = env.get("TC_STATE") or "%s/tmux-ctl-%d" % ((env.get("TMPDIR") or "/tmp").rstrip("/") or "/tmp", os.getuid())
    base = env.get("TC_STATE") or "%s/.local/state/agent-board" % env.get("HOME", "")
    marker = os.path.join(state, "remote", sid)
    if '<channel source="plugin:discord:discord"' in prompt:
        m = re.search(r'<channel source="plugin:discord:discord"[^>]*?\buser_id="([^"]+)"', prompt)
        if not m:
            sys.exit(0)
        uid = m.group(1)
        ok = False
        for f in glob.glob(os.path.join(base, "discord", "*", "access.json")):
            try:
                if uid in [str(x) for x in (json.load(open(f)).get("allowFrom") or [])]:
                    ok = True
                    break
            except Exception:
                continue
        if ok:
            os.makedirs(os.path.dirname(marker), exist_ok=True)
            with open(marker, "a"):
                pass
            os.utime(marker, None)
    elif "<channel " not in prompt and not prompt.lstrip().startswith(("<teammate-message", "<task-notification", "<cross-session-message")):
        try:
            os.remove(marker)
        except FileNotFoundError:
            pass
except SystemExit:
    raise
except Exception:
    pass
sys.exit(0)
PY
