# Sieve: hooks, always-on context, observer (Task 9)

Window 2026-09-26..2026-10-25, toolkit a58d81b. Read-only audit. Sources: `~/.claude/settings.json`, enabled plugins, `agent-board/claude/plugin/hooks/hooks.json`, `audit-out/2026-10-25/injection_costs.json` (cited as `IC`), `~/.task-observer` (frontmatter and review files only).

Scope rule for every transcript-derived count below (Stop events, Skill calls, tool calls): the toolkit's rule in `tools/audit/transcripts.py` (`in_repo`, `window_start`): a line counts when its `cwd` (last seen `cwd` in the file if the line has none) is `master-gcp-repo`, `agent-board`, or a worktree under their `.claude/worktrees/`, and its timestamp is within 2026-09-26..2026-10-25. Command: `python3 -I scope.py` (scratchpad script reusing `transcripts.candidate_files`, `in_repo`, `window_start`; it reads every line of the files with `tools/audit/transcripts.py`'s per-line filter and counts `tool_use` name `Skill` by `input.skill` and `subtype == stop_hook_summary` by `hookInfos[].command`). An earlier draft of this report read whole files with no per-line filter and gave 54/52 skill calls and 2,601 Stop events; those figures are withdrawn. Counts from `/tmp/claude-hooks/*.log` are not scoped by repo or window: the logs start 2026-10-15 and are labelled "trace" where used.

Method notes:
- Token figures marked "est." are chars/4 (derived), never measured.
- Runtime probes use `/usr/bin/time -p`, 3 runs, dummy stdin, scratch dir. The harness floor for `bash -c true` is 0.15 s, so subtract it: raw seconds are shown with the floor-adjusted figure in brackets.
- Stop-hook runtimes are not probes: they are `durationMs` from `stop_hook_summary` events in the transcripts (2,378 `stop_hook_summary` events).
- Per-hook PreToolUse/PostToolUse durations and counts are not recorded in `IC`; those cells say `unmeasured`.

## Mechanisms

### Hook count (recorded command)

```
python3 - <<'PY'
import json,os
H=os.path.expanduser
ip=json.load(open(H('~/.claude/plugins/installed_plugins.json')))
en=json.load(open(H('~/.claude/settings.json')))['enabledPlugins']
files=[H('~/.claude/settings.json'),H('~/.claude/settings.local.json')]
for k,v in ip.get('plugins',ip).items():
    if en.get(k): files.append(v[0]['installPath']+'/hooks/hooks.json')
files.append('/Users/francisco.ruiz/agent-board/claude/plugin/hooks/hooks.json')
tot=0
for f in files:
    if not os.path.exists(f): print(f,'absent'); continue
    n=sum(len(g.get('hooks',[])) for gs in json.load(open(f)).get('hooks',{}).values() for g in gs)
    print(f,n); tot+=n
print('TOTAL',tot)
PY
```

Output:

```
settings.json 10 | settings.local.json absent | superpowers-extended-cc 6.5.3-dev 5
gitlab: no hooks.json | claude-security 0.11.0 3 | claude-md-management: no hooks.json
agent-board claude/plugin/hooks/hooks.json 4
TOTAL 22
```

Also checked and not counted: `claude/session-settings.json` has env and teammateMode only, no hooks. `~/.claude/hooks/*.sh` are symlinks into `agent-board/claude/hooks/` (same files, not extra hooks). Stale plugin cache versions are not loaded (`installed_plugins.json` points at one version each).

Table: 22 hook rows (H1-H22) plus 2 observer rows (O1-O2) = 24 rows. Columns: trigger, frequency, implementation, context cost, runtime, purpose, outcome, failure behaviour, overlap. All hooks are scripts; none calls a model.

