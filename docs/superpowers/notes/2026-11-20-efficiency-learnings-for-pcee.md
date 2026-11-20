# Efficiency learnings for PCEE from a "Claude Code limits" video transcript

Source: one 9 KB YouTube transcript (untrusted, read as data). It has 11 usable claims. Checked locally: Claude Code 2.1.329 (`claude --help`, strings in the binary), our specs, `docs/superpowers/metrics/`.

- Its main point matches our own measurement: input re-read from cache is the cost, not what the model writes. In `runs.jsonl` (29 runs) cache reads are 97.5% of tokens and output 0.44%; the lead is 54% of tokens and 59% of dollars.
- Take: a rule for any output trimming (keep the failure whole, keep the full log reachable, judge by tokens per task with failures counted). Adapt: trim the failure text the engine hands back to a worker; trial Code Mode as a loop variant; record context size at job end; a spec-boundary fresh lead while the split queue lasts.
- Skip: "answer concisely" in CLAUDE.md, and the Caveman skill and its telemetry.
- Doubted or unchecked: Code Mode's scope ("terminal only", "one variable set to one"), the Caveman and reset facts, the 99% status-line saving.

Our numbers (all from `docs/superpowers/metrics/runs.jsonl`, `kind: run`, 29 records; `tasks.jsonl`, 176 tasks):

| Measure | Value |
|---|---|
| Tokens: cache read / cache write / output / fresh input | 1,600M / 34M / 7.3M / 0.025M of 1,641M total (97.5% / 2.1% / 0.44% / 0.0%) |
| Lead vs agents, tokens | 879M vs 762M (lead 53.6%) |
| Lead vs agents, dollars | $293.93 vs $208.11 (lead 58.5%); median per-run `lead_share` 0.636, range 0.364 to 0.961 (n=29) |
| Reviews inside tasks | $45.02 of $92.90 task dollars (48.5%); 61 of 176 tasks needed at least one fix round |
| Lead handoffs | 28 across 29 runs |
| Runs with a limit reading (`limits.start` or `limits.record`) | 16 of 29 |

## Take / adapt

### 1. Trim output only by the "say nothing" rule, and judge it by tokens per task (take)

- **Claim:** "With the setup that cut the most, Claude read 38.4 percent fewer tokens of tool output, and the bill went up 6.8 percent" (PointFive, about 3,000 runs, API prices); "you cut the lines that say nothing, and you keep the failure whole"; shrink "keeps the full output too, so Claude can ask for the part it cut".
- **We today:** no output trimming exists. `tmux-ctl run` writes the full capture to a log file and returns its tail (`bin/tmux-ctl` run case, the `grab`/`logf` code near lines 397-415; the "returns only the tail" gotcha in the shared context). The engine returns a red check's output to the implementer as a bounce (engine design §3, line 209) with no size rule.
- **Applies to PCEE:** yes, as a guard on every later trimming change, ours or the loop's.
- **Change:** one acceptance rule in the improvement loop spec (`2026-11-16-supervised-improvement-loop-design.md`): a proposal that shrinks what a worker reads is trialled on tokens per task plus fix rounds and bounces per task, with failed tasks kept in the denominator. This is the same rule as ECC insight 8 in `2026-11-20-ecc-insights-for-pcee.md`; the new part is the reason (cutting too much makes the agent re-read and re-run, so the bill can rise).
- **Gain:** protects against a loss rather than adding a saving. Unmeasured; no trimming trial exists.
- **Risk:** none beyond a few lines of spec.
- **Verdict:** take.

### 2. Bound the failure text the engine hands back (adapt)

- **Claim:** "Three hundred passing tests and one failing, and the output came to about sixty-two hundred tokens ... shrink took those sixty-two hundred tokens down to two hundred ninety-three"; "a hook that returns only the error lines of a log takes it from tens of thousands of tokens down to hundreds".
- **We today:** the engine runs the green check itself, so code, not a model, reads the full output; the bounce carries "the output" (engine design line 209) with no cap. A worker running tests in its own session reads whatever `tmux-ctl run` returns (tail, `claude/worker.md` lines 41-46). Hooks in `claude/plugin/hooks/hooks.json` only mirror and guard; none rewrites tool results.
- **Applies to PCEE:** yes, for the bounce only. A bounce re-enters a worker's context and is then re-read on every later turn of that worker.
- **Change:** in engine design §3 (green check and bounce): the bounce text is the failing test names, their errors and the summary line, plus the path of the full log; a cap in lines is a constant in the strategy file. Do not add a hook that rewrites commands for interactive agents now; the transcript's own source says even a measured trimmer is an estimate until run on real work.
- **Gain:** unmeasured. We have no record of tool-result bytes per job; the statusline tap and the job events could add "bounce bytes" to measure it (engine events, `detail`).
- **Risk:** a cut that removes the line the worker needs; mitigated by the full-log path and by item 1's trial.
- **Verdict:** adapt.

### 3. Trial Code Mode as a loop variant, not a default (adapt)

