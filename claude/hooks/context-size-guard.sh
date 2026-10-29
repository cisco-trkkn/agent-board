#!/usr/bin/env bash
# UserPromptSubmit / Stop / PostToolUse hook: warn once the session's context passes a token threshold.
# The event is read from .hook_event_name (default UserPromptSubmit). UserPromptSubmit and PostToolUse emit
# systemMessage + hookSpecificOutput.additionalContext; Stop emits systemMessage only.
# Once per 50K band: band = tokens / 50000; the hook warns only when the band is above the one stored in
# ${CLAUDE_CONTEXT_GUARD_STATE:-$HOME/.local/state/agent-board/context-guard}/<session_id>.band.
# Stop warns (user-visible systemMessage) but never records the band: the model does not see it.
# Without a session_id (or with an unwritable state dir) it warns every time and stores nothing.
# A run below the threshold deletes the band file, so after /compact the next crossing warns again.
# Threshold override: export CLAUDE_CONTEXT_WARN_TOKENS=400000
THRESHOLD="${CLAUDE_CONTEXT_WARN_TOKENS:-300000}"

input=$(cat)
transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
sid=$(printf '%s' "$input" | jq -r '.session_id // empty')
event=$(printf '%s' "$input" | jq -r '.hook_event_name // "UserPromptSubmit"')
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# Context size = everything sent as input on the latest main-thread assistant turn.
tokens=$(tail -n 400 "$transcript" \
  | jq -c 'select(.type == "assistant" and (.isSidechain | not) and .message.usage != null)
           | .message.usage
           | (.input_tokens // 0) + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)' 2>/dev/null \
  | tail -n 1)

[ -n "$tokens" ] || exit 0
sdir="${CLAUDE_CONTEXT_GUARD_STATE:-$HOME/.local/state/agent-board/context-guard}"
if [ "$tokens" -lt "$THRESHOLD" ]; then
  # Below the threshold (e.g. after /compact): forget the band so the next crossing warns again.
  [ -n "$sid" ] && rm -f "$sdir/$sid.band" 2>/dev/null
  exit 0
fi

band=$((tokens / 50000))
if [ -n "$sid" ]; then
  last=$(cat "$sdir/$sid.band" 2>/dev/null || echo -1)
  [ "$band" -gt "$last" ] || exit 0
  # Stop's systemMessage never reaches the model, so Stop warns but leaves the band alone: only
  # UserPromptSubmit and PostToolUse record it. An unwritable state dir is silent: warn as if no session_id.
  if [ "$event" != "Stop" ]; then
    { mkdir -p "$sdir" && printf '%s\n' "$band" > "$sdir/$sid.band"; } 2>/dev/null
  fi
fi

k=$((tokens / 1000))
msg="🛑 CONTEXT AT ${k}K TOKENS (limit ${THRESHOLD}). Run /handoff: it checkpoints the team, writes a handoff doc and asks before switching this window to a fresh orchestrator. Or /compact to stay here."
ctx="IMPORTANT: This session's context is ${k}K tokens, past the user's ${THRESHOLD}-token budget. Begin your reply with one short, prominent line strongly recommending the user run /handoff (it checkpoints the team, writes the doc, and asks before relaying to a fresh orchestrator in this window). Suggest a one-line /handoff argument describing what the next session should focus on. Then answer their message normally."
if [ "$event" != "UserPromptSubmit" ]; then
  msg="$msg If you are a teammate, tell the lead in your next message."
  ctx="$ctx If you are a teammate, tell the lead in your next message."
fi

if [ "$event" = "Stop" ]; then
  jq -n --arg msg "$msg" '{systemMessage: $msg}'
else
  jq -n --arg msg "$msg" --arg ctx "$ctx" --arg ev "$event" \
    '{systemMessage: $msg, hookSpecificOutput: {hookEventName: $ev, additionalContext: $ctx}}'
fi