| ID | Hook (source line) | Trigger | Frequency | Impl. | Context cost | Runtime | Purpose | Outcome | Failure behaviour | Overlap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | task-observer-session-start.sh (settings.json:68) | SessionStart | `IC hook:SessionStart` 340 sessions, count median 1, max 2 (key is shared with H11) | script | probe output 1,378 chars (est. 345 tokens); shared key median 8,393 chars | probe 0.26 s [0.11 s] | Inject the observer mandate, workspace path, open count | Makes every lead invoke the skill (see O1) | none: always prints JSON; `find` errors hidden (`task-observer-session-start.sh:8`) | orchestrator.md:64, :139; worker.md:15; skill description |
| H2 | revise-claude-md-nudge.py (settings.json:79) | Stop | 1,991 runs in scope (`scope.py`); blocks once per session at 40+ tool calls: 3 "Long session" blocks recorded in `hookErrors` | script | block reason is 3 events; no `IC` key (`attachment:hook_blocking_error` 2 sessions, 1,008 chars, not attributable). unmeasured, needs per-hook output size | measured from transcripts: median 115 ms, max 2,200 ms (in scope). Probe not run: writes a marker (`revise-claude-md-nudge.py:45`) | Prompt a CLAUDE.md revision after long sessions | 3 blocks in 2,184 runs | fail-open: bad JSON, no transcript return 0 (`:23-:40`) | none found |
| H3 | superpowers-hook.sh stop-revalidate-user-gates.sh (settings.json:84) | Stop | 2,207 runs in scope (`scope.py`); trace log (unscoped, since 10-15): 3,003 enter, 3,002 pass, 0 block | script (dispatcher then bash) | no block output seen: 0 chars; blocks 0 | measured: median 1,064 ms, max 14,236 ms (in scope). Probe not run: writes `/tmp/claude-hooks/user-gate-trace.log` | Block "plan complete" claims when a user-gate task has no evidence | never fired | exit 0 when plugin not found (`superpowers-hook.sh:57`) | post-task-complete-revalidate (H8) covers the same gates at close time |
| H4 | superpowers-hook.sh stop-wait-guard.sh (settings.json:88) | Stop | 2,207 runs in scope; `wait-guard-trace.log` (unscoped) 0 block lines | script | 0 observed | measured: median 1,038 ms, max 11,934 ms (in scope). Probe not run: trace writes | Stop a turn that ends on a wait during plan execution | never fired | fail-open on read errors (script header) | none live (an orchestrator.md rule 3 on waiting is staged in the 10-21 round, not installed) |
| H5 | context-size-guard.sh (settings.json:98) | UserPromptSubmit | `IC hook:UserPromptSubmit` 34 sessions, median 3 per session, max 7 | script (jq) | 63,395 chars total, median 1,752 chars per session | probe against the largest main transcript (13.5 MB): 0.11-0.25 s [about 0.1 s] | Warn at 300K context, point at /handoff | 34 of 357 sessions warned | exits 0 when no transcript (`context-size-guard.sh:7`) | handoff skill + orchestrator.md:31 describe the restart |
| H6 | bash-mirror.sh (settings.json:110) | PostToolUse Bash, async | one per Bash call: 11,193 Bash tool_use events (parser count) | script (zsh + python) | none (silent) | unmeasured, writes feed logs | Mirror Bash calls into the tests/shell window feeds | n/a | always exit 0 (`bash-mirror.sh:87`) | duplicate of H20 in agent-board sessions |
| H7 | artifact-register.sh (settings.json:121) | PostToolUse Write/Edit/MultiEdit/Artifact, async | one per matching call: Write 419, Edit 505, Artifact 12 | script | none | unmeasured, appends jsonl | Register plans, specs, handoffs for the board | n/a | always exit 0 (`artifact-register.sh:99`) | duplicate of H21 |
| H8 | superpowers-hook.sh post-task-complete-revalidate.sh (settings.json:132) | PostToolUse TaskUpdate | up to 431 TaskUpdate calls; trace: 389 skip, 145 pass, 0 block | script | 0 observed | unmeasured, trace writes | Re-validate closed user-gate tasks | never blocked | exit 0 when plugin not found | H3 |
| H9 | bash-mirror.sh (settings.json:143) | PostToolUseFailure Bash, async | failed Bash calls only; count unmeasured, needs failure count | script | none | unmeasured | Same as H6 for failed calls | n/a | exit 0 | H22 |
| H10 | kill-guard.sh (settings.json:156) | PreToolUse Bash | 11,193 Bash calls | script (bash + python) | on a block only: 2 blocks have ever reached transcripts via `attachment:hook_blocking_error` (not attributable) | probe, no pkill in command: 0.23 s [0.08 s]; with `AGENT_BOARD=1` dedupe-exit: 0.17 s [0.02 s] | Refuse pkill/killall that would hit Claude processes | blocks counted: unmeasured, needs PreToolUse block counter | fail-open on any error (`kill-guard.sh:94`) | orchestrator.md:132, worker.md:43; H19 |
| H11 | superpowers session-start (hooks.json SessionStart, matcher startup/clear/compact) | SessionStart | same key as H1; also re-fires on clear and compact (`IC` count max 2) | script | probe output 7,973 chars (est. 1,993 tokens): using-superpowers body (4,737 chars file) + routing notice | probe 0.57 s [0.42 s] | Inject using-superpowers and the routing notice | Skill-first rule in every session | none observed | CLAUDE.md:3-8 companion rule; skill_listing |
| H12 | pre-taskcreate-model-tier (hooks.json PreToolUse TaskCreate) | PreToolUse TaskCreate | 222 TaskCreate calls; trace: 222 pass, 18 block | script | block message only | unmeasured, trace writes | Require modelTier in plan tasks | 18 blocks | fail-open by design (script header) | orchestrator.md:85-94 states the same rule |
| H13 | pre-taskcreate-commit-strategy | PreToolUse TaskCreate | trace: 265 skip, 0 block | script | 0 | unmeasured | Enforce at-end commit strategy | dormant (no workflow.json found) | fail-open | session-start workflow notice |
| H14 | pre-agent-model-routing | PreToolUse Agent | 388 Agent calls; trace: 584 pass, 24 block | script | block message only | unmeasured | Match Agent model/effort to task tier | 24 blocks (one false block: observation #55) | fail-open on unresolvable | H11 notice, orchestrator.md:85-94 |
| H15 | pre-askuser-handoff-guard | PreToolUse AskUserQuestion | 187 calls; trace: 194 not-armed | script | 0 | unmeasured | Force the plan handoff question shape | never armed | fail-open | writing-plans skill text |
| H16 | claude-security hooks.sh banner (hooks.json UserPromptExpansion) | UserPromptExpansion, matcher `^claude-security:claude-security$` | only when that skill is invoked; count unmeasured | script | 1 banner message when python3 is old | unmeasured | Warn about python3 version | n/a | prints nothing on success | none |
| H17 | claude-security hooks.sh metrics (PostToolUse Bash) | PostToolUse Bash | 11,193 Bash calls | script (sh + python) | none; stdout empty for non-scan commands | probe: 0.28 s [0.13 s] | Telemetry for scan helper scripts | no output on normal commands | stderr discarded, exit 0 (`hooks.sh:4-9`) | H6, H10 and H19 also spawn on every Bash call |
| H18 | claude-security hooks.sh metrics (PostToolUseFailure Bash) | PostToolUseFailure Bash | failed Bash calls | script | none | same as H17 | same | none | same | H9 |
| H19 | agent-board plugin kill-guard.sh --scoped (plugin hooks.json PreToolUse Bash) | PreToolUse Bash | 11,193 Bash calls, agent-board sessions only | script | as H10 | as H10 | Same guard, scoped registration | runs the check when `--scoped` | as H10 | exact duplicate of H10 (global copy exits at `kill-guard.sh:5`) |
| H20 | agent-board plugin bash-mirror.sh --scoped (PostToolUse Bash, async) | PostToolUse Bash | as H6 | script | none | unmeasured, writes feed logs | as H6 | as H6 | as H6 | duplicate of H6 |
| H21 | agent-board plugin artifact-register.sh --scoped (PostToolUse Write/Edit/MultiEdit/Artifact, async) | PostToolUse | as H7 | script | none | unmeasured, appends jsonl | as H7 | as H7 | as H7 | duplicate of H7 |
| H22 | agent-board plugin bash-mirror.sh --scoped (PostToolUseFailure Bash, async) | PostToolUseFailure Bash | as H9 | script | none | unmeasured | as H9 | as H9 | as H9 | duplicate of H9 |
| O1 | task-observer skill, protocol run at session start | invoked by the model after H1 | 45 Skill calls in 44 sessions, in scope (`task-observer:task-observer` 29, `task-observer` 16); 29 calls in 28 lead sessions (of 65 lead sessions with a main request; 67 if sessions with a main prompt but no main request are counted), 16 calls in 16 teammate sessions | model plus inline shell | SKILL.md 44,715 chars (est. 11,179 tokens) per call; its references (500,758 chars total) unmeasured, needs per-call tool_result sizes | unmeasured | Scan the log, offer review, write observations | 85 observations (see Observer value) | skipped silently if the model ignores H1 | H1, orchestrator.md:64, worker.md:15 |
| O2 | scheduled weekly review (launchd `com.user.task-observer-review`) | cron | runs 2026-10-16 (3), 10-19, 10-21, 10-23 | model (headless Claude) | not in transcripts scope; unmeasured, needs usage of the headless run | unmeasured (`scheduled-review.log` records only the 10-21 end time, 11:55) | Triage observations, stage skill patches | see Observer value | 10-23 run died on the weekly usage limit, exit 1 (`scheduled-review.log`) | none |

The 4 entries of `claude/plugin/hooks/hooks.json` are H19-H22.

Table row count: 24 (22 hook rows + O1, O2) vs 22 hook entries counted. The check passes (24 ≥ 22).

## Always-on context

`IC first_request_prompt_tokens` (357 rows, source measured): 351 non-null, 6 null (no main or team request). Median of the 351 non-null values is 34,016 tokens (my computation; the shared context quotes about 33.6K, so treat it as the same figure within rounding). Lead sessions (65): median 52,300. Teammate sessions (286): median 33,802.

`IC static_files` (chars measured, tokens est. = chars/4):

| File | Chars | Tokens (est.) | Who receives it |
| --- | --- | --- | --- |
| `~/.claude/CLAUDE.md` | 2,672 | 668 | every agent |
| `master-gcp-repo/CLAUDE.md` | 2,405 | 601 | sessions in that repo |
| `agent-board/CLAUDE.md` | 1,347 | 337 | sessions in that repo |
| `claude/orchestrator.md` | 16,221 | 4,055 | lead (orchestrator) |
| `claude/worker.md` | 3,420 | 855 | teammates |
| Sum | 26,065 | 6,516 | never all at once |

A lead in agent-board carries about 20,240 chars (est. 5,060 tokens) of static text; a teammate about 7,439 chars (est. 1,860 tokens).

Largest injected sources per session (`IC sources`, median chars per session, all measured):

| Key | Sessions | Median chars | Total chars |
| --- | --- | --- | --- |
| `attachment:skill_listing` | 332 | 31,218 (est. 7,800 tokens) | 11,659,146 |
| `attachment:deferred_tools_delta` | 331 | 9,102 | 3,404,897 |
| `attachment:deferred_tools_record` | 328 | 8,264 | 3,449,696 |
| `hook:SessionStart` | 340 | 8,393 (est. 2,100 tokens) | 2,920,928 |
| `attachment:instructions` | 299 | 4,739 | 1,902,567 |
| `attachment:mcp_instructions_delta` | 329 | 3,968 | 1,681,267 |
| `attachment:hook_success` | 349 | 9,481 | 3,660,729 |
| `attachment:prompt_snapshot` | 348 | 126,633 | 50,236,444 |

The skill listing alone (31,218 chars median) is larger than all five static files together (26,065 chars), and 7.8 times the two CLAUDE.md files a lead reads in agent-board (31,218 / 4,019 chars; `~/.claude/CLAUDE.md` 2,672 + `agent-board/CLAUDE.md` 1,347). `skillOverrides` in `settings.json:43` already turns off 16 skills and sets one to name-only, so a trimming mechanism exists and is in use.

Superpowers loading, read from `hooks/session-start` and `hooks.json`: Superpowers injects the full `using-superpowers` skill text via the SessionStart hook (matcher `startup|clear|compact`), not via a file the model reads. The probe of that hook printed 7,973 chars. Other skills load on demand through the Skill tool; the companion skills load as separate Skill calls (counts in scope, `scope.py`: test-driven-development 83, its extras 65; requesting-code-review 26, extras 22; writing-plans 23, extras 16, from tool_use `Skill` inputs).

## Overlap matrix

Rule × where it is enforced. "Hook" means a script that blocks or injects; "prose" means instruction text only.

| Rule | `~/.claude/CLAUDE.md` | orchestrator.md | worker.md | Skill | Hook |
| --- | --- | --- | --- | --- | --- |
| Never pkill/killall by pattern | no | line 132 (prose) | line 43 (prose) | no | kill-guard (H10, H19) blocks it |
| Task-observer: lead runs the protocol, teammates do not | no (moved out, per review 2026-10-21) | lines 64, 139 | line 15 | skill description says invoke before first tool call | H1 injects the rule (and exempts teammates in its text) |
| Load `-extras` with the base skill | lines 3-8 | no | no | each extras skill says "use together with" | none |
| Task modelTier / model routing | no | lines 85-94 | no | writing-plans, SDD | H11 notice + H12, H14 gates |
| 300K context, handoff | no | line 31 (starting from a handoff) | no | handoff skill | H5 warns |
| Report with evidence | no | line 123 | line 55 | verification-before-completion | H3, H8 for user-gate tasks only |
| Ask via AskUserQuestion shape | no | line 47 | line 22 (answer it yourself) | writing-plans | H15 |
| Do not stash/reset in shared worktrees | no | no | no | none | none (observation #86 shows this was violated; see F-sieve-5) |

## Observer value

Counts come from the YAML frontmatter only (`status`, `date`, `type`) of `observation-log/*.md` and `observation-log/archive/*.md`.

- Total 85 observation files. Status: 59 `actioned` (all in `archive/`), 25 `open`, 1 `parked`. The log did not exist before 2026-10-16, so the whole population falls in the window.
- By date: 10-16: 32, 10-17: 5, 10-19: 12, 10-20: 16, 10-21: 13, 10-22: 2, 10-23: 3, 10-25: 2. Type: 62 open-source, 23 internal.
- 11 of the 85 are carriers (file name contains `carrier`): records that exist to hold the remainder of a split observation.
- Reviews (`reviews/*/REVIEW.md`): 2026-10-16 (three runs), 2026-10-19, 2026-10-21. The 2026-10-23 directory has scripts but no REVIEW.md, and `scheduled-review.log` shows that run ended with "You've hit your weekly limit" and exit 1.
- What the reviews changed: 10-19 staged 18 observations into the three `-extras` skills (new checks and sections 6-7); that round was installed on 2026-10-20 (`PENDING.md`). 10-21 staged 24 observations: `requesting-code-review-extras`, `test-driven-development-extras`, `writing-plans-extras` (sections 8-10), `gitlab-ci-loop` code fixes with tests, `fix-merge-conflicts`, `tmux-orchestrator`, and patches to `claude/orchestrator.md`, the handoff skill, `task-observer-session-start.sh` and `bin/claude-config-link`.
- "Actioned" means staged, not live. `PENDING.md` says the 10-21 round is "awaiting install", and the live `writing-plans-extras` skill ends at section 7 (headings read from `~/.claude/skills/writing-plans-extras/SKILL.md:49-65`), so sections 8-10 are not in effect.

Cost side (all from this report's measurements):
- Every session pays H1's text: 1,378 chars (est. 345 tokens).
- Each invocation loads SKILL.md: 44,715 chars (est. 11,179 tokens). 45 invocations is about 2.0 M chars (est. 503K tokens) over the window; this is derived from file size, not from measured tool_result sizes.
- 16 of the 45 invocations are in teammate sessions (all on 2026-10-16, 01:20-11:40, all under the bare skill name `task-observer`). They predate the exemption text in the hook (commit d73eca2, 2026-10-20 11:28) and the worker.md rule (commit 841282c, 2026-10-16 11:44); see F-sieve-3. No teammate session in scope calls it after 10-16 11:40.
- Reference files (500,758 chars) load only if the protocol opens them: unmeasured.
- The weekly review runs a headless model; its usage is not in the transcript scope: unmeasured.

Judgement: the observer produced 59 actioned observations and three completed review rounds in 10 days, so value is visible. The per-lead-session cost is roughly a third of the 34K median first request again on top of it, and half of lead sessions pay it. Whether the staged changes help is not yet measurable because the biggest round is not installed.

## Findings

### F-sieve-1: The skill listing, not CLAUDE.md, is the largest controllable always-on item
Label: Measured
Evidence: IC `attachment:skill_listing` 332 sessions, median 31,218 chars, total 11,659,146; IC `static_files` sum 26,065 chars; IC `first_request_prompt_tokens` median 34,016 (351 non-null)
Component: skill_listing injection · Root cause: every installed skill's name and description is listed in each session, and descriptions are long (the observer and extras descriptions run to several lines) · Impact: about 7,800 tokens (est., chars/4) of a 34K first request; the CLAUDE.md files are 668+337 tokens (est.)
Confidence: med (token share is an estimate) · Candidate change: set more `skillOverrides` entries to `name-only` or `off`, and shorten the longest descriptions · How to validate: re-run `injection_costs.py` and compare `skill_listing` median chars and first-request median

### F-sieve-2: Two Stop hooks add about 2.1 s per Stop (1,064 + 1,038 ms) and have never blocked
Label: Measured
Evidence: `stop_hook_summary` durationMs: in scope (`scope.py`, 2,378 Stop events): stop-revalidate median 1,064 ms (max 14,236, 2,207 runs); stop-wait-guard median 1,038 ms (max 11,934, 2,207 runs); `/tmp/claude-hooks/user-gate-trace.log` (unscoped, since 10-15) 3,002 pass, 0 block; `wait-guard-trace.log` 0 block lines
Component: H3, H4 (settings.json:84-88 via superpowers-hook.sh) · Root cause: both are registered globally and scan the transcript on every Stop, but only act when a plan or user-gate is in play (`stop-wait-guard.sh` is armed only after executing-plans) · Impact: up to 2.1 s per Stop if the two run one after the other; whether they run in parallel is unmeasured, needs a wall-clock Stop timer. No blocking benefit seen in the window logs, which start 2026-10-15
Confidence: med · Candidate change: register them only in sessions that run executing-plans, or short-circuit on a cheap marker before scanning the transcript · How to validate: compare Stop `durationMs` before and after, and keep the trace block counts

### F-sieve-3: The observer costs every session a little and each lead session a lot; the teammate calls pre-date the exemption
Label: Measured
Evidence: probe of `task-observer-session-start.sh` output 1,378 chars; `~/.claude/plugins/synced/.../task-observer/SKILL.md` 44,715 chars; in scope (`scope.py`): Skill `task-observer:task-observer` 29 + `task-observer` 16 = 45 calls in 44 sessions, 29 calls in 28 lead sessions (65 lead sessions with a main request), 16 calls in 16 teammate sessions, all 16 dated 2026-10-16 01:20-11:40; IC `hook:SessionStart` 340 sessions
Component: H1, O1 · Root cause: (a) Verified: the hook asks for a full skill load plus a protocol run before the first tool call, and the skill body is 44.7K chars. (b) Verified: the live hook already carries the teammate exemption (`claude/hooks/task-observer-session-start.sh:10`, "a teammate or subagent dispatched by a lead session ... does not run the protocol"; added in commit d73eca2, 2026-10-20 11:28; working tree clean). The earlier hook (`~/.claude/hooks/task-observer-session-start.sh.bak-20261019`) has no such text, and `worker.md` gained its "don't invoke task-observer" rule in commit 841282c (2026-10-16 11:44). (c) Verified: all 16 teammate calls fall on 2026-10-16 between 01:20 and 11:40, before both of those commits, and none occurs afterwards in scope; so the 16 calls are not evidence that the exemption is ignored today. (d) Hypothesis: before 10-20 the mandate was the "Task observer" block in `~/.claude/CLAUDE.md` (backup `CLAUDE.md.bak-20261019:1-16`), which every teammate also reads; the same backup's line 10 carries the teammate exception, but the backup's mtime is 10-16 13:31, after the calls, so whether that exception existed at 01:20-11:40 is unknown. (e) Hypothesis: the 12 teammate sessions from 09:52 on (and the 4 earlier ones) read the global block without the exception; a trigger path through the skill description ("invoke before the FIRST tool call of any session") is a second candidate, since 10-16 teammates called the bare name `task-observer`, not the plugin name · Impact: est. 11,179 tokens per invocation, 45 invocations, est. 503K tokens over the window (derived from file size); reference-file loads and the headless review job are unmeasured, needs per-call tool_result sizes and headless usage
Confidence: med · Candidate change: make the hook output a short protocol stub and load the full SKILL.md only when a review or write is due. The staged observation #41 change (worker condition on `TC_ROLE=worker`, `grep -c TC_ROLE` on the live hook = 0) would add a second exemption path; it is not needed to explain the 16 calls · How to validate: count task-observer Skill calls in teammate sessions in the next window (expected 0 after 10-16 11:40; the current scope shows 0); compare `hook:SessionStart` median

### F-sieve-4: Observer output is real but mostly staged, not live
Label: Verified
Evidence: frontmatter counts: 59 actioned (archive), 25 open, 1 parked, 85 total; `PENDING.md` "One round awaiting install: 2026-10-21"; live `~/.claude/skills/writing-plans-extras/SKILL.md` headings end at section 7 (lines 49-65) while review 2026-10-21 staged sections 8-10; `scheduled-review.log` 2026-10-23 run ended "You've hit your weekly limit", exit 1, no `reviews/2026-10-23/REVIEW.md`
Component: O2, install step · Root cause: staging and installing are separate manual steps (installer defaults to a dry run), and the scheduled run shares the user's usage limit · Impact: the 24 observations actioned on 10-21 have no effect on live skills yet; the 10-23 review is missing. Value delivered so far: the 10-19 round only (18 observations)
Confidence: high · Candidate change: apply the 10-21 round or drop it, and give the review job a retry or a separate budget · How to validate: re-read the live skill headings and `last-review-date.txt` after the next run

### F-sieve-5: The same rule is written in 3-4 places for pkill and task-observer
Label: Verified
Evidence: pkill: `claude/orchestrator.md:132`, `claude/worker.md:43`, `claude/hooks/kill-guard.sh:1-3` (and its copy in `claude/plugin/scripts/`); task-observer: `claude/orchestrator.md:64` and `:139`, `claude/worker.md:15`, `task-observer-session-start.sh:10`, the skill description in the listing
Component: orchestrator.md, worker.md, hooks · Root cause: rules are added to prose first and a hook later, and the prose is not removed (observations are routed to orchestrator.md patches, for example 10-21 review) · Impact: duplicated text in a 16,221-char orchestrator prompt and a 3,420-char worker prompt; exact token share unmeasured, needs per-rule char counts. Observation #86 (shared worktree git stash by a parallel teammate) shows a rule with no hook and no prose that was violated
Confidence: med · Candidate change: keep the hook for hard rules and drop the prose copy, add a one-line stash rule where it was violated · How to validate: diff orchestrator.md and worker.md after the change; check observation log for repeats of #86

### F-sieve-6: In agent-board sessions every Bash and Write call spawns duplicate hook processes
Label: Measured
Evidence: `settings.json:110-156` registers kill-guard, bash-mirror, artifact-register globally; `claude/plugin/hooks/hooks.json` registers the same three with `--scoped`; global copies exit at `kill-guard.sh:5`, `bash-mirror.sh:14`, `artifact-register.sh:32` when `AGENT_BOARD=1` (set in `claude/session-settings.json`); probe dedupe-exit 0.17 s vs 0.15 s floor; Bash tool_use 11,193, Write 419, Edit 505
Component: H6, H7, H9, H10 and H19-H22 · Root cause: the global registration is kept for non-board sessions and defers by environment variable instead of being skipped by the harness · Impact: about 0.02 s per duplicate (floor-adjusted), 3 extra process spawns per Bash call; small, no tokens
Confidence: high on the duplication, low on the impact · Candidate change: leave as is unless Bash-heavy sessions show wall-clock cost; if so, register only one set · How to validate: PreToolUse/PostToolUse durations (not recorded now, needs a hook timer)

### F-sieve-7: Superpowers gates mostly sit idle; the routing gates are the only ones that block
Label: Measured
Evidence: `/tmp/claude-hooks/user-gate-trace.log` (11,898 lines, since 2026-10-15): pre-routing 584 pass, 24 block; pre-taskcreate-tier 222 pass, 18 block; pre-taskcreate-commit-strategy 265 skip, 0 block; pre-handoff 194 not-armed; post-complete 145 pass, 389 skip, 0 block; stop-revalidate 0 block. Observation #55: the routing gate read the metadata field instead of the fence and blocked a valid frontier dispatch
Component: H8, H12-H15 · Root cause: the gates are generic and dormant unless a project opts in; the two active ones enforce what the routing notice (H11) already states · Impact: 42 blocks, of which at least one was a false block (#55). Runtime of these gates is unmeasured, needs PreToolUse durations
Confidence: med · Candidate change: keep the routing gates, review whether H13, H15 and H3/H8 are needed in this setup · How to validate: count blocks and false blocks per gate over the next window

### F-sieve-8: hook_success may duplicate the SessionStart text in the transcript
Label: Hypothesis
Evidence: IC `attachment:hook_success` 349 sessions, 3,660,729 chars, median 9,481 per session, count median 2; IC `hook:SessionStart` 340 sessions, 2,920,928 chars, median 8,393
Component: hook output handling · Root cause: unknown; the two keys have similar sizes, which suggests the same hook output is recorded as both a hook_success attachment and hook additional context · Impact: unmeasured, needs a check of whether `hook_success` text reaches the model request (compare against `prompt_snapshot` or first-request tokens)
Confidence: low · Candidate change: none until confirmed · How to validate: take one session, diff its `hook_success` content with its `hook:SessionStart` content, and test whether first-request tokens change when the observer hook is disabled in a scratch run