- **Claim:** "Anthropic shipped something like it on November twelfth. It's called Code Mode. Claude writes code that calls its tools, and only the result comes back"; "one user ... reported fourteen percent of the five-hour limit without it, and five percent with it. That's one run each."
- **We today:** not used. `~/.claude/settings.json` `env` has no such variable. Local check: `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE` is a string in the 2.1.329 binary (found with `strings`, also the phrase "Code Mode"), so the switch exists in our version.
- **Applies to PCEE:** partly. Our gates are `PreToolUse` and `PostToolUse` hooks (`claude/plugin/hooks/hooks.json`: dispatch gate, kill guard, spawn record, bash mirror). Whether those fire for a tool call made from inside Code Mode code is unchecked here; if they do not, the gates are bypassed.
- **Change:** do nothing in the engine specs. In the loop spec's variant list (`variants` on the run record), allow `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1` as a trial on one low-risk job kind (mechanical-tier implementers), after one real check that the hooks still fire (a probe note like `2026-11-19-teammate-probes.md`).
- **Gain:** unmeasured; the only figure is one run each way, so not evidence.
- **Risk:** experimental flag, hook bypass, the trimmed tool output can hide what a reviewer needs; a probe first.
- **Verdict:** adapt (probe, then trial).

### 4. Record context size at the end of each job (adapt)

- **Claim:** "To see what's in your own conversation, type slash context"; "watch ... how much of the ring one finished feature takes, not how many tokens went by".
- **We today:** `claude/hooks/context-size-guard.sh` already reads the latest main-thread usage (input + cache read + cache write) and warns at 300,000 tokens, once per 50K band. The slash commands `context`, `usage`, `clear` and `compact` exist in 2.1.329 (strings). We record limit readings on only 16 of 29 runs (`limits` null on the rest, all listed as `missing`).
- **Applies to PCEE:** yes. The engine's "tokens per task" (decomposition K2) needs a per-job number that says how big the worker's context got, to tell a long context from a chatty one. Today the 97.5% cache-read share cannot be split by job kind.
- **Change:** engine design §1 events: when a job ends, write `context_tokens` (the same transcript read as the guard, one function shared) and the limit-ring reading when it exists. Fix the limit gap in the run record rather than adding a new measure.
- **Gain:** a measurement, not a saving. It makes items 2 and 3 measurable.
- **Risk:** low; the guard's transcript read is a `tail -n 400` of a JSONL, cheap.
- **Verdict:** adapt.

### 5. Fresh session at a spec boundary for today's lead (adapt)

- **Claim:** "ending the conversation" is the cut that cannot go wrong: "Say checkout works now, and you ask for a receipt email in the same chat ... that short message goes out with the eight test runs, the server log and the product list. But if you start a new session instead, the receipt task starts without them."
- **We today:** the engine does this by design: disposable workers and a code-driven lead replacement (decomposition lines 195-197, "an always-on Opus lead is 48 to 74% of each spec's cost, almost all re-reading its own context"; engine design lines 60-66). Today's lead handles one queue in one long session; 28 handoffs in 29 runs, triggered by the context guard (`claude/orchestrator.md` handoff section), not by a spec boundary.
- **Applies to PCEE:** the engine already covers it. The gap is the split-queue period ("half the specs under the lead", engine design Decisions): the lead half keeps paying for old specs' context.
- **Change:** in `claude/orchestrator.md` queue mode: hand off to a fresh lead after each spec merges, before the next spec's plan, instead of waiting for the 300K guard. The handoff skill already exists. Not a spec change; a rule for the lead during the split.
- **Gain:** the lead is 53.6% of tokens (measured above). How much shorter handoffs per spec would make it is unmeasured; the baseline `lead_share` ranges 0.364 to 0.961 and the run with the lowest share is the evidence to look at. Check the handoff count per run against `lead_share` first.
- **Risk:** each handoff costs a doc write plus the new lead re-reading it; the lead's rulings and parked state must survive in the doc (the existing skill handles it).
- **Verdict:** adapt.

### 6. Limit MCP connectors in workers (adapt)

- **Claim:** "When Claude asks the Stripe connector for your products, the whole raw answer goes into the conversation. That's every field of every product, even if Claude only needed three prices."
- **We today:** unmeasured. Workers started by `tmux-ctl agent` get whatever MCP servers the user's settings load. `claude --help` has `--strict-mcp-config` with `--mcp-config` and `--tools` (lines 131-257 of the help), so a worker can start with none. Nothing in `claude/worker.md` or `claude/orchestrator.md` mentions MCP.
- **Applies to PCEE:** yes, for engine workers: a job's tool list is a function of the job kind, and a job that never needs a connector should not load its schemas or take its raw results.
- **Change:** engine design §3 job table: a per-kind column `tools` and `mcp` passed to the backend's `start` (tmux backend: the flags above). Look first at one real worker's `/context` to see whether connector schemas are a measurable share; if not, drop the item.
- **Gain:** unmeasured.
- **Risk:** a job that needs a tool it was denied stalls; start with allow-by-default and deny only measured offenders.
- **Verdict:** adapt (measure first).

