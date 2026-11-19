# Teammate requests in the lead's window, late teammate messages, dream skip — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A teammate's permission request that queues in the lead's window reaches Discord, a gone teammate's request is denied automatically, the lead learns when a teammate stopped, and the dream job stops reporting empty projects.

**Architecture:** A real capture (Task 1) fixes what the lead-side request and the teammate's waiting box look like; `tools/lib/dialog.zsh` parses the request with a `from:` field, `board/paneclass.py` classifies the waiting box, and `board/discord_dialogs.py` posts the lead-side request and presses Deny for gone teammates. A teammate Stop hook writes a status file that a lead hook and `tmux-ctl teammates` read. `board/dream.py` passes over empty cores in `--all`.

**Tech Stack:** zsh (tmux-ctl, dialog.zsh, hooks), Python 3 stdlib (board), tmux, Claude Code hooks.

**Spec:** `docs/superpowers/specs/2026-11-19-teammate-requests-messages-dream-design.md`

## Global Constraints

- Builds on spec C as merged on main (`db07580`): `tmux-ctl dialog <win> show|press`, `board/discord_dialogs.py` scan, posts and `_finish`. Reuse those; no second parser, no second press path.
- Every press goes through `tmux-ctl dialog <pane> press … --expect <lines>` with the exact-text re-check. A `changed` / no-prompt / copy-mode result presses nothing and is retried on the next tick, never forced.
- Stale Deny only for a request whose `from` names a teammate with no `✦ <name>` window in the lead's tmux session on two scans at least 30 s apart. Never for a live teammate, a request with no `from`, a worker (`tmux-ctl agent`) or a peer. At most 10 presses per lead pane per tick.
- Stale Deny records: audit line `dialog / stale-deny / <name>`; Activity feed line `denied stale request from <name> (window gone)`; an existing Discord post for that request is edited to `→ denied: <name> is gone`.
- Lead-side post header: `🔐 <project> · <name> (in the lead's window) wants to …`.
- Teammate pane class for the waiting box: `waiting-on-lead`. The scan posts nothing for that pane.
- Status file: `<state>/teammates/<lead session id>/<name>.json` = `{"ts": <epoch>, "name": …, "first_line": …, "text": <last assistant message, first 2000 chars>}`, written atomically (temp file + rename). Seen file: `<state>/teammates/<lead session id>/<name>.seen`. `<state>` is the toolkit state dir (`TC_STATE`, as `board/tc_env.py` and `tools/lib` resolve it).
- Reminder text, once per stop: `<name> stopped at HH:MM: <first line> — read its report file.`
- Both hooks exit 0 on every error, never block, never write a partial file.
- `tmux-ctl teammates` prints `no teammates` when the calling lead has none.
- Dream: `run --all` passes over a project whose core has no `- ` entry lines, with no output line; a project with entries and no root still prints `dream: <p> skipped, no repo root`; `run <project>` is unchanged.
- Sections 1-2 (Tasks 2-4) depend on Task 1's capture. If Task 1 reports that the lead-side request never renders, Tasks 2-4 are skipped (recorded as a ruling) and Tasks 5-8 still ship.
- Shared worktree: stage only your own paths (`git add <paths>`); no `stash`, `reset`, `checkout`, `clean`, `rebase`.
- Commits: conventional with scope (`feat(board): …`, `fix(tmux-ctl): …`), ending with the attribution trailer your harness specifies.

**User decisions (already made):**
- D1: a gone teammate's request in the lead's window gets Deny pressed automatically and logged ("press deny automatically").
- D2: late messages: teammate Stop hook + lead reminder hook + `tmux-ctl teammates`.
- D3: dream `--all` silently passes over a project whose core has no entries; entries + no root still reports `skipped, no repo root`.
- D4: the spec design approved as sent ("Ok", 22:46Z).
- Queue: integration `merge` to main locally, no push.

---

