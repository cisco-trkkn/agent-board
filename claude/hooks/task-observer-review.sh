#!/bin/bash
# Scheduled task-observer comprehensive review (launchd: Mon/Wed/Fri 09:00).
# Runs headless Claude against the pinned workspace; stages skill updates in
# ~/.task-observer/skill-updates — never edits live skills.
set -u

export TASK_OBSERVER_WORKSPACE="$HOME/.task-observer"
export CLAUDE_MD_REVISE_HOOK=0   # headless: nobody to approve CLAUDE.md diffs
export NODE_EXTRA_CA_CERTS="$HOME/.certs/netskope-bundle.pem"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
obs="$TASK_OBSERVER_WORKSPACE/skill-observations"
log="$obs/scheduled-review.log"

if [ ! -d "$obs/observation-log" ]; then
  echo "$(date '+%F %H:%M') review skipped — workspace missing: $obs" >> "$log"; exit 0
fi

# Open = every observation file minus those whose frontmatter status is
# actioned/declined/superseded/parked. A file with no status counts as open.
open=0
for f in "$obs/observation-log"/[0-9]*.md; do
  [ -e "$f" ] || continue
  st=$(awk 'NR==1 && /^---/ {fm=1; next} fm && /^---/ {exit} fm && /^status:/ {print $2; exit}' "$f")
  case "$st" in actioned|declined|superseded|parked) ;; *) open=$((open+1));; esac
done
if [ "$open" -eq 0 ]; then
  echo "$(date '+%F %H:%M') review skipped — 0 open observations" >> "$log"; exit 0
fi

# Read-only mirror of the live files the review compares against. The headless
# claude -p cannot read ~/.claude or ~/agent-board (outside its allowed dirs), so
# this wrapper, running as the user, copies them under skill-updates (covered by
# --add-dir). The mirror sits in a dot-dir so staged-work listings skip it.
mirror="${LIVE_MIRROR:-$TASK_OBSERVER_WORKSPACE/skill-updates/.live-mirror}"
src_skills="${SRC_SKILLS:-$HOME/.claude/skills}"
src_claude_md="${SRC_CLAUDE_MD:-$HOME/.claude/CLAUDE.md}"
src_board="${SRC_BOARD:-$HOME/agent-board}"
refresh_mirror() {
  local rc=0 r
  [ -e "$mirror" ] && chmod -R u+w "$mirror"
  mkdir -p "$mirror/skills" "$mirror/agent-board/bin" "$mirror/agent-board/claude" || return 1
  # rsync exit 23/24 (partial transfer, e.g. a dangling symlink; vanished file) is a
  # warning: log it and carry on. Any other failure is remembered but does not skip
  # the remaining copies, the manifest, or the final chmod.
  sync_dir() {
    rsync -aL --delete "$1/" "$2/"; r=$?
    case "$r" in
      0) ;;
      23|24) echo "WARN: rsync exit $r for $1 (partial transfer, continuing)" ;;
      *) echo "ERROR: rsync exit $r for $1"; rc=1 ;;
    esac
  }
  sync_dir "$src_skills" "$mirror/skills"
  cp -p "$src_claude_md" "$mirror/CLAUDE.md" || { echo "ERROR: cp $src_claude_md failed"; rc=1; }
  sync_dir "$src_board/bin" "$mirror/agent-board/bin"
  sync_dir "$src_board/claude" "$mirror/agent-board/claude"
  {
    echo "live-path skills $src_skills"
    echo "live-path CLAUDE.md $src_claude_md"
    echo "live-path agent-board/bin $src_board/bin"
    echo "live-path agent-board/claude $src_board/claude"
  } > "$mirror/MANIFEST.paths" || rc=1
  ( cd "$mirror" && find skills CLAUDE.md agent-board -type f -print0 \
      | sort -z | xargs -0 shasum -a 256 ) > "$mirror/MANIFEST.sha256" || rc=1
  chmod -R a-w "$mirror"
  return "$rc"
}
refresh_mirror >> "$log" 2>&1 \
  || echo "$(date '+%F %H:%M') live-mirror refresh FAILED — review continues; mirror may be stale" >> "$log"

cd "$obs" || exit 1
echo "=== $(date '+%F %H:%M') scheduled review start ($open open) ===" >> "$log"
claude -p "Scheduled autonomous review. First probe the workspace folder (one ls of $obs), then write the date and time to $obs/review-started.txt, then invoke the task-observer skill with no arguments (Skill arguments rewrite \$1…\$9 in its inline snippets) and run its Comprehensive Review in scheduled mode. Workspace root: $TASK_OBSERVER_WORKSPACE. Offline policy: if the probe finds nothing, end with the one-line 'review skipped — workspace offline'; if the probe or a write fails with a permission or sandbox error on a path that exists, end with a one-line note naming the missing grant in the scheduled task definition (not 'offline'), with no retries. Live skills and target files are mirrored read-only at $mirror (MANIFEST.paths maps each root to its live path, MANIFEST.sha256 holds the hashes): compare, copy and hash from there; record the manifest hash in staged patches. Shell: Bash here allows only single commands matching the allowed prefixes; inline variables, loops, \$? and find -exec are refused, so write each multi-statement snippet to a file under $obs/reviews/<date>/ and run it with bash <file>." \
  --permission-mode acceptEdits \
  --add-dir "$TASK_OBSERVER_WORKSPACE/skill-updates" \
  --allowedTools "Read Glob Grep Write Edit Skill Bash(bash:*) Bash(find:*) Bash(ls:*) Bash(cat:*) Bash(grep:*) Bash(head:*) Bash(wc:*) Bash(date:*) Bash(mkdir:*) Bash(cp:*) Bash(python3:*) Bash(cmp:*) Bash(diff:*) Bash(shasum:*)" \
  < /dev/null >> "$log" 2>&1
rc=$?
echo "=== $(date '+%F %H:%M') scheduled review end (exit $rc) ===" >> "$log"
