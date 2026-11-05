# Artifact Session Id Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tmux-ctl artifact` (manual mode of `artifact-register.sh`) records the caller's session id: `--session <id>` if given, else `$CLAUDE_CODE_SESSION_ID`, else `""`.

**Architecture:** `claude/hooks/artifact-register.sh` is a symlink to `claude/plugin/scripts/artifact-register.sh`; only the target changes. The zsh wrapper picks the manual session id and passes it to its embedded Python as one more argv. Hook mode is unchanged (session id from hook JSON). `bin/tmux-ctl` is not changed (the environment passes through; the flag is not forwarded). `board/planview.py` gets a docstring line only.

**Tech Stack:** zsh, embedded Python 3, the `tools/tests/lib.zsh` scratch-tmux test harness.

**Spec:** `docs/superpowers/specs/2026-11-05-artifact-session-id-design.md`

## Global Constraints

- Edit `claude/plugin/scripts/artifact-register.sh` only (the hooks path is a symlink to it: `ls -l claude/hooks/artifact-register.sh` → `../plugin/scripts/artifact-register.sh`). Never replace the symlink.
- Manual mode precedence: `--session <id>` (even if `$CLAUDE_CODE_SESSION_ID` is set) > `$CLAUDE_CODE_SESSION_ID` > `""`. Hook mode keeps `session_id` from the hook JSON and ignores the environment.
- The script stays silent and always exits 0.
- Targeted tests only: `zsh tools/tests/test_artifact_hook.zsh` and `python3 -m unittest discover -s board/tests -p 'test_planview*.py'`. Never `run-all.zsh` or the full board suite.
- A session id is not a credential (queue ruling), but docs record only a match verdict and the id's length, not the id.
- Commit messages: conventional with scope (`fix(hooks): …`, `docs(test): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):** none beyond the spec.

**Lead rulings:**
- Ruling: `--session` is not forwarded by `tmux-ctl artifact` (spec: "only if the flag is forwarded"); `tmux-ctl`'s usage line is unchanged. Cost if wrong: a user who wants to set the id by hand calls the hook script directly.

---

### Task 1: Manual registrations carry the session id

**Goal:** `artifact-register.sh --path …` writes `session_id` from `--session`, else `$CLAUDE_CODE_SESSION_ID`, else `""`; `plan_entry`'s docstring explains the blank-id fallback.

**Files:**
- Modify: `claude/plugin/scripts/artifact-register.sh` (usage comment line 4, the `case` parser, the Python argv and `sid`)
- Modify: `board/planview.py` (`plan_entry` docstring only)
- Test: `tools/tests/test_artifact_hook.zsh`

**Acceptance Criteria:**
- [ ] Manual registration with `CLAUDE_CODE_SESSION_ID=abc` writes `"session_id": "abc"`.
- [ ] Manual registration with `CLAUDE_CODE_SESSION_ID` unset writes `"session_id": ""`.
- [ ] `--session x` with `CLAUDE_CODE_SESSION_ID=abc` writes `"session_id": "x"`.
- [ ] Hook mode with `CLAUDE_CODE_SESSION_ID=abc` and JSON `"session_id":"S2"` writes `S2`.
- [ ] Both targeted suites pass; `planview.py` diff is docstring-only.

**Verify:** `zsh tools/tests/test_artifact_hook.zsh && python3 -m unittest discover -s board/tests -p 'test_planview*.py'` → `ALL PASS` then `OK`

**Steps:**

- [ ] **Step 1: Add the failing checks** to `tools/tests/test_artifact_hook.zsh`, right after the existing `check "manual mode" …` line:

```zsh
( unset TMUX TMUX_PANE CLAUDE_CODE_SESSION_ID; "$H" --path "$other" --project tt )
check "manual, no session env"   test "$(jq -r .session_id "$m" | tail -1)" = ""
( unset TMUX TMUX_PANE; CLAUDE_CODE_SESSION_ID=abc "$H" --path "$other" --project tt )
check "manual, session from env" test "$(jq -r .session_id "$m" | tail -1)" = abc
( unset TMUX TMUX_PANE; CLAUDE_CODE_SESSION_ID=abc "$H" --path "$other" --session x --project tt )
check "manual, --session wins"   test "$(jq -r .session_id "$m" | tail -1)" = x
CLAUDE_CODE_SESSION_ID=abc hook "{\"tool_name\":\"Write\",\"session_id\":\"S2\",\"tool_input\":{\"file_path\":\"$plan\"}}"
check "hook mode ignores env"    test "$(jq -r .session_id "$m" | tail -1)" = S2
```

- [ ] **Step 2: Run to see them fail**

Run: `zsh tools/tests/test_artifact_hook.zsh; echo rc=$?`
Expected: `2 FAILED`, `rc=1` — "manual, session from env" and "manual, --session wins" fail (both write `""`). "manual, no session env" and "hook mode ignores env" pass on the old code; they are regression guards. Mutations, after Step 3: mutate hook mode to prefer the env (`sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or d.get("session_id")`) → "hook mode ignores env" fails; mutate manual mode to ignore `--session` → "--session wins" fails. Run each, record the failure, restore.

- [ ] **Step 3: Implement** in `claude/plugin/scripts/artifact-register.sh`:

Usage comment (line 4):
```zsh
#   manual mode: artifact-register.sh --path P [--kind K] [--agent A] [--project NAME] [--session ID]
#     session_id: --session, else $CLAUDE_CODE_SESSION_ID (set in Claude Code's Bash tool), else ""
```
Parser: add `msid= has_msid=0` to the `apath= kind= …` line and a case:
```zsh
      --session) msid="$2"; has_msid=1; shift 2 ;;
