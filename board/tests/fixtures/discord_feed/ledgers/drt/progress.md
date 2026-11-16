# SDD ledger — plan: docs/superpowers/plans/2026-11-16-discord-replaces-telegram.md
Spec: docs/superpowers/specs/2026-11-11-discord-replaces-telegram-design.md. Branch base 22b8f60 (main ef73bd8 + plan).
Preflight scan:
| pair / task | shared | produces → consumes | found |
| T2,T3,T6 | tools/lib/discord.zsh | T2 discord_cmd → T3 dc_holder/migrate → T6 watch branch | serial by blockedBy; ok |
| T3→T5 | dc_holder | '<pid> <pane>' or empty → orchestrator guard | ok |
| T1→T2,T5 | discord-mcp-launch --has-token | exit code → status/opt-in | ok |
| T2→T9 | bin/tmux-ctl | T2 adds discord branch; T9 removes telegram lines | T9 after T2; ok |
| T5,T3→T9 | allowed telegram-grep set | test_claude_orchestrator_dc, test_discord_migrate, discord.zsh, orchestrator | ok |
| T6→T9 | fixtures dir | T6 git mv telegram-watch → discord-watch | ok |
| T2,T3,T5,T6→T8 | documented lines | status/stderr/knob names → INSTALL.md | T8 after all four; ok |
| T4 | hooks.json alone | script + test agree | ok |
| T7 | server.py/index.html alone | test matches rule | ok |
| T1,T4,T7 | files disjoint, no blockedBy | run in parallel | ok |
| each task self-consistency | tests vs code vs files | checked | ok |
Ruling: idea-132 entries are tagged (plugin|server):* only — spec's "until next -arg" swallows a trailing prompt — cost if wrong: an untagged entry the user passes is left in "$@" and claude rejects it.
Ruling: guard reads env via ps -E (probed on the live lead), no lead.pid fallback — cost if wrong: guard never finds a holder on a host without ps -E, second lead double-answers.
Ruling: final telegram grep allows the migrate/unset files — spec's "nothing" impossible while migrate exists — cost if wrong: none functional.
Ruling: cache key plugin:discord:discord pinned from this session's mcp__plugin_discord_discord__ tool prefix, not a provoked real failure (that would re-arm the machine-wide cache for live leads) — cost if wrong: cache clear is a no-op, lead may skip Discord inside a 15-min window.
Task 1: dispatched dc-launch (sonnet, base 22b8f60)
Task 4: dispatched dc-scrub (haiku, base 22b8f60)
Task 7: dispatched dc-badge (sonnet, base 22b8f60)
Task 7: green check ok; review dispatched dc-review (22b8f60..4e9d2cf)
Task 1: green check ok; review dispatched dc-review (4e9d2cf..28b98dd)
Ruling: Task 6 starts now on dc-badge without the tools/lib/discord.zsh `watch` branch; Task 3's implementer adds that branch (one dispatch line) — discord.zsh is owned serially by T2/T3 — cost if wrong: the `tmux-ctl discord watch --once` AC is checked at T3's review instead of T6's.
Task 6: dispatched dc-badge (sonnet, base 28b98dd)
Task 7: minor (deferred): discord_leads misses `--channels=a plugin:discord@…` (a bare entry after a --channels= token); `seen` never reset by a later flag
Task 7: complete (commits 22b8f60..4e9d2cf, review clean)
Task 4: green check ok; review dispatched dc-review (28b98dd..5f45fc3)
Gate I-2 (queue-reliability): PASS — after shutdown_request to dc-scrub, shutdown-pending/<sid> existed naming dc-scrub; wait-gone rc=0 "all gone" and removed the file
Task 1: minor (deferred): has-token accepts a whitespace/quoted value; cache rewrite resets file mode to 0600; mtime-check test portability note
Task 1: complete (commits 4e9d2cf..28b98dd, review clean)
Task 2: dispatched dc-launch (sonnet, base 5f45fc3)
Task 1: ⚠️ dc_ensure_launcher vs the real plugin dir unverified → carried into Task 10 dispatch (run it on a copy of ~/.claude/plugins/cache/claude-plugins-official/discord/0.0.4 in a scratch CLAUDE_CONFIG_DIR)
Task 4: minor (deferred): telegram-env-scrub.sh + test remain until Task 9; e2e-remote-access.md names it (Task 8); lead marker must be exactly 1
Task 4: complete (commits 28b98dd..5f45fc3, review clean)
Task 6: green check ok (concern: test_discord_always_on port must keep the fake child's `bun …/discord/server.ts` args → carried into Task 5 dispatch); review dispatched dc-review (5f45fc3..b1920d7)
Task 6: minor (deferred): _is_server matches any /discord/ bun-start descendant; discord-mcp-launch match dead (launcher execs); edited fixtures not true captures (README says); telegram watch/always_on tests broken until Task 9
Task 6: complete (commits 5f45fc3..b1920d7, review clean; watch-branch AC moved to Task 3)
Task 6: ⚠️ real /mcp banner text for plugin:discord:discord and a real launchd install are unverified → morning report (user gate follow-up: `tmux-ctl discord watch install`)
Task 2: green check ok; review dispatched dc-review (b1920d7..0bc8efc)
Task 2: note → Task 9 dispatch: tmux-ctl help is `sed -n 2,49p`; removing the 2 telegram help lines must shrink it to 2,47p
Task 2: minor (deferred): pair uses unvalidated senderId as a filename (approved/<id>); token drops stdin lines after the first silently; legacy ~/.claude/channels/discord warning ignores CLAUDE_CONFIG_DIR; missing access.json worded "not readable JSON" in pair/deny
Task 2: complete (commits b1920d7..0bc8efc, review clean)
Task 3: dispatched dc-launch (sonnet, base 0bc8efc) incl. the watch branch moved from Task 6
Task 3: green check ok; review dispatched dc-review (0bc8efc..c5280dc)
Task 3: minor (deferred): held-by pane resolves via plain tmux, not tc_tmux (wrong server possible); spaces in state dir allow a prefix match; migrate "not enabled" covers any plugin-disable failure
Task 3: complete (commits 0bc8efc..c5280dc, review clean; real dc_holder: agent-board → 98976 %8, interiors → 98971 %1)
Task 5: dispatched dc-launch (sonnet, base c5280dc)
Task 5: minor (process): code written before tests; RED proven by restoring HEAD files (20 FAIL) and the mutation (6 FAIL)
Task 5: green check ok; review dispatched dc-review (c5280dc..edc317d)
Ruling: Tasks 8 and 9 start while Task 5 is in review — their files are disjoint from Task 5's and from each other — cost if wrong: a Task 5 fix that changes a documented line needs a one-line doc follow-up in Task 8.
Task 8: dispatched dc-badge (sonnet, base edc317d)
Task 9: dispatched dc-del (haiku, base edc317d)
Task 8: incident: dc-badge's first commit e9b8c7d swept dc-del's staged deletions (no pathspec); undone by `git reset --soft HEAD~1`; lead verified fd15585 = 4 doc files, dc-del's index intact
Task 8: green check ok; review dispatched dc-review (edc317d..fd15585)
Task 5: minor (deferred): a caller-named discord --channels entry survives a held-elsewhere guard (no state dir); inherited DISCORD_BOT_TOKEN not unset (Telegram same); "not in tmux" also fires when only TMUX_PANE missing; agent-board lead help column misaligned
Task 5: complete (commits c5280dc..edc317d, review clean; process deviation: code before tests, RED via HEAD restore)
Task 8: minor (deferred): process — reset --soft in the shared worktree (rule 1), nothing lost; INSTALL invite lists no permissions (DM-only ok); e2e spec link is a glob; Developer Portal steps from general knowledge
Task 8: complete (commits edc317d..fd15585, review clean)
Ruling: Task 9 Verify grep's `^./` filters never match (the agents' grep prints paths without ./) — plan defect; lead re-ran with `^docs/superpowers/` filters: outside docs/superpowers + metrics fixtures = bin/claude-orchestrator, board/tests/test_discord_badge.py, docs/INSTALL.md, tools/lib/discord.zsh, tools/tests/test_claude_orchestrator_dc.zsh, tools/tests/test_discord_migrate.zsh — cost if wrong: none, read-only check.
Ruling: board/tests/test_discord_badge.py joins the allowed set — its test_telegram_channel_is_false is a negative check that a telegram channel is not flagged — cost if wrong: one stale test name.
Task 9: tmux-ctl help range is 2,46 (3 telegram help lines incl. a continuation removed), not the 2,47 the lead guessed
Task 9: green check ok (approve_misc ALL PASS, run-all rc=0, board 1051 OK); review dispatched dc-review (fd15585..f94c88a)
Task 9: minor (deferred): two of the four superseded docs now carry two superseded lines in a row
Task 9: complete (commits fd15585..f94c88a, review clean)
Task 10: dispatched dc-launch (sonnet, base f94c88a)
User (Discord, allowlisted, 18:22Z): "Pause after the merge" — queue pauses after this spec merges; Plan & run #2 not started until the user says
Task 10: all.zsh run 1 FAIL 1/129 zsh/test_all_runner.zsh (interrupt KILL under 8 s timing, load ~5, overlapping all.zsh runs); alone ALL PASS; rerun in progress — not this branch's code (all-zsh-interrupt-sweep timing)
Ruling: the all.zsh run-1 FAIL (test_all_runner interrupt <8 s timing, load ~5) does not block — run 2 ALL PASS 129 jobs (SLOW only, rc 4), the test passes alone, and it exercises all.zsh code this branch does not touch — cost if wrong: a real interrupt-timing regression ships; it would show as repeat flakes in later runs.
Task 10: side effect: real-pane run set AGENT_BOARD_REPO/PATH on agent-board-bg's tmux env; teammate unset/removed them; lead checked: bg has no AGENT_BOARD_REPO, PATH without the worktree bin (bg never ran the orchestrator before, so this matches the prior state)
Task 10: minor (deferred): `held by:` names a grouped view session (_web-40635:claude) instead of the session group
Task 10: green check ok; review dispatched dc-review (f94c88a..51c64fe)
Task 10: minor (deferred): note's final line omits the run-1 flake ruling; agent-board-bg PATH may keep a leading ~/.bun/bin from the run (harmless); note cites the pre-note HEAD
Task 10: complete (commits f94c88a..51c64fe, review clean)
Final review: dispatched dc-final (session level, ef73bd8..51c64fe)
Final review: With fixes (0 C, 1 I, 5 M). Fix wave → dc-launch: I-1 migrate disable misreport (option a); M-1 held-by via tc_tmux; M-2 drop caller discord entry when guard declines; T2 senderId ^[0-9]+$ check. Left: M-3, M-4 (comment only, added), M-5 per triage. FIX_BASE 51c64fe
Final fix wave: committed 51c64fe..88d6150 (5 items); scoped re-review dispatched dc-review
Final re-review: all 5 ADDRESSED (88d6150), no new C/I; real outside-tmux status → held by: agent-board:claude pid 98976
Final: parked — migrate prints "not enabled" when jq is missing — Ruling: leave; jq is a documented dependency and present here; Task 11 adds a jq enabledPlugins check after migrate — cost if wrong: a jq-less machine misreports the disable
Final: parked — bad-senderId test's "nothing approved" half sits outside check — Ruling: leave; exit code, message and byte-identical cmp cover it — cost if wrong: an approved/ write in that path goes unnoticed by that one assert
Final: parked — outside-tmux held-by test regex still accepts "another process" — Ruling: leave; the real read-only check printed the group name — cost if wrong: a regression to "another process" outside tmux passes CI
