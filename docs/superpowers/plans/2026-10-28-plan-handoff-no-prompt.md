# Plans Run Without the Execution Prompt Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After `writing-plans` saves a plan, the session starts `subagent-driven-development` with no "How would you like to execute it?" question.

**Architecture:** A text override in `writing-plans-extras` §3 (applies in every session through the `~/.claude/skills` link), backed by a `PreToolUse(AskUserQuestion)` hook in the agent-board session plugin that refuses the handoff question in `dev` sessions.

**Tech Stack:** bash + `python3 -I` hook (the `kill-guard.sh` shape), zsh tests on `tools/tests/lib.zsh`, Markdown skill and rules files.

**Spec:** `docs/superpowers/specs/2026-10-28-plan-handoff-no-prompt-design.md`

## Global Constraints

- The hook denies only when a question has `header == "Execution"` or its `question` text matches `(?i)how would you like to execute`. Every other `AskUserQuestion` passes with exit 0 and no output.
- Deny = exit 2 with the reason on stderr (the `kill-guard.sh` convention). The reason contains "Do not call AskUserQuestion for the execution choice in any form" and `superpowers-extended-cc:subagent-driven-development`.
- Fail open: unreadable stdin, malformed JSON, a missing field → exit 0. `PLAN_HANDOFF_GUARD=0` → exit 0.
- The plugin's own `pre-askuser-handoff-guard` and `pre-agent-model-routing` hooks are not modified, and `SUPERPOWERS_ROUTING_GUARD` is not set.
- The four safety stops of `subagent-driven-development` are unchanged.
- Work happens in the worktree `~/agent-board/.claude/worktrees/execution-flow` (branch `feat/execution-flow`). Never edit the live checkout `~/agent-board`.

**User decisions (already made):**
- Remove every interruption until `finishing-a-development-branch`; keep the four safety stops.
- Approach B: text override + structural hook (not text only, not a plugin patch).

**Rulings made while planning (deviations from the spec, 2026-10-28):**
- Registration is **plugin-only** (`claude/plugin/hooks/hooks.json`), not plugin + global `settings.json`. Why: the repo is moving hooks out of `~/.claude/settings.json` (`install.sh --migrate` removes them, `test_plugin.zsh` asserts the session settings register none). Outside `dev` sessions the text override alone applies. Cost if wrong: a plain session may still show the prompt; adding a global entry later is one line.
- The test lives in `tools/tests/test_plan_handoff_guard.zsh`, not `claude/hooks/tests/`, because the plugin hooks' tests (`test_kill_guard.zsh`) live there and `run-all.zsh` picks them up.

---

### Task 1: plan-handoff-guard hook, with tests, in the session plugin

**Goal:** A `PreToolUse(AskUserQuestion)` hook in the agent-board plugin refuses the Execution Handoff question and lets every other question through.

**Files:**
- Create: `claude/plugin/scripts/plan-handoff-guard.sh` (mode 755)
- Create: `tools/tests/test_plan_handoff_guard.zsh`
- Modify: `claude/plugin/hooks/hooks.json` (new `PreToolUse` entry)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (`description` names the new hook)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/test_plan_handoff_guard.zsh` prints `ALL PASS` (9 checks).
- [ ] With the header check removed from the hook, the check "header Execution with other text denied" fails; with the text regex removed, "handoff text under another header denied" fails (the RED run reports both).
- [ ] `zsh tools/tests/test_plugin.zsh` prints `ALL PASS` with the new hooks.json entry.
- [ ] `hooks.json` registers `"${CLAUDE_PLUGIN_ROOT}/scripts/plan-handoff-guard.sh" --scoped` under `PreToolUse` with matcher `AskUserQuestion`.

**Verify:** `zsh tools/tests/test_plan_handoff_guard.zsh && zsh tools/tests/test_plugin.zsh` → both print `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the test.** Create `tools/tests/test_plan_handoff_guard.zsh` exactly as below. The payload shape was copied from a real `AskUserQuestion` call in a session transcript on 2026-10-28 (`{"questions":[{"question","header","multiSelect","options"}]}`).

