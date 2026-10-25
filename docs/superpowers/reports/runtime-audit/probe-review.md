# Probe evidence review — runtime audit baseline 2026-10

Independent re-check of `report.md` at 58b77a1 (28 findings: 15 Verified, 12 Measured, 1 Hypothesis). Reviewer: probe, who authored none of Tasks 8–11. Read-only: raw transcripts under `~/.claude/projects/`, the live checkout `~/agent-board`, `audit-out/2026-10-25/` (toolkit c24ce6b) and `/tmp/claude-hooks/`. My scratch scripts reuse `tools/audit/transcripts.py` (same scope, same 30-day window) and live in the session scratchpad, not in the repo.

**Drift rule.** The json on disk and the live logs have grown since the figures in the report were taken. Where a figure differs I give the observed value; growth alone is not a drop. Typical drift seen: Stop events 2,378 → 2,405, skill-listing sessions 332 → 333, first-request median 34,016 → 34,024 (354 non-null), teammate agents 286 → 291, handoff docs 35 → 37.

**Sample (16 of 28) and why.** Every Verified finding in the top 5 (F-relay-2 is the only one; the others are Measured). The four other top-5 findings, because they set the roadmap order. The three findings that rest on `/tmp/claude-hooks` gate logs, which the task reviewer never re-checked (F-sieve-2, F-sieve-7, F-relay-4). Findings whose numbers feed the headline summary (F-relay-1, F-sieve-3, F-sieve-4). Verified findings with a file, path or ledger claim that can be falsified in one command (F-relay-9, F-relay-7, F-atlas-1, F-atlas-6, F-sieve-5). The one Hypothesis (F-sieve-8), to see if a quick probe could settle it.

**Gate-log status.** `/tmp/claude-hooks/user-gate-trace.log` and `wait-guard-trace.log` still exist (created 2026-10-15 01:08 local; 12,213 and 3,089 lines; last entry 2026-10-25T07:07Z, still growing). The report's counts are an exact snapshot of the log at about 2026-10-25T05:42Z: the 584th `pre-routing` pass is at 05:40:18Z and the 3,002nd `stop-revalidate` pass at 05:42:37Z. Reproducibility risk: the logs live in `/tmp`, are not copied into `audit-out/`, are unscoped (all projects, since 10-15, no session id on `pre-routing` lines) and are lost on a reboot or tmp cleanup. Recommend a snapshot copy next to `manifest.json` before Task 13 publishes.

### F-relay-2: The 300K guard is silent for agent-driven turns and for every teammate
Label: Verified
Evidence: `~/.claude/settings.json` registers `context-size-guard.sh` once, on `UserPromptSubmit` (python loop over `hooks`: one hit); `claude/plugin/hooks/hooks.json` has no entry. Lead `48822fd2`: first request at ≥300K is 2026-10-20T17:01:37Z (301,792; report 13:01:37 local); `CONTEXT AT` appears exactly 3 times, all `hook_system_message` attachments, at 17:12:00, 17:13:27 and 17:15:52Z, each directly after a typed prompt or `/handoff`. Teammate messages arrived at 17:10:35 and 17:11:15 with no warning. Teammates `984afea4` (peak 473,995) and `ddd65627` (peak 498,409): 0 `CONTEXT AT` in 1,523 and 883 lines. `session_metrics.json`: 13 `team:` agents with `peak_context` ≥ 300K (a 14th is a `sub:` agent), now of 291 team agents (report: 13 of 286). Lead turn-starters: 30 `<teammate-message>` user entries + 13 `<task-notification>` queued_command entries from agents (`a…` ids) + 3 typed + 1 `/handoff` + 2 shell lines (`bash-input`/`bash-stdout`) = 49; a 14th queued notification (id `b…`, a background shell task) is correctly not counted. Observed: all values match.
Confidence: high. The "why" (teammate messages do not raise `UserPromptSubmit`) is inferred from the absence of warnings, not from a hook-firing log, but the hook's own header says UserPromptSubmit and no counter-example exists in the three transcripts.
Verdict: holds

