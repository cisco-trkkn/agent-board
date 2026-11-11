# SDD ledger — plan: docs/superpowers/plans/2026-11-09-remote-access.md
Spec: docs/superpowers/specs/2026-11-09-remote-access-design.md · branch feat/remote-access · base 7f3cc43
## Pre-flight scan
| Tasks | Shared | Found |
| T1/T4 | bin/tmux-ctl header+help range, case stmt | T4 blockedBy T1, serial on one implementer; T1 AC names "(Task 4) lines" it cannot see |
| T1/T2 | project key + telegram state dir | both compute it; same formula (Global Constraints) — consistent |
| T3/T4 | fixtures + selection key | T4 blockedBy T3; key comes from T3 README |
| T1,T4/T6 | command names in docs | T6 blockedBy T1,T4 |
| T5 | board only | no overlap |
| T1 self | moves the not-inside-tmux guard for telegram only | consistent with its AC |
| T2 self | tests stub claude; AC both exec lines | consistent |
| T3 self | real claude run | consistent; side effects in scratch dir only |
| T4 self | --expect is a plan addition implementing spec §5.3 | consistent |
| T5 self | len(f)==16 -> 17 | consistent |
| T6 self | must not touch user's locally edited row | consistent |
Ruling: T1's help check covers only its own telegram line; T4 adds its approve line and re-widens the range — T1 cannot see Task 4 — cost if wrong: one help-range fix in T4.
Ruling: run two implementers in parallel lanes (A: T1→T4→T6, B: T3→T2→T5): files disjoint across lanes, deps stay within or across lanes as ordered (T4 waits for T3) — cost if wrong: a git index.lock retry.
Task 1: dispatched impl-a (sonnet/standard), base 7f3cc43
Task 3: dispatched impl-b (sonnet/standard), base 7f3cc43
Task 3: report green (verify 6 files, 0 /Users/ each); trust entry for the deleted scratch dir left in ~/.claude.json (user config, not edited)
Ruling: T4 `once` selects only an option whose label is exactly `Yes` (after the number, trimmed); `deny` only exactly `No`; anything else refuses — captures show `don’t` (U+2019) and "Yes, and switch to auto mode/accept edits" rows that the spec's blacklist would let through — cost if wrong: approve refuses a future prompt whose plain yes is worded differently (fails closed).
Task 3: review dispatched to rev (sonnet/standard), package review-7f3cc43..a35f881.diff
Task 2: dispatched impl-b, base a35f881
Task 3: minor (deferred): after-no-arrows.txt is an 8-line excerpt, not a full capture
Task 3: minor (deferred): fixtures come from a plain claude, not a teammate (spec says teammates); README should say so
Task 3: minor (deferred): digit probe covered 1 and 4 only; approve must re-read the pane right before sending (carried to T4)
Task 3: complete (commits 7f3cc43..a35f881, review clean)
Task 1: report green (ALL PASS rc=0, 14 files scanned 0 hits, 9 mutations)
Ruling: dispatch T4 to impl-a while T1 is in review — same implementer, T1 fixes would come before T4 commits — cost if wrong: a rebase-free fixup inside tmux-ctl by the same writer.
Task 1: review dispatched to rev, package review-a35f881..a1c4762.diff
Task 4: dispatched impl-a, base a1c4762
Task 2: report green (24 ok ALL PASS rc=0, 4 mutations); test_orchestrator_path 4/5 FAIL also on main 2833b81 (relay launch check regression) — out of scope, idea filed
Task 2: review dispatched to rev, package review-ddbefe2~1..ddbefe2
Task 5: dispatched impl-b, base ddbefe2
Task 1: review spec ❌ — 2 Important (--project <token> leaks token + token-named dir; status stderr on missing bot.pid)
Task 1: minor (deferred): `claude plugin list | grep -q` under pipefail can SIGPIPE into false "plugin: missing"; no enabled-status check
Task 1: minor (deferred): claude stub is not the real `plugin list` layout
Task 1: minor (deferred): forget says "token removed" when none existed
Task 1: minor (deferred): a test comment claims a check that doesn't exist
Task 1: minor (deferred): help assertion hard-codes the last header line
Task 1: fix round 1/5 dispatched to impl-a (FIX_BASE ddbefe2)
Task 2: review spec ✅ quality Approved; minor 1 (--channels arity) checked by lead: binary defines `--channels <servers...>` (variadic)
Ruling: promote T2 minor 1 to Important — line 44 swallows a relay prompt as a channel — fix: TG_ARGS before AB_ARGS in both exec lines — cost if wrong: one reordered flag
Task 2: minor (deferred): ~/.bun/bin prepended for every lead, token or not
Task 2: minor (deferred): bun PATH test accepts position 1 or 2; TC_TELEGRAM=0 + inherited TELEGRAM_STATE_DIR untested
Task 2: minor (deferred): project name not validated for / or leading . (only used in a -f test)
Task 2: fix round 1/5 dispatched to impl-b (FIX_BASE ddbefe2)
Task 5: report green (8 tests OK; 43 related OK; real-state :7710 0.106s, 6 live panes telegram false); also edited 5 board tests' fake rows 16->17 fields
Task 5: test_restart_orchestrator 2 FAIL also on main 2833b81 — pre-existing, added to the relay-tests idea
Task 5: review dispatched to rev, package review-ddbefe2..6c48616
Task 2: fix commit fe4f8c2 (26 ok ALL PASS rc=0); scoped re-review queued to rev
Task 5: minor (deferred): badge matches any descendant whose args mention the flag (e.g. a tool shell); tighten to argv[0] claude/node
Task 5: minor (deferred): --channels=plugin:telegram spelling not detected
Task 5: minor (deferred): ps -A 76-102 ms per uncached build_state with a lead; a short proc_table cache would remove it
Task 5: complete (commits ddbefe2..6c48616, review clean)
Task 2: fix round 1/5 (1 addressed, 0 open; commits 6c48616..fe4f8c2)
Task 2: minor (deferred): fix comment placed above the Telegram comment block, away from the exec lines
Task 2: complete (commits a1c4762..ddbefe2 + fe4f8c2, review clean); real-CLI flag order left to the T7 e2e (add a relay-with-prompt item in T6's checklist)
Task 4: report green (32 ok ALL PASS rc=0; 5 mutations); folder-trust refusal not implemented (no fixture)
Task 4: review dispatched to rev, package review-fe4f8c2..9729aa9
Task 1: fix round 1 not started by impl-a (crossed messages) — re-sent
Task 1: fix commit 097802b (ALL PASS rc=0; RED 6 FAILED); _-prefixed session names now refused (_web views — acceptable, wrong key anyway); scoped re-review to rev
Ruling: dispatch T6 before T4's review closes — docs depend only on command names, which are fixed — cost if wrong: a doc line edit after a T4 fix
Task 6: dispatched impl-a, base 097802b
Task 6: report green (verify 2,1,14); review queued to rev, package review-097802b..4a1864b
Task 4: review spec ❌ — Critical (option rows parsed inside the command preview → spoofed ` 2. Yes` presses the always row), Important (tail -40 drops the preview from the compare), Important (divider match locale-dependent)
Ruling: promote T4 minor "empty --expect disables the check" to Important — the lead protocol relies on --expect — cost if wrong: one extra refusal path
Task 4: minor (deferred): eval "$TC_APPROVE_BEFORE_SEND" test seam in production code
Task 4: minor (deferred): digit can reach a non-claude pane if the prompt vanishes after re-capture
Task 4: minor (deferred): tests use a single dialog layout
Task 4: fix round 1/5 dispatched to impl-a (FIX_BASE 4a1864b)
Task 1: fix round 1/5 (2 addressed, 0 open; commits 9729aa9..097802b)
Task 1: minor (deferred): charset also refuses session names with spaces/non-ASCII; such leads never opt in — docs could say so
Task 1: complete (commits a35f881..a1c4762 + 097802b, review clean)
Task 6: review spec ❌ — Important: e2e item 10 greps the bot id not the secret; item 6 checks a gitignored file; approve step must mirror the T4 fix + multi-line --expect guidance
Ruling: fold T6 minors (accept-edits row, charset sentence, Bun pointer, re-wrap, trust-entry note, worker-window e2e item) into fix round 1 — same files, cheap — cost if wrong: a slightly larger re-review diff
Task 6: minor (deferred): e2e item 5 button name "Allow" unverified
Task 6: fix round 1/5 queued to impl-a after T4 fix round 1
Task 4: fix commit 0a8b829 (ALL PASS rc=0, RED 7, 4 mutations); scoped re-review to rev
Task 6: fix commit 0e62476 (greps 2,1,15); scoped re-review queued to rev
Task 4: fix round 1/5 (4 addressed, 1 new open — rows after the chosen run not checked: unrecognised real question + spoofed preview presses the always row; commits 4a1864b..0a8b829)
Ruling: --expect mandatory for once and deny — the protocol always passes it and it fails closed if the divider glyph changes — cost if wrong: manual callers must pass a line of the command
Task 4: minor (deferred): eval "$TC_APPROVE_BEFORE_SEND" seam still in production code
Task 4: fix round 2/5 dispatched to impl-a (FIX_BASE 0e62476)
Task 6: fix round 1/5 (3 addressed, 1 new open — item 10's forget deletes .env before item 11's relay; commits 0a8b829..0e62476)
Task 6: fix round 2/5 queued to impl-a after T4 round 2 (with item-6 glob (N) and item-14 wording folded in)
Task 4: round-2 fix commit d137056 (ALL PASS rc=0; RED 5; 2 mutations); scoped re-review to rev
Task 6: round-2 fix commit bc3aff7 (greps 2,1,16); scoped re-review queued to rev
Task 4: fix round 2/5 (2 addressed, 0 open; commits 0e62476..d137056)
Task 4: minor (deferred): any extra line under the `Esc to cancel…` footer (status/notification) reads as "no permission prompt" — fails closed; check what sits under a real teammate's footer at the user gate
Task 4: complete (commits fe4f8c2..9729aa9 + 0a8b829 + d137056, review clean)
Task 6: fix round 2/5 (1 addressed, 0 open; commits d137056..bc3aff7)
Task 6: minor (deferred): item 6 diffs only permissions.allow; an "always allow access to <dir>" row may land in permissions.additionalDirectories — diff .permissions // {}
Task 6: minor (deferred): step 3's footer parenthetical reads as part of the `no No option` string
Task 6: minor (deferred): e2e approve-on-a-real-teammate item should ask to note what sits under the dialog footer (T4 minor)
Task 6: complete (commits 097802b..4a1864b + 0e62476 + bc3aff7, review clean)
Final review: dispatched final (session level), package review-2833b81..bc3aff7
Ruling: the 3 Task 6 doc minors (footer note in e2e items 6/14, diff .permissions, step-3 footer sentence) go into the single final-review fix wave, not a Task 6 round 3 — cost if wrong: none, same files
Final review: Ready with fixes — 0 Critical, 4 Important (I1 TELEGRAM_STATE_DIR inherited by the lead's Bash children → a child claude kills the lead's poller; I2 --expect substring over whole block; I3 e2e trust item lacks --expect; I4 e2e item 6 diffs only .allow); M1 tee missing; M3 copy-mode false "chose Yes"
Ruling: I1 fix = lead-only SessionStart hook appending `unset TELEGRAM_STATE_DIR` to CLAUDE_ENV_FILE + INSTALL sentence + e2e pid gate — the MCP server is started by claude from its own env, Bash children get the scrubbed env — cost if wrong: the env file doesn't apply and the e2e gate catches it
Ruling: I2 fix = --expect must equal one whole preview line, compared only within preview lines — cost if wrong: approve refuses more often (fails closed)
Ruling: fold M1 and M3 (copy-mode refusal) into the fix wave; leave M2 and the other deferred minors — cost if wrong: a later small follow-up
Final fix wave: dispatched to impl-a (FIX_BASE bc3aff7)
Final fix wave: commits b04eb4c 4e17a4c 17963a4 (all suites ALL PASS, hook test 10/0); scoped re-review to final
Final re-review: 8/8 addressed; residual N1 (Important): --expect "<one line>" passes a changed multi-line preview that contains that line (crafted A: curl line + approved line; C: embedded divider) → approve presses Yes; protocol step 3 dropped spec §5.3's own lead re-read; N2 (Minor): INSTALL "never polls" holds for Bash-tool shells only, hooks still inherit
Ruling: N1 is load-bearing (spec §5.3 "same tool and command text" not met by the only check left) — no second fix wave — spec 11 kept unmerged on feat/remote-access, outcome failed; fix proposed: preview line count must equal --expect line count, --expect takes newline-separated lines, A and C as refusal tests, restore the lead's own re-read in step 3 — cost if wrong: the feature waits one morning for a one-round fix
Final: parked — N2 — Ruling: doc wording, fix with N1