```
Before the `line="$(print -r -- "$payload" | python3 …` line:
```zsh
  (( has_msid )) || msid="${CLAUDE_CODE_SESSION_ID-}"
```
Python: change `manual, path, kind, agent, epoch, home, tmp, manifest = sys.argv[1:9]` to
```python
manual, path, kind, agent, epoch, home, tmp, manifest, msid = sys.argv[1:10]
```
and after `url = sid = title = slug = ""` add
```python
if manual:
    sid = msid
```
and append `"$msid"` as the last argument of the `python3` call (after `"$STATE/artifacts-$project.jsonl"`).

`board/planview.py` `plan_entry` docstring becomes:
```python
    """Path of the newest `kind == "plan"` manifest line of this session, or None. A line with a blank session_id
    (`tmux-ctl artifact` of a worktree copy) counts when it names a file this session registered itself. Blank ids
    come from lines written before manual registrations recorded $CLAUDE_CODE_SESSION_ID, and from `tmux-ctl
    artifact` run in a plain shell; a non-blank id is matched only by that id."""
```

- [ ] **Step 4: Run to see them pass** — the Verify command; expect `ALL PASS` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add claude/plugin/scripts/artifact-register.sh board/planview.py tools/tests/test_artifact_hook.zsh
git commit -m "fix(hooks): manual artifact registrations record the session id"
```

```json:metadata
{"files": ["claude/plugin/scripts/artifact-register.sh", "board/planview.py", "tools/tests/test_artifact_hook.zsh"], "verifyCommand": "zsh tools/tests/test_artifact_hook.zsh && python3 -m unittest discover -s board/tests -p 'test_planview*.py'", "acceptanceCriteria": ["CLAUDE_CODE_SESSION_ID=abc manual writes abc", "unset env manual writes empty", "--session x wins over env", "hook mode keeps JSON session_id with env set", "both targeted suites pass; planview diff docstring-only"], "modelTier": "mechanical"}
```

---

### Task 2: Real run from an agent's Bash tool

**Goal:** Show that `tmux-ctl artifact` run from a Claude Code Bash tool writes the session's real id, against a scratch state dir, and that the live manifest's existing blank-id lines still resolve.

**Files:**
- Create: `docs/superpowers/notes/2026-11-05-artifact-session-id-real-run.md`

**Acceptance Criteria:**
- [ ] From the implementer's own Bash tool, inside its tmux pane: a scratch plan file registered with `TC_STATE=<mktemp -d> bin/tmux-ctl artifact <file>` (the worktree's `bin/tmux-ctl`); the new manifest line's `session_id` equals `$CLAUDE_CODE_SESSION_ID` (doc records `MATCH` and the id length, not the id).
- [ ] The same command with `env -u CLAUDE_CODE_SESSION_ID` writes `""` (doc records it).
- [ ] Read-only real state: an uncapped count of `kind == "plan"` lines with blank and non-blank `session_id` in the live manifest `"$(tmux-ctl …state dir)"/artifacts-agent-board.jsonl` (resolve the live state dir with the repo's `tc_state_dir` helper or `python3 -c 'import sys; sys.path.insert(0,"board"); import tc_env; print(tc_env.state_dir())'` with `TC_STATE` unset), recorded in the doc; nothing written there.
- [ ] The scratch state dir and scratch file are removed afterwards (`ls` shows them gone, recorded).

**Verify:** `grep -c 'MATCH' docs/superpowers/notes/2026-11-05-artifact-session-id-real-run.md` → `1` or more

**Steps:**

- [ ] **Step 1:**
```zsh
S=$(mktemp -d); F=$(mktemp -d)/docs/superpowers/plans; mkdir -p "$F"; print '# scratch' > "$F/2099-01-01-scratch.md"
TC_STATE="$S" bin/tmux-ctl artifact "$F/2099-01-01-scratch.md"
got=$(jq -r .session_id "$S"/artifacts-*.jsonl | tail -1)
[ -n "$CLAUDE_CODE_SESSION_ID" ] && [ "$got" = "$CLAUDE_CODE_SESSION_ID" ] && echo "MATCH len=${#got}" || echo "MISMATCH len=${#got}"
TC_STATE="$S" env -u CLAUDE_CODE_SESSION_ID bin/tmux-ctl artifact "$F/2099-01-01-scratch.md"
jq -r '.session_id|length' "$S"/artifacts-*.jsonl | tail -1
```
- [ ] **Step 2:** read-only count on the live manifest (see AC 3).
- [ ] **Step 3:** remove `$S` and the scratch dir; write the notes doc with the commands, outputs (ids redacted to MATCH/length), the counts and the cleanup check; commit.

```bash
git add docs/superpowers/notes/2026-11-05-artifact-session-id-real-run.md
git commit -m "docs(test): artifact session id real run"
```

```json:metadata
{"files": ["docs/superpowers/notes/2026-11-05-artifact-session-id-real-run.md"], "verifyCommand": "grep -c 'MATCH' docs/superpowers/notes/2026-11-05-artifact-session-id-real-run.md", "acceptanceCriteria": ["real tmux-ctl artifact from an agent Bash tool writes the session id (MATCH, length only)", "env -u run writes empty", "uncapped blank/non-blank plan-line counts from the live manifest, read-only", "scratch state and file removed"], "modelTier": "mechanical"}
```