### F-sieve-1: The skill listing, not CLAUDE.md, is the largest controllable always-on item
Label: Measured
Evidence: `injection_costs.json` `attachment:skill_listing`: 333 sessions, median 31,218 chars (matches), total 11,735,775 (report 11,659,146, 332 sessions: drift). `first_request_prompt_tokens`: 354 non-null, median 34,024 (report 34,016 over 351). `static_files` sum 26,065 chars over 5 files (matches). `~/.claude/settings.json:43` `skillOverrides`: 16 `off`, 1 `name-only` (matches). Est. 31,218/4 = 7,804 tokens and 11.66M/4 = 2.9M follow from the chars. Competing sources by median chars: `prompt_snapshot` 126,633 is larger, but it is a record of the system prompt, and the snapshot I opened holds no skill text; `report.md:180` says so. Next after the listing: `hook_success` 9,481, `deferred_tools_delta` 9,102, `hook:SessionStart` 8,393. Observed: the ranking holds.
Confidence: med, as the report says; the token share rests on chars/4 and on `first_request_prompt_tokens` including non-controllable system prompt and tool schemas.
Verdict: holds

### F-relay-3: A quarter of lead requests and 39% of lead tokens run past the warning line
Label: Measured
Evidence: I re-derived from `transcripts.iter_events` (30 days, same two repos), `agent == main`, context = input + cache_read + cache_creation, de-duplicated by request id. Over the first 65 leads by first request: 7,149 requests of which 1,710 at ≥300K (23.9%), 33 sessions crossed; tokens 633,489,745 of 1,623,134,205 (39.0%). Report: 1,710 / 7,144 (23.9%), 633,489,745 / 1,621,855,199 (39.1%), 33 sessions. The numerator and session count match exactly; the denominators differ by 5 requests and 0.08% of tokens, from how I count a request (rounding-level). Handoff side: `handoff_trace.json` is from c24ce6b, not re-derived here beyond F-relay-2's sessions.
Confidence: high on the 23.9% and 33 sessions; the 39.1 vs 39.0 split is rounding.
Verdict: holds

### F-relay-12: The Opus lead's cost is turn count, not reasoning
Label: Measured
Evidence: `session_metrics.json` `48822fd2` `tokens_by_agent.main`: input 412, output 97,994, cache_read 37,323,187, cache_creation 256,016 = 37,677,609 tokens; output share 0.2601% (report 0.26%). Window `totals.by_agent_kind.main`: output 4,792,882 of 1,624,573,973 (input + output + cache_read + cache_creation) = 0.295% (matches); main holds 60.9% of all cache reads (matches), 60.2% of tokens. Turn-starter count 49 with 43 agent-sent reproduced (see F-relay-2). The "41% of the joined task" reproduces as 37,677,609 / 90,962,772 = 0.414.
Confidence: high on the numbers. The causal wording ("turn count, not reasoning") is an inference from 98.4% cache reads plus the agent-sent count; it is one session of 65, which the report itself says.
Verdict: holds

### F-sieve-3: The observer costs every session a little and each lead session a lot
Label: Measured
Evidence: `claude/hooks/task-observer-session-start.sh` run directly prints 1,378 chars (matches). task-observer `SKILL.md` (`~/.claude/plugins/synced/…/task-observer/SKILL.md`) is 44,715 bytes (matches). Skill calls naming task-observer in scope: 46 calls in 44 sessions now (report 45 in 44; one more lead call since): 30 `main` in 28 sessions, 16 teammate calls, all between 2026-10-16T05:20Z and 15:40Z. Commit 841282c (worker.md rule) is 2026-10-16 15:44Z-equivalent (11:44 -04:00), four minutes after the last teammate call; d73eca2 is 2026-10-20. `hook:SessionStart` 341 sessions (report 340). Est. 44,715/4 = 11,179 and ×45 = 503K reproduce.
Confidence: med, as stated (no per-call `tool_result` size).
Verdict: holds

