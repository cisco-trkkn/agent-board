# SDD ledger — plan: docs/superpowers/plans/2026-11-05-overnight-queue.md
Preflight scan:
| pair/task | shared | finding |
| T1-T2 | claude/orchestrator.md (T1 writes, T2 runs it as the lead prompt) | T2 blockedBy T1 — ok |
| T1 self | 6 checks vs text in step 3 | lead ran all 6 checks on main: each exits 1 (RED ok); each phrase appears verbatim in step 3/4 text — ok |
| T2 self | Verify counts 4 sections; AC needs transcript count, merges, report | consistent; the doc is the deliverable, AC carry the real checks |
BASE e7d3342
Task 1: dispatched scribe (sonnet/medium), BASE e7d3342
Task 1: green check ok (RED 6 FAIL → ALL PASS rc=0); review dispatched qrev on e7d3342..5494a4c
Task 1: review ❌ spec (no "no other question" rule), 2 Important, 7 Minor
Task 1: Ruling: the exceptions question names at most 3 specs plus None (AskUserQuestion's 4-option cap); a longer queue gets one exceptions question per group of 3, in call 1 while it has room (4 questions per call), the rest in call 2; per-spec options 4 per call; "at most two calls" holds for queues the two calls can hold, more calls only beyond that — the spec's design assumed the cap away — cost if wrong: one extra question call on a big queue
Task 1: Ruling: minor "a failed spec must be marked completed" promoted into the fix round — a blocked next task stalls the queue and the morning report never fires — cost if wrong: none, one clause
Task 1: minor (deferred): no→keep doesn't spell the stored metadata {"integration":"keep","push":false}
Task 1: minor (deferred): step 2 omits writing-plans-extras and subagent-driven-development-extras (loaded via CLAUDE.md anyway)
Task 1: minor (deferred): Rules "Don't push, merge…" line not cross-referenced to queue answers
Task 1: minor (deferred): step 1 is ~190 words
Task 1: minor (deferred): MR pipeline fix loop unbounded in queue mode
Task 1: minor (deferred): tests pin phrases only
Task 1: fix round 1 sent scribe, FIX_BASE 5494a4c
Task 1: fix 9b4ec8c green; re-review sent qrev on 5494a4c..9b4ec8c
Task 1: fix round 1/5 (3 addressed, 0 open — no-later-questions, exceptions groups of 3, failed marked completed; commits 5494a4c..9b4ec8c)
Task 1: complete (commits e7d3342..9b4ec8c, review clean)
Task 1: minor (deferred): "a spec queued after the batch gets one question" reads as conflicting with "asks nothing until the morning report"
Task 1: minor (deferred): exception groups spilling into call 2 can't share it with the per-spec questions they feed
Task 2: dispatched nightrun (sonnet/medium), BASE 9b4ec8c
Task 2: green check ok (verify 4 rc=0; 1 AskUserQuestion before report; both merged; report present); review dispatched qrev on 9b4ec8c..d01b8ef
Task 2: minor (deferred): report table splits outcome and sha instead of literal `merged <sha>`
Task 2: minor (deferred): lead set task owner after implementer started → each implementer re-checked twice
Task 2: complete (commits 9b4ec8c..d01b8ef, review clean; cleanup verified by lead: 0 oq processes, scratch dir gone, live status only the user's edit)
Task 2: minor (deferred): answeredAt written as a made-up 00:00:00Z — rule should say read the clock (date -u)
Task 2: minor (deferred): dry run covers the happy path only (no failed/exception/MR/handoff/ruling/user-patch/ideas) — doc should say so
Task 2: minor (deferred): prompt triggered the Next steps round, not regroup step 4; "b blocked by a" came from the tester
Task 2: minor (deferred): auto mode (no permission prompts) not stated in Setup; 10-minute permission rule untested
Final review: dispatched finalq (session level), merge base e7d3342
Final review: with fixes — 0 Critical, 2 Important (regroup queue stops at running plan's finishing; handoff loses metadata.queue), 5 Minor
User decision 2026-11-05: Next steps round with ≥2 groups picked brainstorms all, queues approved specs as Plan & run, then queue mode
Final review: Ruling: one fix wave for I1, I2, the user's Next-steps decision, M1, M2, M5 and the answeredAt clock minor; M3, M4 and the rest left — I1/I2 break the spec's goal; the minors are one-clause text — cost if wrong: one revertable commit
Final fix: dispatched scribe (sonnet/medium), FIX_BASE d01b8ef
Final fix: 54ec6fe green (RED 5 FAIL → test_plugin ALL PASS rc=0); scoped re-review NOT yet run (handoff)
Final fix: re-review dispatched qrev (sonnet/medium) on d01b8ef..54ec6fe
Final fix: re-review qrev — 7/7 addressed; 1 new Important, 1 Minor (review-final-fix.qrev.md)
Final fix: parked — Next steps round queues ≥2 groups but ideas aren't marked until after the queue, so the post-queue round can re-ask them (orchestrator.md:66,69) — Ruling: real, deferred to the user at finishing (no second fix wave; one-clause follow-up: mark ideas `- [x] → spec` at queue time) — cost if wrong: one extra AskUserQuestion about already-run groups in a morning round
Final fix: parked — running plan's integration has no own question, shape of metadata.queue.current unspecified, spec says "counted in call 1's cap" (orchestrator.md:72) — Ruling: minor, deferred; the running plan takes the queue default, which is the stated behaviour — cost if wrong: a running plan on the MR default has undefined push consent
