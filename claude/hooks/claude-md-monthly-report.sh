#!/bin/bash
# Monthly CLAUDE.md audit (launchd: 1st of the month, 09:30). Report-only:
# runs the claude-md-improver skill through its quality report and stops —
# read-only tools, no edits. Report lands in ~/.claude/claude-md-reports/.
set -u
export NODE_EXTRA_CA_CERTS="$HOME/.certs/netskope-bundle.pem"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export CLAUDE_MD_REVISE_HOOK=0   # headless: nobody to approve CLAUDE.md diffs
repo="$HOME/master-gcp-repo"
out_dir="$HOME/.claude/claude-md-reports"
mkdir -p "$out_dir"
report="$out_dir/$(date +%F).md"

cd "$repo" || { echo "$(date '+%F %H:%M') skipped — $repo missing" >> "$out_dir/runs.log"; exit 0; }
git fetch --quiet origin dev3 2>/dev/null
claude -p "Scheduled monthly audit, report only. Invoke the claude-md-management:claude-md-improver skill and run Phases 1-3 (discovery, quality assessment, quality report) for this repository's CLAUDE.md files and ~/.claude/CLAUDE.md. Compare against the code on origin/dev3, not just the working tree. Do NOT run Phases 4-5 and do not edit any file: list the recommended changes as proposed diffs in the report instead." \
  --add-dir "$HOME/.claude" \
  --allowedTools "Read Glob Grep Skill Bash(find:*) Bash(ls:*) Bash(cat:*) Bash(grep:*) Bash(wc:*) Bash(git log:*) Bash(git show:*) Bash(git diff:*) Bash(git ls-files:*)" \
  --disallowedTools "Write Edit NotebookEdit" \
  > "$report" 2>&1
echo "$(date '+%F %H:%M') report $report (exit $?)" >> "$out_dir/runs.log"