### Task 1: Capture the lead-side request and probe the teammate hook environment

**Goal:** Real fixtures of a teammate's request in the lead's pane and of the teammate's "Waiting for team lead approval" box, plus two recorded probes the hook tasks need.

**Constraints:**
- Scratch tmux server only (`~/.local/bin/tmux -L <sock> -f /dev/null`), temp repo, real `claude`; the repo's settings deny one harmless command (e.g. `touch probe`) without a prompt rule so the teammate's attempt asks. Nothing touches the real tmux server or the user's sessions; kill the scratch server and remove the temp repo at the end (leak check with `ps` and `ls`).
- Probe A: which environment variables (or hook input fields) mark a hook as running inside a teammate, and how the teammate's name and its lead's session id can be read there. Record the raw env/stdin dump lines that prove it.
- Probe B: whether `UserPromptSubmit` fires in the lead when a teammate message arrives (record the hook input), else confirm `PostToolUse` fires in the lead.
- If the request never renders in the lead pane, stop and report what was seen (both panes captured); do not invent a fixture.

**Files:**
- Create: `tools/tests/fixtures/dialogs/team-request.txt`, `tools/tests/fixtures/dialogs/team-waiting.txt`
- Modify: `tools/tests/fixtures/dialogs/README.md` (how the teammate's name appears, whether the lead must be idle for the request to render, the capture command)
- Create: `docs/superpowers/notes/2026-11-19-teammate-probes.md` (Probe A and B, raw lines, the capture setup)

**Acceptance Criteria:**
- [ ] `team-request.txt` is a raw `capture-pane -p -J` of the lead pane while the request shows, and contains the teammate's name.
- [ ] `team-waiting.txt` is the teammate pane with the "Waiting for team lead approval" box.
- [ ] The notes file names the teammate marker (variable or field), how the name and lead session id are read, and Probe B's answer, each with a raw output line.
- [ ] No scratch tmux server or temp dir is left (`ps` / `ls` output in the report).

**Verify:** `ls tools/tests/fixtures/dialogs/team-request.txt tools/tests/fixtures/dialogs/team-waiting.txt && grep -c 'Probe' docs/superpowers/notes/2026-11-19-teammate-probes.md`

```json:metadata
{"files": ["tools/tests/fixtures/dialogs/team-request.txt", "tools/tests/fixtures/dialogs/team-waiting.txt", "tools/tests/fixtures/dialogs/README.md", "docs/superpowers/notes/2026-11-19-teammate-probes.md"], "verifyCommand": "ls tools/tests/fixtures/dialogs/team-request.txt tools/tests/fixtures/dialogs/team-waiting.txt && grep -c 'Probe' docs/superpowers/notes/2026-11-19-teammate-probes.md", "acceptanceCriteria": ["team-request.txt raw lead capture with teammate name", "team-waiting.txt teammate box capture", "notes name teammate marker, name/lead-session source, Probe B answer with raw lines", "no scratch server or temp dir left"], "modelTier": "frontier"}
```

### Task 2: `dialog show` reads the lead-side request with `from:`

**Goal:** `tmux-ctl dialog <win> show` on the lead pane reads a teammate's request as `kind: permission` with the same options and `--expect` lines as a teammate's own prompt, plus `from: <teammate name>`.

**Files:**
- Modify: `tools/lib/dialog.zsh` (`_dlg_parse`, `_dlg_json`)
- Test: `tools/tests/test_ctl_dialog_show.zsh`

**Acceptance Criteria:**
- [ ] `team-request.txt` reads as `kind: permission`, `from: <the name in the fixture>`, options and `expect` lines exactly as the capture shows (asserted line by line).
- [ ] The JSON form (`--json`, as `_dlg_json` emits) carries `"from"`; dialogs without a teammate source have no `from` (or an empty one) and every existing fixture's output is unchanged.
- [ ] `press --option No --expect <those lines>` on a scratch pane showing the fixture sends the No key (reuse `test_ctl_dialog_press.zsh`'s fake-pane pattern) — remove the `from` handling → the `from:` assertion fails (state the mutation run in the report).

**Verify:** `zsh tools/tests/test_ctl_dialog_show.zsh && zsh tools/tests/test_ctl_dialog_press.zsh`

**Steps:** follow test-driven-development: add the fixture assertions first (RED for the stated reason), then parse the teammate line `_dlg_parse` finds above the request, as the README from Task 1 describes, into `from`.

```json:metadata
{"files": ["tools/lib/dialog.zsh", "tools/tests/test_ctl_dialog_show.zsh", "tools/tests/test_ctl_dialog_press.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_dialog_show.zsh && zsh tools/tests/test_ctl_dialog_press.zsh", "acceptanceCriteria": ["team-request.txt reads kind permission with from and exact options/expect", "json carries from; other fixtures unchanged", "press No on the fixture works; mutation reported"], "modelTier": "standard"}
```

### Task 3: `waiting-on-lead` pane class

**Goal:** A teammate pane whose last rows are the "Waiting for team lead approval" box classifies as `waiting-on-lead`; the board shows it as waiting, pointing at the lead window, and the dialog scan posts nothing for it.

**Files:**
- Modify: `board/paneclass.py`, the board's pane state / label code that renders classes (`board/server.py` and the client file that maps classes to labels, found by `grep -rn "needs-input\|waiting" board/ --include=*.py --include=*.js`)
- Modify: `board/discord_dialogs.py` (`_waiting` / `_scan`: skip `waiting-on-lead` panes)
- Test: `board/tests/test_paneclass.py`, `board/tests/test_discord_dialogs.py`

**Acceptance Criteria:**
- [ ] `team-waiting.txt` classifies as `waiting-on-lead`; every existing paneclass fixture keeps its class.
- [ ] The board labels such a pane as waiting on the lead window (test on the state/label function).
- [ ] A scan over a fake teammate pane showing `team-waiting.txt` posts nothing (remove the skip → the test sees a post; state the mutation run).

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_paneclass.py' && python3 -m unittest discover -s board/tests -p 'test_discord_dialogs.py'`

```json:metadata
{"files": ["board/paneclass.py", "board/server.py", "board/discord_dialogs.py", "board/tests/test_paneclass.py", "board/tests/test_discord_dialogs.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_paneclass.py' && python3 -m unittest discover -s board/tests -p 'test_discord_dialogs.py'", "acceptanceCriteria": ["team-waiting.txt is waiting-on-lead; other fixtures unchanged", "board labels it waiting on the lead window", "scan posts nothing for it; mutation reported"], "modelTier": "standard"}
```

### Task 4: Lead-side posts and stale Deny in the dialog scan

**Goal:** The scan posts a lead-side request with the `(in the lead's window)` header and presses Deny for requests from gone teammates, as Global Constraints state.

**Files:**
- Modify: `board/discord_dialogs.py` (`header`, `_scan`, a new stale-deny step; audit and feed through the module's existing audit/feed helpers)
- Test: `board/tests/test_discord_dialogs.py`

**Acceptance Criteria:**
- [ ] A lead-side request posts once, headed `🔐 <project> · <name> (in the lead's window) wants to …`; Allow once / Deny press in the lead pane through `dialog press` with `--expect`.
- [ ] Gone = no `✦ <name>` window in the lead's session on two scans ≥ 30 s apart: exactly one `press <lead pane> --option No --expect <its lines>`; audit `dialog / stale-deny / <name>`; feed `denied stale request from <name> (window gone)`; an existing post edited to `→ denied: <name> is gone`.
- [ ] No press for: a live teammate's request; a request seen gone on the first scan only, or on two scans < 30 s apart; a request with no `from`; a `changed` re-check (and it is retried next tick).
- [ ] A queue of three stale requests gets three presses in one tick; with eleven, ten are pressed and the 11th waits for the next tick.
- [ ] Each guard test names its mutation in a comment (remove the 30 s check, the `from` check, the live-window check, the cap) and the report says each was run and failed.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_discord_dialogs.py'`

```json:metadata
{"files": ["board/discord_dialogs.py", "board/tests/test_discord_dialogs.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_discord_dialogs.py'", "acceptanceCriteria": ["lead-side request posts once with header; presses via dialog press --expect", "gone on two scans >=30s apart: one No press, audit, feed, post edit", "no press for live, first-scan, <30s, no-from, changed", "3 stale -> 3 presses; 11 -> 10 then 1 next tick", "guard mutations run and reported"], "modelTier": "standard"}
```

### Task 5: Teammate Stop hook and lead reminder hook

**Goal:** A teammate's Stop writes its status file; the lead gets one reminder per stop when the status file is newer than that teammate's last message.

**Files:**
- Create: `claude/plugin/scripts/teammate-stop.sh`, `claude/plugin/scripts/teammate-remind.sh`
- Modify: `claude/plugin/hooks/hooks.json` (Stop: `teammate-stop.sh`; the event Task 1's Probe B names: `teammate-remind.sh`; both `--scoped`, like the existing entries)
- Test: `tools/tests/test_teammate_hooks.zsh`

**Acceptance Criteria:**
- [ ] The teammate marker, name and lead session id come from Task 1's notes (cite the notes line in the script comment).
- [ ] Stop hook: writes the status file only in a teammate env, atomically (temp + rename; the test checks no temp file remains and the JSON parses), `text` capped at 2000 chars; exits 0 and writes nothing when the state dir is unwritable; writes nothing in a lead or worker env.
- [ ] Lead hook: emits the reminder once per stop; not again for the same `ts`; not when `.seen` is newer; touches `.seen` when a message from that name arrives; silent in a teammate or worker; with `PostToolUse`, at most once a minute.
- [ ] Each absence test names its mutation (drop the teammate check, the `.seen` comparison, the once-per-stop record) and the report says it was run.

**Verify:** `zsh tools/tests/test_teammate_hooks.zsh`

```json:metadata
{"files": ["claude/plugin/scripts/teammate-stop.sh", "claude/plugin/scripts/teammate-remind.sh", "claude/plugin/hooks/hooks.json", "tools/tests/test_teammate_hooks.zsh"], "verifyCommand": "zsh tools/tests/test_teammate_hooks.zsh", "acceptanceCriteria": ["marker from Task 1 notes", "stop hook atomic, teammate-only, 2000 cap, exit 0 unwritable", "lead hook once per stop, .seen respected, teammate/worker silent, rate limit", "mutations run and reported"], "modelTier": "standard"}
```

### Task 6: `tmux-ctl teammates`

**Goal:** `tmux-ctl teammates` lists, per teammate of the calling lead's session: name, window alive (yes/no), busy/idle, last stop time, first line; `no teammates` when there are none.

**Files:**
- Modify: `bin/tmux-ctl` (new `teammates)` case, help/usage line)
- Create: `tools/lib/teammates.zsh` if the case body exceeds ~20 lines
- Test: `tools/tests/test_ctl_teammates.zsh` (scratch server via `tools/tests/lib.zsh` `tt_setup`)

**Acceptance Criteria:**
- [ ] On a scratch server with one live `✦ a` window and a status file for `a` and one for a dead `b`: two rows, `a yes …` and `b no …`, each with the stop time `HH:MM` and first line.
- [ ] Busy/idle reads the pane class the board uses (`board/paneclass.py` via the existing helper tmux-ctl uses for `list`), not a new heuristic.
- [ ] No status files and no `✦` windows → exactly `no teammates`.

**Verify:** `zsh tools/tests/test_ctl_teammates.zsh`

```json:metadata
{"files": ["bin/tmux-ctl", "tools/lib/teammates.zsh", "tools/tests/test_ctl_teammates.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_teammates.zsh", "acceptanceCriteria": ["live and dead teammate rows with yes/no, time, first line", "busy/idle from existing pane class helper", "no teammates when none"], "modelTier": "standard"}
```

### Task 7: Rules for report files and late messages

**Goal:** `claude/worker.md` and `claude/orchestrator.md` carry the report-file and late-message rules.

**Files:**
- Modify: `claude/worker.md` (section "If you are a teammate")
- Modify: `claude/orchestrator.md` (the bullet list under "Rules")

**Acceptance Criteria:**
- [ ] worker.md has the bullet of Step 1 verbatim, placed before the `Context learned:` bullet.
- [ ] orchestrator.md has the bullet of Step 2 verbatim, after the "Replacing a stalled teammate" bullet.

**Verify:** `grep -c 'Write your report file before' claude/worker.md && grep -c 'tmux-ctl teammates' claude/orchestrator.md`

**Steps:**

- [ ] **Step 1:** In `claude/worker.md`, section "If you are a teammate", insert before the bullet that starts `- Your report ends with \`Context learned:\``:

```markdown
- Write your report file before you send the done message, and name its path in the message. Messages
  can reach the lead late; the file is what the lead reads first.
```

- [ ] **Step 2:** In `claude/orchestrator.md`, under "## Rules", insert after the bullet that starts `- Replacing a stalled teammate or subagent:`:

```markdown
- Teammate messages can arrive late or not at all. When a teammate looks idle, or a `<name> stopped at …`
  reminder appears, read its report file before waiting longer (`tmux-ctl teammates` lists who stopped
  and when). Act once on a report: a late duplicate message changes nothing.
```

- [ ] **Step 3:** Run the Verify line; each count is `1`.
- [ ] **Step 4:** Commit: `git add claude/worker.md claude/orchestrator.md && git commit -m "docs(rules): teammates write the report file first; the lead reads it when a teammate stops"` with your harness's attribution trailer.

```json:metadata
{"files": ["claude/worker.md", "claude/orchestrator.md"], "verifyCommand": "grep -c 'Write your report file before' claude/worker.md && grep -c 'tmux-ctl teammates' claude/orchestrator.md", "acceptanceCriteria": ["worker.md bullet verbatim before Context learned", "orchestrator.md bullet verbatim after Replacing a stalled teammate"], "modelTier": "mechanical"}
```

### Task 8: Dream `--all` passes over empty cores

**Goal:** `dream run --all` prints nothing for a project whose core has no entry lines; entries + no root still prints `skipped, no repo root`; `run <project>` is unchanged.

**Files:**
- Modify: `board/dream.py` (`main`, the `for n in names:` loop)
- Test: `board/tests/test_dream.py` (new class after `AllTest`)

**Acceptance Criteria:**
- [ ] `--all` with an empty core `e` (skeleton only) and core `p` with entries, no root: output is exactly `dream: p skipped, no repo root\n`.
- [ ] `run e` (named) still prints `dream: e skipped, no repo root`.
- [ ] Mutation: remove the `continue` → `test_all_passes_over_an_empty_core` fails with `dream: e skipped, no repo root` in the output.

**Verify:** `python3 -m unittest discover -s board/tests -p 'test_dream.py'`

**Steps:**

- [ ] **Step 1: Write the failing tests** — add after `class AllTest` in `board/tests/test_dream.py`:

```python
class AllSkipEmptyTest(DreamBase):
    def test_all_passes_over_an_empty_core(self):
        # mutation: remove the `continue` in dream.main's --all loop -> "dream: e skipped, no repo root" appears
        (self.D / "e.md").write_text(context.skeleton("e"))
        rc, out = self.run_dream("--all", project=None, root=False)
        self.assertEqual(out, "dream: p skipped, no repo root\n")
        self.assertEqual(rc, 0)

    def test_named_empty_project_still_reports(self):
        (self.D / "e.md").write_text(context.skeleton("e"))
        rc, out = self.run_dream(project="e", root=False)
        self.assertEqual(out, "dream: e skipped, no repo root\n")
```

- [ ] **Step 2: Run, expect FAIL** — `python3 -m unittest discover -s board/tests -p 'test_dream.py' -k AllSkipEmpty` → `test_all_passes_over_an_empty_core` fails: the output also has `dream: e skipped, no repo root`. `test_named_empty_project_still_reports` passes already.

- [ ] **Step 3: Implement** — in `board/dream.py` `main`, change the loop head:

```python
    for n in names:
        if a.all and _empty_core(n):
            continue
        try:
```

and add above `main`:

```python
def _empty_core(project):
    """True when the project's core has no '- ' entry lines (only title, Last curated and headings)."""
    try:
        return not context.entries(context.context_path(project).read_text())
    except OSError:
        return False
```

- [ ] **Step 4: Run, expect PASS** — the Verify line passes (whole `test_dream.py`, including `AllTest`).
- [ ] **Step 5: Commit** — `git add board/dream.py board/tests/test_dream.py && git commit -m "fix(dream): --all passes over a project whose core has no entries"` with your harness's attribution trailer.

```json:metadata
{"files": ["board/dream.py", "board/tests/test_dream.py"], "verifyCommand": "python3 -m unittest discover -s board/tests -p 'test_dream.py'", "acceptanceCriteria": ["--all empty core e + p no root -> only p's skipped line", "run e named still reports skipped no repo root", "mutation: remove continue -> test fails"], "modelTier": "mechanical"}
```

### Task 9: Full suite and the gate runbook items

**Goal:** The whole suite passes on the branch, and the post-merge real check is written into the remote runbook.

**Files:**
- Modify: `tools/tests/e2e-remote-discord-only.md` (new section "Group 1: teammate requests and reminders" with the three items of the spec's Testing "one real check", each with its observation and the command that shows it)

**Acceptance Criteria:**
- [ ] `zsh tools/tests/all.zsh` verdict line reads ALL PASS (a time-budget-only rc is reported with the line).
- [ ] The runbook section has three `- [ ]` items: a real teammate request answered from Discord; a teammate killed while its request waits gets Deny within a minute (`tmux-ctl discord audit --since <ISO>` shows `stale-deny`); the reminder line appears in the lead when a teammate stops (`tmux-ctl teammates` shows the stop).

**Verify:** `zsh tools/tests/all.zsh; echo rc=$?`

```json:metadata
{"files": ["tools/tests/e2e-remote-discord-only.md"], "verifyCommand": "zsh tools/tests/all.zsh; echo rc=$?", "acceptanceCriteria": ["all.zsh ALL PASS", "runbook has three group 1 items with commands"], "modelTier": "mechanical"}
```

### Task 10: User gate: teammate requests and reminders on the real setup

**Goal:** After the merge, the user runs the three group 1 runbook items on the real setup.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none

**Acceptance Criteria:**
- [ ] A real teammate's request in the lead's window is posted to Discord with the `(in the lead's window)` header and answered from the phone.
- [ ] A teammate killed while its request waits gets Deny pressed within a minute (audit shows `stale-deny`).
- [ ] The reminder line appears in the lead when a teammate stops.

**Verify:** `tmux-ctl discord audit --since <gate start ISO> | grep -E 'stale-deny|dialog'`

```json:metadata
{"files": [], "verifyCommand": "tmux-ctl discord audit --since <gate start ISO> | grep -E 'stale-deny|dialog'", "acceptanceCriteria": ["lead-window request posted and answered from the phone", "killed teammate's request denied within a minute, audit stale-deny", "reminder line appears when a teammate stops"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
