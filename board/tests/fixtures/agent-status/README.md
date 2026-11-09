Agent-status files (claude/plugin/mods/agent-status.js). `old.json` is a copy of a real file from
`${TMPDIR%/}/tmux-ctl-$UID/agent-status/` written by the installed mod before the overview fields existed
(session id and pane replaced by fixture values): it has no `tool`, `turnStartedAt`, `waiting`, `failStreak`, `lastToolAt`.
`busy-tool.json`, `waiting-question.json` and `waiting-permission.json` are derived by hand from it with those five fields, in the
shapes the mod writes (task 1 of spec 8); they stay. `real-new-fields.json` is a real capture: the file the new mod wrote
during a `sleep 20; echo done` Bash call in the task 4 run (tools/tests/e2e-mod-overview.md), session id and pane replaced.
