#!/bin/sh
# SessionStart hook: inject task-observer activation + review state as additionalContext.
# Adapted from task-observer references/environments.md ("A session-start hook").
d="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}/skill-observations"
open=$(find "$d/observation-log" -maxdepth 1 -name '*.md' -exec grep -l '^status: open$' {} + 2>/dev/null | wc -l | tr -d ' ')
last=$(cat "$d/last-review-date.txt" 2>/dev/null || echo never)
msg="Invoke the task-observer skill before the first tool call and run its Session Start Protocol. Workspace root (pinned, never the cwd or a worktree): ${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}. Observation files are created only by scripts/new-observation.sh in the skill directory, never by copying a header."
if [ "$open" -gt 0 ]; then
  msg="$msg $open open observations; last review: $last."
  cutoff=$(date -d '7 days ago' +%F 2>/dev/null || date -v-7d +%F)   # GNU, then BSD/macOS
  case "$last" in
    (never) msg="$msg Offer the review." ;;
    (*) [ "$(printf '%s\n%s\n' "$last" "$cutoff" | sort | head -1)" = "$last" ] && msg="$msg Offer the review." ;;
  esac
fi
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg"
