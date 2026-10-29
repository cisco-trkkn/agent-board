#!/bin/sh
# SessionStart hook: the single task-observer mandate (decision memo session-start-tax.md, Option 1:
# the former "Task observer" section of ~/.claude/CLAUDE.md lives here now). Injects the activation
# rule, the teammate exemption, the pinned workspace and the review state as additionalContext; paths,
# scheduled jobs and the skill-creator rule live in <workspace>/README.md, which the text points to. Adapted from task-observer references/environments.md ("A session-start hook").
ws="${TASK_OBSERVER_WORKSPACE:-$HOME/.task-observer}"
d="$ws/skill-observations"
# A worker started by `tmux-ctl agent` carries TC_ROLE=worker (bin/tmux-ctl). Workers do not run the
# protocol, so the mandate is replaced by the exemption instead of sitting next to it.
if [ "${TC_ROLE:-}" = worker ]; then
  printf '%s\n' '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Worker session (TC_ROLE=worker): do not invoke task-observer or write to its log; put any skill findings in your final report."}}'
  exit 0
fi
if [ -d "$ws" ]; then wsok=ok; else wsok=MISSING; fi
open=$(find "$d/observation-log" -maxdepth 1 -name '*.md' -exec grep -l '^status: open$' {} + 2>/dev/null | wc -l | tr -d ' ')
last=$(cat "$d/last-review-date.txt" 2>/dev/null || echo never)
# Review due: never reviewed, or the last review is 7+ days old (GNU date, then BSD/macOS)
due=
cutoff=$(date -d '7 days ago' +%F 2>/dev/null || date -v-7d +%F)
case "$last" in
  (never) due=1 ;;
  (*) [ "$(printf '%s\n%s\n' "$last" "$cutoff" | sort | head -1)" = "$last" ] && due=1 ;;
esac
# The review job writes "completed DATE" on a normal finish; anything else (limit-hit, budget-hit, a start timestamp) means it fired without recording a review
fired=
if [ -f "$d/review-started.txt" ]; then
  rs=$(head -n 1 "$d/review-started.txt" | tr -d '\r')
  case "$rs" in (completed*|'') ;; (*) fired=" · fired $rs, no review recorded"; due=1 ;; esac
fi
# Staged updates: rounds PENDING.md lists as "awaiting install"; without PENDING.md, count the directories
K=0
u="$ws/skill-updates"
if [ -d "$u" ]; then
  for e in "$u"/*; do
    [ -e "$e" ] || continue
    n=${e##*/}
    case "$n" in (PENDING.md*) continue ;; esac
    if [ -f "$u/PENDING.md" ]; then
      grep -F -- "## $n " "$u/PENDING.md" | grep -q 'awaiting install' && K=$((K+1))
    elif [ -d "$e" ]; then
      K=$((K+1))
    fi
  done
fi
if [ "$wsok" = MISSING ]; then
  msg="Task observer: workspace MISSING. Run the full protocol: load the task-observer skill with no Skill arguments (storage check, frontmatter scan, review trigger). Observations are created only by scripts/new-observation.sh. Teammates and subagents never load it and report findings to the lead. Workspace (pinned, never the cwd or a worktree): $ws. Details: $ws/README.md."
else
  msg="Task observer: workspace ok · $open open · last review $last"
  [ -n "$due" ] && msg="$msg (due)"
  msg="$msg$fired · $K staged updates."
  [ -n "$due" ] && msg="$msg The review is due: offer it in one line and carry on with the user's task."
  msg="$msg Load the task-observer skill (no Skill arguments) only to write an observation, to run a review the user opted into, or to reconcile staged updates. Observations are created only by scripts/new-observation.sh. Re-read this summary before writing or proposing a plan. Teammates and subagents never load it and report findings to the lead. Workspace (pinned, never the cwd or a worktree): $ws. Details: $ws/README.md."
fi
# JSON string escaping: backslash and quote, tab as \t, other control characters dropped
tab=$(printf '\t')
msg=$(printf '%s' "$msg" | tr -d '\000-\010\013-\037\177' | sed -e 's/[\\"]/\\&/g' -e "s/$tab/\\\\t/g")
printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' "$msg"
