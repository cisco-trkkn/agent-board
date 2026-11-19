# Remote Means Discord-Only (Spec C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-extended-cc:subagent-driven-development (recommended) or superpowers-extended-cc:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** While the user is remote, every Claude Code dialog on the tmux server (questions, permission prompts, permanent rows, startup screens) and every user gate reaches Discord as buttons that press the dialog, and a hook stops agents from opening question dialogs the user cannot see.

**Architecture:** `tmux-ctl dialog <win> show|press` (new `tools/lib/dialog.zsh`, built from `tools/lib/approve.zsh`) reads any dialog from pane text and presses it only after re-checking the exact text. A new board module `board/discord_dialogs.py` scans every waiting `claude` pane each tick, posts one Discord message per distinct dialog through a new `dialog` outbox op, and consumes the bridge's click and reply events by running `tmux-ctl dialog … press`. The bridge handles the confirm step, the multi-select toggles and the reply listener locally, so a tap answers at once. Two plugin hooks set a remote marker and deny `AskUserQuestion` by role.

**Tech Stack:** zsh (`tmux-ctl`, `tools/tests` on a scratch tmux server), Python 3 (board, unittest), Node.js (discord.js bridge, `node --test`), bash/python hooks (`claude/plugin/scripts`).

**Spec:** `docs/superpowers/specs/2026-11-19-remote-discord-only-design.md` (read all of it, including the amendment lines in §2 and §3; the spec wins over this plan wherever they differ, except the Assumption lines below).

## Global Constraints

**CLI (`tmux-ctl dialog`), exact strings**

- `tmux-ctl dialog <win> show` prints one JSON object on stdout, rc 0: `{"kind", "question", "options": [{"n", "label", "permanent"}], "multi", "other", "lines"}`.
- `kind` is one of `permission` | `question` | `trust` | `resume` | `login` | `unknown`. The plan-approval dialog (`ExitPlanMode`) and the handoff skill's relay question are kind `question`.
- `permanent` is true when the label contains, case-insensitive, one of: `don't ask again`, `always allow`, `switch to auto mode`, `accept edits` (one list in the module; `'` and `’` both match, the real screens use `’`). An unparsed row is `permanent: true`.
- `lines`: every line of the dialog exactly as the pane shows it, with two normalisations: trailing whitespace is dropped, and the auto-mode countdown time is written `M:SS` (the mask `approve.zsh` line 112 uses). The same screen captured twice gives byte-identical `lines`.
- No dialog: rc 1, stderr `dialog: none in <win>`. Copy mode: rc 1, `dialog: <win> is in copy mode`.
- `tmux-ctl dialog <win> press --expect "<lines joined by newline>" (--option <n>… | --text "<reply>")`: on success rc 0 and `dialog: <win>: chose "<label>"` (multi-select: the labels joined by `, `; `--text`: the typed text). A changed dialog: rc 1, `dialog: the dialog in <win> changed`, no key sent.
- `<win>` is a window name of the session, or a pane id (`%<digits>`) anywhere on the server. The board always passes the pane id.

**Board and bridge, exact values**

- Dialog key: `p<pane number>-<first 16 hex of sha1("\n".join(lines))>` (pane `%12` → `p12-…`). Key regex: `p[0-9]+-[0-9a-f]{16}`.
- Button custom ids: option `ab:dlg:<key>:<n>`; confirm step `ab:dlg:<key>:<n>:confirm` and `ab:dlg:<key>:<n>:cancel`; multi-select toggle `ab:dlg:<key>:t<n>`; `ab:dlg:<key>:submit`; `ab:dlg:<key>:reply`. User gate: `ab:gate:<gkey>:done`, `ab:gate:<gkey>:notyet`, `gkey` = `g` + first 12 hex of `sha1(project + "\0" + subject)`.
- Header: `❓ <project> · <window>: <question>`; `🔐 <project> · <window>: <question>` for kind `permission`. The message body under the header is `lines` in a code block (cut at 1500 characters, as `PROMPT_MAX` in `bridge.js`).
- Button styles: ordinary option 2, permanent row 4 (red; in a dialog message red is used for permanent rows only), toggle 2 unpicked and 3 picked, `Submit` 1, `Reply` 1, confirm step `Confirm` 4 and `Cancel` 2. Button label: `<n>. <label>` cut to 80 characters. At most 20 option buttons; beyond that the text gains `… <k> more options: answer at the terminal`.
- Confirm step text (ephemeral): `this allows <label> from now on`, with `Confirm` / `Cancel`.
- Message edits (header line kept, buttons removed, this text on the second line): `answered at the terminal`; `→ <label> (from Discord)`; `the dialog changed; re-sent below`. A second tap on an answered dialog is audited `already answered` and presses nothing.
- Audit lines (`discord_feed.audit_append`): action `dialog`, `dialog-reply` or `gate`; results `pressed: <label>`, `already answered`, `needs confirm`, `changed`, `not pressed: <first line>`, `ignored`, `rejected`, `done`, `not yet`.
- New outbox op: `{"op": "dialog", "key", "text", "rows": [[{"label", "style", "custom_id"}, …], …], "mention_user": bool}` (at most 5 rows of at most 5 buttons). `edit` gains an optional `rows` of the same shape; without it `edit` removes the buttons as today.
- New bridge events: clicks as today (`{type: "click", custom_id, user, message_id, channel_id, ts}`), `Submit` with an added `picks: [<n>, …]`; replies as `{type: "reply", key, text, user, message_id, ts}`.
- Routing: a pane whose project has a channel (`discord_feed.channel_of(project)`) posts to that project's outbox; any other pane posts to the ops dir (`tc_env.ops_dir()`), where the bridge sends `dialog` ops to `#approvals`; neither configured means no post and no state.
- Dialog state: `tc_env.agent_base() / "dialogs" / "state.json"` under its own `flock` (`state.lock`). `discord_dialogs` never takes the ops-state lock (`discord_ops._state`): `discord_ops.consume` holds it while it calls `_click`.

**Hooks, exact values**

