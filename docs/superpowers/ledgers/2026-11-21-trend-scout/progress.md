# SDD ledger — plan: docs/superpowers/plans/2026-11-21-trend-scout.md
Spec: docs/superpowers/specs/2026-11-13-trend-scout-design.md. Native tasks #105-#119 (plan Task N = #104+N). Branch spec-trend-scout, base 3b002b9, plan commit 6f76986.
Plan-time rulings (in the plan header): evidence count = len(evidence) for the 50% rule; #scout requests and ✅ via REST in the daily poll; Reject/Revise notes via bridge reply-arming; [Scout] approved line via add_line on the click path only; retry_copies driven by the controls tick; Monday retry = separate LaunchAgent with --retry; week's items = fetched_at after last_run_at.
Ruling: first poll of a source marks all items seen and keeps only the newest 3 (feeds) or none (html_links/html_diff) — probe found 446 changelog sections and category links on /news — cost if wrong: the first digest misses older items.
Ruling: plugin kind reports only version-numbered plugins via the remote marketplace.json; sha-versioned and @anthropic-plugin-directory plugins are skipped and counted — cost if wrong: updates to those plugins go unnoticed.
Ruling: api-pricing default = platform.claude.com API pricing docs, not claude.com/pricing (consumer plans) — cost if wrong: consumer plan changes unseen.

