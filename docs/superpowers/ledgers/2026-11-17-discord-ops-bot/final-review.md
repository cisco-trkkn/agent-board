# Final whole-branch review: discord ops bot

Branch `feat/discord-ops-bot`, range `21d03b8..1035daa` (17 commits, 31 files, +3858 −57). Reviewer: ops-final (session level, read-only).
Spec: `docs/superpowers/specs/2026-11-12-discord-ops-bot-design.md`. Plan: `docs/superpowers/plans/2026-11-17-discord-ops-bot.md`.

## Verdict

**Ready after fixes.** There are 0 Critical findings and 1 Important finding. The Important one is cheap: merge-request records the worktree path, which is removed later (I1 below). I also recommend folding in three one-line Minors (M1, M2, M3) with the same fix. The Task 10 items listed at the end still need the user's run from the phone.

## What I ran (evidence)

- `python3 -m unittest test_discord_ops test_discord_merge test_discord_digest test_discord_wiring test_discord_feed test_discord_controls` from `board/tests`: **Ran 217 tests, OK** (83 s). I did not run all.zsh or the node suite, because ops-test owns those.
- **A cross-seam run on real artefacts, with no fixture views** (scratch TC_STATE and a scratch git repo with 13 changed files, one of which holds a ``` fence):
  1. Real `discord_merge.request` and two real `discord_ops.tick` calls produced `views.json`: 1 merge approval, and evidence with 13 files.
  2. The real `bridge.js` (`createBridge`, `ops: true`, test FakeClient) drained the real `_ops/outbox`. The card went to CC with the three exact button ids. The approval went to AP with Merge, Keep branch and `ab:ops:files:<key>:0`, plus a string select of 13 options. Show files page 2 gave 3 files and a Prev button. The diff select on `src/f1.py` returned a fenced diff with the inner ``` escaped. Inbox listed the approval. A Merge click from U1 wrote a `click` event. A Merge click from a non-allowlisted user got "Not authorized." and wrote a `rejected` event.
  3. Real `discord_ops.consume(..., on_merge=discord_merge.on_merge)` handled all 5 events. It sent `add_line('alpha', '[Discord] merge approved for spec-x')`, then wrote the ops edit `alpha: merge approved — sent to the lead` and the project-channel edit with key `merge:7:97f59975`. The audit had 5 lines: answered ×3, rejected, merged.
  4. Moved-branch path: I committed on `feat/x` after a second request, then clicked Merge. The result was `stale`, no lead line was sent, and the next tick held exactly one open merge approval: the fresh `merge:8:<new sha8>`, with its evidence in views.
- I read every changed board, bridge and zsh file, the overseer and orchestrator rules, and INSTALL.

## Seams checked

| Seam | Result |
|---|---|
| bridge.js events ↔ `discord_ops.consume` / `handle_event` | ✅ click, read and rejected run end to end (above). slash and modal are covered by unit tests on both sides, and their shapes match the Global Constraints. |
| views.json writer ↔ bridge reader | ✅ The real writer was read by the real bridge (above). The node tests themselves use a hand-written VIEWS fixture (see M8). |
| approval keys / customId ≤ 100 | ✅ Keys are 12 hex characters. The longest ids are `ab:ops:pause-all-confirm:<13 digits>` (38 chars) and `ab:modal:new-spec:<project ≤60>` (78 chars). Select values are cut to 100. |
| merge evidence + Merge re-check | ✅ The re-check works on the repo path it stores, but that path is the problem: see I1. |
| ops tick + digest wiring in server.py | ✅ `feed_tick` calls `ops_tick` once after every project; tick, consume and digest each have their own try. Digest wiring has no dedicated test (Task 8 deferred); I confirmed it by reading `server.py:521-538`. |
| overseer channel + launcher heal | ✅ `bin/claude-overseer:13-24` drops the inherited `DISCORD_STATE_DIR` and adds `--channels` only with an ops token. `dc_ensure_launcher` runs every time. Settings allow only `reply` and `fetch_messages`. |
| Discord input → shell argv | ✅ None found. Form text goes only to `ideas.add` or to `add_line` (`discord_ops.py:336-351`). customIds only look up `st.approvals`. Git argv in `discord_merge` takes values from the evidence file and the lead's CLI, shape-checked and with `--` before paths. |
| allowFrom re-read per event | ✅ The board reads it in the loop at `discord_ops.py:436` and in controls `consume_events`. The bridge reads it on every interaction (`allowFrom()`). |
| audit lines | ✅ Every event is audited. One cosmetic issue: see M4. |

## Critical

None.

## Important

**I1. A merge approval made from a spec worktree can never be merged once that worktree is gone.** Files: `board/discord_merge.py:199-202` (repo = `git rev-parse --show-toplevel`), `:159-165` (on_merge), and `claude/orchestrator.md` Queue mode step 2 (the `ask` rule passes no `--repo`).
- What happens: the lead runs `tmux-ctl discord merge-request` from the spec's worktree, so the evidence file stores the worktree path as `repo`. If that worktree is removed before the user taps Merge (a cleanup, a relay, or the user), `rev_parse(ev["repo"], …)` returns None. The post is then edited to "branch changed since this was posted", no fresh request is posted, and no lead line is sent. The approval is gone, and only the lead can post it again.
- Ledger: this is the Task 5 ⚠ line, which was never carried into a fix.
- Fix (a few lines): when `--repo` is not given, resolve the main checkout from `git rev-parse --path-format=absolute --git-common-dir` (its parent) instead of `--show-toplevel`. Branch refs are shared, so the re-check is the same and survives the worktree. Optionally, the `ask` rule can also say "from the main checkout". Add one test that removes the worktree before `on_merge`.

## Minor

- **M1. Git diffs follow the user's git config** (`discord_merge.py:71,75,80`). With `color.ui=always` the stat lines in the post carry ANSI codes. With `diff.external` set, the stored diffs come from that external tool. Fix: add `--no-ext-diff --no-color` to the three `diff` calls. Recommended with I1 (Task 5 deferred).
- **M2. The approval title is the post's first 100 characters, newlines included** (`discord_ops.py:156,248`). In the real run, the Inbox and `/approvals` showed `merge approval: spec-x\nfeat/x → main @ …\n src/f1.py | 1 +…`, three lines of diff stat per merge. The digest's decision lines inherit the same title. Fix: use the first line, or `merge approval: <spec>`. Recommended with I1.
- **M3. The card's unlabelled `k/n` is the plan digest of every lead task** (`discord_ops.py:116`). The spec (:44) asks for `<running spec> k/n`, and the queue column already shows it as `queue: running <spec> (k/n)`. The extra `0/5` (lead note, 05:43Z) counts Plan & run and gate tasks, which reads as wrong progress on the phone. Fix: drop it, or label it `plan k/n`.
- **M4. Ops events that name no project are audited with the target `None:<what>`** (`discord_ops.py:356`). Seen in the real run: `"target": "None:ab:ops:inbox"`. Fix: use `project or ""` in the format string.
- **M5. Same-millisecond events are processed in random order** (bridge `writeEvent` random suffix; Task 3 deferred). Confirmed in the real run: a non-allowlisted click written after U1's Merge click was handled first. It is harmless today, because the actions are idempotent per record. Defer.
- **M6. The ops bot does not cover projects without a project channel.** `sink_event` and `discord_feed.tick` only write the feed for projects with a channel (`discord_feed.py:552-556`, `server.py:500`). Such a project gets no critical posts, no teammate perm approvals and no "other" decisions, and the digest always calls it `quiet`, even when it has activity. Merge approvals and lead questions still work. The spec assumes every project has a bot. Defer, but either say so in INSTALL or print `no channel` in place of `quiet`.
- **M7. A merge approval can be posted without its diff select.** In `tick`, the approval op goes to the outbox (`discord_ops.py:247`) before views.json gets its evidence (`:295`). If the bridge drains the outbox in that gap, the post has no select menu, permanently. Show files still works, because it reads views when clicked. Fix: write views first, or write approval ops after views. Defer.
- **M8. The node tests read a hand-written VIEWS fixture** (`test/ops.test.js:13-22`, `test/commands.test.js`). The real board-written file passed through the real bridge in this review (above), but nothing keeps that true. Defer; a test that feeds board-written views.json to the bridge is a follow-up.
- **M9. The Pause-all confirm says "Sent." even after the 60 s window**, while the board audits `expired` (`bridge.js` `onOpsInteraction` vs `discord_ops.py:394`). The user believes the queues were paused. Fix: the bridge compares the customId's ms with `now()` and answers "Expired, tap Pause all again." Defer, or fix before Task 10 if cheap.
- **M10. INSTALL leaves out three Task 10 setup steps** (`docs/INSTALL.md` Ops bot section; extras check 7):
  1. Pairing needs the discord plugin running on `_ops`. That is the overseer, which only connects it when the overseer starts after `token --ops`. INSTALL does not say to restart the overseer, or how; `allow <user id> --ops` avoids the problem.
  2. `TC_DISCORD_DIGEST_AT` is documented nowhere outside the module docstring.
  3. Chat in #command-center reaches the overseer, and the overseer runs under bun.

  Fix the docs before Task 10.
- **M11. An `ask` spec never counts as merged in the digest.** Its feed `spec_outcome` is emitted once, as `awaiting merge approval …`, and the later `merged <sha>` outcome update is never re-emitted (emit dedup by `outcome:<rid>`). Defer.
- **M12. A merge or keep on a project with no channel writes an edit into that project's outbox, which no bridge drains** (`discord_ops.py:368`; seen in the run). `_enforce_cap` never evicts `edit` ops. That is one file per merge. Defer.

## Deferred-minor, parked and Ruling triage (progress.md)

**Fix before merge:** the Task 5 ⚠ "merge-request run from a spec worktree" (= I1), and Task 5 "diff honours user git config" (= M1, one line).

**Fix before Task 10 (docs or UX, cheap):** M10 (INSTALL), and M3 (the card's `0/5`, from the lead's note and the Task 7 deferred line).

**Defer (follow-up ideas), each still accurate as recorded:**
- **Task 2:**
  - read event when views.json is missing;
  - st.posts has no channel (keyed posts all go to home, so there is no live case);
  - select value collisions at 100 chars;
  - ctx/fence surface and test gaps.
- **Task 1:** usage text, untested `--ops` on deny/remove/forget/audit, identical cc/approvals ids.
- **Task 3:**
  - same-ms order (= M5);
  - a project bridge accepting another project's name (the same allowlisted user, so audit only);
  - a ctx comment.
- **Task 4:**
  - a perm forwarded from an ops user who is not in the project's allowFrom is audited `forwarded` and rejected downstream. Watch for this in Task 10 if the two bots' allowlists differ;
  - getattr dispatch and unused args;
  - a feed offset advanced before processing;
  - pause-all queue state one tick old;
  - an action repeated after an edit failure (add_line dedups a waiting identical line);
  - a raise inside the except audit.
- **Task 4, already resolved:** "merge key collides across lead sessions". Task 5 made the key `merge:<task>:<sha8>`, and this review checked it.
- **Task 9:** no dc_holder guard for a second overseer, the ops path spelled three times, reply can attach files (allowlisted channel only).
- **Task 5:**
  - git calls under the ops lock. This also runs on the overview request path (`overview_payload` → `feed_tick`), so a slow repo delays `/api/overview` while a Merge is handled. That is acceptable for local repos;
  - the evidence name collision `a-b`/`7` (task ids are numeric);
  - test leftovers;
  - `_evidence_view` reading ≤ 200 files.
- **Task 7:**
  - `configured()` outside the try (`_load` swallows its errors, so it cannot raise);
  - log noise every build for a channel-less project whose lead list fails;
  - all.zsh at the tip (ops-test owns this).
- **Task 8:** no wiring test, a re-post when the state write fails, and a critical-not-held test that never calls `dg.tick`.

**Rulings:** all are sound and match the code I read: T9 parallel; approval.project; needs_you not mirrored; the on_merge `{result, text}` interface with pop-after-success; the keep text; the open cap of 200 with a 7-day TTL; known project = records or discord dir; INSTALL `pair --ops` via the overseer (M10 adds the missing restart step); the lead committing ops-board's user-approved commit; the react-delivery side fix on a separate branch. None needs changing before merge.

**Not in the ledger, out of scope:** the card's `blockers: stuck 198m` while the lead is active comes from `overview.agent_alerts` on main, not from this branch. It is a follow-up for the stuck heuristic.

## Only Task 10 can show

- The ops bot really registers its guild slash commands (the `applications.commands` scope), and the project bots' commands coexist with them in the picker.
- The ephemeral replies, modals, link buttons and select menus render on the phone, and the 3 s interaction deadline holds against the real gateway.
- Pairing or allow through the overseer's plugin on `_ops`, and chat in #command-center answered by the overseer.
- A real `integration: ask` queue spec: the lead keeps the branch, posts evidence, and starts the next spec. Then Merge from the phone, after which the lead runs finishing with merge (watch for I1 if it was not fixed).
- Pause all → Confirm within 60 s reaches only the leads with a running queue; Resume all; `/idea` lands in the ideas file.
- A real teammate permission prompt mirrored into #approvals, allowed from there, with both copies edited. Note the react-delivery side finding: a dialog in the lead pane holds lines.
- The digest at `TC_DISCORD_DIGEST_AT` on a real day's feed, and the card's 30 s edit throttle on the live board.
