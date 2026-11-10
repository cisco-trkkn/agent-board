# SDD ledger — plan: n1-fix one-round fix (brief .superpowers/sdd/n1-fix/brief.md; plan docs/superpowers/plans/2026-11-09-remote-access.md)
Task 1: dispatched fixer (standard, sonnet), base 22f7de6
Task 1: bounced 1/2 (report lacked per-command output)
Task 1: re-review by redteam (frontier): A, C, doc, N2 addressed; R1 Critical (taller-than-pane fake frame), T1, T2 Important (uncaught mutations); out-of-scope O:*:No deny presses row 2
Ruling: fix the O:*:No deny match in this round though out of scope — it presses "Yes, and don't ask again" on deny, a Critical-class defect on the same code path — cost if wrong: a few extra lines in the round
Ruling: R1 is settled by one real Claude Code probe of multi-line preview indentation; if every preview line is indented, approve enforces it (column-1 line inside the rules → refuse) — cost if wrong: approve refuses some real prompts (fails closed)
Task 1: R1 probe (claude 2.1.321): every preview line indented; multi-line drawn " │ line"; fixture bash-multiline.txt
Ruling: R1 variant a11 (column-1 fake frame) is unreachable — a real preview never draws a column-1 line — so it is parked, with the column-1 refusal between the real rules as the enforced premise — cost if wrong: a future Claude Code that draws unindented preview lines reopens C/R1 (the probe fixture and the test would then be stale)
Ruling: multi-line --expect keeps the "│ " gutter as the pane shows it (no stripping); orchestrator step 3 says so — cost if wrong: the lead must type the gutter, a refusal (fails closed), not a wrong press
Task 1: fix round 2/5 (O1, T1, T2 fixed, R1 a11 parked unreachable; commits 375c175..5c9f6aa)
Task 1: re-review round 2 (redteam, 375c175..819868d): R1 (by ruling, own probe on 2.1.322 agrees), T1, T2, O1 ADDRESSED; 0 new Critical/Important
Task 1: minor (deferred): a11 ruling lives only in report/ledger, not a code comment; fixture README/comment cite 2.1.321 while 2.1.322 is installed
Task 1: minor (deferred): not probed — MCP/WebFetch prompts and teammate/subagent panes (refused unless they draw two ╌ rules: fails closed)
Task 1: note: redteam probe left a trust entry for a deleted scratch dir in ~/.claude.json
Task 1: complete (commits 22f7de6..819868d, 1 parked)