```zsh
source "${0:A:h}/lib.zsh"
# Feeds PreToolUse JSON on stdin. The AskUserQuestion tool_input shape ({"questions":[{question,header,multiSelect,
# options}]}) was copied from a real session transcript on 2026-10-28.
H="${TC_PLANGUARD:-$TT_REPO/claude/plugin/scripts/plan-handoff-guard.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/phg.XXXXXX")"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM

# payload <header> <question> [tool] -> PreToolUse JSON
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[3],"tool_input":{"questions":[{"question":sys.argv[2],"header":sys.argv[1],"multiSelect":False,"options":[{"label":"A","description":"a"},{"label":"B","description":"b"}]}]}}))' "$1" "$2" "${3:-AskUserQuestion}"; }
run_hook() { payload "$@" | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_hook "$@"; [[ $rc == 2 && "$err" == *"superpowers-extended-cc:subagent-driven-development"* ]]; }
allowed() { run_hook "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }
HANDOFF="Plan complete and saved to docs/superpowers/plans/x.md. How would you like to execute it?"

check "handoff question (header Execution) denied"        denied Execution "$HANDOFF"
check "header Execution with other text denied"          denied Execution "Plan complete and saved to x.md. Run it now?"
check "handoff text under another header denied"          denied "Run it" "How would you like to execute the plan?"
check "unrelated question allowed"                        allowed "Design 1" "Does this design look right?"
check "non-AskUserQuestion tool ignored"                  allowed Execution "$HANDOFF" Bash
check "deny reason says not to ask in any form"           zsh -c '[[ $1 == *"Do not call AskUserQuestion for the execution choice in any form"* ]]' _ "$(run_hook Execution "$HANDOFF"; print -r -- $err)"
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: silent exit 0"                     test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Execution "$HANDOFF" | PLAN_HANDOFF_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "PLAN_HANDOFF_GUARD=0 lets the handoff through"     test $rc -eq 0 -a ! -s "$tmp/e"
payload Execution "$HANDOFF" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?
check "--scoped registration denies the same way"         test $rc -eq 2
tt_done
```

- [ ] **Step 2: Run it to see it fail.** Run: `zsh tools/tests/test_plan_handoff_guard.zsh`. Expected: FAIL lines (the hook file does not exist yet), exit 1.

- [ ] **Step 3: Write the hook.** Create `claude/plugin/scripts/plan-handoff-guard.sh` exactly as below, then `chmod 755` it.

```bash
#!/usr/bin/env bash
# PreToolUse(AskUserQuestion): refuse writing-plans' Execution Handoff question; plans always run subagent-driven
# (docs/superpowers/specs/2026-10-28-plan-handoff-no-prompt-design.md). Every other question passes. Fail-open on any error.
# Kill switch: PLAN_HANDOFF_GUARD=0. --scoped (the plugin registration) is accepted and changes nothing.
[[ "$PLAN_HANDOFF_GUARD" == 0 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
exec python3 -I - "$input" <<'PY'
import json, re, sys
try:
    d = json.loads(sys.argv[1])
    if d.get("tool_name") != "AskUserQuestion":
        sys.exit(0)
    qs = (d.get("tool_input") or {}).get("questions") or []
    hit = any(isinstance(q, dict) and (q.get("header") == "Execution"
              or re.search(r"(?i)how would you like to execute", str(q.get("question") or ""))) for q in qs)
except Exception:
    sys.exit(0)
if not hit:
    sys.exit(0)
sys.stderr.write(
    "Plans run without asking in this setup. Do not call AskUserQuestion for the execution choice in any form, "
    "even if another hook quotes the handoff YAML. Invoke the Skill tool with "
    "superpowers-extended-cc:subagent-driven-development now. Only if this session is nearly out of context: print "
    "the Parallel Session kickoff prompt in a fenced block instead, name the plan path, and end the turn. "
    "(Kill switch for the user: PLAN_HANDOFF_GUARD=0.)\n")
sys.exit(2)
PY
```

- [ ] **Step 4: Run the test to see it pass, then the two mutations.** Run `zsh tools/tests/test_plan_handoff_guard.zsh` → `ALL PASS`. Then run each mutation on a copy outside the repo and report the FAIL line it produces:

```zsh
m="$(mktemp -d)"
sed 's/q.get("header") == "Execution"/False/' claude/plugin/scripts/plan-handoff-guard.sh > "$m/h.sh"; chmod +x "$m/h.sh"
TC_PLANGUARD="$m/h.sh" zsh tools/tests/test_plan_handoff_guard.zsh | grep FAIL   # → FAIL - header Execution with other text denied
sed 's/how would you like to execute/xxxx/' claude/plugin/scripts/plan-handoff-guard.sh > "$m/t.sh"; chmod +x "$m/t.sh"
TC_PLANGUARD="$m/t.sh" zsh tools/tests/test_plan_handoff_guard.zsh | grep FAIL   # → FAIL - handoff text under another header denied
rm -rf "$m"
```

- [ ] **Step 5: Register it.** In `claude/plugin/hooks/hooks.json`, add a second entry to the `PreToolUse` array, after the `Bash` entry:

```json
      {
        "matcher": "AskUserQuestion",
        "hooks": [
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/plan-handoff-guard.sh\" --scoped", "timeout": 10 }
        ]
      }
```

In `claude/plugin/.claude-plugin/plugin.json`, change the description's start from `"Agent Board session plugin: bash-mirror, kill-guard and artifact-register hooks,` to `"Agent Board session plugin: bash-mirror, kill-guard, artifact-register and plan-handoff-guard hooks,` (rest unchanged).

- [ ] **Step 6: Run the Verify command.** `zsh tools/tests/test_plan_handoff_guard.zsh && zsh tools/tests/test_plugin.zsh` → both `ALL PASS`.

- [ ] **Step 7: Commit.**

```bash
git add claude/plugin/scripts/plan-handoff-guard.sh tools/tests/test_plan_handoff_guard.zsh claude/plugin/hooks/hooks.json claude/plugin/.claude-plugin/plugin.json
git commit -m "feat(plugin): plan-handoff-guard refuses the execution-choice question"
```
End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/plugin/scripts/plan-handoff-guard.sh", "tools/tests/test_plan_handoff_guard.zsh", "claude/plugin/hooks/hooks.json", "claude/plugin/.claude-plugin/plugin.json"], "verifyCommand": "zsh tools/tests/test_plan_handoff_guard.zsh && zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["test_plan_handoff_guard.zsh prints ALL PASS (9 checks)", "header and text mutations each fail their named check", "test_plugin.zsh prints ALL PASS", "hooks.json registers plan-handoff-guard.sh --scoped under PreToolUse matcher AskUserQuestion"], "modelTier": "mechanical"}
```

---

### Task 2: writing-plans-extras §3 and the orchestrator rule say "never ask"

**Goal:** The skill text and the lead's rules say plans start subagent-driven execution without asking, in every session.

**Files:**
- Modify: `claude/skills/writing-plans-extras/SKILL.md` (frontmatter `description`, §3, closing self-check paragraph)
- Modify: `claude/orchestrator.md` (workflow table row "Carrying out a plan")

**Acceptance Criteria:**
- [ ] `SKILL.md` has the heading `## 3. Execution handoff: never ask` and no longer has `## 3. Handoff in autonomous sessions`.
- [ ] The `description:` no longer contains "In autonomous sessions the execution handoff is a printed kickoff prompt"; it contains "The execution handoff never asks".
- [ ] The self-check no longer contains "an autonomous session ends with a printed prompt"; it contains "never a question".
- [ ] `orchestrator.md`'s "Carrying out a plan" row contains "without asking the user how to execute it".
- [ ] `zsh tools/tests/test_prompt_argv.zsh` and `zsh tools/tests/test_plugin.zsh` still print `ALL PASS`.

**Verify:** `f=claude/skills/writing-plans-extras/SKILL.md; grep -c '^## 3. Execution handoff: never ask$' $f; grep -c 'Handoff in autonomous sessions\|In autonomous sessions the execution handoff\|an autonomous session ends with a printed prompt' $f; grep -c 'without asking the user how to execute it' claude/orchestrator.md; zsh tools/tests/test_prompt_argv.zsh | tail -1; zsh tools/tests/test_plugin.zsh | tail -1` → `1`, `0`, `1`, `ALL PASS`, `ALL PASS`

