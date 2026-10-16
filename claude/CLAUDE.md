# Task observer

Before the first tool call of any session — and before writing or
proposing a plan, not merely before executing one — invoke the
task-observer skill AND execute its Session Start Protocol (storage
check, frontmatter scan, review trigger). Loading the skill and running
the protocol are separate steps; a session that loads the file and stops
has activated nothing. Any turn that will involve a tool call counts; do
not classify the session as "too simple" from its opening message.
Exception: a teammate or subagent dispatched by a lead session (Agent tool,
tmux-ctl worker) does not run the protocol, offer a review or write to the log;
it puts skill findings in its final report for the lead to log.

- Workspace root (pinned): `/Users/francisco.ruiz/.task-observer` — the log is
  `/Users/francisco.ruiz/.task-observer/skill-observations/`, staged skill updates go to
  `/Users/francisco.ruiz/.task-observer/skill-updates/`. Never anchor the log on the cwd:
  sessions often run in throwaway git worktrees under `.claude/worktrees/`.
- Scheduled jobs (launchd, `~/Library/LaunchAgents/`): task-observer review Mon/Wed/Fri
  09:00 (`com.user.task-observer-review`, log `skill-observations/scheduled-review.log`);
  CLAUDE.md audit report on the 1st at 09:30 (`com.user.claude-md-monthly-report`,
  reports in `~/.claude/claude-md-reports/`). If `last-review-date.txt` is still 7+ days
  old, the review job isn't running — offer the review in-session.
- When an observation or review calls for creating a new skill or restructuring
  an existing one, use the `skill-creator` skill to build it, and check the result
  against `skill-observations/cross-cutting-principles.md`.

# Plan and review companions

- Whenever `superpowers-extended-cc:writing-plans` runs, also load `writing-plans-extras`
  (step granularity by modelTier, audit tasks, autonomous handoff, real-state e2e).
- Whenever `superpowers-extended-cc:requesting-code-review` runs, also load
  `requesting-code-review-extras` (fixture origin, artefact-under-test, user-experienced checks).
- Whenever `superpowers-extended-cc:test-driven-development` runs, also load
  `test-driven-development-extras` (isolation seam before the RED run of side-effecting code, leak check after).

# Local tooling gotchas

- Scratch tmux servers must start with `-f /dev/null`
  (`~/.local/bin/tmux -L <sock> -f /dev/null …`). `~/.tmux.conf` runs
  resurrect + continuum restore with `claude --continue`, so a plain scratch
  server relaunches resumed Claude sessions. The test harness `lib.zsh`
  already does this.
- zsh scripts: never name a variable `path` (it is tied to `$PATH`), and brace
  variables before a colon (`"=${sess}:tests"`, not `"=$sess:tests"`, where
  `:t` is a modifier). Quote tmux `=name` targets (`-t "=name"`): an unquoted
  leading `=` is zsh's command-path expansion and fails with "name not found".
- tmux session-scoped options need the trailing colon: `show-options -t '=name:'`.
- The `~/.local/bin`, `~/.local/share/tmux-*` and `~/.claude` tool files are not
  under git: back them up (`F.bak-YYYYMMDD`) and stage live ones as `F.next`
  before swapping. Some now are symlinks into `~/agent-board`: `ls -l F` before
  installing, and if it is a link, apply the change to `realpath F` — never `mv`
  `F.next` over the link.
- Staged patches are generated (`diff -u live-copy edited-copy`), never typed, and
  must pass `patch --dry-run` against the live file before staging. If the live file
  can't be read, stage a full edited copy instead of a diff.