### F-relay-1: In-session `orchestrator_share` overstates the lead's share of team work by ~2×
Label: Measured
Evidence: `session_metrics.json` `48822fd2` `orchestrator_share.value` 0.9487 (matches 0.949). Lead + 13 subagents + teammates `d34ef111`, `984afea4`, `ddd65627`, `947dde66`: total 90,962,772 tokens, main share 0.4142; output 629,778, main share 0.1556 (all match). Window `by_agent_kind` tokens main 60.2 / team 36.2; output main 38.4 / team 56.0 (report 56.1: rounding; the three kinds sum to 100.0).
Confidence: high.
Verdict: holds

### F-sieve-2: Two Stop hooks add about 2.1 s per Stop and have never blocked
Label: Measured
Evidence: re-read `stop_hook_summary` entries (same scope and window): 2,405 events (report 2,378). `superpowers-hook.sh stop-revalidate-user-gates.sh`: 2,234 runs, median 1,061 ms, max 14,236 (report 1,064 / 14,236 / 2,207). `stop-wait-guard.sh`: two command spellings, 572 + 1,662 = 2,234 runs, medians 1,084 and 979.5 ms (pooled about 1,038), max 11,934 (matches). `preventedContinuation` true on 0 of 2,405 events. Gate logs: `user-gate-trace.log` has 3,089 `stop-revalidate` pass lines now (3,002 at the report's snapshot, see header), 0 block; `wait-guard-trace.log` 3,089 lines, `grep -ci block` = 0. A third Stop hook, `revise-claude-md-nudge.py`, runs 2,016 times at median 115 ms, outside the finding's scope. Whether the two hooks run in parallel (1.04 s) or serially (2.1 s) is unmeasured, as stated.
Confidence: med (agree).
Verdict: holds

### F-sieve-7: Superpowers gates mostly sit idle; the routing gates are the only ones that block
Label: Measured
Evidence: uncapped count of `block` verdicts in `user-gate-trace.log` by gate (all 12,213 lines parsed, field 4): `pre-routing` 24, `pre-taskcreate-tier` 18, every other gate 0; total 42 (matches the report's 42). So the "only ones that block" claim holds on the full log. Other counts at the 05:42Z snapshot match; the live file is a few percent larger (pre-routing pass 592, pre-taskcreate-tier pass 228, pre-handoff not-armed 197, post-complete pass 150 / skip 395, commit-strategy skip 271). Observation #55 not re-opened.
Confidence: med (agree). The log is unscoped, so the 42 blocks include any project, not only the two in scope.
Verdict: holds

### F-relay-4: Routing gates work and fail safe; every observed block was a downgrade attempt that was corrected
Label: Verified
Evidence: block census from `user-gate-trace.log` (all 24 `pre-routing` blocks listed): 20 are `effort-mismatch … got=none` (the dispatch carried no effort pin at all), 2 are `effort-mismatch … got=low` where `medium` was required, 2 are `tier-mismatch … got=haiku` (lines 2870 and 7492). So only 4 of 24 are downgrade attempts; 20 are a missing effort pin, which is not a downgrade. The "1 error" is `trap-ERR` at 2026-10-16T02:11:38Z. "Each block followed by a pass within 0–278 s (one 9,703 s gap)": the log's `pre-routing` lines carry no session id, so "next pass" can be another session's; taking the next pass line, the gaps are 0–63 s for 16, then 278, 299, 315, 349, 393, 9,703 and 9,713 s. Six of 24 exceed 278 s and two exceed 9,000 s, not one. The 47/47 and 7/7 brief↔model regex was not re-run. The Task 11 replay of `48822fd2` 12:24:10 block → sonnet re-dispatch was not re-opened.
Confidence: high for the pass/block counts (584/24 at snapshot; 592/24 now); low for "every block was a downgrade … corrected", which the log cannot show.
Verdict: relabel Measured

### F-relay-9: The SDD rulings ledger — named "source of truth" — was deleted with the worktree
Label: Verified
Evidence: `~/.claude/handoffs/2026-10-20-docs-architecture-sdd-t3.md` and `-t9.md` each contain "source of truth" once (and t9 line 29 plans the SDD workspace deletion). `ls ~/agent-board/.claude/worktrees/docs-architecture` → No such file or directory (the only worktrees now are `docs-compose` and `runtime-audit`). `grep -rl "Ruling R" docs` → 0 files; `grep -rlE '\bR24\b' docs claude` → 0 files; `git log --all -S'Ruling R' -- docs` printed nothing. Observed: no copy of the ledger survives in the repo.
Confidence: high. I did not search outside the repo and `~/.claude`.
Verdict: holds

### F-sieve-4: Observer output is real but mostly staged, not live
Label: Verified
Evidence: `observation-log/` frontmatter: 25 `status: open`, 1 `parked`; `find ~/.task-observer/skill-observations -name '*.md' -path '*archive*'` → 59 files; 59 + 25 + 1 = 85 (matches). Live `~/.claude/skills/writing-plans-extras/SKILL.md` ends at `## 7` (line 59) and `## Before you finish` (line 65, 69 lines); the staged `skill-updates/2026-10-21/writing-plans-extras/SKILL.md` has sections 8 (line 65), 9 and 10. `scheduled-review.log` tail: "2026-10-23 09:02 scheduled review start (21 open)", "You've hit your weekly limit", "end (exit 1)"; `reviews/` has 2026-10-16 to 2026-10-21, nothing for 2026-10-23. Path corrections for the report: the awaiting-install index is `~/.task-observer/skill-updates/PENDING.md` and the log, `last-review-date.txt` and `reviews/` are under `~/.task-observer/skill-observations/`; `~/.task-observer/PENDING.md` does not exist. The "24 observations actioned on 10-21" figure was not recounted.
Confidence: high.
Verdict: holds

### F-relay-7: Lead→teammate messages are not delivered mid-turn; one went undelivered for 38 minutes
Label: Verified
Evidence: lead `SendMessage to: e2e` 2026-10-20T16:37:25.921Z, 1,169 chars, summary "Interview answers: all defaults accepted". Teammate `ddd65627`: one user entry at 17:15:56.847Z containing 2 `<teammate-message>` blocks, the interview answers and the "Handoff checkpoint request" the lead sent at 17:13:32Z; shutdown request at 17:16:47Z (51 s later). Latency 38 min 31 s. Teammate transcript spans 16:33:23–17:16:50Z. That the delivery came after the teammate's single turn ended also matches the batching of the two messages. One instance; the mechanism claim rests on it plus the t9 handoff doc's note.
Confidence: high for the instance; med for the general "not delivered mid-turn" rule (n = 1 teammate, 2 messages).
Verdict: holds

### F-atlas-1: Live install runs the "legacy" shared tmux server
Label: Verified
Evidence: `ls /private/tmp/tmux-503` lists 100+ sockets, none named `agent-board`; `tmux -L agent-board list-sessions` → "error connecting to /private/tmp/tmux-503/agent-board (No such file or directory)"; `tmux -L default list-sessions` lists the project sessions (`Desktop`, `Desktop-bg`, `_web-12074`). `~/.tmux.conf:69` and `:71` hold the `tmux-teammate-window` and `tmux-session-closed` hooks. `bin/_tc_bins.zsh:31-35` defines `tc_tmux_legacy`; `README.md:23` and `docs/ARCHITECTURE.md:9` describe a dedicated server; `ARCHITECTURE.md:259` documents legacy detection. All cited lines say what the report says.
Confidence: high.
Verdict: holds

### F-atlas-6: Handoff docs are still read and written at the legacy `~/.claude/handoffs/`
Label: Verified
Evidence: `ls ~/.claude/handoffs | grep -c .` → 37 (report 35; two more handoffs written since); `ls ~/.local/state/agent-board/handoffs` → No such file or directory; `docs/ARCHITECTURE.md:228` names `~/.local/state/agent-board/handoffs/<date>-<slug>.md` and says older docs in `~/.claude/handoffs/` are still read. `orchestrator.md:31` not re-opened. Note that the report's wording "written" at the legacy path rests on the 37 files, two of which postdate the report's count.
Confidence: med (agree).
Verdict: holds

### F-sieve-5: The same rule is written in 3–4 places for pkill and task-observer
Label: Verified
Evidence: uncapped grep. The pkill/killall rule: prose in `claude/orchestrator.md:132` and `claude/worker.md:43`; hook in `claude/hooks/kill-guard.sh:1-3` plus its copy `claude/plugin/scripts/kill-guard.sh:2-3` (4 places; the report cites the plugin copy without a path). task-observer: `orchestrator.md:64` and `:139`, `worker.md:15`, `task-observer-session-start.sh:10` (grep -c: 2 + 1 + 4 lines in the three files, and line 10 holds the mandate), plus the skill description in the listing. All lines cited exist and say what is claimed. Size: `orchestrator.md` is 16,256 bytes (report 16,221 chars; multibyte), `worker.md` 3,423 bytes (report 3,420). "No hook and no prose" for `git stash`: `grep -rn 'git stash' claude` → 0 lines (count 0); observation #86 exists, status open, dated 2026-10-25 and arose in this audit's own session.
Confidence: med (agree).
Verdict: holds

### F-sieve-8: hook_success may duplicate the SessionStart text in the transcript
Label: Hypothesis
Evidence: sizes now `attachment:hook_success` 351 sessions, 3,675,920 chars, median 9,481 (report 349 / 3,660,729 / 9,481); `hook:SessionStart` 341 / 2,930,275 / 8,393 (report 340 / 2,920,928 / 8,393). Probe on `48822fd2`: two `hook_success` entries with `hookEvent: SessionStart` (stdout 1,376 chars from `task-observer-session-start.sh` and 7,947 chars from the plugin `run-hook.cmd session-start`) and one `hook_additional_context` SessionStart attachment of 9,223 chars. Comparing 60-char windows of the additional context against the two stdouts: 20 of 153 windows in the first, 122 of 153 in the second, 142 of 153 in total (the rest differ by JSON escaping). So the same text is recorded twice in the transcript, in this session. Whether `hook_success` text also reaches the model request is still unmeasured, which is what the finding's impact line says.
Confidence: med for "recorded twice in the transcript" (one session); low for any token-cost effect.
Verdict: relabel Measured

## Summary

Sampled 16 of 28 findings, including F-relay-2, the only Verified finding in the top 5, and the other four top-5 findings.

| Verdict | Count | Findings |
|---|---|---|
| holds | 14 | F-relay-2, F-sieve-1, F-relay-3, F-relay-12, F-sieve-3, F-relay-1, F-sieve-2, F-sieve-7, F-relay-9, F-sieve-4, F-relay-7, F-atlas-1, F-atlas-6, F-sieve-5 |
| relabel | 2 | F-relay-4 → Measured; F-sieve-8 → Measured |
| drop | 0 | — |

Things to fix before publishing (none changes a ranking):
1. F-relay-4 headline: 20 of 24 blocks are a missing effort pin (`got=none`), 4 are downgrades; the gap claim "0–278 s, one 9,703 s gap" is wrong (6 of 24 exceed 278 s, 2 exceed 9,000 s) and the log has no session id, so "corrected" cannot be shown from it. The 584 / 24 counts are right.
2. F-sieve-4 paths: `~/.task-observer/skill-updates/PENDING.md`, and `~/.task-observer/skill-observations/{reviews,last-review-date.txt,scheduled-review.log}`.
3. F-sieve-8: one session shows the SessionStart text stored twice in the transcript (142 of 153 windows); say so and keep the model-request question open.
4. Gate-log reproducibility: snapshot `/tmp/claude-hooks/*.log` into `audit-out/` (or state the 05:42Z cutoff) because the logs are unscoped, in `/tmp`, and still growing.

Not re-checked: the other 12 findings; the 47/47 and 7/7 brief↔model regex; the `handoff_trace.json` figures (c24ce6b) beyond what F-relay-2 touches; observation #55; the a58d81b figures beyond the live-json reproductions above.
