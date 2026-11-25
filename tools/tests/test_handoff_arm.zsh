source "${0:A:h}/lib.zsh"
# handoff-arm.sh (PostToolUse Write|Edit|MultiEdit): a lead that writes a handoff doc arms the Stop guard's mark
# <state>/handoff-pending/<session id>; `tmux-ctl handoff-mark --clear` (or the relay) disarms it.
# Spec docs/superpowers/specs/2026-11-24-run-watch-design.md §a. Seams: TC_HANDOFFS_DIR (the handoffs dir), HOME (the
# default and the older dir), TC_TEAMMATE_ARGS_FILE (the Claude process args). TC_STATE is the test's temp dir.
A="${TC_HANDOFF_ARM:-$TT_REPO/claude/plugin/scripts/handoff-arm.sh}"
G="$TT_REPO/claude/plugin/scripts/lead-stop-guard.sh"
C="$TT_REPO/bin/tmux-ctl"
SID=ha000000-1111-4222-8333-444444444444
REAL=("${${TMPDIR:-/tmp}%/}/tmux-ctl-$UID/handoff-pending" "$HOME/.local/state/agent-board/handoff-pending")
# leak check: no real handoff-pending dir holds this test's session id; prints how many real marks it read
leak() { local f n=0 hit=0; for f in "${^REAL[@]}"/*(N); do (( n++ )); [[ ${f:t} == $SID ]] && (( hit++ )); done
  print -r -- "leak check: read $n real marks, $hit named $SID"; (( hit == 0 )) }
check "no real mark for the test session before the run" leak
tt_setup claude
tmp="$TT_DIR/ha"; mkdir -p "$tmp"
HD="$TT_DIR/handoffs"; mkdir -p "$HD" "$HD-old" "$TT_DIR/other"
export TC_HANDOFFS_DIR="$HD" AGENT_BOARD_LEAD=1
MF="$TC_STATE/handoff-pending/$SID"
print -r -- "/x/claude --permission-mode default" > "$tmp/lead-args"
print -r -- "/x/claude --agent-id m@t --agent-name m --team-name t --parent-session-id $SID" > "$tmp/mate-args"
export TC_TEAMMATE_ARGS_FILE="$tmp/lead-args"
# hook <tool> <file_path> [session id]: one PostToolUse input, as Claude Code sends it
hook() { python3 -c 'import json,sys
print(json.dumps({"session_id": sys.argv[3], "transcript_path": "/x.jsonl", "cwd": "/x", "hook_event_name": "PostToolUse",
                  "tool_name": sys.argv[1], "tool_input": {"file_path": sys.argv[2], "content": "Project: /x"},
                  "tool_response": {"filePath": sys.argv[2], "success": True}}))' "$1" "$2" "${3-$SID}" 2>/dev/null |
  "$A" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$? }
quiet() { [[ $rc == 0 && ! -s "$tmp/o" && ! -s "$tmp/e" ]] }
armed() { quiet && [[ -f "$MF" ]] }
unarmed() { quiet && [[ ! -e "$MF" && ! -d "$TC_STATE/handoff-pending" ]] }
reset() { rm -rf "$TC_STATE/handoff-pending" "$TC_STATE/stop-guard" }

hook Write "$HD/2026-11-24-a.md"
check "lead Write of a handoffs .md: mark exists, prints nothing"  armed
reset; hook Edit "$HD/2026-11-24-a.md"
check "lead Edit: mark exists"                                   armed
reset; hook MultiEdit "$HD/2026-11-24-a.md"
check "lead MultiEdit: mark exists"                              armed
reset; ln -s "$HD" "$tmp/via-link"; hook Write "$tmp/via-link/b.md"
check "a path through a symlink into the dir: mark exists"       armed

reset; AGENT_BOARD_LEAD= hook Write "$HD/a.md"
check "not a lead: no mark"                                      unarmed
reset; TC_TEAMMATE_ARGS_FILE="$tmp/mate-args" hook Write "$HD/a.md"
# mutation: drop the --agent-name test -> a teammate (it inherits AGENT_BOARD_LEAD=1) arms, this fails
check "a teammate (AGENT_BOARD_LEAD inherited, --agent-name in its args): no mark"  unarmed
reset; hook Write "$TT_DIR/other/a.md"
check "a .md outside the handoffs dir: no mark"                  unarmed
reset; hook Write "$HD-old/a.md"
# mutation: compare with "${d:A}"* (no slash) -> the sibling dir arms, this fails
check "a sibling dir that only shares the prefix: no mark"       unarmed
reset; hook Write "$HD/a.txt"
check "a non-.md in the handoffs dir: no mark"                   unarmed
reset; hook Write "$HD/a.md" '../handoff-pending/x'
check "a session id that is not a plain id: no mark"             unarmed

# the default dir and the older one, from HOME
reset; mkdir -p "$tmp/home/.local/state/agent-board/handoffs" "$tmp/home/.claude/handoffs"
HOME="$tmp/home" TC_HANDOFFS_DIR= hook Write "$tmp/home/.local/state/agent-board/handoffs/a.md"
check "no TC_HANDOFFS_DIR: ~/.local/state/agent-board/handoffs arms"  armed
reset; HOME="$tmp/home" hook Write "$tmp/home/.claude/handoffs/a.md"
check "the older ~/.claude/handoffs arms"                        armed

# the Stop guard blocks on the armed mark; handoff-mark --clear lets the stop through
reset; hook Write "$HD/2026-11-24-a.md"
print -r -- '{"session_id":"'"$SID"'","hook_event_name":"Stop","stop_hook_active":false}' | "$G" --scoped >"$tmp/g" 2>&1
check "armed: the Stop guard blocks with the relay reason"       test "$(jq -r '.decision + " " + .reason' "$tmp/g")" = "block a self-started handoff has not relayed: run tmux-ctl relay <doc> --old-session $SID (handoff skill step 5)"
CLAUDE_CODE_SESSION_ID=$SID "$C" handoff-mark --clear >/dev/null 2>&1
print -r -- '{"session_id":"'"$SID"'","hook_event_name":"Stop","stop_hook_active":false}' | "$G" --scoped >"$tmp/g" 2>&1
check "after handoff-mark --clear: the Stop guard lets the stop through"  test ! -s "$tmp/g" -a ! -e "$MF"

# fail-open, and a non-lead never reads its input
reset; print -r -- 'not json' | "$A" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed stdin: silent exit 0, no mark"                  unarmed
# mutation: move the AGENT_BOARD_LEAD check below `input="$(cat)"` -> the endless stdin keeps it until the alarm (rc 142)
yes | env -u AGENT_BOARD_LEAD perl -e 'alarm 5; exec @ARGV' "$A" >"$tmp/o" 2>"$tmp/e"; rc=${pipestatus[2]}
check "endless stdin, not a lead: exit 0 without reading"        quiet
check "script is executable"                                     test -x "$A"
check "no real mark for the test session after the run" leak
tt_done
