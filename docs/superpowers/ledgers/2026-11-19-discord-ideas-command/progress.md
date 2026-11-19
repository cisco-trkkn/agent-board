# SDD ledger — plan: docs/superpowers/plans/2026-11-19-discord-ideas-command.md
Spec: docs/superpowers/specs/2026-11-17-discord-ideas-command-design.md. Base f428acb.
Preflight scan:
| pair / task | produces → consumes | found |
| T1↔T2 | T1 discord_feed post `buttons` [{label,style,custom_id}] → T2 opPost renders it | consistent |
| T2↔T3 | T2 slash event {command:ideas, project, bridge} → T3 handle_event → T1 request(project, bridge, …) | consistent |
| T1↔T3 | T1 public API (idea_id, open_ideas, request, post, expire, click, main) → T3 routing + CLI | consistent |
| T3↔T4 | T3 tmux-ctl discord ideas-list/ideas-post (stdin `-`) → T4 overseer rules + probe | consistent |
| T3↔T4 file | both may touch tools/tests/test_discord_ideas_cli.zsh | serial (T4 blocked by T3), no conflict |
| T1 | tests vs code: mutations named per guard | self-consistent |
| T2 | R2 no default project vs commands.js default | self-consistent (explicit) |
| T3 | ideas branch before _known | self-consistent |
| T4 | Write denied → stdin form; probe decides | self-consistent |
| T5 | user gate, after merge | n/a |
Ruling: spec's ephemeral "already done" on second tap replaced by buttons removed on edit (plan R1) — board answers async after deferUpdate — cost: one bridge round trip later.
Ruling: /ideas never defaults to the channel's project (plan R2) — user decision "covers every project" — cost: one-line change.
Ruling: discord_ideas has its own state.lock (plan R3) — ops-state flock held by consume would self-deadlock — cost: none known.
Ruling: T1 and T2 run in parallel — files disjoint, no blockedBy — cost: none.
Task 1: dispatched id-core (standard, sonnet), BASE f428acb
Task 2: dispatched id-bridge (standard, sonnet), BASE f428acb
Task 2: report green (132/0, rc 0); review dispatched id-rev2 (standard) on f428acb..cd7017a
Task 2: minor (deferred): bridge.js:186 missing label → "undefined"; custom_id not cut to 100
Task 2: minor (deferred): /ideas bogus with no views.json is acked and forwarded; board request() must reject (Task 1 covers)
Task 2: minor (deferred): unknown-project test lacks flags:64 check; no project-mode /ideas <given> test
Task 2: complete (commits f428acb..cd7017a, review clean)
Task 1: report green (118 OK, rc 0); review dispatched id-rev1 (standard) on cd7017a..242f474
Task 1: review: spec ✅, quality approved-with-fixes; 2 Important (post ordering, click ordering), 9 Minor
Task 1: minor (deferred): corrupt req ts raises (float) in expire/post; title newline/length unconstrained; PROJECT_RE copied; ANSWER_WINDOW comment; vacuous `or` assert :505; precedence trap :533; dead code :619/:546, file-path form untested; untested branches (closed req click, missing post file, expire write fail, non-dict group); `list <bad project>` rc 0 silent
Task 1: fix round 1/5 dispatched to id-core (Important 1+2, decided: validate-all-then-persist-then-write; edit pre-checked, done after action even if edit write fails)
Task 1: fix report green (128 OK, rc 0, commit 96aed0b); scoped re-review sent to id-rev1 on 242f474..96aed0b
Task 1: fix round 1/5 (2 addressed, 0 open — post ordering, click ordering; commits 242f474..96aed0b)
Task 1: minor (deferred): re-review 5 minors in task-1-rereview.md (top: `error: edit failed` replaces the real audit result queued/dropped n)
Task 1: complete (commits cd7017a..96aed0b, review clean)
Task 3: dispatched id-wire (standard, sonnet), BASE 96aed0b
Task 3: report green (100 OK + CLI ALL PASS rc 0; all.zsh ALL PASS 155 rc 4 budget); lead unstaged a force-added report; review dispatched id-rev3 on 96aed0b..a773c48
Task 3: minor (deferred, final review to triage — hot path): server.py:339-345 _overseer_sessions runs an extra capture_panes tmux call on every build_state poll
Task 3: minor (deferred): discord_controls click branch dense one-liner; obscure addCleanup drain in wiring test; hardcoded 'claude' window name (comment)
Task 3: complete (commits 96aed0b..a773c48, review clean)
Task 4: dispatched id-over (standard, sonnet), BASE a773c48
Task 4: report green (CLI ALL PASS rc 0; probe: heredoc denied → here-string; live 31/31; touched test_overseer_channel.zsh outside owned paths); review dispatched id-rev4 on a773c48..7ac12e5
Task 4: minor (deferred): allow patterns lack word boundary (ideas-list*); test_overseer_channel exclusion not end-anchored; CLI test pins deny list to git show a773c48 (fragile); grep -c ≥2 loose; overseer.md "no ' in titles" conservative
Task 4: complete (commits a773c48..7ac12e5, review clean)
Final review: dispatched id-final (fable) on 9246e05..7ac12e5
Final review: ready with fixes (0/2/13), suite ALL PASS 155 jobs rc=4 budget
Final fix wave: id-fix (standard), commits 7ac12e5..6bf800c (Important 1, Important 2, Minor 1, Minor 2); board 1614 OK rc0, all.zsh ALL PASS 155 rc=4 budget, FAIL 0
Final fix wave: re-review (id-rereview, standard) all 4 addressed, no new breakage; nit (deferred): whitespace-only title renders "** **"
