# Lead Named Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dev lead can never start a hidden background agent: every Agent call it makes must carry a `name` (so it opens in a `✦` window), forks are refused, and the lead rules say so.

**Architecture:** `bin/claude-orchestrator` exports `AGENT_BOARD_LEAD=1` into the lead's own process only (not the tmux session environment). A new PreToolUse(Agent) plugin hook, `agent-name-guard.sh`, registered after `sdd-call-guard.sh`, denies (exit 2) an unnamed or fork Agent call when that marker is set. Two bullets in `claude/orchestrator.md` state the rule and the spawn-failure fallback.

**Tech Stack:** bash + `python3 -I` (hook), zsh (launcher, tests via `tools/tests/lib.zsh`), JSON (plugin hooks).

**Spec:** `docs/superpowers/specs/2026-11-09-lead-named-agents-design.md`

## Global Constraints

- Marker: `AGENT_BOARD_LEAD=1`, exported by `bin/claude-orchestrator` before `exec claude`; NEVER passed to `tc_tmux set-environment` (teammates, `tmux-ctl agent` workers and `bin/claude-overseer` must not inherit it).
- Guard: `claude/plugin/scripts/agent-name-guard.sh`, executable. `AGENT_NAME_GUARD=0` → allow; `AGENT_BOARD_LEAD` not `1` → allow; `tool_name` not `Agent` → allow; deny (exit 2, reason on stderr, nothing on stdout) when `tool_input.name` is missing, not a string, or blank after trimming, or `tool_input.subagent_type == "fork"`; any parse/runtime error → allow.
- Registration: `claude/plugin/hooks/hooks.json`, PreToolUse entry `"matcher": "Agent"`, AFTER `sdd-call-guard.sh`, command `"\"${CLAUDE_PLUGIN_ROOT}/scripts/agent-name-guard.sh\" --scoped"`, `"timeout": 10`.
- Deny reason ends with `(Kill switch for the user: AGENT_NAME_GUARD=0.)`.
- Tests: targeted files only (named in each Verify). NEVER run `tools/tests/run-all.zsh` or any full suite (user rule).
- Shared worktree `.claude/worktrees/lead-named-agents`: stage only your own paths (`git add <paths>`), no whole-tree git operations.
- Commit messages: conventional with scope; end with the attribution trailer your harness specifies.

**User decisions (already made):**
- No exemptions: every Agent call a dev lead makes must carry a `name`, read-only helpers (Explore, web-fetch, claude-code-guide) included.
- Integration: merge to `main` locally, no push.

---

### Task 1: agent-name-guard hook script with unit tests

**Goal:** `claude/plugin/scripts/agent-name-guard.sh` denies unnamed and fork Agent calls in a dev lead and allows everything else, with a zsh unit test.

**Files:**
- Create: `claude/plugin/scripts/agent-name-guard.sh` (mode 755)
- Create: `tools/tests/test_agent_name_guard.zsh`

**Acceptance Criteria:**
- [ ] With `AGENT_BOARD_LEAD=1`: name missing, `""`, `"  "`, `7`, `null` → exit 2 with the reason on stderr and empty stdout; a named `subagent_type: "fork"` → exit 2.
- [ ] Named Explore call, non-Agent tool, non-object `tool_input`, malformed JSON → exit 0, no output.
- [ ] Marker unset or `0`, or `AGENT_NAME_GUARD=0` → unnamed call allowed silently.
- [ ] Mutations fail the stated checks (Step 2).

**Verify:** `zsh tools/tests/test_agent_name_guard.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Write the test** — create `tools/tests/test_agent_name_guard.zsh` with exactly:

```zsh
source "${0:A:h}/lib.zsh"
# agent-name-guard: PreToolUse(Agent) hook that, in a dev lead (AGENT_BOARD_LEAD=1), denies an Agent call with no name
# or a fork. Payloads are synthetic hook JSON in the PreToolUse shape.
H="${TC_AGENTNAMEGUARD:-$TT_REPO/claude/plugin/scripts/agent-name-guard.sh}"
tmp="$(mktemp -d "${TMPDIR:-/tmp}/ang.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT INT TERM