## Pre-flight scan
| pair / task | produces → consumes | found |
| T1→T8 | findings.Store/decide/value_line → scout_post | ok; Store(extra=) adds drafts keys beside default keys, harmless |
| T2→T3 | scout_fetch.py both write | sequential (T3 blockedBy T2) |
| T3→T4 | FetchError("no token"/"no channel"), {"request":…} entries → poll | ok |
| T4→T11 | items.jsonl → weekly items.json | ok |
| T5→T6/T11 | pack build() str → pick(queued_specs) | GAP: no function returns spec states |
| T6↔T9 | pick(revise_first) ← pending_revisions() | ok |
| T7→T9/T11 | draft(root, week, pick, note, prev) | ok; T11 dry-run passes a clone as root |
| T8→T9 | approve_fn(draft, add_line) vs approve(draft, root, now, add_line) | MISMATCH in signature |
| T8,T9 discord_controls.py | both modify | sequential |
| T9,T11,T12 bin/tmux-ctl | idea branch / scout branch / scout schedule | sequential |
| T10 | bridge.js alone | independent |
| T13 | orchestrator.md (protected path, edited by plan, not the scout) | ok |
| T14 | uses scout pack --root (T11), source test (T4 via T11 CLI) | ok |
| T15 | user gate, real model | ok |
| each task self-consistency | tests vs code vs files | ok; T7/T11 frontier, no Steps |
Ruling: T5 also exports spec_states(root) -> {path: "merged"|"superseded"|"queued"}, used by T11 for pick's queued_specs — plan gap — cost if wrong: none, an extra function.
Ruling: T8's default approve_fn is lambda d, al: scout_decisions.approve(d, root, time.time(), al) with root = dream.resolve_root("agent-board", {}, None) (tests pass approve_fn) — signature mismatch in plan — cost if wrong: none.
Ruling: parallel lanes — T1, T2, T5, T10 have disjoint files and no deps; run up to two implementers at once on disjoint files.
Task 1: dispatched to core (standard, sonnet), base 6f76986
Task 2: dispatched to fetch (standard, sonnet), base 6f76986, parallel with Task 1 (disjoint files)
Task 10: dispatched to bridge (standard, sonnet), base 6f76986, parallel (disjoint files)
Task 10: green check passed (npm test # fail 0), review package 6f76986..1a4dfb2
Task 10: review dispatched to rev (standard, sonnet)
Task 10: minor (deferred): scout-reply edit test never asserts the digest edit was applied (would pass on "no message")
Task 10: minor (deferred): scout arms share the 200-entry trim cap with dialog arms and never expire
Task 10: ⚠ cannot-verify (consumer reads reply keyed by custom id) — resolved: Task 8 AC routes ab:scout: reply events
Task 10: complete (commits 6f76986..1a4dfb2, review clean)
Ruling: T5 spec state "merged" = a `docs(metrics): <spec basename>` commit on main, OR a docs/superpowers/ledgers/ dir whose name contains the spec slug (basename minus date prefix and -design), OR a Status: line with merged/done/implemented; "superseded" = Status line with superseded; else "queued" — the plan's "git log shows a commit AND a metrics commit" misses specs merged before metrics existed — cost if wrong: a wrong overlap note.
Task 5: dispatched to pack (standard, sonnet), base 1a4dfb2, parallel with Tasks 1-2 (disjoint files)
Task 1: green check passed (Ran 101 OK rc=0), review package 1a4dfb2..4eaf0e4
Task 1: review dispatched to rev1 (standard, sonnet)
Task 1: minor (deferred): discover_post replaced _paths with _store (brief said _paths stays; unreferenced)
Task 1: minor (deferred): Store.save unrequested extra; dismiss-after-regrowth has no direct test
Task 1: complete (commits 1a4dfb2..4eaf0e4, review clean)
Ruling: Draft records also carry "evidence": [{url, quote}] and "what_it_enables" — Task 8's reject needs len(evidence) for the dismissed count and the ideas line needs what_it_enables; the constraints' Draft schema omitted them — cost if wrong: none.
Task 8: dispatched to core (standard, sonnet), base 9859763
Task 2: green check passed (Ran 39 OK rc=0), review dispatched to rev2 (standard, sonnet), package 4eaf0e4..9859763
Task 5: green check passed (Ran 8 OK rc=0), commit 397310b; pack shut down (team cap)
Task 5: review dispatched to rev5 (standard, sonnet), package 9859763..397310b
Task 2: review — spec PASS, 2 Important (HTTPError not closed; RSS dates keep offset as Z / raw string on parse failure)
Task 2: minor (deferred): gh token forwarded on redirects / http://api.github.com in clear
Task 2: minor (deferred): changelog header regex accepts any "## Word"; nav-only test not itself mutation-sensitive
Ruling: npm fetcher reads https://registry.npmjs.org/-/package/<pkg>/dist-tags (60 bytes) built from the source URL, not the 1.6 MB packument — reviewer cross-task ⚠; packument grows toward the 4 MB cap — cost if wrong: none, same latest value.
Task 5: review — spec ❌, 1 Important (hard cut drops ## Versions and ## Claude Code features in use on real state)
Task 5: minor (deferred): STATUS_RE misses **Status:** and ## Status forms; loose merged/done/implemented match; name-sorted "newest 60"; no truncation marker on context cut; unused now
Task 5: fix round 1 dispatched to pack2 (fresh, standard, sonnet; pack was shut down), FIX_BASE 397310b
Ruling: the "mods index" is claude/plugin/mods/index.js; the pack lists claude/plugin/mods/*.js (not tests/fixtures) — plan said claude/mods/, which does not exist — cost if wrong: one wrong pack line.
Task 2: fix round 1 green (Ran 42 OK rc=0), commit c3194fb, re-review sent to rev2
Task 2: fix round 1/5 (3 addressed, 0 open; commits 9859763..c3194fb)
Task 2: minor (deferred): npm items have published None — consumers must not assume a date
Task 2: complete (commits 4eaf0e4..c3194fb, review clean after round 1)
Task 3: dispatched to fetch (standard, sonnet), base c3194fb
Task 5: fix round 1 green (Ran 9 OK; real repo 30496 bytes, all six headings), commits 8a486d5..bd7f501, re-review dispatched to rr5 (standard, sonnet)
Task 8: DONE reported by core, commit aa6890b only (verify Ran 46 OK rc=0); not yet reviewed — green check passed; package aa6890b^..aa6890b
Task 8: note for Task 9: approve_fn runs after both locks are released (flock not re-entrant); scout_post.refresh(week) exists for expiry; health arg = sources.json dict
Handoff: lead context over budget at this point; team checkpointed; next lead respawns from the handoff doc
Task 5: fix round 1/5 (2 addressed, 0 open; commits 397310b..bd7f501)
Task 5: complete (commits 9859763..bd7f501, review clean after round 1)
Resume: new lead session fc262de2; tasks copied from session-9cc63974
Task 3: green check passed (17 OK), review dispatched to rev3 (standard, sonnet), package aa6890b..86b7fdc (= 86b7fdc^..86b7fdc)
Task 8: review dispatched to rev8 (standard, sonnet), package bd7f501..aa6890b (= aa6890b^..aa6890b)
Task 8: minor (deferred): a second publish for the same week resets decided drafts to pending and restores their buttons — carry to Task 11 (weekly publishes once per week, or guard)
Task 8: ⚠ cannot-verify (scout_decisions.approve(draft, root, now, add_line) signature) — carried to Task 9's dispatch as a must-match interface
Task 8: complete (commits bd7f501..aa6890b, review clean)
Task 3: minor (deferred): a failed marketplace fetch beside a successful one is not counted in new_state
Task 3: minor (deferred): #scout source-request regex lacks MULTILINE; a multi-line request is fetched as a page
Task 3: ⚠ cannot-verify (poll log line "plugins: <n> without a version") — carried to Task 4's dispatch
Task 3: complete (commits aa6890b..86b7fdc, review clean)
Task 4: dispatched to fetch (standard, sonnet), base 86b7fdc
Ruling: Task 4 may add "author_id": str(author["id"]) to scout_fetch's request dict and compare allowFrom (access.json user ids, as discord_controls._allow) against ids, not usernames — Task 3's request carries only the username — cost if wrong: none, one extra key.
Ruling: Task 4 makes scout_post.scout_dir() delegate to scout_sources.scout_dir() (one-line edit to Task 8's file) — Task 8 noted Task 4 replaces it; Global Constraints say every module gets it from scout_sources — cost if wrong: none.
Ruling: the poll writes `<ts> poll plugins: <n> without a version` from new_state["skipped_no_version"] when n > 0, and does not store that dict as plugin state — plan Task 3 text names the log line; Task 3 left it to Task 4 — cost if wrong: one log line.
Task 4: green check passed (Ran 21 OK), commit e89c30c, review dispatched to rev4 (standard, sonnet), package 86b7fdc..e89c30c
Ruling: on a first poll, plugin and discord_channel write all unseen items (no cap) — the Global Constraints cap only changelog_md/github_releases/rss/npm, and plugin updates and user-posted #scout links are wanted at once — cost if wrong: a noisy first week.
Ruling: `scout: <reason>` refusals go to stderr with exit 2 — constraints name no stream; Task 11 wraps main() — cost if wrong: a test reading stdout.
Task 4: review — spec PASS, 2 Important (requested source skips _check_url, http allowed; discord after-state stored before a failed reply post loses the request)
Task 4: ⚠ cannot-verify (fetchers return newest first) — resolved: scout_fetch.fetch docstring and _newest_first in each fetcher
Ruling: production request URLs must be https like source add; http is allowed only for hosts in a module constant `_HTTP_OK_HOSTS = ()` that tests patch to ("127.0.0.1",) — the tests need a local server — cost if wrong: none in production.
Task 4: minor (deferred): 14-day check DST offset; misleading import-cycle comment in scout_post.scout_dir; duplicate keys within one fetch both written
Task 4: fix round 1 dispatched to fetch (resume), FIX_BASE e89c30c
Task 4: fix round 1 green (25 OK), commit 5dfded0, re-review sent to rev4
Task 4: fix round 1/5 (2 addressed, 0 open; commits e89c30c..5dfded0)
Task 4: minor (deferred): post_message "" on a 2xx without id skips retry, request lost; a permanently failing reply POST pins the #scout cursor with no cap, may re-answer requests
Task 4: complete (commits 86b7fdc..5dfded0, review clean after round 1)
Task 6: dispatched to eval (standard, sonnet), base 5dfded0
Task 6: green check passed (23 OK), commit cba7a70, review dispatched to rev6 (standard, sonnet), package 5dfded0..cba7a70
Task 6: review — spec PASS, 1 Important (pick crashes on an entry without what_it_enables or with non-string overlaps; validate does not check them)
Task 6: minor (deferred): evidence count includes quote-less evidence entries
Task 6: fix round 1 dispatched to eval (resume), FIX_BASE cba7a70
Task 6: fix round 1 green (26 OK), commit d5952da, re-review sent to rev6
Task 6: fix round 1/5 (1 addressed, 0 open; commits cba7a70..d5952da)
Task 6: minor (deferred): validate's `e.get("item") not in by_key` raises TypeError on an unhashable item from the model — same crash class; final review should fold in a str guard
Task 6: complete (commits 5dfded0..d5952da, review clean after round 1)
Ruling: Task 7 Draft title = the spec file's first '# ' heading (minus a trailing ' — design'/' design'), slug = from the written path; why = the entry's what_it_enables; value/effort/risk/url/published/evidence/key copied from the pick — evaluate entries carry no title — cost if wrong: digest wording.
Ruling: Task 7 finds the written spec as the one new docs/superpowers/specs/<week>-*-design.md in the worktree (for a revision, the prev path or a new one); more than one new file → keep the first by name, remove the rest — cost if wrong: one lost extra spec.
Task 7: dispatched to drafter (frontier, fable), base d5952da
Task 7: green check passed (30 OK), commit 86f4451, review dispatched to rev7 (standard, sonnet), package d5952da..86f4451
Ruling: Draft path stays repo-relative; scout_post._copy_files must resolve it against the draft's worktree — carried to Task 11 (it may fix _copy_files to use worktree/path) — cost if wrong: a digest without files.
Ruling: --dry-run drafts in a throwaway clone of root (Task 11 passes the clone as root), since draft() always commits on scout/<week> — spec: dry-run makes no commit — cost if wrong: a dry run leaves a scout branch.
Task 7: review — spec PASS, 1 Important (_title strips "design" without a separator: "Hook redesign" → "Hook re")
Task 7: minor (deferred): a reused scout worktree is never refreshed from main; scout_draft imports scout_post only for draft_id
Task 7: fix round 1 dispatched to drafter (resume), FIX_BASE 86f4451
Task 7: minor (deferred): a revision prompt loses component and overlaps
Task 7: fix round 1 green (31 OK), commit 8672c98, re-review sent to rev7
Task 7: fix round 1/5 (1 addressed, 0 open; commits 86f4451..8672c98)
Task 7: complete (commits d5952da..8672c98, review clean after round 1)
Ruling: Task 9 redraft rebuilds the pick from the Draft record (key, what_it_enables, value, effort, risk, url, published, evidence; component = the finding key's part after the last ':') and calls scout_draft.draft(root, week, pick, note=draft.note, prev=draft.path) — Drafts store no full pick — cost if wrong: a revision prompt with less context.
Task 9: dispatched to core (standard, sonnet), base 8672c98
Ruling: Task 9 approve() idempotency keys on a Draft field `copied_at` (set after the main commit), not on status — Task 8's click stores status "approved" before calling approve_fn, so a status check would skip every first copy — cost if wrong: none, one extra field.
Ruling: the add_done line loads with status "taken" (the existing [x] status), not "done" — the brief says done, but [x]="taken" is asserted by test_ideas and used by gitlab_sync, and the lead rule marks taken-up ideas the same way — cost if wrong: none.
Task 9: green check passed (41 OK), commit e018425, review dispatched to rev9 (standard, sonnet), package 8672c98..e018425
Ruling: Task 9 may edit scout_post._edit so revision posts (posts["<week>-<id>"]) are edited on a click too — a redraft is its own post per the brief — cost if wrong: none.
Ruling: a failed copy/commit (not only mid-change) queues the id in pending_copies; retry_copies gives up after 24 h with the decision line — cost if wrong: a 24 h wait before the user hears of a broken branch.
Task 9: review — spec ❌ (cleanup deletes a branch with an approved-not-copied draft), 2 Important (cleanup; copied_at written before add_done/approved.jsonl/add_line, a raise there loses them)
Ruling: copied_at stays right after the main commit (the commit is the irreversible step, so a retry must never recommit); each follow-up (add_done, approved.jsonl, add_line) runs in its own try, a failure is logged to weekly.log as `approve <id>: <step> failed: <err>` and the others still run — cost if wrong: a missing ideas line the log names.
Task 9: fix round 1 dispatched to core (resume), FIX_BASE e018425
Task 9: minor (deferred): a failed commit leaves the written spec dirty in the live checkout until the 24 h give-up; "already approved" leaves the id in pending_copies on a race; _scout_retry runs git under controls-state.lock; redraft reads the old draft without the lock
Task 9: fix round 1 green (43 OK), commit a91407e, re-review sent to rev9
Task 9: fix round 1/5 (2 addressed, 0 open; commits e018425..a91407e)
Task 9: complete (commits 8672c98..a91407e, review clean after round 1)
Ruling: Task 11 guards against a second publish in one week: weekly with last_week == week (without --force) prints 'scout: already ran for <week>'; with --force, scout_post.publish keeps the stored status of decided drafts — Task 8 minor (a second publish resets decided drafts to pending) — cost if wrong: a forced rerun re-arms buttons.
Task 11: dispatched to weekly (frontier, fable), base a91407e
Task 11: green check passed (31 OK), commits de99275..544c769, review dispatched to rev11 (standard, sonnet), package a91407e..544c769
Ruling: a week with no new items stops before pick, so a pending revise waits for a week with items or `scout redraft <id>` — spec §3 "skipped with no post when the week has no new items" — cost if wrong: a revision waits a week.
Ruling: a week with items always posts a digest, even 0 drafted (it still carries source health and overlaps) — spec skips only on no new items — cost if wrong: one quiet post.
Ruling: without --root, the root falls back to the checkout holding scout.py; Task 12's plists pass --root explicitly — resolve_root(PROJECT, {}, None) is None under launchd — cost if wrong: none.
Ruling: --dry-run obeys the skip rules (Task 15's command already passes --force); it prints `would redraft: …` instead of running redraft and keeps its state copy under $TMPDIR/scout-dry-* for inspection — cost if wrong: a stale temp dir.
Task 11: minor (deferred): redraft and dropped-draft tokens are not counted in the metrics record
Task 11: minor (deferred): _guarded reads weekly.json before the lock (overlapping runs can double-publish); cleanup runs before last_week is set (a raise there allows a second digest); non-model exceptions never count in failed_weeks; failed_weeks counts events not Sundays; early-exit dry-run leaves a temp dir; publish --force resets created_at and the revise note of a pending/revise draft
Task 11: complete (commits a91407e..544c769, review clean)
Ruling (amends the Task 11 --root ruling): Task 12's plists keep the brief's exact ProgramArguments, no --root — scout.py's fallback is the checkout holding it, which under launchd is the live checkout the CLI path points at — cost if wrong: none.
Task 12: dispatched to sched (standard, sonnet), base 544c769, parallel with Task 13 (disjoint files)
Task 13: dispatched to docs (mechanical, haiku), base 544c769, parallel with Task 12
Task 13: green check passed (greps 1/1, test_scout_docs 3 OK), commit e8c37ec, review dispatched to rev13 (standard, sonnet)
Task 12: green check passed (18 OK), commit 254728e, review dispatched to rev12 (standard, sonnet)
Task 13: minor (deferred): the INSTALL scout line splits the discover code block (between discover install and status)
Task 13: complete (commits 544c769..e8c37ec, review clean)
Task 12: ⚠ cannot-verify (weekly falls back to the checkout without --root) — resolved: scout.py _root passes {"root": REPO} to dream.resolve_root
Task 12: minor (deferred): a partial install leaves earlier plists loaded (as discover_schedule); the poll plist pins an unused TC_STATE
Task 12: complete (commits e8c37ec..254728e, review clean)
Task 14: dispatched to verify (standard, sonnet), base 254728e
Task 14: real-state finding (load-bearing): every https source fails with CERTIFICATE_VERIFY_FAILED on the real python3 (/usr/local/bin/python3, python.org 3.14, its openssl cafile missing); with SSL_CERT_FILE=/etc/ssl/cert.pem all 10 fetch
Ruling: scout_fetch builds _OPENER with an HTTPSHandler whose context is ssl.create_default_context(), and when the default verify paths have no existing cafile/capath it loads /etc/ssl/cert.pem (if present); SSL_CERT_FILE still wins — stdlib only per the constraints, and launchd runs the same python — cost if wrong: none, verification stays on.
Ruling: the CA fix is dispatched after Task 14's full suite finishes (it would edit scout_fetch.py mid-run), as a fix to Task 3 with its own scoped review
Task 14: full suite FAIL 9/200 (rc=1) — cause: Task 11/12 header usage lines pushed the help text past bin/tmux-ctl `sed -n '2,80p'`; commit f70e30d (isolation test + note)
Ruling: help prints the header comment from line 2 up to the first non-comment line (awk), not a fixed line range — a fixed range breaks on every new usage line — cost if wrong: none.
Task 14: fix dispatched to verify (help range + the CA-bundle ruling in scout_fetch), FIX_BASE f70e30d
Ruling (amends the help ruling): help keeps the pinned `sed -n '2,Np'` form with N=84 — 9 suites pin that form, and the header has comment lines after the usage block that awk would print — cost if wrong: the next header line must move N again.
Task 14: fix green — all.zsh `ALL PASS 200 jobs in 9m25s` rc=4 (over budget, accepted); scout_fetch 47 OK; all 10 sources rc 0 on PATH python3; isolation mutation FAILED then restored OK; outbox mtime flake fixed (compare by name); commits f70e30d..6af6cfd
Task 14: review dispatched to rev14 (standard, sonnet), package 254728e..6af6cfd
Task 14: minor (deferred): the isolation snapshot includes this worktree's for-each-ref, so a teammate commit mid-run flakes it; "compared N paths" counts labels; no RED run for SslContextTest
Task 14: complete (commits 254728e..6af6cfd, review clean)
Final review: dispatched to final (session model), package 3b002b9..b14976b
Handoff: lead context over budget (301K) after the final review dispatch; final is running
Final review: re-dispatched to final (session model) after handoff, package 3b002b9..b14976b
Final review: with fixes — 0 Critical, 5 Important (stranded phone Approve, seen keys expire while listed, model junk crash uncounted, failed commit pins approval, launchd unproven); final-review.md
Ruling: final Important 5 (real launchd run, #scout real run) is not fixed in the wave — it needs schedule install in the user's launchd and a #scout channel the user creates; its three checks join user gate #119 for the morning — cost if wrong: a launchd-only failure surfaces at the morning gate, not before merge.
Ruling: the fix wave also takes the #scout allowFrom + _check_request_url Minor (untrusted page text reaches the draft prompt) and the INSTALL docs Minor (with the Task 13 deferred minor); all other Minors and deferred items wait — cost if wrong: small follow-up specs.
Ruling (amends T8 approve_fn root, T9 retry, T11 catch-all): accepted the final reviewer's disagreement — root falls back to the module's checkout, a failed copy restores the path, a crash counts as a failed week — cost if wrong: none.
Final fix: dispatched to fixer (standard, sonnet), FIX_BASE b14976b, brief final-fix-brief.md
Final fix: green — fixer 4 commits b14976b..b59f481; /usr/bin/python3 Ran 306 OK rc=0; lead re-ran python3 Ran 306 OK rc=0 (fixer's log overwritten)
Final re-review: dispatched to rereview (standard, sonnet), package b14976b..b59f481
Final re-review: all findings addressed (Important 1-4, both folded Minors), no new breakage; out-of-scope minor: _check_request_url does not refuse private/link-local https hosts (same gap as source: requests) — filed as an idea
Final review: clean (commits b14976b..b59f481)
User gate #119 (Task 15), 2026-11-23: real `TC_SCOUT_DIR=<tmp> tmux-ctl scout poll && tmux-ctl scout weekly --dry-run --force` rc=0 — poll 8 new from 10 sources, 0 failed; digest "🛰 scout agent-board 2026-11-22: 3 drafted, 0 other" (superpowers-extended-cc 6.5.3-dev → 7.1.2 upgrade, statusLine tap bounds, `=`-quoting note scope), Approve/Reject/Revise 1-3, 1456984 tokens. `refs/heads/scout` empty; real scout dir unchanged (stat snapshot before = after). User verdict: "the digest is not worth having". Scout schedule stays not installed. Gate closed: ran and answered; the verdict is negative.
