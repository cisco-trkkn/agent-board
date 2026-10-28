---
name: "writing-plans-extras"
description: Local additions to superpowers-extended-cc:writing-plans. Use together with writing-plans, every time it runs, before drafting any task. It overrides three base rules. Step granularity follows each task's modelTier (frontier tasks get goal, constraints and acceptance criteria instead of code). Audit or discovery tasks are exempt from code in every step. The execution handoff never asks: it invokes subagent-driven-development (a printed kickoff prompt only when context is nearly exhausted). It also adds plan-content rules. e2e tasks check real, aged state; commit steps name the harness attribution trailer; copy-X steps name the differences; event consumers state delivery semantics; each Verify line matches its verifyCommand; plan-authored tests and snippets are run once by the author and name the mutation that fails them; external-tool values cite a probe; migrations, CI variables and runbooks state their gates and preconditions; security gates state the shape they accept and the bypasses tried; repeat-count runs time one iteration first.
---

# writing-plans extras

Load alongside `superpowers-extended-cc:writing-plans`. Where this file and the base skill disagree, this file wins; everything else in the base skill stands.

## 1. Granularity follows modelTier

How much a plan prescribes should match how capable its executor is. Scripted steps help a small model and hurt a frontier one, which does better with a goal and room to choose the method.

- `mechanical`: full steps with code, as the base skill says.
- `standard`: the base format, with code where the pattern is non-obvious.
- `frontier`: Goal, Constraints, Acceptance Criteria, Verify. No Steps block and no code. The executor chooses the method. "No Placeholders" does not apply; the acceptance criteria and the Verify line are the contract.

Example, a frontier task:

```
**Goal:** Reconnect a dropped worker session without losing its queue.
**Constraints:** no change to the queue file format; reconnect within 5s.
**Acceptance Criteria:** [ ] kill -9 on a worker, queue length unchanged after reconnect
**Verify:** `tests/e2e/reconnect.sh` → exit 0
```

## 2. Audit or discovery tasks

A security review, threat model or inventory cannot have its code written in advance. Write the task around its deliverable, a document with checkable structure, and the executor decides how to find the content.

- Name the output path.
- List the required sections or fields.
- Acceptance Criteria count and cover: "every route in `routes/` appears in the table", "each finding cites file:line".
- Verify is a command that checks that structure, e.g. `grep -c '^## ' report.md` against the expected number.

## 3. Execution handoff: never ask

Plans run without asking how. When the plan is complete, skip the `AskUserQuestion` in Execution Handoff in every session, watched or not, and invoke the Skill tool with `superpowers-extended-cc:subagent-driven-development`. In a `dev` session the agent-board plugin's `plan-handoff-guard.sh` hook refuses the question anyway; another hook quoting the handoff YAML does not change this.

The one exception is a session nearly out of context: print the base skill's Parallel Session kickoff prompt in a fenced block, name the plan path, and end the turn. A line before the fence says which execution skill the prompt invokes. Still no question.

## 4. e2e acceptance criteria use real state

A fresh scratch project hides every bug that needs accumulated state. Each e2e task carries at least one of these in its Acceptance Criteria and Verify:

- a read-only check against the user's existing long-lived state (real board, real logs, installed config);
- or a fixture aged past a day boundary and seeded with several agents or sessions.

Example: "the feed renders in order for a log that spans midnight" is verified by `feed --dry-run ~/.agent-board/log` (read-only), not by a log created five minutes ago.

## 5. Values the executor's environment supplies

When tasks route to different models, don't write a value that each executor's harness provides. Commit steps say "end with the attribution trailer your harness specifies", never a literal `Co-Authored-By: Claude <model>` line. A hardcoded line contradicts the trailer a Haiku or Sonnet teammate is told to use, and each one stops to ask or picks its own.

## 6. Steps that copy another component name the differences

A step that says "copy X's structure" (or "follow X's pattern") names each difference between X and the target that changes behaviour, or states that there are none, checked. A mechanism the spec fixes (auth mode, transport, entrypoint, storage) is quoted from the spec in the task's Acceptance Criteria, not inferred from X.

Example: a deploy task copied another layer's script, but the target layer had a Procfile that overrides `--function`; the spec's "IAM DB user" became the existing password-based connection helper in a sibling task. Both passed task review, because reviewers see the brief, not the spec.

## 7. Event and message consumers state their delivery semantics

For any task whose component consumes events or messages (Pub/Sub push, queues, webhooks), the Acceptance Criteria answer three questions, each with a test: what if two deliveries run concurrently, arrive out of order, or repeat? Typical answers are idempotence, a monotonic guard (version or timestamp), or an ordering key. Also compare the subscription's ack deadline with the handler's worst-case latency.

Example: "retire every other active snapshot" let a redelivered older message retire a newer snapshot. Six task reviews passed; only the final whole-branch review found the race.

## 8. Code the plan carries is run once by its author

