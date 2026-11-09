Agent-status files (claude/plugin/mods/agent-status.js). `old.json` is a copy of a real file from
`${TMPDIR%/}/tmux-ctl-$UID/agent-status/` written by the installed mod before the overview fields existed
(session id and pane replaced by fixture values): it has no `tool`, `turnStartedAt`, `waiting`, `failStreak`, `lastToolAt`.
The other files are derived from it with those five fields, in the shapes the mod writes (task 1 of spec 8);
a capture from a real run with the new mod replaces them in task 4.
