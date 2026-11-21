# SDD ledger — plan: docs/superpowers/plans/2026-11-21-supervised-improvement-loop.md
Stale check: stale (bin/tmux-ctl +7 lines in list case, metrics jsonl appends); rebased 1451cf1 -> 15cf56c on d4ded08.
Ruling: no refresh agent — the stale paths do not touch any task's files beyond a 7-line list-case hunk in bin/tmux-ctl outside improve); the refresh's main job (engine paths reads->writes) needs Task 1's note — costs if wrong: Task 3+ briefs carry an old base for bin/tmux-ctl, a rebase conflict at most.
Ruling: preflight conflict scan deferred until Task 1 passes — engine/bin has only registry.js on main (PCEE engine parts 1/2 failed gate K1), so Task 1 is expected to stop the plan — costs if wrong: scan runs late, before Task 2.
Task 1: dispatched (base 15cf56c, teammate iface-check, standard)
Task 1: failed — engine interface missing: rows 1-12 (commit 8289363; verify 12 then 13, the 13th MISSING is the note's intro line)
Ruling: plan stopped at Task 1 per its own acceptance criterion; no fallbacks; branch supervised-improvement-loop kept unmerged — costs if wrong: none, the loop needs the engine built first (user's call)