A mechanical-tier executor copies plan code verbatim, so the plan's tests are the test suite and its snippets run as written.

- Next to each plan-authored test of a guard, branch or absence ("no call made", "nothing written"), name the mutation that makes it fail: "remove the shrink check → `test_truncated_file_is_reread` fails". The implementer's RED step runs that mutation and reports the failure. If no mutation can make the test fail, rewrite the assertion. Example: an absence check on `args[0]` of every mocked `subprocess.run` call could never fail, because `args[0]` was always the hook path.
- Before committing the plan, run each plan-authored check line and shell snippet once, in the agents' shell (zsh), against the current code. RED must fail for the stated reason, not for a missing builtin (`sh -c "print …"`: `sh` has no `print`). Bash idioms zsh breaks: `for f in $LIST` loops once over the whole string (use `${(f)LIST}` or `while read -r f`), and `${k:+--kind "$k"}` expands to one word (use an array, `kopt=(--kind "$k")` and `"${kopt[@]}"`).
- A safety check whose success means "no matches" also prints how many items it checked, so it cannot pass on an empty input.

## 9. Values from external tools cite a probe

A step that writes an external tool's variable, flag or hook context into code or config cites a one-line probe run in a scratch instance, with its output. Example: a plan wrote `#{hook_pane}` into an after-split-window hook and its tests; on tmux 3.8 it expands empty there, which only the implementer's real run showed.

## 10. Migrations, CI variables and runbooks state their gates

- Add/switch/remove migration of a config key: gate the remove step on the earliest state in which every remaining reader of the old value fails closed, and name that state. "After the new code is everywhere" is later than needed.
- A step that adds CI or project variables also runs the suites of every script that reads those keys, with the keys exported to dummy values, before the variables MR merges. A new variable reaches every later job, including test fixtures that copy `os.environ`.
- A task that writes a runbook lists each precondition with the command or file that creates it, or marks it as a human gate and says why it cannot be derived from source.

## 11. Security gates are specified by the shape they accept

For a task that specifies a security gate (an allowlist or deny list, a sandbox, a read-only wrapper around a CLI):

- State the gate as the exact form it accepts (`<group…> <verb> [<one arg>]`, with token shapes and a flag allowlist matched after normalising the flag name), never as "contains an allowed word and no denied word". The second form fails open for every bad word nobody listed.
- List the bypass attempts the plan's author tried, with their results: an unlisted write verb plus a read-verb positional, a flag whose separate value hides the verb, repeated or contradictory flags (last one wins), single- and double-dash spellings, quoting tricks and flag files.
- Check the ALLOWED list against the deny list for contradictions.
- Where the gate re-implements another tool's argv parsing, add one test that resolves each allowed argv with the real tool's parser (offline, e.g. `--help`), not only the gate's own model of it.

Example: a read-only gcloud wrapper built to "a read verb anywhere and no deny word" passed its own tests and allowed `gcloud storage rm gs://b/obj list`; after a structural fix, `--project list copy …` still hid the verb.

## 12. Repeat-count runs are sized and recorded per iteration

For a task that proves a fix by repeating a run N times (a flake count, a stress or soak run):

- Step 0 times one iteration under the same load. Size the time cap from that measurement, and split the count into chunks so no single call runs longer than about 30 minutes.
- Each iteration appends its result, a wall-clock timestamp and its duration to a tally file as it goes. The timestamps let a stall be lined up with sleep/wake lines (`pmset -g log`) at once.
- A non-pass iteration saves its full output and a process snapshot (`ps`), never only `tail -1`.
- A background load generator is started with its PID saved and killed in a `trap`, early stop included; afterwards its current child and any scratch tmux server or test process it left are killed by PID and checked with `ps`.
- Long runs keep the machine awake (`caffeinate -w <pid>`). `caffeinate` does not stop a closed laptop on battery from sleeping, so a run that must not stall stays on power with the lid open.

Example: 120 loaded runs at about 37 s each were given one 3600 s call; it timed out with no tally and left its load loop running for a day and a half. The retry kept only `tail -1` per iteration, so its two failures, during a sleep, had no output.

## Before you finish

Re-read the plan's tasks: every security gate is stated as an accepted shape with its tried bypasses, every repeat-count task sizes its cap from a timed iteration and records each iteration, every `frontier` task has no Steps block, every e2e task names a real-state or aged-fixture check, no commit step hardcodes a model attribution line, every "copy X" step names its differences, every consumer task answers the three delivery questions, every plan-authored guard test names its mutation, every snippet and external-tool value was run once, and the plan ends by invoking subagent-driven-development (or, with context nearly exhausted, a printed prompt), never a question.

Then check that each task's `**Verify:**` command is byte-identical to its json:metadata `verifyCommand`, or that the Verify line says "see verifyCommand". Two different commands give the executor two acceptance numbers. Mechanical check: extract both per task and diff them.
