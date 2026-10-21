#!/usr/bin/env bash
# UserPromptSubmit hook: warn loudly once the session's context passes a token threshold.
# Threshold override: export CLAUDE_CONTEXT_WARN_TOKENS=400000
THRESHOLD="${CLAUDE_CONTEXT_WARN_TOKENS:-300000}"

transcript=$(jq -r '.transcript_path // empty')
[ -n "$transcript" ] && [ -f "$transcript" ] || exit 0

# Context size = everything sent as input on the latest main-thread assistant turn.
tokens=$(tail -n 400 "$transcript" \
  | jq -c 'select(.type == "assistant" and (.isSidechain | not) and .message.usage != null)
           | .message.usage
           | (.input_tokens // 0) + (.cache_read_input_tokens // 0) + (.cache_creation_input_tokens // 0)' 2>/dev/null \
  | tail -n 1)

[ -n "$tokens" ] && [ "$tokens" -ge "$THRESHOLD" ] || exit 0

k=$((tokens / 1000))
msg="🛑 CONTEXT AT ${k}K TOKENS (limit ${THRESHOLD}). Run /handoff: it checkpoints the team, writes a handoff doc and asks before switching this window to a fresh orchestrator. Or /compact to stay here."

jq -n --arg msg "$msg" --arg ctx "IMPORTANT: This session's context is ${k}K tokens, past the user's ${THRESHOLD}-token budget. Begin your reply with one short, prominent line strongly recommending the user run /handoff (it checkpoints the team, writes the doc, and asks before relaying to a fresh orchestrator in this window). Suggest a one-line /handoff argument describing what the next session should focus on. Then answer their message normally." \
  '{systemMessage: $msg, hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $ctx}}'
