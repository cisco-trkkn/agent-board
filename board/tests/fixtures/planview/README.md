# planview fixtures

Captured from the real system, then scrubbed (keys all kept):

- `sessions/1001.json`: one real `~/.claude/sessions/*.json`. sessionId -> `11111111-...`, cwd/name -> `proj`, tmux -> `proj:@80.%82`, pid -> 1001.
- `sessions/1002.json`: the decoy, a copy for another pane (`proj:@81.%83`, sessionId `22222222-...`, newer `updatedAt`).
- `tasks/session-11111111/{1,2,3}.json`: three real task files from `~/.claude/tasks/session-201273be/` (owners `parse`, `parse`, `sift`). subject/description/activeForm -> `x`. Statuses set to completed/in_progress/pending.
- `tasks/session-22222222/1.json`: decoy task of the other session.
- `artifacts-proj.jsonl`: the first two `kind: plan` lines of `$TMPDIR/tmux-ctl-$UID/artifacts-agent-board.jsonl`. path -> `/proj/docs/superpowers/plans/2026-01-01-demo.md`, session_id -> `1111...` (older line) and `2222...` (newer line), hash zeroed.
- `repo/docs/superpowers/plans/2026-01-01-demo.md.tasks.json`: the first three tasks of the real `2026-10-16-board-fix-batch.md.tasks.json`, subject/description scrubbed.
