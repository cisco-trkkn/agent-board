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
Invoke task-observer with no Skill arguments: arguments rewrite `$1`…`$9` in
its inline shell and awk snippets (an `$2` became a word of the argument string).

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
  (step granularity by modelTier, audit tasks, autonomous handoff, real-state e2e,
  copy-X differences, event-consumer delivery semantics, Verify = verifyCommand).
- Whenever `superpowers-extended-cc:requesting-code-review` runs, also load
  `requesting-code-review-extras` (fixture origin, artefact-under-test, user-experienced checks,
  uncapped evidence for all/none claims).
- Whenever `superpowers-extended-cc:test-driven-development` runs, also load
  `test-driven-development-extras` (isolation seam before the RED run of side-effecting code, leak check after,
  one real run of a deciding external command).

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
- Agent Bash calls run zsh, not bash. A word starting with `=` is the same
  expansion: `echo ===` fails with "== not found" and aborts a `&&` chain, so
  quote it (`echo '==='`). An unquoted `$VAR` is not word-split: `grep $FLAGS`
  with `FLAGS='-rn -E'` passes one argument; use `${=FLAGS}` or an array.
- tmux session-scoped options need the trailing colon: `show-options -t '=name:'`.
- The `~/.local/bin`, `~/.local/share/tmux-*` and `~/.claude` tool files are not
  under git: back them up (`F.bak-YYYYMMDD`) and stage live ones as `F.next`
  before swapping. A file inside a skill directory (`~/.claude/skills/<s>/…`) is
  backed up to `~/.claude/skill-backups/<s>/F.bak-YYYYMMDD`, never beside it:
  a backup inside the skill is copied, packed and diffed with it. Some now are symlinks into `~/agent-board`: `ls -l F` before
  installing, and if it is a link, apply the change to `realpath F` — never `mv`
  `F.next` over the link.
- Staged patches are generated (`diff -u live-copy edited-copy`), never typed, and
  must pass `patch --dry-run` against the live file before staging. If the live file
  can't be read, stage a full edited copy instead of a diff.