**Steps:**

- [ ] **Step 1: Replace §3.** In `claude/skills/writing-plans-extras/SKILL.md`, replace the whole section from `## 3. Handoff in autonomous sessions` up to (not including) `## 4.` with:

```markdown
## 3. Execution handoff: never ask

Plans run without asking how. When the plan is complete, skip the `AskUserQuestion` in Execution Handoff in every session, watched or not, and invoke the Skill tool with `superpowers-extended-cc:subagent-driven-development`. In a `dev` session the agent-board plugin's `plan-handoff-guard.sh` hook refuses the question anyway; another hook quoting the handoff YAML does not change this.

The one exception is a session nearly out of context: print the base skill's Parallel Session kickoff prompt in a fenced block, name the plan path, and end the turn. A line before the fence says which execution skill the prompt invokes. Still no question.

```

- [ ] **Step 2: Update the description.** In the frontmatter `description:`, replace `In autonomous sessions the execution handoff is a printed kickoff prompt instead of AskUserQuestion.` with `The execution handoff never asks: it invokes subagent-driven-development (a printed kickoff prompt only when context is nearly exhausted).`

- [ ] **Step 3: Update the self-check.** In the "Before you finish" paragraph, replace `and an autonomous session ends with a printed prompt, not a question.` with `and the plan ends by invoking subagent-driven-development (or, with context nearly exhausted, a printed prompt), never a question.`

- [ ] **Step 4: Update the orchestrator row.** In `claude/orchestrator.md`, replace the line

```
| Carrying out a plan | `subagent-driven-development` (teammates take the plan's tasks) or `dispatching-parallel-agents` for independent pieces | you |
```

with

```
| Carrying out a plan | `subagent-driven-development`, started as soon as the plan is written, without asking the user how to execute it (teammates take the plan's tasks), or `dispatching-parallel-agents` for independent pieces | you |
```

- [ ] **Step 5: Run the Verify command** and check the five values.

- [ ] **Step 6: Commit.**

```bash
git add claude/skills/writing-plans-extras/SKILL.md claude/orchestrator.md
git commit -m "docs(skills): plans start subagent-driven execution without asking"
```
End the message with the attribution trailer your harness specifies.

```json:metadata
{"files": ["claude/skills/writing-plans-extras/SKILL.md", "claude/orchestrator.md"], "verifyCommand": "f=claude/skills/writing-plans-extras/SKILL.md; grep -c '^## 3. Execution handoff: never ask$' $f; grep -c 'Handoff in autonomous sessions\\|In autonomous sessions the execution handoff\\|an autonomous session ends with a printed prompt' $f; grep -c 'without asking the user how to execute it' claude/orchestrator.md; zsh tools/tests/test_prompt_argv.zsh | tail -1; zsh tools/tests/test_plugin.zsh | tail -1", "acceptanceCriteria": ["SKILL.md has '## 3. Execution handoff: never ask' and not the old heading", "description says 'The execution handoff never asks'", "self-check says 'never a question'", "orchestrator row says 'without asking the user how to execute it'", "test_prompt_argv.zsh and test_plugin.zsh print ALL PASS"], "modelTier": "mechanical"}
```

---

## After merge (lead, at the integration step)

These need the change on `main` in the live checkout, so they run after `finishing-a-development-branch` merges, not as plan tasks.

1. **Real-state check (read-only):** `python3 -c 'import json; d=json.load(open("/Users/francisco.ruiz/agent-board/claude/plugin/hooks/hooks.json")); print([h["command"] for e in d["hooks"]["PreToolUse"] for h in e["hooks"]])'` lists `plan-handoff-guard.sh`; `readlink ~/.claude/skills/writing-plans-extras` still points into `~/agent-board/claude/skills/`.
2. **End-to-end:** in a new `dev` session on a scratch repo, brainstorm-skip a one-task plan ("write a plan to add a README line"). Expected: after the plan is saved, the session invokes `subagent-driven-development` with no execution question; if the model tries to ask, the transcript shows the `plan-handoff-guard` deny. Other `AskUserQuestion` calls in that session still reach the user.