# payload <tool_name> <tool_input-json> -> PreToolUse JSON
payload() { python3 -c 'import json,sys; print(json.dumps({"tool_name":sys.argv[1],"transcript_path":"/nonexistent","cwd":"/tmp","tool_input":json.loads(sys.argv[2])}))' "$1" "$2"; }
# run_lead <tool_name> <tool_input-json>: run the hook as a dev lead
run_lead() { payload "$1" "$2" | AGENT_BOARD_LEAD=1 AGENT_NAME_GUARD= "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
denied()  { run_lead "$@"; [[ $rc == 2 && -z "$out" && "$err" == *"Give this agent a name"* && "$err" == *"never fall back to an unnamed agent"* && "$err" == *"AGENT_NAME_GUARD=0"* ]]; }
allowed() { run_lead "$@"; [[ $rc == 0 && -z "$out" && -z "$err" ]]; }

NAMED='{"description":"x","prompt":"y","subagent_type":"Explore","name":"scout"}'
check "lead, named Explore: allowed"                 allowed Agent "$NAMED"
check "lead, name missing: denied"                    denied Agent '{"description":"x","prompt":"y","subagent_type":"Explore"}'
check "lead, name empty: denied"                      denied Agent '{"description":"x","prompt":"y","name":""}'
check "lead, name blank: denied"                      denied Agent '{"description":"x","prompt":"y","name":"  "}'
check "lead, name not a string: denied"               denied Agent '{"description":"x","prompt":"y","name":7}'
check "lead, name null: denied"                       denied Agent '{"description":"x","prompt":"y","name":null}'
check "lead, named fork: denied"                      denied Agent '{"description":"x","prompt":"y","subagent_type":"fork","name":"f"}'
check "lead, non-Agent tool without name: allowed"    allowed Bash '{"command":"ls"}'
check "lead, tool_input not an object: allowed"       allowed Agent '"oops"'
print -r -- 'not json' | AGENT_BOARD_LEAD=1 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "lead, malformed JSON: silent exit 0"           test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | env -u AGENT_BOARD_LEAD "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "marker unset, unnamed: allowed"                test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "marker 0, unnamed: allowed"                    test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=1 AGENT_NAME_GUARD=0 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "kill switch AGENT_NAME_GUARD=0: allowed"       test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
payload Agent '{"description":"x","prompt":"y"}' | AGENT_BOARD_LEAD=1 "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "without --scoped denies the same way"          test $rc -eq 2
tt_done
```

- [ ] **Step 2: Run it RED, then write the script** — `zsh tools/tests/test_agent_name_guard.zsh` → every deny check FAILs (script missing). Create `claude/plugin/scripts/agent-name-guard.sh` with exactly the content below, then `chmod 755` it:

```bash
#!/usr/bin/env bash
# PreToolUse(Agent): in a dev lead, deny an Agent call that has no name, or a fork, so every agent the lead starts opens
# in its own ✦ window where the user can watch it. The lead marker AGENT_BOARD_LEAD=1 is exported only by
# bin/claude-orchestrator into the lead's own process (never the tmux session environment), so teammates, tmux-ctl agent
# workers and the overseer are never checked. Kill switch: AGENT_NAME_GUARD=0. --scoped (the plugin registration) is
# accepted and changes nothing. Fail-open on any parse or runtime error.
[[ "$AGENT_NAME_GUARD" == 0 || "$AGENT_BOARD_LEAD" != 1 ]] && { cat >/dev/null; exit 0; }
input=$(cat) || exit 0
verdict=$(printf '%s' "$input" | python3 -I -c 'import json, sys
try:
    d = json.load(sys.stdin)
    ti = d.get("tool_input")
    if d.get("tool_name") != "Agent" or not isinstance(ti, dict):
        print("allow")
    else:
        n = ti.get("name")
        bad = not isinstance(n, str) or not n.strip() or ti.get("subagent_type") == "fork"
        print("deny" if bad else "allow")
except Exception:
    print("allow")' 2>/dev/null) || exit 0
[[ "$verdict" == deny ]] || exit 0
printf '%s\n' "Give this agent a name (the Agent tool's name parameter) so it opens in its own ✦ window where the user can watch it. Dev leads never run agents hidden in the background: read-only lookups (Explore, web-fetch, claude-code-guide) and reviewers included. A fork (subagent_type \"fork\") is never allowed, named or not, because it never opens a window. If the teammate's window fails to spawn, retry once, then tell the user the error and wait; never fall back to an unnamed agent. (Kill switch for the user: AGENT_NAME_GUARD=0.)" >&2
exit 2
```

Run the test → `ALL PASS`. Then run each mutation on a scratch copy (`cp` the script to your scratchpad, apply the `sed -i ''`, run with `TC_AGENTNAMEGUARD=<copy> zsh tools/tests/test_agent_name_guard.zsh`), and report the FAIL lines:
  - delete ` or ti.get("subagent_type") == "fork"` → `lead, named fork: denied` fails
  - delete ` or not n.strip()` → `lead, name empty: denied` and `lead, name blank: denied` fail
  - delete ` || "$AGENT_BOARD_LEAD" != 1` → `marker unset, unnamed: allowed` and `marker 0, unnamed: allowed` fail
  - delete `"$AGENT_NAME_GUARD" == 0 || ` → `kill switch AGENT_NAME_GUARD=0: allowed` fails

- [ ] **Step 3: Commit**

```bash
git add claude/plugin/scripts/agent-name-guard.sh tools/tests/test_agent_name_guard.zsh
git commit -m "feat(plugin): agent-name-guard denies unnamed and fork Agent calls in a dev lead"
```

```json:metadata
{"files": ["claude/plugin/scripts/agent-name-guard.sh", "tools/tests/test_agent_name_guard.zsh"], "verifyCommand": "zsh tools/tests/test_agent_name_guard.zsh", "acceptanceCriteria": ["lead marker set: missing/empty/blank/non-string/null name and named fork denied with exit 2 and the reason", "named call, non-Agent tool, non-object tool_input, malformed JSON allowed silently", "marker unset/0 and AGENT_NAME_GUARD=0 allow", "the four named mutations fail their checks"], "modelTier": "mechanical"}
```

### Task 2: register the hook and document it

**Goal:** The plugin runs `agent-name-guard.sh` on every Agent call after `sdd-call-guard.sh`, and the plugin description and docs name it.

**Files:**
- Modify: `claude/plugin/hooks/hooks.json` (the `"matcher": "Agent"` entry, line ~21)
- Modify: `claude/plugin/.claude-plugin/plugin.json` (`description`)
- Modify: `tools/tests/test_plugin.zsh` (after the sdd-call-guard registration check, line ~51)
- Modify: `docs/INSTALL.md:23`, `docs/ARCHITECTURE.md:151`

**Acceptance Criteria:**
- [ ] hooks.json has exactly one agent-name-guard registration: in the Agent entry, after sdd-call-guard, `--scoped`, timeout 10.
- [ ] plugin.json description contains `plan-handoff-guard, sdd-call-guard, agent-name-guard and context-inject hooks`.
- [ ] INSTALL.md names `agent-name-guard` and `AGENT_NAME_GUARD=0`; ARCHITECTURE.md lists it among the exit-2 hooks.
- [ ] `claude plugin validate claude/plugin` passes.

**Verify:** `zsh tools/tests/test_plugin.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Add the checks** to `tools/tests/test_plugin.zsh`, right after the `PY` line that ends the sdd-call-guard registration check:

```zsh
check "hooks.json registers agent-name-guard on PreToolUse Agent after sdd-call-guard, --scoped, timeout 10" python3 - "$P/hooks/hooks.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))["hooks"]["PreToolUse"]
assert len([h for e in d for h in e["hooks"] if "agent-name-guard" in h["command"]]) == 1
ent = [e for e in d if e["matcher"] == "Agent"]
assert len(ent) == 1, ent
hs = ent[0]["hooks"]; cmds = [h["command"] for h in hs]
i = [k for k, c in enumerate(cmds) if c.endswith("/scripts/agent-name-guard.sh\" --scoped")]
j = [k for k, c in enumerate(cmds) if c.endswith("/scripts/sdd-call-guard.sh\" --scoped")]
assert len(i) == 1 and len(j) == 1 and i[0] > j[0] and hs[i[0]]["timeout"] == 10, cmds
PY
check "agent-name-guard.sh is executable" test -x "$P/scripts/agent-name-guard.sh"
check "plugin.json description names agent-name-guard" zsh -c 'python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[\"description\"])" "$1" | grep -qF "plan-handoff-guard, sdd-call-guard, agent-name-guard and context-inject hooks"' _ "$P/.claude-plugin/plugin.json"
```

Run `zsh tools/tests/test_plugin.zsh` → the registration and description checks FAIL.

- [ ] **Step 2: Register.** In `claude/plugin/hooks/hooks.json` replace the Agent entry's single hook line with two lines (keep the file's one-line-per-hook style):

```json
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/sdd-call-guard.sh\" --scoped", "timeout": 10 },
          { "type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/agent-name-guard.sh\" --scoped", "timeout": 10 }
```

- [ ] **Step 3: Description.** In `plugin.json` replace `the plan-handoff-guard, sdd-call-guard and context-inject hooks` with `the plan-handoff-guard, sdd-call-guard, agent-name-guard and context-inject hooks`.

- [ ] **Step 4: Docs.** In `docs/INSTALL.md:23`, after the `sdd-call-guard (…; `SDD_CALL_GUARD=0` disables it), ` parenthetical, insert:
`` `agent-name-guard` (in the lead only, marked `AGENT_BOARD_LEAD=1` by `claude-orchestrator`: denies an Agent call with no `name`, or a fork, so every agent opens in a `✦` window; `AGENT_NAME_GUARD=0` disables it), ``
In `docs/ARCHITECTURE.md:151` replace `` `plan-handoff-guard` and `sdd-call-guard` (exit 2) `` with `` `plan-handoff-guard`, `sdd-call-guard` and `agent-name-guard` (exit 2) ``.

- [ ] **Step 5: Run** `claude plugin validate claude/plugin` (passes) and `zsh tools/tests/test_plugin.zsh` → `ALL PASS`. Mutation: move the agent-name-guard line before sdd-call-guard in a scratch copy of hooks.json and run the check's python against it → AssertionError.

- [ ] **Step 6: Commit**

```bash
git add claude/plugin/hooks/hooks.json claude/plugin/.claude-plugin/plugin.json tools/tests/test_plugin.zsh docs/INSTALL.md docs/ARCHITECTURE.md
git commit -m "feat(plugin): register agent-name-guard after sdd-call-guard"
```

```json:metadata
{"files": ["claude/plugin/hooks/hooks.json", "claude/plugin/.claude-plugin/plugin.json", "tools/tests/test_plugin.zsh", "docs/INSTALL.md", "docs/ARCHITECTURE.md"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["one agent-name-guard registration in the Agent entry after sdd-call-guard, --scoped, timeout 10", "plugin.json description names agent-name-guard", "INSTALL.md and ARCHITECTURE.md name it", "claude plugin validate passes"], "modelTier": "mechanical"}
```

### Task 3: lead marker in claude-orchestrator

**Goal:** The lead's claude process gets `AGENT_BOARD_LEAD=1`; the tmux session environment does not.

**Files:**
- Modify: `bin/claude-orchestrator` (after the `export PATH=… AGENT_BOARD_REPO=…` line)
- Modify: `tools/tests/test_prompt_argv.zsh` (stub and checks near line 8 and line 24)

**Acceptance Criteria:**
- [ ] The exec'd claude (stub) sees `AGENT_BOARD_LEAD=1`.
- [ ] `show-environment` of the scratch session holds `AGENT_BOARD_REPO` and no `AGENT_BOARD_LEAD` line.
- [ ] Mutations fail the stated checks (Step 3).

**Verify:** `zsh tools/tests/test_prompt_argv.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Tests.** Apply this diff to `tools/tests/test_prompt_argv.zsh` (generated against the current file; `patch -p1 --dry-run` first):

```diff
diff --git a/tools/tests/test_prompt_argv.zsh b/tools/tests/test_prompt_argv.zsh
index 8f8fc6d..58ef115 100644
--- a/tools/tests/test_prompt_argv.zsh
+++ b/tools/tests/test_prompt_argv.zsh
@@ -4,7 +4,8 @@ tt_setup
 stub="$(mktemp -d)"; trap 'rm -rf "$stub"; tt_teardown' EXIT INT TERM
 print -r -- '#!/bin/sh
 for a in "$@"; do printf "%s\n" "$a"; done
-printf "PATH=%s\n" "$PATH"' > "$stub/claude"; chmod +x "$stub/claude"
+printf "PATH=%s\n" "$PATH"
+printf "AGENT_BOARD_LEAD=%s\n" "$AGENT_BOARD_LEAD"' > "$stub/claude"; chmod +x "$stub/claude"
 cfg="$(mktemp -d)"   # a HOME with no user override: the repo rules apply
 out="$(HOME="$cfg" TC_TMUX="$TT_BIN" PATH="$stub:$PATH" $R/bin/claude-orchestrator)"; rm -rf "$cfg"
 check "orchestrator uses -file flag"  grep -qxF -- '--append-system-prompt-file' <<< "$out"
@@ -22,6 +23,10 @@ check "orchestrator passes --settings"      grep -qxF -- '--settings' <<< "$out"
 check "orchestrator settings path"          grep -qxF -- "$R/claude/session-settings.json" <<< "$out"
 check "orchestrator puts <repo>/bin first"  grep -qE "^PATH=${R}/bin:" <<< "$out"
 check "set-environment AGENT_BOARD_REPO"    test "$(tt show-environment -t '=tt:' AGENT_BOARD_REPO 2>&1)" = "AGENT_BOARD_REPO=$R"
+check "lead marker exported to claude"       grep -qxF 'AGENT_BOARD_LEAD=1' <<< "$out"
+sessenv="$(tt show-environment -t '=tt:' 2>&1)"
+check "session env was read (has AGENT_BOARD_REPO)" grep -q '^AGENT_BOARD_REPO=' <<< "$sessenv"
+check "lead marker not in the tmux session env"     test -z "$(grep '^-*AGENT_BOARD_LEAD' <<< "$sessenv")"
 check "set-environment PATH has <repo>/bin" grep -qE "^PATH=${R}/bin:" <<< "$(tt show-environment -t '=tt:' PATH 2>&1)"
 out2="$(TC_TMUX=/nonexistent PATH="$stub:$PATH" $R/bin/claude-orchestrator 2>&1)"
 check "failing set-environment does not stop the launch" grep -qxF -- '--settings' <<< "$out2"
```

Run → `lead marker exported to claude` FAILs.

- [ ] **Step 2: Launcher.** In `bin/claude-orchestrator`, right after `export PATH="$(ab_path)" AGENT_BOARD_REPO="$AB_REPO"`, add:

```zsh
# the dev-lead marker read by the agent-name-guard hook: this process only, never the tmux session environment, so
# teammates, tmux-ctl agent workers and the overseer do not inherit it
export AGENT_BOARD_LEAD=1
```

Run → `ALL PASS`.

- [ ] **Step 3: Mutations** (on the file, then restore it with `git checkout -- bin/claude-orchestrator` — that one path only):
  - delete the `export AGENT_BOARD_LEAD=1` line → `lead marker exported to claude` fails
  - add `  tc_tmux set-environment AGENT_BOARD_LEAD 1 2>/dev/null` inside the `if [[ -n "$TMUX" ]]` block → `lead marker not in the tmux session env` fails

  Re-apply Step 2 and re-run → `ALL PASS`.

- [ ] **Step 4: Commit**

```bash
git add bin/claude-orchestrator tools/tests/test_prompt_argv.zsh
git commit -m "feat(dev): claude-orchestrator marks the lead with AGENT_BOARD_LEAD=1"
```

```json:metadata
{"files": ["bin/claude-orchestrator", "tools/tests/test_prompt_argv.zsh"], "verifyCommand": "zsh tools/tests/test_prompt_argv.zsh", "acceptanceCriteria": ["stub claude sees AGENT_BOARD_LEAD=1", "scratch session env has AGENT_BOARD_REPO and no AGENT_BOARD_LEAD", "both mutations fail their checks"], "modelTier": "mechanical"}
```

### Task 4: lead rules bullets

**Goal:** `claude/orchestrator.md` tells the lead that every agent gets a name (no forks) and what to do when a teammate window fails to spawn.

**Files:**
- Modify: `claude/orchestrator.md` ("Default: use an agent team", after the bullet ending `they become the window names.`)
- Modify: `tools/tests/test_plugin.zsh` (lead-rules checks block, after `check "lead rules: queue asks nothing after the batch" …`)

**Acceptance Criteria:**
- [ ] The two bullets below appear verbatim, directly after the "Give teammates short, distinct names" bullet.
- [ ] The orchestrator.md skill-name check in test_plugin.zsh still passes.

**Verify:** `zsh tools/tests/test_plugin.zsh` → last line `ALL PASS`

**Steps:**

- [ ] **Step 1: Checks.** Add to `tools/tests/test_plugin.zsh` after the `lead rules: queue asks nothing after the batch` check:

```zsh
check "lead rules: every agent gets a name" grep -qF 'Every agent you start gets a `name`' "$O"
check "lead rules: name rule enforced by agent-name-guard" grep -qF 'The `agent-name-guard` hook enforces this.' "$O"
check "lead rules: spawn failure retries once, never unnamed" grep -qF 'Never fall back to an unnamed background agent.' "$O"
```

Run → those three FAIL.

- [ ] **Step 2: Bullets.** Insert after the bullet that ends `Give teammates short, distinct names; they become the window names.`:

```markdown
- Every agent you start gets a `name`, so it opens in a `✦` window: read-only lookups (Explore, web-fetch,
  claude-code-guide) and reviewers included. Never start a fork. The `agent-name-guard` hook enforces this.
- If a teammate's window fails to spawn, retry once; if it fails again, tell the user with the error and wait.
  Never fall back to an unnamed background agent.
```

Run → `ALL PASS`.

- [ ] **Step 3: Commit**

```bash
git add claude/orchestrator.md tools/tests/test_plugin.zsh
git commit -m "docs(rules): every agent a dev lead starts is named; spawn-failure fallback"
```

```json:metadata
{"files": ["claude/orchestrator.md", "tools/tests/test_plugin.zsh"], "verifyCommand": "zsh tools/tests/test_plugin.zsh", "acceptanceCriteria": ["both bullets verbatim after the window-names bullet", "skill-name resolution check still passes"], "modelTier": "mechanical"}
```

### Task 5: real run and real-state check

**Goal:** Show on a real lead that an unnamed Agent call is denied and a named one opens a `✦` window whose teammate lacks `AGENT_BOARD_LEAD`, and that the guard's verdicts on the user's real past Agent calls match an independent count; record both in `tools/tests/e2e-lead-named-agents.md`.

**Files:**
- Create: `tools/tests/e2e-lead-named-agents.md`

**Constraints:** scratch tmux only (`~/.local/bin/tmux -L <sock> -f /dev/null`, temp `TC_STATE`), lead started through this worktree's `bin/claude-orchestrator` (so this worktree's plugin loads); never touch the live `dev` session or the live checkout; kill the scratch server afterwards and show with `ps` that no scratch claude is left. Prompt sending: `send-keys "text"`, wait 1 s, separate `send-keys Enter`. Read-only on `~/.claude/projects`.

**Acceptance Criteria:**
- [ ] Unnamed Agent call by the scratch lead → the pane shows the deny reason (quote the captured pane lines).
- [ ] Named Agent call → a `✦ <name>` window exists (`list-windows` output quoted); the teammate's process env (`ps eww <pid>` or the teammate running `env`) and `show-environment` both lack `AGENT_BOARD_LEAD`, and the lead's process env has it.
- [ ] Real-state: every Agent `tool_use` input in `~/.claude/projects/*/*.jsonl` (uncapped; print the total count and the number of files scanned) is fed to the guard with `AGENT_BOARD_LEAD=1`; deny count equals an independently computed count of inputs with no/blank/non-string `name` or `subagent_type == "fork"`; zero mismatches, printed.
- [ ] The doc records commands, outputs, date and the plugin path used.

**Verify:** `grep -c '^## ' tools/tests/e2e-lead-named-agents.md` → `3` (sections: `## Denied unnamed call`, `## Named call opens a window`, `## Real transcripts`)

```json:metadata
{"files": ["tools/tests/e2e-lead-named-agents.md"], "verifyCommand": "grep -c '^## ' tools/tests/e2e-lead-named-agents.md", "acceptanceCriteria": ["unnamed call denied in a real scratch lead, pane quoted", "named call opens a ✦ window; teammate env and session env lack AGENT_BOARD_LEAD, lead env has it", "guard verdicts on every real Agent call in ~/.claude/projects match an independent count, totals printed, zero mismatches", "doc records commands, outputs, date, plugin path"], "modelTier": "standard"}
```
