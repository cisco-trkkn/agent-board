# SDD ledger — plan: docs/superpowers/plans/2026-11-05-queue-followups.md
Preflight: 1 task; self-consistency: test lines target phrases present in Step 3/4 text (checked: 'ideas are marked when queued', '`Running plan: <title>`', 'metadata.queue.current = {"plan": "<plan path>"'); length 1725<=1743 bytes; no conflicts.
Task 1: dispatch impl (haiku) base 250ac6e; DONE 50718cc green
Task 1: minor (deferred): orchestrator.md:66/:76 "ideas steps 1–4 wait" wording now partly stale (step 4 ran at queue time)
Task 1: minor (deferred): step 3 at :69 says "their ideas" — dropped ideas (- [-]) not named explicitly
Task 1: minor (deferred): Running plan check tests presence, not that it is listed first
Task 1: complete (commits 250ac6e..50718cc, review clean)
Final review: with fixes — I1 dropped ideas not marked at queue time; minors :66/spec:107 wording fix-before-merge; Running-plan-first check left; fix wave -> impl, base 50718cc
Final fix wave: 2 addressed, 0 open (commits 50718cc..7022a2e)
Final: parked — spec :107 "round" repeated in the parenthesis — Ruling: leave; wording only, meaning is correct — costs one awkward spec sentence if wrong