## Already done or skip

### 7. Whole conversation re-sent each request; caching cheaper, not free (already done)

- **Claim:** "It sends the whole conversation so far ... Caching does make the repeated part cheaper, but it doesn't make it free."
- **We today:** this is the premise of the engine: 97.5% of our tokens are cache reads; the Problem section of the engine design and decomposition line 85 say the same, with 12 baseline specs.
- **Verdict:** already done. Nothing to add; the new figure is above (lead 53.6% of tokens in 29 runs).

### 8. Tiered models and effort (already done)

- **Claim (implicit):** the video says nothing on model choice; its measured advice is "answer concisely" and shrinking output. Noted only because the brief asks for model choice, effort and subagents.
- **We today:** tier-to-model map and enforced effort (`docs/superpowers/model-routing.json`, `claude/orchestrator.md` lines 130-153); fresh subagents per task. Fable's measured value is in the memory note `fable-routing-worth-it.md` (review and verification, not rendering or dedup).
- **Verdict:** already done.

### 9. Compact is not free (already done)

- **Claim:** "compact ... swaps the conversation for a summary of it. That one isn't free. To write the summary, the model has to read the whole conversation again."
- **We today:** `~/.claude/settings.json` has `autoCompactEnabled: true` and a `precomputeCompactionEnabled` key; `claude --autocompact <auto|tokens>` exists. Long-lived agents are replaced by handoff, not compacted (`claude/orchestrator.md` handoff section; `context-size-guard.sh` restarts its warning "after /compact").
- **Applies to PCEE:** no change; disposable workers never need it. Whether `precomputeCompactionEnabled` removes the extra read is unchecked.
- **Verdict:** already done.

### 10. "Answer concisely" in CLAUDE.md (skip)

- **Claim:** ten prompts: about 7,000 reply tokens with no instruction, about 4,300 with "answer concisely", about 4,100 with the caveman voice.
- **We today:** no such line in `~/.claude/CLAUDE.md`, the repo `CLAUDE.md` or `claude/worker.md` (grep of "concis", "brief" found only unrelated lines). Our output is 7.3M of 1,641M tokens (0.44%). Output tokens cost more each than cache reads, so the dollar share is higher than 0.44%; I did not compute it (needs per-model prices) and mark it unmeasured.
- **Verdict:** skip. Even a 40% cut of 0.44% of tokens is below the noise of the K2 comparison. Revisit only if a priced breakdown shows output above about 10% of dollars.

### 11. Caveman, its trial estimator and telemetry (skip)

- **Claim:** the Caveman skill, its `shrink` command, `trial` (an estimate from one recorded session) and default usage telemetry ("caveman telemetry off").
- **We today:** `docs/superpowers/metrics/` measures real runs against a baseline (`seq-sdd`), which is stronger than a one-session estimate. The ECC note's rule applies: take ideas, install nothing third-party into a project that runs engine workers (`2026-11-20-ecc-insights-for-pcee.md`, prompt-injection section).
- **Verdict:** skip.

## Claims I doubt or could not check

- **"Code Mode ... only runs in the terminal for now, not in the desktop app or VS Code"; "one environment variable ... set to one".** Partly checked: a variable named `CLAUDE_CODE_EXPERIMENTAL_CODE_MODE` and the words "Code Mode" are in the 2.1.329 binary. The value, the terminal-only limit, whether connectors are covered and the "November twelfth" date are unchecked. The transcript hedges the connector part itself.
- **"14 percent ... five percent".** One run each way, by the transcript's own account; not evidence. Unchecked.
- **"Each update now costs about ninety-nine percent less" (background-helper status line).** An upstream fix; the 2.1.329 changelog is not in the repo. Unchecked.
- **Caveman "has about a hundred and twenty thousand stars ... more than Google's Gemini CLI"; "everybody on a paid plan one free reset".** Not checkable from local files and not relevant to PCEE. Unchecked.
- **"Anthropic doesn't publish how cached tokens count against Pro or Max limits."** Consistent with what we found: nothing in the repo or help says. Our own limit readings exist for 16 of 29 runs, so we cannot yet calibrate tokens against the ring either (item 4).
- **"Slash clear ... costs nothing."** `clear` exists in the binary; the cost claim is unchecked. After a clear the next request writes a new cache prefix, so "nothing" is likely "a small cache write".
- **Outdated for current Claude Code?** I found nothing in the transcript that contradicts 2.1.329: `/context`, `/usage`, `/clear`, `/compact` all exist as command names in the binary. Command bodies were not run.

## Suggested next step for the lead

Items 1, 2 and 4 are spec edits of a few lines each (loop spec acceptance rule, engine §3 bounce cap, engine events). Item 3 needs a probe (do our `PreToolUse` gates fire under Code Mode) before anything else. Item 5 is a rule change in `claude/orchestrator.md`. Item 6 needs one `/context` look at a real worker first.
