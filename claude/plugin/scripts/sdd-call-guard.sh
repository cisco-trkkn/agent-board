#!/usr/bin/env bash
# PreToolUse(Agent): deny a dispatch while the superpowers handoff guard would be armed for this session, i.e. a writing-plans
# Skill call was followed by a TaskCreate and no subagent-driven-development / executing-plans Skill call came after it.
# That Skill call is what disarms superpowers' pre-askuser-handoff-guard; without it, regroup and finishing questions are
# refused ("EXECUTION HANDOFF VIOLATION"). See docs in .superpowers/briefs/handoff-guard-debug.guarddbg.md.
# Kill switch: SDD_CALL_GUARD=0. --scoped (the plugin registration) is accepted and changes nothing. Fail-open on any error.
#
# The arm/disarm scan below is a copy of PY_SCAN from
#   ~/.claude/plugins/cache/superpowers-extended-cc-marketplace/superpowers-extended-cc/6.5.3-dev/hooks/pre-askuser-handoff-guard
# (lines 82-232, superpowers-extended-cc 6.5.3-dev). Differences from the original, all of them:
#   1. The scan is run with python3 -I from this script instead of python3 -c from the original.
#   2. Its final print is "true|false" only (the original also prints arm_pos for its trace log).
# The logic (SIG pre-filter, arm, disarm, last_taskcreate rule) is unchanged. Keep it that way: tools/tests/test_sdd_call_guard.zsh
# checks parity against the installed upstream scan.
PY_SCAN='
import json, re, sys

path = sys.argv[1]

# Pre-filter: every signal this scan reacts to lives on a line containing one
# of these literals. Tool_use signals always carry the tool name
# ("Skill"/"TaskCreate"/"AskUserQuestion"); every user-message signal string
# starts with "superpowers-extended-cc:". One compiled-regex search per line
# is the cheapest formulation that needs no per-line Python overhead.
SIG = re.compile(b"Skill|TaskCreate|AskUserQuestion|superpowers-extended-cc:")

try:
    f = open(path, "rb")
except Exception:
    print("false\nerror")
    sys.exit(0)

arm_pos = None
disarm_pos = None
last_taskcreate_pos = None

def extract_text(content_val):
    """Return plain text from a content field that is either a string or a list of blocks."""
    if isinstance(content_val, str):
        return content_val
    if isinstance(content_val, list):
        parts = []
        for block in content_val:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return " ".join(parts)
    return ""

with f:
    for pos, line in enumerate(f):
        if not SIG.search(line):
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue

        etype = e.get("type", "")

        # --- assistant messages: scan tool_use entries ---
        if etype == "assistant":
            for c in (e.get("message") or {}).get("content") or []:
                if not isinstance(c, dict) or c.get("type") != "tool_use":
                    continue
                name = c.get("name", "")
                inp = c.get("input") or {}

                # writing-plans arm signals
                if name == "Skill":
                    skill_val = inp.get("skill", "") or ""
                    if (skill_val == "writing-plans"
                            or skill_val.endswith(":write-plan")
                            or "writing-plans" in skill_val):
                        arm_pos = pos

                # TaskCreate (compared against arm_pos at the end)
                if name == "TaskCreate":
                    last_taskcreate_pos = pos

                # Execution disarm signals — Skill tool_use
                if name == "Skill":
                    skill_val = inp.get("skill", "") or ""
                    if (skill_val in ("subagent-driven-development", "executing-plans", "execute-plan")
                            or skill_val.endswith(":subagent-driven-development")
                            or skill_val.endswith(":executing-plans")
                            or skill_val.endswith(":execute-plan")):
                        disarm_pos = pos

                # Compliant prior handoff: AskUserQuestion whose options include both required labels
                if name == "AskUserQuestion":
                    questions = inp.get("questions") or []
                    if questions:
                        q0 = questions[0] if isinstance(questions[0], dict) else {}
                        options = q0.get("options") or []
                        labels = [str(o.get("label", "")) if isinstance(o, dict) else str(o) for o in options]
                        has_subagent = any("Subagent-Driven" in lbl for lbl in labels)
                        has_parallel = any("Parallel Session" in lbl for lbl in labels)
                        if has_subagent and has_parallel:
                            disarm_pos = pos

        # --- user messages: check for slash-command skill invocations ---
        if etype == "user":
            msg = e.get("message") or {}
            # content may be string or list of blocks
            raw_content = msg.get("content", "")
            text = extract_text(raw_content)

            # A Skill invocation injects the skill BODY as a user message that starts
            # with "Base directory for this skill:". The body of writing-plans names
            # executing-plans and subagent-driven-development in its handoff section,
            # so scanning it disarmed the guard right after it armed (live: plan
            # session 2026-09-12, trace "not-armed | arm_pos=704" at the real
            # handoff). A skill body is a mention, not an invocation; every other
            # user message keeps the full-text scan so a human instruction that
            # names the skill late in a long message still counts.
            if text.lstrip().startswith("Base directory for this skill:"):
                continue

            # writing-plans arm via user message (slash command injection pattern)
            if "superpowers-extended-cc:writing-plans" in text or "superpowers-extended-cc:write-plan" in text:
                arm_pos = pos

            # execution disarm via user message
            if ("superpowers-extended-cc:subagent-driven-development" in text
                    or "superpowers-extended-cc:executing-plans" in text):
                disarm_pos = pos

# armed iff: arm_pos set AND (no disarm OR disarm before arm)
#            AND the most recent TaskCreate came after the most recent arm
armed = (
    arm_pos is not None
    and (disarm_pos is None or disarm_pos < arm_pos)
    and last_taskcreate_pos is not None
    and last_taskcreate_pos > arm_pos
)

print("true" if armed else "false")
'
[[ "$SDD_CALL_GUARD" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
tp=$(printf '%s' "$input" | python3 -I -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get("transcript_path") or "" if d.get("tool_name") == "Agent" else "")
except Exception:
    print("")' 2>/dev/null) || exit 0
[[ -n "$tp" && -f "$tp" ]] || exit 0
armed=$(python3 -I -c "$PY_SCAN" "$tp" 2>/dev/null | head -1) || exit 0
[[ "$armed" == true ]] || exit 0
printf '%s\n' "A plan was written and its tasks created, but subagent-driven-development was not invoked for it. Invoke the Skill tool with superpowers-extended-cc:subagent-driven-development now, even if it is already loaded. That call is what lets later questions (regroup, finishing) through the handoff guard. Then retry this dispatch. (Kill switch: SDD_CALL_GUARD=0.)" >&2
exit 2
