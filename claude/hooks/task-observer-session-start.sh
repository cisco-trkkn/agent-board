#!/bin/sh
# SessionStart hook: the single task-observer mandate (decision memo session-start-tax.md, Option 1:
# the former "Task observer" section of ~/.claude/CLAUDE.md lives here now). Injects the activation
# rule, the teammate exemption, the pinned workspace, the scheduled-jobs note and the review state as
# additionalContext. Adapted from task-observer references/environments.md ("A session-start hook").
ws="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}"
d="$ws/skill-observations"
open=$(find "$d/observation-log" -maxdepth 1 -name '*.md' -exec grep -l '^status: open$' {} + 2>/dev/null | wc -l | tr -d ' ')
last=$(cat "$d/last-review-date.txt" 2>/dev/null || echo never)
msg='Task observer. Before the first tool call of this session, and again before writing or proposing a plan (not merely before executing one), invoke the task-observer skill AND execute its Session Start Protocol (storage check, frontmatter scan, review trigger). Loading the skill and running the protocol are separate steps: a session that loads the file and stops has activated nothing. Any turn that will involve a tool call counts; do not classify the session as too simple from its opening message. Invoke it with no Skill arguments: arguments rewrite $1…$9 in its inline shell and awk snippets. Exception: a teammate or subagent dispatched by a lead session (Agent tool, tmux-ctl worker) does not run the protocol, offer a review or write to the log; it puts skill findings in its final report for the lead to log.'
msg="$msg Workspace root (pinned, never the cwd or a worktree under .claude/worktrees/): $ws; the log is $d/, staged skill updates go to $ws/skill-updates/. Observation files are created only by scripts/new-observation.sh in the skill directory, never by copying a header. When an observation or review calls for creating a new skill or restructuring one, build it with the skill-creator skill and check the result against $d/cross-cutting-principles.md. Scheduled jobs (launchd, ~/Library/LaunchAgents/): task-observer review Mon/Wed/Fri 09:00 (com.user.task-observer-review, log $d/scheduled-review.log); CLAUDE.md audit report on the 1st at 09:30 (com.user.claude-md-monthly-report, reports in ~/.claude/claude-md-reports/). If last-review-date.txt is 7+ days old the review job is not running: offer the review in-session."
if [ "$open" -gt 0 ]; then
  msg="$msg $open open observations; last review: $last."
  cutoff=$(date -d '7 days ago' +%F 2>/dev/null || date -v-7d +%F)   # GNU, then BSD/macOS
  case "$last" in
    (never) msg="$msg Offer the review." ;;
    (*) [ "$(printf '%s\n%s\n' "$last" "$cutoff" | sort | head -1)" = "$last" ] && msg="$msg Offer the review." ;;
  esac
fi
# JSON string escaping for the two characters a path or note could carry
msg=$(printf '%s' "$msg" | sed 's/[\\"]/\\&/g')
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg"