- Marker: `<state>/remote/<session id>` (`<state>` = `TC_STATE_DIR` of `tools/lib/tc-env.zsh`). Peer window: a marker younger than 12 h (43200 s, by mtime).
- Channel tag (probe, lead transcript `78659598`, 2026-11-19): `<channel source="plugin:discord:discord" chat_id="…" message_id="…" user="…" user_id="…" ts="…">`.
- Deny texts, verbatim: teammate or worker `ask the lead with SendMessage; the user is not at your window`; remote lead `the user is remote: ask in Discord as a numbered list with the reply tool`; peer `the user is remote: write the question as plain text and end your turn; it reaches Discord as a Needs you item`.
- Roles: worker = `TC_ROLE=worker` (set by `tmux-ctl agent`); lead = `AGENT_BOARD_LEAD=1` (set by `bin/claude-orchestrator`); teammate = the Claude process's argv holds `--agent-id` or the pane's window option `@tc_teammate` is `1` or the hook payload has `agent_id`; peer = none of these. Probe (this plan's author, a teammate, 2026-11-19): `ps -o args= -p $CLAUDE_PID` → `…/versions/2.1.328 --agent-id c-planner@session-78659598 --agent-name c-planner --team-name … --parent-session-id …`; `tmux display -p -t "$TMUX_PANE" '#{@tc_teammate}|#{@tc_agent}'` → `1|`; `AGENT_BOARD_LEAD` and `TC_ROLE` unset.

**Process**

- Scratch tmux servers start with `-f /dev/null` (`~/.local/bin/tmux -L <sock> -f /dev/null …`); `tools/tests/lib.zsh` `tt_setup` already does. Agent Bash runs zsh: quote `=name` targets, brace variables before a colon, never name a variable `path`.
- The live install runs from the main checkout. No task before the merge restarts or signals the board, a bridge, the overseer or a lead, writes to a real `<agent_base>/discord/*` directory, or sends anything to real Discord. Restarts are listed, in order, in Task 11's precondition.
- Never press an "always" / "don't ask again" row of a real dialog during a capture or a test: it writes a rule into the user's settings.
- Commit messages: conventional with scope (`feat(tmux-ctl): …`, `feat(board): …`, `feat(bridge): …`, `feat(hooks): …`, `test(fixtures): …`, `docs(…): …`); end with the attribution trailer your harness specifies. Stage only the files your task names.

**Assumptions (planner, to confirm with the lead):**

- Assumption: `<win>` of `tmux-ctl dialog` also accepts a pane id, because §2 covers panes outside any project and a window name cannot address them.
- Assumption: `lines` masks the auto-mode countdown as `M:SS` and drops trailing whitespace; without that the key would change every second and post a new message per tick.
- Assumption: the confirm step and the multi-select toggles are handled inside the bridge (the board ticks every 10 s); the board still refuses a permanent row without `:confirm`.
- Assumption: Q5's "reply to the message" is implemented literally: the bridge adds a `messageCreate` listener and the `MessageContent` intent (the channel plugin on the same bot already requests it). The same reply also reaches a lead through the channel plugin; `claude/orchestrator.md` tells the lead it was already typed.
- Assumption: a project dialog posts only to that project's home channel; the `#approvals` copy of teammate prompts (`discord_ops.mirror_prompt`) goes away with the 🔐 path. The bridge keeps its `prompt` op and `ab:perm:` handler for messages already posted.
- Assumption: the `AskUserQuestion` hook is a plugin hook, so it reaches only sessions that load the agent-board plugin (leads, teammates, workers, the overseer); a plain `claude` peer is covered by the dialog mirror alone (Q3: "where no hook runs").
- Assumption: whether a `UserPromptSubmit` hook fires for a Discord channel message is not known (the transcript row has `isMeta: true`, `promptSource: "system"`, `origin.kind: "channel"`). Task 8 keeps the spec's hook and adds a fallback that reads the same fact from the transcript; Task 11 checks the marker on the phone.
- Assumption: the marker is removed only by a prompt typed at the terminal: a prompt with no `<channel ` tag that does not start with `<teammate-message`, `<task-notification` or `<cross-session-message`. Otherwise every teammate report would clear it.
- Assumption: "a pending user-gate task" is a lead task with `"userGate": true` in its `json:metadata` fence or a subject starting `User gate:`, status `pending`, and no unfinished `blockedBy` task. It posts once per project and subject, so a relay's new task list does not repost it.
- Assumption: a "Needs you item without a dialog" is (a) a waiting pane whose dialog does not parse, and (b) a `claude` pane that is not a teammate or worker, does not hold a Discord channel, and turns `ready` after working while a remote marker younger than 12 h exists. The code has no other signal for "waiting on a typed answer".
- Assumption: login expiry cannot be captured without logging the user's account out, and the resume picker and plan-approval dialog may not appear in a scratch session; a kind Task 1 could not capture has no parser branch and no invented fixture, reaches Discord through the generic parse, and is an item of Task 11.

**User decisions (already made):**

- Q1 scope: "all of these": lead and teammate question dialogs; the lead's own and peer-session prompts; "always allow" / "don't ask again" rows; startup dialogs; user gates and "Needs you" items.
- Q2: "both a rule and a net": a hook blocks the dialog, and the bridge, not an AI, mirrors any dialog that still appears as one button per option.
- Q3: "generalize the 🔐 path": `tmux-ctl dialog <win> show|press` reads any dialog from the pane text; a tap re-checks the exact text before pressing.
- Q4: permanent rows are "shown, with a confirm step".
- Q5: multi-select and Other get "full support": toggle buttons plus Submit; Other asks the user to reply to the message.
- Q6: leads are blocked from `AskUserQuestion` while remote; teammates and workers always.
- Amendments (2026-11-19): peer sessions are denied while any remote marker is younger than 12 h; the plan-approval dialog and the handoff relay question are named, tested kinds.
- Out of scope: phone escalation for unanswered dialogs (spec B); an AI answering dialogs for the user (never).

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/tests/fixtures/dialogs/*.txt`, `expect/*.json`, `README.md`, `check.py` | real captured dialog screens, their oracles, the key probes (Task 1) |
| `tools/lib/dialog.zsh` | parse a dialog from pane text (`show`), press it (`press`), type a reply (`type`) (Tasks 2, 3, 9) |
| `bin/tmux-ctl` | the `dialog` case and help lines (Tasks 2, 3) |
| `tools/lib/approve.zsh` | thin wrapper over `dialog.zsh` (Task 4) |
| `tools/discord-bridge/bridge.js`, `lib/state.js`, `README.md` | `dialog` op, `edit` rows, confirm step, toggles, reply listener (Task 5) |
| `board/discord_feed.py` | `_check` shapes for `dialog` and `edit.rows` (Task 5) |
| `board/discord_dialogs.py` | scan, message shape, lifecycle, click and reply consumer, gates (Tasks 6, 7, 9) |
| `board/discord_controls.py`, `board/discord_ops.py`, `board/server.py` | wiring; the old 🔐 scan removed (Task 7) |
| `tools/lib/tc-env.zsh` | `TC_PROMPT_RE` covers every captured dialog (Task 6) |
| `claude/plugin/scripts/remote-marker.sh`, `remote-ask-guard.sh`, `claude/plugin/hooks/hooks.json` | the remote marker and the `AskUserQuestion` block (Task 8) |
| `claude/orchestrator.md`, `claude/worker.md` | one line each (Task 8) |
| `tools/tests/e2e-remote-discord-only.md` | the user gate's runbook (Task 10) |

---

### Task 1: Capture real dialog fixtures and key probes

**Goal:** `tools/tests/fixtures/dialogs/` holds real Claude Code screens of each dialog kind that a scratch session can show, an oracle JSON per screen, and a table of the keys that answer each kind.

**Files:**
- Create: `tools/tests/fixtures/dialogs/trust.txt`, `question-single.txt`, `question-multi.txt`, `question-two.txt`, `question-handoff.txt`, and `plan.txt`, `resume.txt` when they can be captured
- Create: `tools/tests/fixtures/dialogs/expect/<name>.json` (one per `.txt`)
- Create: `tools/tests/fixtures/dialogs/README.md`
- Create: `tools/tests/fixtures/dialogs/check.py`

**Acceptance Criteria:**
- [ ] The five required fixtures exist, each a `tmux capture-pane -p -J` of a 200x50 pane running a real `claude` on a scratch tmux server started with `-f /dev/null`.
- [ ] Each `expect/<name>.json` has exactly the keys `kind`, `question`, `options` (`n`, `label`, `permanent`), `multi`, `other`, written by reading the screen, and every label appears on the screen.
- [ ] `README.md` has the sections `## Commands used`, `## Key probes`, `## Not captured`, `## Redaction`, `## Cleanup evidence`, a table row for every `.txt`, and the `claude --version` used.
- [ ] `## Key probes` states, from keys actually sent, for each of permission (cite `fixtures/approve/README.md`), single question, multi-select, two-question, trust: the keys that choose option n, toggle a checkbox, submit, and enter free text in the Other row.
- [ ] `## Not captured` names every kind without a fixture (login always; plan or resume if the attempt failed) and why.
- [ ] No fixture holds a `/Users/` path; no "always" / "don't ask again" row was pressed; the scratch server and directory are gone (`ps` count 0).

**Verify:** `python3 -I tools/tests/fixtures/dialogs/check.py`

**Steps:**

- [ ] **Step 1: Write the checker** (`tools/tests/fixtures/dialogs/check.py`, run by the plan's author on an empty, a valid and a mutated sample):

```python
#!/usr/bin/env python3
"""check.py: structure check of the dialog fixtures. Run: python3 -I tools/tests/fixtures/dialogs/check.py
Every *.txt here needs expect/<name>.json (the oracle `dialog show` is tested against) and a row in README.md."""
import json
import sys
from pathlib import Path

D = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
REQUIRED = ["trust", "question-single", "question-multi", "question-two", "question-handoff"]
KINDS = {"permission", "question", "trust", "resume", "login", "unknown"}
bad = []
readme = (D / "README.md").read_text(encoding="utf-8") if (D / "README.md").is_file() else ""
names = sorted(p.stem for p in D.glob("*.txt"))
for want in REQUIRED:
    if want not in names:
        bad.append(f"missing fixture {want}.txt")
for sec in ("## Commands used", "## Key probes", "## Not captured", "## Redaction", "## Cleanup evidence"):
    if sec not in readme:
        bad.append(f"README.md lacks the section {sec!r}")
for n in names:
    text = (D / f"{n}.txt").read_text(encoding="utf-8")
    if "/Users/" in text:
        bad.append(f"{n}.txt holds a /Users/ path")
    if f"`{n}.txt`" not in readme:
        bad.append(f"README.md has no row for `{n}.txt`")
    try:
        e = json.loads((D / "expect" / f"{n}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as x:
        bad.append(f"expect/{n}.json: {type(x).__name__}")
        continue
    if set(e) != {"kind", "question", "options", "multi", "other"}:
        bad.append(f"expect/{n}.json keys are {sorted(e)}")
        continue
    if e["kind"] not in KINDS or not isinstance(e["question"], str) or type(e["multi"]) is not bool or type(e["other"]) is not bool:
        bad.append(f"expect/{n}.json has a bad kind, question, multi or other")
    opts = e["options"]
    if not (isinstance(opts, list) and opts and all(
            isinstance(o, dict) and set(o) == {"n", "label", "permanent"} and type(o["n"]) is int
            and isinstance(o["label"], str) and o["label"] and type(o["permanent"]) is bool for o in opts)):
        bad.append(f"expect/{n}.json options are not a non-empty list of {{n, label, permanent}}")
        continue
    rows = [" ".join(l.split()) for l in text.splitlines()]
    for o in opts:
        if not any(" ".join(o["label"].split()) in r for r in rows):
            bad.append(f"expect/{n}.json label {o['label']!r} is not on the screen in {n}.txt")
for b in bad:
    print("FAIL - " + b)
print(f"fixtures: {len(names)} checked, {len(bad)} problems")
sys.exit(1 if bad else 0)
```

Run it now: expected `fixtures: 0 checked, 10 problems`, rc 1 (five missing fixtures, five missing README sections).

- [ ] **Step 2: Start the scratch server** (snippet run once by the plan's author without `claude`; it printed the pane as `%0 200x50` and left 0 processes):

```zsh
S="$(mktemp -d "${TMPDIR:-/tmp}/dlgcap.XXXXXX")"; S="${S:A}"; git -C "$S" init -q
T=(~/.local/bin/tmux -L dlgcap-$$ -f /dev/null)
"${T[@]}" new-session -d -s dc -x 200 -y 50 -c "$S"
# type a line:  "${T[@]}" send-keys -t "=dc:" -l -- "<text>"; "${T[@]}" send-keys -t "=dc:" Enter
# capture:      "${T[@]}" capture-pane -p -J -t "=dc:" | sed "s|$S|/tmp/scratch|g" > tools/tests/fixtures/dialogs/<name>.txt
# at the end:   "${T[@]}" kill-server; rm -rf "$S"; ps -ax -o args= | grep -c "[d]lgcap-$$"    # expect 0
```

- [ ] **Step 3: Capture, in this order.** Start `claude --permission-mode default` in the pane (a plain `claude`: no `--plugin-dir`, so no agent-board hook interferes). Poll `capture-pane` until the dialog is drawn before saving.
  1. `trust.txt`: the folder-trust screen of the fresh directory, before any key. Then probe its keys (the approve README found that a digit does not move its selection) and answer Yes.
  2. `question-single.txt`: send `Use the AskUserQuestion tool once and nothing else: question "Which fruit?", header "Fruit", multiSelect false, options "Apple" (description "red") and "Pear" (description "green").` Capture, then probe: the key that chooses option 2; the keys that reach the free-text row, type `hello` and submit it (two runs of the same request).
  3. `question-multi.txt`: the same request with `multiSelect true` and a third option "Plum". Capture, then probe the toggle and submit keys.
  4. `question-two.txt`: one AskUserQuestion call with two questions ("Which fruit?" and "Which size?" with options "Small", "Large"). Capture the first screen; note in the README what the screen shows after the first answer.
  5. `question-handoff.txt`: `Use the AskUserQuestion tool once and nothing else: question "Switch to a fresh orchestrator now?", options "Yes" (description "This window restarts as a new orchestrator that starts from the doc and respawns the team. This session stays resumable.") and "Not yet" (description "Keep this session. I'll print the doc path and the command to switch later.").` (the wording of `claude/plugin/skills/handoff/SKILL.md` step 4). Answer Not yet.
  6. `plan.txt` (attempt): exit, start `claude --permission-mode plan`, send `Plan how to add a file hello.txt containing hi, then present the plan for approval.` Capture the approval dialog; answer the "keep planning" row. If no dialog appears after two tries, list it under `## Not captured`.
  7. `resume.txt` (attempt): exit, run `claude --resume` in the same directory; capture the picker; leave it with Esc. If it shows no picker, list it under `## Not captured`.
  8. Login expiry: do not attempt. List it under `## Not captured` ("needs the user's account logged out").

- [ ] **Step 4: Write each `expect/<name>.json`** by reading the saved screen: `kind` (`trust`, `question`, `resume`; `plan.txt` is `question`), the question text, each option's number and label as drawn, `permanent` by the substring list in Global Constraints, `multi`, `other`.

- [ ] **Step 5: Write `README.md`** in the format of `tools/tests/fixtures/approve/README.md` (capture date, `claude --version`, commands, the file table, the key probes, the redaction count `grep -c '/Users/'` per file, the cleanup evidence).

- [ ] **Step 6: Run the checker and commit**

Run: `python3 -I tools/tests/fixtures/dialogs/check.py` → `fixtures: <n> checked, 0 problems`, rc 0.

```bash
git add tools/tests/fixtures/dialogs
git commit -m "test(fixtures): real Claude Code dialog screens and key probes"
```

```json:metadata
{"files": ["tools/tests/fixtures/dialogs/README.md", "tools/tests/fixtures/dialogs/check.py", "tools/tests/fixtures/dialogs/trust.txt", "tools/tests/fixtures/dialogs/question-single.txt", "tools/tests/fixtures/dialogs/question-multi.txt", "tools/tests/fixtures/dialogs/question-two.txt", "tools/tests/fixtures/dialogs/question-handoff.txt"], "verifyCommand": "python3 -I tools/tests/fixtures/dialogs/check.py", "acceptanceCriteria": ["five required fixtures captured from a real claude on a scratch tmux server", "one expect JSON per fixture with kind, question, options, multi, other; every label on the screen", "README has Commands used, Key probes, Not captured, Redaction, Cleanup evidence and a row per fixture", "key probes recorded from keys actually sent for permission, single, multi, two-question, trust", "no /Users/ path, no permanent row pressed, scratch server gone"], "modelTier": "standard"}
```

---

### Task 2: `tmux-ctl dialog <win> show`

**Goal:** `tmux-ctl dialog <win> show` prints the JSON of any Claude Code dialog showing in a window or pane, read from the pane text alone, and sends no key.

**Constraints:**
- New module `tools/lib/dialog.zsh`, sourced by a new `dialog)` case in `bin/tmux-ctl` next to `approve)`; built from `tools/lib/approve.zsh` (its screen read, its option-run rule "only the contiguous run `1.` `2.` … counts", its ambiguity rules for a preview that fakes its own frame). `approve.zsh` is not changed in this task.
- Output, `kind`, `permanent`, `lines` and the error strings exactly as Global Constraints state them. `<win>` may be a pane id.
- An ambiguous permission prompt (`approve`'s `X:ambiguous` cases) is `kind: "unknown"` with every row `permanent: true`; it is still shown.
- Kinds are recognised only from real screens: `tools/tests/fixtures/approve/*.txt` (permission) and `tools/tests/fixtures/dialogs/*.txt`. A kind listed under `## Not captured` in the dialogs README gets no branch; such a screen is `unknown` through the generic parse (question = the last non-option text line above the option run, options = the numbered run).
- The teammate status divider (`──── @name ─`) after the footer is not part of the dialog and does not change the result (`approve/bash-teammate-divider.txt`).
- Byte-literal dividers and cursor, no locale-dependent class: `LC_ALL=C` gives the same output.

**Files:**
- Create: `tools/lib/dialog.zsh`
- Modify: `bin/tmux-ctl` (help header near line 39, a `dialog)` case after `approve)` near line 459)
- Create: `tools/tests/dialog_common.zsh` (scratch server and replay helpers, from `tools/tests/approve_common.zsh`), `tools/tests/test_ctl_dialog_show.zsh`
- Create: `tools/tests/check_real_dialog_show.zsh`

**Acceptance Criteria:**
- [ ] For every `tools/tests/fixtures/dialogs/<name>.txt`, `show` on a pane replaying it equals `expect/<name>.json` on `kind`, `question`, `options`, `multi`, `other` (compared as parsed JSON), rc 0.
- [ ] For `approve/bash-git.txt`: kind `permission`, question `Do you want to proceed?`, four options, option 2 (`Yes, and don’t ask again for: git config *`) and option 3 (`switch to auto mode`) `permanent: true`, options 1 and 4 false. For `approve/write.txt`: option 2 (`accept edits`) permanent.
- [ ] `lines` of `approve/bash-git.txt` holds the command line ` git config user.name probe-user` and every option row; `show` twice on one pane gives byte-identical output; `approve/bash-auto-countdown.txt` and a copy with another `M:SS` give identical `lines`.
- [ ] `approve/no-prompt.txt` and `approve/after-yes.txt`: rc 1, stderr `dialog: none in <win>`, empty stdout. A pane in copy mode: rc 1, `dialog: <win> is in copy mode`.
- [ ] `show` leaves the pane text and cursor unchanged and the pane receives no key (the `snap` and `got` checks of `test_ctl_approve_show.zsh`).
- [ ] The same result when `<win>` is the pane id, and under `LC_ALL=C`.
- [ ] Each test of a refusal names its mutation in a comment, and that mutation was run and failed (for example: drop the copy-mode check → the copy-mode test fails).
- [ ] Real state, read-only: `tools/tests/check_real_dialog_show.zsh` runs `show` on every pane of the real tmux server whose command is `claude`, and for each prints either `dialog` (valid JSON, rc 0) or `none` (rc 1 with the `dialog: none in` line); any other result fails. It ends with `REAL CHECK PASS: <n> panes` and sends no key.

**Verify:** `zsh tools/tests/test_ctl_dialog_show.zsh | tail -1; zsh tools/tests/check_real_dialog_show.zsh | tail -1`

```json:metadata
{"files": ["tools/lib/dialog.zsh", "bin/tmux-ctl", "tools/tests/dialog_common.zsh", "tools/tests/test_ctl_dialog_show.zsh", "tools/tests/check_real_dialog_show.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_dialog_show.zsh | tail -1; zsh tools/tests/check_real_dialog_show.zsh | tail -1", "acceptanceCriteria": ["show equals expect JSON for every dialogs fixture", "permission fixtures: permanent rows flagged by the substring list", "lines stable across captures and across the countdown time", "no dialog and copy mode: rc 1 with the exact messages", "show sends no key and leaves the pane unchanged", "pane id and LC_ALL=C give the same result", "every refusal test names a mutation that was run", "read-only real-state check over every live claude pane passes"], "modelTier": "frontier"}
```

---

### Task 3: `tmux-ctl dialog <win> press`

**Goal:** `tmux-ctl dialog <win> press --expect … (--option <n>… | --text …)` answers the dialog with the keys Task 1 recorded, and only when the dialog on screen is byte-identical to `--expect`.

**Files:**
- Modify: `tools/lib/dialog.zsh`, `bin/tmux-ctl` (help line)
- Modify: `tools/tests/dialog_common.zsh`
- Create: `tools/tests/test_ctl_dialog_press.zsh`

**Acceptance Criteria:**
- [ ] `press` reads the dialog, compares its `lines` joined by newlines with `--expect` byte for byte, reads once more and compares again, checks copy mode, then sends keys. Any difference: rc 1, `dialog: the dialog in <win> changed`, and the pane received nothing.
- [ ] The keys sent for each kind are the ones in the `## Key probes` table of `tools/tests/fixtures/dialogs/README.md` (permission: the digit alone, no Enter). The free text of `--text` goes through `tmux send-keys -l`.
- [ ] `--option` repeated on a multi-select toggles each option, then submits. `--option` repeated on a dialog that is not multi-select, `--option` with a number that is not an option, `--text` on a dialog with `other: false`, or neither or both of `--option` and `--text`: rc 2 usage error, nothing sent.
- [ ] Success prints `dialog: <win>: chose "<label>"` (multi: labels joined by `, `; text: the text), rc 0.
- [ ] `press` works on a worker window and with a pane id; it never chooses a row by position alone: the label of option n comes from the same read that matched `--expect`.
- [ ] `TC_DIALOG_BEFORE_SEND` (tests only, as `TC_APPROVE_BEFORE_SEND`) runs a command between the two reads; the swap test uses it.

**Verify:** `zsh tools/tests/test_ctl_dialog_press.zsh | tail -1`

**Steps:**

- [ ] **Step 1: Extend the replay pane to record every key.** `approve_common.zsh`'s pane reads one key. Add to `dialog_common.zsh` a pane script that, after showing the fixture, reads raw bytes until its stop file appears and prints `GOT:<lowercase hex of all bytes>` (`GOT:NONE` for nothing); `got <win>` returns that string. Check the helper first with `tt send-keys -t "=tt:<win>" 2` → `GOT:32`.

- [ ] **Step 2: Write the failing tests** in `tools/tests/test_ctl_dialog_press.zsh` (source `dialog_common.zsh`; each row is one `check`; `E` = the `lines` of `show` on that pane joined by newlines):

| name | fixture | call | expected |
|---|---|---|---|
| permission by digit | `approve/bash-git.txt` | `press --expect "$E" --option 1` | rc 0, `dialog: <win>: chose "Yes"`, `GOT:31` |
| permission permanent row | `approve/bash-git.txt` | `--option 2` | rc 0, chose `Yes, and don’t ask again for: git config *`, `GOT:32` (the confirm step is the caller's job) |
| single question | `dialogs/question-single.txt` | `--option 2` | rc 0, chose `Pear`, the README's bytes for option 2 |
| multi-select | `dialogs/question-multi.txt` | `--option 1 --option 3` | rc 0, chose `Apple, Plum`, the README's toggle and submit bytes |
| Other text | `dialogs/question-single.txt` | `--text "two words"` | rc 0, chose `two words`, the README's bytes, with `two words` literal |
| trust | `dialogs/trust.txt` | `--option 1` | rc 0, the README's bytes (not a bare digit) |
| changed: other command | `approve/bash-git.txt` | `--expect` of `approve/bash-touch.txt` | rc 1, `dialog: the dialog in <win> changed`, `GOT:NONE` |
| changed between reads | `approve/bash-git.txt`, `TC_DIALOG_BEFORE_SEND` respawns the pane with `bash-touch.txt` | `--option 1` | rc 1, changed, `GOT:NONE` |
| one byte off | any | `--expect "$E"` with one trailing space added to a line | rc 1, changed, `GOT:NONE` |
| copy mode | any, pane put in copy mode | `--option 1` | rc 1, `dialog: <win> is in copy mode`, `GOT:NONE` |
| no dialog | `approve/no-prompt.txt` | `--option 1` | rc 1, `dialog: none in <win>`, `GOT:NONE` |
| bad option | `approve/bash-git.txt` | `--option 9` | rc 2, `GOT:NONE` |
| two options, not multi | `approve/bash-git.txt` | `--option 1 --option 4` | rc 2, `GOT:NONE` |
| text without Other | `approve/bash-git.txt` | `--text x` | rc 2, `GOT:NONE` |
| no `--expect` | any | `--option 1` | rc 2, `GOT:NONE` |
| pane id | `approve/bash-git.txt` | `<win>` = the pane id | rc 0, `GOT:31` |

Mutations to run in RED and name in comments: remove the second read → "changed between reads" fails; compare trimmed text instead of bytes → "one byte off" fails; remove the copy-mode check → "copy mode" fails; send the digit for every kind → "trust" fails.

- [ ] **Step 3: Run it to see it fail**

Run: `zsh tools/tests/test_ctl_dialog_press.zsh | tail -3`
Expected: `FAIL` lines, because `dialog` has no `press` yet (usage error rc 2 on every call).

- [ ] **Step 4: Implement `press`** in `tools/lib/dialog.zsh`, following `approve_cmd` (`approve.zsh` lines 82-117): argument loop, `use_win`/`exists` only when `<win>` is not a pane id, first read, compare, `TC_DIALOG_BEFORE_SEND`, copy-mode check, second read, compare, copy-mode check, send, print. Differences from `approve_cmd`, each one deliberate: the compare is over all `lines` (not the `P:` preview lines); the option is chosen by number (not by the labels `Yes` / `No`); permanent rows are allowed; the keys depend on the kind.

- [ ] **Step 5: Run the tests, then the neighbours**

Run: `zsh tools/tests/test_ctl_dialog_press.zsh | tail -1` → `ALL PASS`
Run: `zsh tools/tests/test_ctl_dialog_show.zsh | tail -1` → `ALL PASS`

- [ ] **Step 6: Commit**

```bash
git add tools/lib/dialog.zsh bin/tmux-ctl tools/tests/dialog_common.zsh tools/tests/test_ctl_dialog_press.zsh
git commit -m "feat(tmux-ctl): dialog press re-checks the exact dialog text before any key"
```

```json:metadata
{"files": ["tools/lib/dialog.zsh", "bin/tmux-ctl", "tools/tests/dialog_common.zsh", "tools/tests/test_ctl_dialog_press.zsh"], "verifyCommand": "zsh tools/tests/test_ctl_dialog_press.zsh | tail -1", "acceptanceCriteria": ["two byte-identical reads before any key; a difference sends nothing and prints the changed message", "keys per kind are the README's probed keys; text goes through send-keys -l", "multi-select toggles then submits; invalid option/text combinations are rc 2 with nothing sent", "success prints dialog: <win>: chose \"<label>\"", "works on worker windows and pane ids", "TC_DIALOG_BEFORE_SEND seam drives the swap test"], "modelTier": "standard"}
```

---

### Task 4: `approve` becomes a thin wrapper over `dialog.zsh`

**Goal:** `tools/lib/approve.zsh` keeps its command line, messages and safety rules but takes its screen read, dialog detection, option list and key send from `tools/lib/dialog.zsh`.

**Files:**
- Modify: `tools/lib/approve.zsh`
- Modify: `tools/lib/dialog.zsh` (only to expose a function `approve.zsh` needs)

**Acceptance Criteria:**
- [ ] `git diff --stat main -- tools/tests/test_ctl_approve*.zsh tools/tests/approve_common.zsh tools/tests/fixtures/approve` is empty: no approve test or fixture changes.
- [ ] Every approve and dialog suite passes: the Verify line prints `fail=0` and the same `ok=` number as before the change. The approve files alone give `ok=97` on `main` at `550f934` (measured by the plan's author with this command restricted to them); the dialog suites add to it.
- [ ] `approve.zsh` no longer contains its own `capture-pane` call or its own awk prompt parser; `grep -c 'capture-pane' tools/lib/approve.zsh` prints 0.
- [ ] `tmux-ctl approve <win> once|deny --expect <text>` still presses only a row labelled exactly `Yes` or `No`, and `show` still prints `T:` and `P:` lines.

**Verify:** `out="$(for f in tools/tests/test_ctl_approve*.zsh tools/tests/test_ctl_dialog*.zsh; do zsh $f; done 2>&1)"; print -r -- "ok=$(print -r -- "$out" | grep -c '^ok ') fail=$(print -r -- "$out" | grep -c -E '^FAIL|FAILED$')"`

**Steps:**

- [ ] **Step 1: Record the baseline.** Run the Verify line before any edit. Expected: `fail=0` and `ok=` 97 plus the dialog suites' checks. Write the number down.

- [ ] **Step 2: Move the shared pieces.** `dialog.zsh` provides the screen read (today `_ap_screen`) and the tagged prompt block (today `_ap_prompt`'s `B:`/`P:`/`O:`/`X:` lines) as functions; `approve.zsh` sources `dialog.zsh` (same directory: `source "${${(%):-%x}:A:h}/dialog.zsh"`) and keeps only `approve_cmd`: the argument parsing, the `P:`-line compare with `--expect`, the `Yes`/`No` label rule, the countdown mask and its messages (`approve: …`). Differences between the two commands that must survive, checked by the unchanged tests: `approve --expect` compares the preview lines only, trimmed; `approve` refuses an ambiguous prompt; `approve` never presses a permanent row.

- [ ] **Step 3: Run the Verify line.** Expected: the same `ok=` number as Step 1 and `fail=0`. A lower `ok` means a suite died early: run that file alone and read its output.

- [ ] **Step 4: Commit**

```bash
git add tools/lib/approve.zsh tools/lib/dialog.zsh
git commit -m "refactor(tmux-ctl): approve reads and presses through dialog.zsh"
```

```json:metadata
{"files": ["tools/lib/approve.zsh", "tools/lib/dialog.zsh"], "verifyCommand": "out=\"$(for f in tools/tests/test_ctl_approve*.zsh tools/tests/test_ctl_dialog*.zsh; do zsh $f; done 2>&1)\"; print -r -- \"ok=$(print -r -- \"$out\" | grep -c '^ok ') fail=$(print -r -- \"$out\" | grep -c -E '^FAIL|FAILED$')\"", "acceptanceCriteria": ["no approve test or fixture file changes", "approve suites: 97 ok, 0 fail, plus the dialog suites", "approve.zsh has no capture-pane call and no parser of its own", "approve still presses only rows labelled exactly Yes or No"], "modelTier": "standard"}
```

---

### Task 5: Bridge `dialog` op, confirm step, toggles and the reply listener

**Goal:** The bridge posts a `dialog` op as a message with button rows, edits it with or without rows, answers permanent rows and toggles locally, and turns clicks and replies into events.

**Files:**
- Modify: `tools/discord-bridge/bridge.js`, `tools/discord-bridge/lib/state.js`, `tools/discord-bridge/README.md`
- Modify: `tools/discord-bridge/test/bridge.test.js`, `tools/discord-bridge/test/fake-client.js`
- Modify: `board/discord_feed.py` (`_check`, `_enforce_cap`), `board/tests/test_discord_feed.py`

**Acceptance Criteria:**
- [ ] `discord_feed._check` accepts `{"op": "dialog", "key", "text", "rows", "mention_user"}` and `edit` with an optional `rows`; rows are at most 5 lists of at most 5 `{label, style, custom_id}` (label and custom_id strings, style an int, custom_id at most 100 characters); anything else raises `ValueError`. `_enforce_cap` never drops a `dialog` op.
- [ ] `dialog` op: project mode sends to the home channel, ops mode to `#approvals` (`chan('approvals')`); content is `<@user> ` + text when `mention_user` and `bridge.json` has `user`, cut to 2000; components are the rows; `bridge-state.json` gains `dialogs[key] = message id` (newest 200 kept; `lib/state.js` defaults add `dialogs: {}` and `reply_armed: {}`).
- [ ] `edit` finds a key in `dialogs` too; with `rows` it keeps those components, without it removes them.
- [ ] Click `ab:dlg:<key>:<n>` on a button whose style is 4: an ephemeral answer `this allows <label> from now on` with `Confirm` (`ab:dlg:<key>:<n>:confirm`, style 4) and `Cancel` (`ab:dlg:<key>:<n>:cancel`, style 2); no event. `<label>` is the clicked button's label without its `<n>. ` prefix.
- [ ] `…:confirm`: the ephemeral message becomes `Sent.` and one click event is written with the full custom id. `…:cancel`: it becomes `Cancelled.`, no event.
- [ ] `ab:dlg:<key>:t<n>`: the message is updated in place (`i.update`) with that button's style flipped between 2 and 3 and every other component unchanged; no event. `ab:dlg:<key>:submit`: one click event with `picks` = the numbers of the buttons whose style is 3, ascending.
- [ ] `ab:dlg:<key>:reply`: an ephemeral `Reply to that message with your answer.`, and `reply_armed[<message id>] = key`; no event.
- [ ] `messageCreate`: a message from an allowlisted non-bot user whose `reference.messageId` is in `reply_armed` writes `{type: "reply", key, text, user, message_id, ts}` (text = the content, trimmed, at most 1000 characters) and disarms that message id. An unarmed message, a non-allowlisted user, a bot, or an empty content writes nothing. The client's intents gain `MessageContent`.
- [ ] Every other `ab:dlg:` and `ab:gate:` click of an allowlisted user is deferred and written as a click event, in project and in ops mode (in ops mode they no longer need the `ab:ops:` prefix); a non-allowlisted user gets `Not authorized.` and no event.
- [ ] README: the `dialog` op, `edit.rows`, the new ids and the `reply` event are described.

**Verify:** `(cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'); python3 -m unittest board.tests.test_discord_feed 2>&1 | tail -1`

**Steps:**

- [ ] **Step 1: Baseline.** Run the Verify line: `# pass 132`, `# fail 0`, `OK` (measured on `main` at `550f934`).

- [ ] **Step 2: Write the failing tests.** In `board/tests/test_discord_feed.py`: a valid `dialog` op is written; six rows, a row of six buttons, a non-int style, a 101-character custom id, a missing `mention_user` each raise `ValueError`; `edit` with valid `rows` is written and with a bad row raises; with 201 files in the outbox a `dialog` op is not the one removed. In `tools/discord-bridge/test/bridge.test.js`, one test per acceptance criterion above, using `fakeInteraction` (extend it with `component: {style, label}` and `message.components`) and a fake `messageCreate` message `{author: {id, bot}, content, reference: {messageId}, id}`. Name the mutations in comments: answer the permanent click by writing the event → the "no event" assertion fails; flip every button on a toggle → the "other components unchanged" assertion fails; skip the allowlist in `messageCreate` → the non-allowlisted reply test fails; skip the disarm → the "second reply writes nothing" test fails.

- [ ] **Step 3: Run to see them fail.** `(cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)')` → `# fail` above 0, for the missing handlers.

- [ ] **Step 4: Implement.** `bridge.js`: `opDialog` beside `opPost` (rows → `{type: 1, components: [{type: 2, style, label (80 max), custom_id}]}`), added to `handlers`; `opEdit` reads `op.rows` and searches `st.dialogs` (channel: `ops ? chan('approvals') : home()`); in `onInteraction`, before the `ab:ops:` branch, a branch for ids matching `^ab:dlg:(p[0-9]+-[0-9a-f]{16}):(t?[0-9]{1,2}|submit|reply)(?::(confirm|cancel))?$`; `onMessage` wired in `attach()` (`client.on('messageCreate', …)`, replacing the comment "no message listener"); `GatewayIntentBits.MessageContent` in `main()`. The confirm answer follows the existing `ab:ops:pause-all` code (`answer(i, text, components)`); the differences are the id shape and that `:cancel` exists.

- [ ] **Step 5: Run the Verify line.** Expected: `# fail 0`, `# pass` above 132, `OK`.

- [ ] **Step 6: Commit**

```bash
git add tools/discord-bridge/bridge.js tools/discord-bridge/lib/state.js tools/discord-bridge/README.md tools/discord-bridge/test/bridge.test.js tools/discord-bridge/test/fake-client.js board/discord_feed.py board/tests/test_discord_feed.py
git commit -m "feat(bridge): dialog op with button rows, confirm step, toggles and replies"
```

```json:metadata
{"files": ["tools/discord-bridge/bridge.js", "tools/discord-bridge/lib/state.js", "tools/discord-bridge/README.md", "tools/discord-bridge/test/bridge.test.js", "tools/discord-bridge/test/fake-client.js", "board/discord_feed.py", "board/tests/test_discord_feed.py"], "verifyCommand": "(cd tools/discord-bridge && npm test 2>&1 | grep -E '^# (pass|fail)'); python3 -m unittest board.tests.test_discord_feed 2>&1 | tail -1", "acceptanceCriteria": ["_check accepts the dialog op and edit.rows with the stated limits; a dialog op is never dropped by the cap", "dialog op posts to home or #approvals and records dialogs[key]", "edit keeps rows when given, removes buttons otherwise", "a red button opens the ephemeral confirm step and writes no event", "confirm writes one click event; cancel writes none", "toggle flips one button in place; submit carries picks", "reply button arms the message; an allowlisted reply writes one reply event and disarms", "MessageContent intent added; ab:dlg and ab:gate clicks become events in both modes", "README describes the op, ids and reply event"], "modelTier": "standard"}
```

---

### Task 6: `board/discord_dialogs.py`: scan, message shape and lifecycle

**Goal:** One function scans every waiting `claude` pane, posts one `dialog` op per distinct dialog with the right header and buttons, and edits the message to `answered at the terminal` when the dialog leaves the screen.

**Constraints:**
- New module `board/discord_dialogs.py`; pure functions plus file I/O like `discord_controls.py`. `run(argv) -> str` (raises on a non-zero exit) is injected, as in `discord_controls.step`; the module calls `tmux-ctl dialog <pane id> show` through it and nothing else touches tmux.
- Entry point `scan(sessions, now, run)`: `sessions` is the list `server.build_state()` returns under `"sessions"` (each `{name, windows: [{name, worker, teammate, panes: [{id, kind, status, discord, preview}]}]}`). It covers every pane with `kind == "claude"` and `status == "waiting"`, whatever its session.
- Key, header, body, button ids, styles, limits, routing, state path and lock exactly as Global Constraints. State record per key: pane, window, project (the session name), target dir, the `show` result and the header.
- Message shape by dialog: single choice → one button per option (red when permanent), plus `Reply` when `other`; multi-select → one toggle per option, `Submit`, plus `Reply` when `other`; a waiting pane where `show` reports no dialog or fails to parse → header `❓ <project> · <window>: (dialog not parsed)`, the pane's `preview` rows as the body, only `Reply`, record kind `raw`.
- `mention_user` is true on every dialog op.
- One failing pane never stops the scan of the others (as `discord_controls._show` treats errors); a `show` that errors for a known key leaves that key alone this tick.
- `tools/lib/tc-env.zsh` `TC_PROMPT_RE` (one single-quoted line, also parsed by `board/tc_env.py`) is extended only as far as needed for every fixture to classify as waiting.

**Files:**
- Create: `board/discord_dialogs.py`, `board/tests/test_discord_dialogs.py`
- Modify: `tools/lib/tc-env.zsh` (`TC_PROMPT_RE`), `board/tests/test_paneclass.py`

**Acceptance Criteria:**
- [ ] `paneclass.classify("claude", rows, False)` is `("claude", "waiting")` for the rows of every file in `tools/tests/fixtures/dialogs/*.txt` and of `approve/bash-git.txt`, `approve/write.txt`, `approve/bash-teammate-divider.txt`; it stays `("claude", "ready")` for `approve/no-prompt.txt` and `approve/after-yes.txt`. The test prints how many fixtures it checked.
- [ ] A waiting pane with a single-choice dialog writes exactly one `dialog` op: text starts `❓ proj · win: <question>` (`🔐` for permission), the body holds the `lines`, one button per option with id `ab:dlg:<key>:<n>` and label `<n>. <label>`, style 4 on permanent rows and 2 otherwise. A second scan of the same screen writes nothing.
- [ ] A multi-select writes toggles `ab:dlg:<key>:t<n>` and `ab:dlg:<key>:submit`; `other: true` adds `ab:dlg:<key>:reply`.
- [ ] 23 options: 20 option buttons and the line `… 3 more options: answer at the terminal`; a body over 1500 characters is cut.
- [ ] A pane in a session with a channel posts to `tc_env.discord_dir(<session>)`; a session without one posts to `tc_env.ops_dir()` when ops is configured, and nothing otherwise.
- [ ] The dialog leaves the screen (`dialog: none`), changes, or its pane disappears: one `edit` op whose text is the header line plus `answered at the terminal`, and the key leaves the state. A `show` error keeps the key.
- [ ] An unparsed waiting pane gets the raw message with only `Reply`.
- [ ] Two scans running at once (two threads on one state dir) post one message for one dialog; the state file is written atomically under the lock.
- [ ] Each absence test ("writes nothing", "keeps the key") names the mutation that makes it fail, and it was run.

**Verify:** `python3 -m unittest board.tests.test_discord_dialogs board.tests.test_paneclass board.tests.test_tc_env 2>&1 | tail -1`

```json:metadata
{"files": ["board/discord_dialogs.py", "board/tests/test_discord_dialogs.py", "tools/lib/tc-env.zsh", "board/tests/test_paneclass.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_dialogs board.tests.test_paneclass board.tests.test_tc_env 2>&1 | tail -1", "acceptanceCriteria": ["every dialog fixture classifies as waiting; idle fixtures stay ready", "one dialog op per distinct dialog with the exact header, ids, labels and styles", "multi-select toggles plus Submit; Reply when other", "20-button cap and 1500-character body cut", "routing: project channel, else ops #approvals, else nothing", "edit to answered at the terminal when the dialog leaves; show errors keep the key", "unparsed waiting pane: raw lines and only Reply", "concurrent scans post once", "absence tests name their mutation"], "modelTier": "frontier"}
```

---

### Task 7: Click and reply consumer, board wiring, the old 🔐 scan removed

**Goal:** A tap or a reply on a dialog message runs `tmux-ctl dialog <pane> press`, the message shows the outcome, every event is audited, and the board calls the scanner each tick in place of `discord_controls.scan_prompts`.

**Files:**
- Modify: `board/discord_dialogs.py`, `board/tests/test_discord_dialogs.py`
- Modify: `board/discord_controls.py`, `board/tests/test_discord_controls.py`
- Modify: `board/discord_ops.py`, `board/tests/test_discord_ops.py`
- Modify: `board/server.py` (`feed_tick`, near lines 502-534), `board/tests/test_discord_wiring.py`

**Acceptance Criteria:**
- [ ] The consumer accepts exactly these shapes; everything else is audited `ignored` and presses nothing:
  - `ab:dlg:<key>:<n>`, `<n>` matching `[1-9][0-9]?`: the key is in the state, option n exists, it is not permanent, the dialog is not multi-select → `press --option n`.
  - `ab:dlg:<key>:<n>:confirm`: option n exists and is permanent → `press --option n`.
  - `ab:dlg:<key>:submit` with `picks`: a non-empty list of distinct option numbers of a multi-select dialog, none permanent → `press --option a --option b …`.
  - `{type: "reply", key, text}`: the record has `other: true` → `press --text <text>`; the text has C0 control characters (newline, ESC, …) replaced by spaces and is cut to 1000 characters.
- [ ] Attempts that must press nothing, each with a test: a permanent row without `:confirm` (audit `needs confirm`); `:confirm` on a row that is not permanent; `ab:dlg:<key>:t2` reaching the consumer; `<n>` of `0`, `03`, `99` (no such option) and `1e1`; a key of another pane with the same hash part; `picks` holding a permanent or unknown number, or `picks` on a single-choice dialog; a reply for a dialog with `other: false`; a user not in `allowFrom` (audit `rejected`); a key not in the state (audit `already answered`).
- [ ] The press argv is `[tmux-ctl, "dialog", <pane id>, "press", "--expect", "\n".join(lines), …]` with the record's own `lines`.
- [ ] Outcomes: success → `edit` to the header plus `→ <label> (from Discord)`, key removed, audit `pressed: <label>`; an error starting `dialog: the dialog in` → `edit` to `the dialog changed; re-sent below`, key removed, audit `changed`, and the next scan posts the new dialog as its own message; any other error → `edit` to `⚠️ not pressed: <first line>`, key removed, audit `not pressed: <first line>`. A press is never retried.
- [ ] Delivery: the same event file consumed twice, or two taps on one button, press once; the second is audited `already answered`. The controls step and the ops consume running at once are serialised by the dialog state lock (a test runs two threads on one key and counts one press). A `:confirm` that arrives after the dialog was answered at the terminal is `already answered`. Events of two dialogs arriving in either order each act on their own key only.
- [ ] `discord_controls.consume_events` routes `ab:dlg:` clicks and `reply` events to `discord_dialogs`; `discord_ops._click` routes `ab:dlg:` clicks and `discord_ops.consume` routes `reply` events of the ops dir. `discord_controls.scan_prompts`, `_show`, `_perm` and the `prompts` state are removed; a leftover `perm` event is audited `unknown`. `discord_ops.mirror_prompt` and the `allow`/`deny` branch of `_click` are removed with their tests.
- [ ] `server.feed_tick` calls `discord_dialogs.scan` once per tick, before the per-project loop, with the sessions of the last state build plus the overseer session's panes (as `deliver_comments` receives them), and with a `run` that has no `TC_SESSION`. A scan error is logged and does not stop the feed tick.
- [ ] No test writes outside its temp `TC_STATE`.

**Verify:** `python3 -m unittest board.tests.test_discord_dialogs board.tests.test_discord_controls board.tests.test_discord_ops board.tests.test_discord_wiring 2>&1 | tail -1`

**Steps:**

- [ ] **Step 1: Baseline.** `python3 -m unittest board.tests.test_discord_controls board.tests.test_discord_ops board.tests.test_discord_wiring 2>&1 | tail -3` → `OK`; note the test count.

- [ ] **Step 2: Write the failing consumer tests** in `board/tests/test_discord_dialogs.py`: one test per accepted shape, per refused attempt and per outcome above, with the `Runner` fake of `test_discord_controls.py` adapted to `dialog` (record every argv; `show` answers from a dict; `press` returns `dialog: %5: chose "Yes"` or raises `RuntimeError("dialog: the dialog in %5 changed")`). Mutations to name and run: drop the permanent check → the "permanent without :confirm" test fails; drop the key lookup → "already answered" fails; skip the control-character replace → the reply test with `\n` fails; remove the key before the press result is known → the "changed" edit test fails.

- [ ] **Step 3: Run to see them fail** (`AttributeError` for the missing `click` / `reply` functions).

- [ ] **Step 4: Implement** `discord_dialogs.click(d, user, cid, ev, run, now)` and `discord_dialogs.reply(d, user, ev, run, now)`, each returning the audit result; the callers audit with `discord_feed.audit_append(d, user, "dialog" | "dialog-reply", <custom id or key>, result)` and check `allowFrom` first, as the `ab:ideas:` branch does.

- [ ] **Step 5: Rewire.** `discord_controls.py`: remove the prompt scan and `_perm`; add the two routes; update its docstring. `discord_ops.py`: the routes; remove `mirror_prompt` and the `allow`/`deny` click branch (`resolve` stays if `discord_merge` or another caller still uses it: check with `grep -n "resolve(" board/*.py`). `server.py`: the scan call. Rewrite the tests of the removed code as tests of the new routes; delete only tests whose subject is gone.

- [ ] **Step 6: Run the Verify line**, then the whole board suite: `python3 -m unittest discover -s board/tests 2>&1 | tail -1` → `OK`.

- [ ] **Step 7: Commit**

```bash
git add board/discord_dialogs.py board/discord_controls.py board/discord_ops.py board/server.py board/tests/test_discord_dialogs.py board/tests/test_discord_controls.py board/tests/test_discord_ops.py board/tests/test_discord_wiring.py
git commit -m "feat(board): dialog taps press through tmux-ctl dialog; the old prompt scan is gone"
```

```json:metadata
{"files": ["board/discord_dialogs.py", "board/discord_controls.py", "board/discord_ops.py", "board/server.py", "board/tests/test_discord_dialogs.py", "board/tests/test_discord_controls.py", "board/tests/test_discord_ops.py", "board/tests/test_discord_wiring.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_dialogs board.tests.test_discord_controls board.tests.test_discord_ops board.tests.test_discord_wiring 2>&1 | tail -1", "acceptanceCriteria": ["the consumer accepts exactly four event shapes; all else is ignored", "each listed bypass attempt presses nothing and is audited", "press argv carries the record's own lines as --expect", "success, changed and failed presses edit the message and audit as specified; never retried", "repeated, concurrent and out-of-order events press at most once per dialog", "controls and ops route dlg clicks and replies; scan_prompts, _perm and mirror_prompt removed", "feed_tick scans once per tick including the overseer session", "tests stay inside a temp TC_STATE"], "modelTier": "standard"}
```

---

### Task 8: Hooks: the remote marker and the `AskUserQuestion` block

**Goal:** A plugin hook keeps `<state>/remote/<session id>` in step with where the last user prompt came from, and a second hook denies `AskUserQuestion` for teammates and workers always, for a remote lead, and for a peer while any marker is younger than 12 h.

**Files:**
- Create: `claude/plugin/scripts/remote-marker.sh`, `claude/plugin/scripts/remote-ask-guard.sh`
- Modify: `claude/plugin/hooks/hooks.json`
- Create: `tools/tests/test_remote_marker.zsh`, `tools/tests/test_remote_ask_guard.zsh`
- Modify: `claude/orchestrator.md` (section "Remote: Discord"), `claude/worker.md` (section "Decide, don't ask")

**Acceptance Criteria:**
- [ ] `remote-marker.sh` (`UserPromptSubmit`; payload `prompt`, `session_id`): a prompt holding `<channel source="plugin:discord:discord"` whose `user_id` is in the `allowFrom` of any `<agent_base>/discord/*/access.json` creates or touches `<state>/remote/<session id>`; a prompt with no `<channel ` tag that does not start with `<teammate-message`, `<task-notification` or `<cross-session-message` removes it; any other prompt changes nothing. `session_id` must match `^[A-Za-z0-9_-]+$`. Any error: exit 0, no output.
- [ ] `remote-ask-guard.sh` (`PreToolUse`, matcher `AskUserQuestion`) denies with exit 2 and the exact text on stderr, by the roles of Global Constraints, checked in this order: payload `agent_id` present, `TC_ROLE=worker`, teammate marker → the teammate/worker text; `AGENT_BOARD_LEAD=1` with its own marker → the remote-lead text; no role and a marker under `<state>/remote/` with mtime within 43200 s → the peer text. Otherwise exit 0 with no output.
- [ ] Fallback for the open question in Assumptions: a lead without a marker whose payload `transcript_path` ends, among non-sidechain `type: "user"` rows that are not tool results, with a row whose `origin.kind` is `"channel"` and `origin.server` is `"plugin:discord:discord"`, is treated as remote, and the guard writes the marker.
- [ ] A tool other than `AskUserQuestion`, malformed JSON, and `REMOTE_ASK_GUARD=0` all exit 0 silently. `--scoped` is accepted and changes nothing.
- [ ] `hooks.json`: `remote-marker.sh --scoped` added to `UserPromptSubmit` (timeout 5), `remote-ask-guard.sh --scoped` added to the existing `AskUserQuestion` matcher after `plan-handoff-guard.sh` (timeout 10). `claude plugin validate claude/plugin` passes.
- [ ] `claude/orchestrator.md` gains one line under "While remote" and `claude/worker.md` one line under "Decide, don't ask", each saying a hook now denies `AskUserQuestion` in that case and what to do instead (the deny text's instruction).
- [ ] Probes cited in the script headers, each a command and its output from this task: the env names a hook process sees in a teammate (`CLAUDE_PID` or not), and whether `UserPromptSubmit` fired for a `<teammate-message` prompt.

**Verify:** `zsh tools/tests/test_remote_marker.zsh | tail -1; zsh tools/tests/test_remote_ask_guard.zsh | tail -1; python3 -c "import json; json.load(open('claude/plugin/hooks/hooks.json')); print('hooks.json ok')"`

**Steps:**

- [ ] **Step 1: Probe the hook environment** (no live session is touched). On a scratch tmux server (`-f /dev/null`), start `claude -p "say hi" --settings <tmp settings>` whose `UserPromptSubmit` hook is `env | cut -d= -f1 | sort > <tmp>/env-names; cat > <tmp>/payload.json`. Record which of `CLAUDE_PID`, `TMUX_PANE`, `AGENT_BOARD_LEAD`, `TC_ROLE` appear and the payload's keys. The teammate case comes from this session if it is a teammate (`ps -o args= -p $PPID`), else from the probe in Global Constraints. Put the outputs in the script header comments.

- [ ] **Step 2: Write the failing tests**, following `tools/tests/test_plan_handoff_guard.zsh` (payload built by `python3 -c`, the hook run with stdin, `rc`/`out`/`err` captured; `TC_STATE` from `tt_setup` so markers land in the temp dir; never call the real `~/.local/state`).

`test_remote_marker.zsh` cases: discord tag with an allowlisted `user_id` → marker exists; the same with a `user_id` not in any `access.json` → no marker; typed prompt after a marker → removed; `<teammate-message teammate_id="x">` prompt after a marker → kept; `<channel source="plugin:telegram:telegram"` prompt → unchanged; `session_id` `../x` → nothing written anywhere under the temp dir (count the files); malformed JSON → rc 0, no output; a second discord prompt → mtime moves forward.

`test_remote_ask_guard.zsh` cases (each asserts rc and the exact stderr text): `TC_ROLE=worker` → teammate/worker text, with and without a marker; payload `agent_id` → the same; a fake teammate (the test sets `REMOTE_GUARD_ARGS="x --agent-id a@b"`, a test seam the script reads in place of `ps` when set) → the same; `AGENT_BOARD_LEAD=1` plus its marker → remote-lead text; `AGENT_BOARD_LEAD=1` without a marker → rc 0 silent; lead without a marker but a transcript whose last user row has the channel origin → remote-lead text and the marker now exists; no role, a marker 1 h old (`touch -t`) → peer text; no role, a marker 13 h old → rc 0; no role, no marker → rc 0; tool `Bash` → rc 0; `REMOTE_ASK_GUARD=0` → rc 0; malformed JSON → rc 0. One more case for the order: `AGENT_BOARD_LEAD=1` with no marker and a payload `agent_id` → the teammate/worker text (an in-process subagent of a local lead). Mutations to name and run: drop the age test → the 13 h case fails; test the lead branch before `agent_id` → the case just named passes silently and its check fails; skip the allowlist in `remote-marker.sh` → the non-allowlisted marker case fails.

- [ ] **Step 3: Run to see them fail** (the scripts do not exist: every check fails with "no such file").

- [ ] **Step 4: Write the two scripts**, on the pattern of `claude/plugin/scripts/plan-handoff-guard.sh` (bash wrapper, `input=$(cat)`, `python3 -I` body, fail-open). Differences from that script, all needed: these read the environment (`TC_ROLE`, `AGENT_BOARD_LEAD`, `TMUX_PANE`, `TC_STATE`, `TMPDIR`, `HOME`), so pass those to python through the environment, not argv; the state dir follows `tools/lib/tc-env.zsh` (`${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}`, trailing slash of `TMPDIR` dropped) and the discord base follows `board/tc_env.py` `agent_base()` (`$TC_STATE`, else `$HOME/.local/state/agent-board`); the teammate check runs `ps -o args= -p <CLAUDE_PID or PPID>` and `tmux display -p -t "$TMUX_PANE" '#{@tc_teammate}'` (binary: `${TC_TMUX:-$HOME/.local/bin/tmux}`, socket from `$TMUX`, as `context-recall.sh` does).

- [ ] **Step 5: Register and document.** Edit `hooks.json`; add the two doc lines. Run `claude plugin validate claude/plugin` and paste its last line into the report.

- [ ] **Step 6: Run the Verify line**, then `zsh tools/tests/test_plan_handoff_guard.zsh | tail -1` and `zsh tools/tests/test_plugin.zsh | tail -1` → `ALL PASS` each.

- [ ] **Step 7: Commit**

```bash
git add claude/plugin/scripts/remote-marker.sh claude/plugin/scripts/remote-ask-guard.sh claude/plugin/hooks/hooks.json tools/tests/test_remote_marker.zsh tools/tests/test_remote_ask_guard.zsh claude/orchestrator.md claude/worker.md
git commit -m "feat(hooks): remote marker and the AskUserQuestion block by role"
```

```json:metadata
{"files": ["claude/plugin/scripts/remote-marker.sh", "claude/plugin/scripts/remote-ask-guard.sh", "claude/plugin/hooks/hooks.json", "tools/tests/test_remote_marker.zsh", "tools/tests/test_remote_ask_guard.zsh", "claude/orchestrator.md", "claude/worker.md"], "verifyCommand": "zsh tools/tests/test_remote_marker.zsh | tail -1; zsh tools/tests/test_remote_ask_guard.zsh | tail -1; python3 -c \"import json; json.load(open('claude/plugin/hooks/hooks.json')); print('hooks.json ok')\"", "acceptanceCriteria": ["marker set by an allowlisted Discord tag, cleared only by a typed prompt, untouched otherwise", "guard denies teammates and workers always, a remote lead, and a peer within 12 h, with the exact texts", "transcript fallback marks a lead remote when the last user row came from the Discord channel", "other tools, bad JSON and the kill switch pass silently", "hooks.json registers both scripts and the plugin validates", "orchestrator.md and worker.md each gain one line", "hook-environment probes are cited in the script headers"], "modelTier": "standard"}
```

---

### Task 9: User gates and "Needs you" items without a dialog

**Goal:** A pending user-gate task posts once with its acceptance criteria and `Done` / `Not yet` buttons, and a pane that waits on a typed answer posts its last screen lines with a `Reply` button whose reply is typed only into an unchanged pane.

**Files:**
- Modify: `board/discord_dialogs.py`, `board/tests/test_discord_dialogs.py`
- Create: `board/tests/test_discord_gates.py`
- Modify: `tools/lib/dialog.zsh`, `bin/tmux-ctl` (help line), `tools/tests/test_ctl_dialog_press.zsh`
- Modify: `board/server.py` (`feed_tick`: pass the lead tasks), `board/discord_controls.py`, `board/discord_ops.py` (route `ab:gate:` clicks)

**Acceptance Criteria:**
- [ ] `discord_dialogs.gates(project, lead_tasks, now)`: for each lead task that is a user gate by the Assumption in the header (metadata `userGate: true` or subject starting `User gate:`; status `pending`; every `blockedBy` task completed), one `dialog` op, once per `gkey`: text `🚧 <project> · user gate: <subject>` then the acceptance criteria as `- ` lines (from metadata `acceptanceCriteria`, else the lines under `**Acceptance Criteria:**` in the description; cut to 1500 characters), buttons `Done` (`ab:gate:<gkey>:done`, style 3) and `Not yet` (`ab:gate:<gkey>:notyet`, style 2). A project without a channel uses the ops dir, as dialogs do.
- [ ] `Done` → `add_line(project, "[Discord] gate done <subject>")`, `edit` to the first line plus `→ Done (from Discord)`, audit `gate` / `done`. `Not yet` → audit `not yet`, the message and its buttons stay. A second `Done` → `already answered`, no second line. A user not in `allowFrom` → `rejected`.
- [ ] A gate seen under a new task list id (a relay) with the same project and subject does not post again; a completed gate never posts; a blocked gate posts on the first tick after its last blocker completes.
- [ ] `tmux-ctl dialog <win> type --expect "<rows>" --text "<reply>"`: captures the pane, takes its last non-empty rows above the input box's rule (as many as `--expect` has), and only when they are byte-identical to `--expect`, the pane is not in copy mode, and the input line holds no typed text (the rule of `paneclass.input_has_text`), sends the text with `send-keys -l` and Enter, printing `dialog: <win>: typed`. Otherwise rc 1, `dialog: the screen in <win> changed`, nothing sent.
- [ ] Idle item: a `claude` pane that is not in a teammate or worker window, has `discord` false, and goes from `working` or `waiting` to `ready` between two scans while a marker under `<state>/remote/` is younger than 12 h gets one message: header `❓ <project> · <window> is waiting for your reply`, its `preview` rows as the body, only `Reply`. A pane already `ready` at the first scan after a board start posts nothing. The pane working again, or its screen changing, edits the message to `answered at the terminal`.
- [ ] A reply to an idle item or to a raw (unparsed) item runs `tmux-ctl dialog <pane> type --expect <the rows shown> --text <reply>`; outcomes and audit as in Task 7 (`→ <reply cut to 60> (from Discord)`, or `the dialog changed; re-sent below`).
- [ ] No marker, or only markers older than 12 h: no idle item is posted (the user is at the terminal).

**Verify:** `python3 -m unittest board.tests.test_discord_gates board.tests.test_discord_dialogs 2>&1 | tail -1; zsh tools/tests/test_ctl_dialog_press.zsh | tail -1`

**Steps:**

- [ ] **Step 1: Write the failing gate tests** in `board/tests/test_discord_gates.py` (temp `TC_STATE`; task dicts as `planview.raw_live_list` returns them: `{"id", "subject", "status", "description", "blockedBy"}`): metadata gate posts once; `User gate:` subject posts once; second tick writes nothing; pending with an unfinished blocker writes nothing, and posts after the blocker completes; completed gate writes nothing; same subject under another list id writes nothing; criteria come from metadata, and from the description when metadata has none; `Done` click → the exact `add_line` text, the edit, the audit; `Not yet` → audit only; second `Done` → `already answered`. Mutations: key the dedupe on the task id → the relay test fails; drop the blocker check → the blocked test fails.

- [ ] **Step 2: Write the failing `type` tests** in `test_ctl_dialog_press.zsh`: a replay pane showing `approve/no-prompt.txt` (an idle `❯` prompt): `type --expect <its last 5 rows above the rule> --text "option 2"` → rc 0, the hex of `option 2` plus Enter; one row different → rc 1, `dialog: the screen in <win> changed`, `GOT:NONE`; copy mode → rc 1, `GOT:NONE`; a variant fixture with typed text in the input line (made with `sed` from `no-prompt.txt`) → rc 1, `GOT:NONE`. Mutation: skip the input-text check → the typed-text case fails.

- [ ] **Step 3: Write the failing idle-item tests** in `test_discord_dialogs.py`: the transition posts once; ready at first sight posts nothing; a teammate window, a worker window and a `discord: true` pane post nothing; no fresh marker posts nothing; the reply runs `type` with the shown rows; working again edits to `answered at the terminal`.

- [ ] **Step 4: Run all three to see them fail**, then implement: `gates` and `gate_click` in `discord_dialogs.py` (state key `gates` in the same state file); the `type` subcommand in `dialog.zsh`; the idle tracking in `scan` (state key `last_status` per pane, in memory of the state file); the routes for `ab:gate:` in `discord_controls.consume_events` and `discord_ops._click`; `feed_tick` passes each project's `tasks` to `gates` inside its existing per-project `try`.

- [ ] **Step 5: Run the Verify line**, then `python3 -m unittest discover -s board/tests 2>&1 | tail -1` → `OK`.

- [ ] **Step 6: Commit**

```bash
git add board/discord_dialogs.py board/tests/test_discord_dialogs.py board/tests/test_discord_gates.py tools/lib/dialog.zsh bin/tmux-ctl tools/tests/test_ctl_dialog_press.zsh board/server.py board/discord_controls.py board/discord_ops.py
git commit -m "feat(board): user gates and typed-answer waits reach Discord"
```

```json:metadata
{"files": ["board/discord_dialogs.py", "board/tests/test_discord_dialogs.py", "board/tests/test_discord_gates.py", "tools/lib/dialog.zsh", "bin/tmux-ctl", "tools/tests/test_ctl_dialog_press.zsh", "board/server.py", "board/discord_controls.py", "board/discord_ops.py"], "verifyCommand": "python3 -m unittest board.tests.test_discord_gates board.tests.test_discord_dialogs 2>&1 | tail -1; zsh tools/tests/test_ctl_dialog_press.zsh | tail -1", "acceptanceCriteria": ["a pending, unblocked user-gate task posts once with its criteria and Done / Not yet", "Done writes the [Discord] gate done line, edits and audits; Not yet only audits; repeats are already answered", "a relay's new list does not repost; blocked and completed gates do not post", "dialog type sends text only into an unchanged screen with an empty input line", "a pane turning ready while a fresh remote marker exists posts its last lines with Reply, once", "replies to idle and raw items run dialog type with the rows shown", "no fresh marker: no idle item"], "modelTier": "standard"}
```

---

### Task 10: The gate runbook and the full suite

**Goal:** `tools/tests/e2e-remote-discord-only.md` holds the user gate's steps with every precondition and the command that creates it, and the whole test suite passes on the branch.

**Files:**
- Create: `tools/tests/e2e-remote-discord-only.md`
- Modify: `README.md` (one line in the `tmux-ctl` command list, if it lists `approve`)

**Acceptance Criteria:**
- [ ] The runbook exists with the text of Step 1, 8 numbered checkbox items, and a Preconditions section whose every line names its command or says "human gate" with the reason.
- [ ] `zsh tools/tests/all.zsh` ends with its one verdict line reporting 0 failed.
- [ ] `grep -c "ab:perm" board/*.py` prints 0 for every board file (the board no longer writes the old prompt path).

**Verify:** `grep -c '^- \[ \] \*\*' tools/tests/e2e-remote-discord-only.md; zsh tools/tests/all.zsh 2>&1 | tail -1`

**Steps:**

- [ ] **Step 1: Write `tools/tests/e2e-remote-discord-only.md`** with exactly this content:

```markdown
# e2e: remote means Discord-only (spec C), run by the user on the phone

Not automated: it needs the real bots, the phone and the real `claude`. Tick a box only after you saw the stated
observation. Spec: `docs/superpowers/specs/2026-11-19-remote-discord-only-design.md`. Use a scratch project (a throwaway
git directory opened with `dev`, with its own bot: `docs/INSTALL.md` → "Remote access"). Replace `<project>`.

## Preconditions, in this order (after the merge to `main`)

1. The branch is merged and `main` is checked out in the main checkout: `git -C ~/agent-board log -1 --format=%s`.
2. Message Content Intent is on for every bot whose bridge runs. Human gate: it is a switch in the Discord Developer
   Portal (Bot → Privileged Gateway Intents) and cannot be read from here. Project bots have it from the install steps.
3. Bridges first, so no `dialog` op meets an old bridge: `tmux-ctl discord bridge stop && tmux-ctl discord bridge start`
   in each project with a bridge, then `tmux-ctl discord bridge --ops stop && tmux-ctl discord bridge --ops start`.
   Check: `tmux-ctl discord status` shows `bridge: running` (a bridge that exits at once lacks the intent of line 2).
4. The board: `agent-board dash stop && agent-board dash start`.
5. The scratch project's lead, so it loads the new hooks: `agent-board lead --continue` in its `claude` window.
   Check: `/hooks` lists `remote-ask-guard.sh` and `remote-marker.sh`.
6. You are away from the Mac's keyboard for items 1 to 7: answer only on the phone.

## Items

- [ ] **1. The remote marker.** Send "ping" to the scratch lead from the phone. On the Mac (or ask the lead to run it):
  `ls -l ${TMPDIR:-/tmp}/tmux-ctl-$UID/remote/` shows a file named after the lead's session id, minutes old.
- [ ] **2. A lead asks in Discord, not in a dialog.** From the phone: "ask me which of two colours I prefer, as a
  question". Expect a numbered list in Discord, no ❓ dialog message, and the lead's reply naming the hook's text if
  it tried AskUserQuestion.
- [ ] **3. A real question dialog.** In a second window of the scratch project start a plain `claude` and type:
  "Use AskUserQuestion: which fruit, Apple or Pear?" Walk away. Expect a `❓ <project> · <window>: …` message with one
  button per option within about 20 s. Tap `2. Pear`. Expect the message to read `→ Pear (from Discord)` and the pane to
  show Pear chosen.
- [ ] **4. A permanent-row permission prompt.** In that plain `claude`: "run `git config user.name probe-user`". Expect a
  `🔐` message with a red `don’t ask again` button. Tap it: expect "this allows … from now on" with Confirm / Cancel. Tap
  Cancel: nothing is pressed. Tap the red button again, then Confirm: the command runs. Afterwards remove the rule this
  wrote: `/permissions` in that session lists it and deletes it.
- [ ] **5. A multi-select.** "Use AskUserQuestion with multiSelect: which fruits, Apple, Pear, Plum?" Tap Apple and Plum
  (each turns green), then Submit. Expect `→ Apple, Plum (from Discord)`.
- [ ] **6. An Other reply.** Ask the single-choice fruit question again. Tap Reply, then reply to that message with
  "kiwi". Expect `→ kiwi (from Discord)` and the pane to show kiwi as the answer.
- [ ] **7. Answered at the terminal, and a double tap.** Ask the question once more and answer it at the keyboard:
  the message becomes `answered at the terminal`. Ask again, tap one button twice quickly: one press, and
  `grep -h '"dialog"' ~/.local/state/agent-board/discord/*/audit.jsonl | tail -3` shows `already answered` for the second.
- [ ] **8. Kinds without a fixture.** For each kind under "Not captured" in `tools/tests/fixtures/dialogs/README.md`
  (login expiry; the resume picker or the plan-approval dialog if listed): the next time one shows on a real pane, run
  `tmux-ctl dialog <pane id> show > /tmp/<kind>.json` and `tmux capture-pane -p -J -t <pane id> > /tmp/<kind>.txt`
  before answering it, check it reached Discord, and hand both files to the lead as a new fixture.
```

- [ ] **Step 2: Run the whole suite** with `tmux-ctl run -t 1800 tests "zsh tools/tests/all.zsh"` (it runs longer than a Bash call allows) and read its last line. Expected: the verdict line with 0 failed. A failure in a file this plan did not touch: run that file alone on `main` first; if it fails there too, report it as pre-existing.

- [ ] **Step 3: Check the old path is gone and commit**

Run: `grep -c "ab:perm" board/*.py` → every line ends `:0`.

```bash
git add tools/tests/e2e-remote-discord-only.md README.md
git commit -m "docs(e2e): the remote Discord-only gate runbook"
```

```json:metadata
{"files": ["tools/tests/e2e-remote-discord-only.md", "README.md"], "verifyCommand": "grep -c '^- \\[ \\] \\*\\*' tools/tests/e2e-remote-discord-only.md; zsh tools/tests/all.zsh 2>&1 | tail -1", "acceptanceCriteria": ["the runbook has 8 items and a Preconditions section with a command or a human-gate reason per line", "all.zsh reports 0 failed", "no board file writes ab:perm"], "modelTier": "mechanical"}
```

---

### Task 11: User gate: dialogs answered on the phone

**Goal:** On the phone, in a scratch project on the merged `main`, the user answers a real question dialog, a permanent-row permission prompt through the confirm step, a multi-select and an Other reply, and a remote lead that tries `AskUserQuestion` asks in Discord instead; each observed as `tools/tests/e2e-remote-discord-only.md` items 1 to 7 state.

> **USER-ORDERED GATE — NON-SKIPPABLE.** This task was requested by the user in the current conversation. It MUST NOT be closed by walking around it, by declaring it "verified inline", or by substituting a cheaper check. Close only after every item in `acceptanceCriteria` has been re-validated independently, with output captured.

**Files:** none. It runs after the merge and needs the user on the phone. Precondition, in order (the runbook's Preconditions section): merged `main` checked out in the main checkout; Message Content Intent on for each bot (human gate, Developer Portal); `tmux-ctl discord bridge stop && tmux-ctl discord bridge start` per project, then `tmux-ctl discord bridge --ops stop && tmux-ctl discord bridge --ops start`, with `tmux-ctl discord status` showing `bridge: running`; `agent-board dash stop && agent-board dash start`; `agent-board lead --continue` in the scratch project's `claude` window.

**Acceptance Criteria:**
- [ ] Item 1: after a phone message, `<state>/remote/<lead session id>` exists (the `ls -l` output is captured).
- [ ] Item 2: the remote lead asks as a numbered list in Discord and opens no dialog.
- [ ] Item 3: a real question dialog is answered by one tap; the message reads `→ Pear (from Discord)`.
- [ ] Item 4: the red button opens the confirm step; Cancel presses nothing; Confirm presses the row.
- [ ] Item 5: a multi-select is answered with two toggles and Submit.
- [ ] Item 6: a reply to the message is typed into the dialog as the Other answer.
- [ ] Item 7: a dialog answered at the keyboard reads `answered at the terminal`; a double tap presses once and the audit shows `already answered`.
- [ ] Item 8 is recorded as open or done per kind listed under "Not captured"; it does not block closing.

**Verify:** `grep -h '"dialog' ~/.local/state/agent-board/discord/*/audit.jsonl | tail -12; ls -l ${TMPDIR:-/tmp}/tmux-ctl-$UID/remote/`

```json:metadata
{"files": [], "verifyCommand": "grep -h '\"dialog' ~/.local/state/agent-board/discord/*/audit.jsonl | tail -12; ls -l ${TMPDIR:-/tmp}/tmux-ctl-$UID/remote/", "acceptanceCriteria": ["after a phone message the lead's remote marker file exists", "a remote lead asks as a numbered list in Discord and opens no dialog", "a real question dialog is answered by one tap and reads → Pear (from Discord)", "a permanent row goes through Confirm / Cancel; Cancel presses nothing", "a multi-select is answered with toggles and Submit", "a reply to the message becomes the Other answer", "answered at the terminal edit and already answered on a double tap, seen in the audit", "kinds without a fixture are recorded as open or done"], "modelTier": "standard", "userGate": true, "tags": ["user-gate"]}
```
