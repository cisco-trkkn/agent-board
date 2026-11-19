# Remote means Discord-only (spec C)

Date: 2026-11-19 · Decided with the user over Discord, 2026-11-19 (spec C of the PCEE revision order A, C, B)

## Problem

While the user is remote, anything that waits on a terminal dialog freezes until they are back at the Mac. Discord
today covers teammate and worker permission prompts (🔐 Allow once / Deny), merge approvals, the queue controls and
messages to a lead. It does not cover the rest. On 2026-11-19 the interiors lead sat on a "Republish now / Not yet"
question dialog from 00:13Z onward, and the user's Discord messages queued behind it.

## Decisions (user, Discord, 2026-11-19)

- **Q1, scope: all of these** (answer "1"):
  a. lead and teammate question dialogs (AskUserQuestion);
  b. the lead's own permission prompts and peer-session prompts;
  c. prompts that offer only "always allow" / "don't ask again" rows;
  d. startup dialogs (trust folder, resume picker, login expiry);
  e. user gates and the board's "Needs you" items.
- **Q2, both a rule and a net** (answer "1"): a lead never opens a dialog while the user is remote and asks in Discord
  as a numbered list instead, enforced by a hook; and the bridge, not an AI, mirrors any dialog that still appears as
  one Discord button per option, so a tap presses it.
- **Q3, detection: generalize the 🔐 path** (answer "1"): `tmux-ctl dialog <win> show|press` reads any Claude Code
  dialog from the pane text; a tap re-checks the exact text before pressing. Covers leads, teammates, peers and
  startup screens where no hook runs.
- **Q4, permanent rows: shown, with a confirm step** (answer "1"): "don't ask again", "always allow", "switch to auto
  mode", "accept edits" rows get buttons; a tap asks "this allows X from now on: Confirm / Cancel" before pressing.
- **Q5, multi-select and Other: full support** (answer "1"): multi-select becomes toggle buttons plus Submit; "Other"
  asks the user to reply to the message, and the bridge types the reply into the dialog after re-checking it.
- **Q6, the hook's reach** (answer "1"): leads are blocked from AskUserQuestion while remote; teammates and workers
  are always blocked (they ask the lead).
- **Design part 1 (the pieces) approved** ("I approve the spec c design", 02:36Z).

## Design

### 1. `tmux-ctl dialog <win> show|press`

A new module `tools/lib/dialog.zsh`, built from `tools/lib/approve.zsh` (which stays, as the 🔐 path's backend, until
the board moves to `dialog`; then `approve` becomes a thin wrapper).

- `show` prints JSON: `{kind, question, options: [{n, label, permanent}], multi, other, lines}`.
  - `kind`: `permission` | `question` | `trust` | `resume` | `login` | `unknown`.
  - `lines`: every line of the dialog between its rules, exactly as the pane shows it (the `--expect` text).
  - `permanent`: true for a row whose label matches "don't ask again", "always allow", "switch to auto mode",
    "accept edits" (case-insensitive substrings, one list in the module).
  - `multi`: true when the options carry checkboxes; `other`: true when a free-text row is present.
  - No dialog on screen: rc 1, `dialog: none in <win>`. Copy mode: rc 1, `dialog: <win> is in copy mode`.
- `press <win> --expect "<lines>" (--option <n>… | --text "<reply>")`: re-reads the pane, presses only when `lines` is
  byte-identical, then re-reads once more and prints `dialog: <win>: chose "<label>"`. For multi-select, `--option` is
  repeated and the module toggles each then submits. For `--text`, it selects the Other row and types the text
  literally (`send-keys -l`), then Enter. A changed dialog: rc 1, `dialog: the dialog in <win> changed`, nothing
  pressed.
- `unknown` dialogs are shown (question and option rows as parsed), never pressed with a permanent flag guessed: an
  unparsed row is `permanent: true`, so it always takes the confirm step.

### 2. Board: the dialog scanner and the Discord message

- `board/discord_dialogs.py`, run from the same tick as `discord_controls.step`, over every project's `needs_you` list
  plus every pane of the tmux server whose command is `claude` and whose screen classifies as waiting (`paneclass`),
  so peers and startup screens are included.
- One Discord message per distinct dialog (key: pane id plus a hash of `lines`), to the project's home channel; a
  pane outside any project with a bridge goes to the ops bridge's #approvals.
  - Header: `❓ <project> · <window>: <question>` (or `🔐` for `permission`).
  - One button per option, `ab:dlg:<key>:<n>`; a permanent row's button is red and opens the confirm step
    (`ab:dlg:<key>:<n>:confirm` / `:cancel`), whose text names what is allowed from now on.
  - Multi-select: toggle buttons `ab:dlg:<key>:t<n>` that edit the message to show the current picks, and `Submit`.
  - Other: a `Reply` button; the next reply to that message from an allowlisted user becomes `--text`.
- A tap writes a click event; the consumer runs `tmux-ctl dialog <win> press --expect …` and audits the result.
- When the dialog leaves the screen without a Discord press, the message is edited to `answered at the terminal`
  and its buttons removed. After a Discord press it reads `→ <label> (from Discord)`.
- The existing 🔐 teammate path is replaced by this one (same buttons for a permission dialog); `discord_controls`
  keeps its react and merge handling.
- Named dialog kinds (amendment, user OK on Discord 2026-11-19, ideas d8293803c6 + 15f9db31fc): besides
  AskUserQuestion and permission prompts, the parser recognises and tests the plan-approval dialog (`ExitPlanMode`:
  approve / keep planning, with the "auto-accept edits" row treated as permanent and confirmed), and the
  handoff skill's relay question. Each gets its own fixture in `tools/tests/fixtures/dialogs/`; any other dialog
  still reaches Discord through the generic parse.

### 3. Hooks: the remote marker and the AskUserQuestion block

- Remote marker: a `UserPromptSubmit` hook writes `<state>/remote/<session id>` when the prompt contains a
  `<channel source="plugin:discord:discord"` tag from the allowlist, and removes it when a prompt has no channel tag
  (typed in the terminal).
- `PreToolUse` hook on `AskUserQuestion`: a teammate or worker session (the existing `AGENT_BOARD_LEAD` /
  teammate env markers) is always denied with "ask the lead with SendMessage; the user is not at your window". A
  lead session with the remote marker is denied with "the user is remote: ask in Discord as a numbered list with the
  reply tool". A peer session (a `claude` pane that is neither a lead, a teammate nor a worker) is denied while
  any remote marker under `<state>/remote/` is younger than 12 h, with "the user is remote: write the question as
  plain text and end your turn; it reaches Discord as a Needs you item" (amendment, user OK on Discord
  2026-11-19). Otherwise allowed.
- `claude/orchestrator.md` and `claude/worker.md`: one line each pointing at the hook's behaviour (the rules
  already say this; the hook enforces it).

### 4. User gates and "Needs you" (scope e)

- A pending user-gate task posts, once, a Discord message with its acceptance criteria and two buttons: `Done`
  (writes a `[Discord] gate done <task>` line to the lead, which still re-validates with its verifyCommand) and
  `Not yet`.
- A "Needs you" item whose pane shows a dialog is handled by §2; one that does not (an idle lead waiting on a typed
  answer) posts its last screen lines with a `Reply` button whose reply is typed into that pane after the same
  idle re-check.

## Error handling

- Parse failure on a waiting pane: the message shows the raw `lines` and only a `Reply` button.
- A press against a changed dialog: the message is edited to `the dialog changed; re-sent below`, and the new dialog
  gets its own message.
- The bridge is down: messages wait in the outbox as today; presses are never retried after the dialog changed.
- Two taps on one button: the second is audited `already answered` and presses nothing.

## Testing

- `dialog show` on captured pane fixtures of each kind, from real Claude Code screens (permission, question,
  multi-select, Other, trust folder, resume picker, login), with the exact `lines`; `press` against a scratch tmux
  pane (`tools/tests/lib.zsh`) that prints the keys it got; changed-dialog refusal; copy-mode refusal.
- Board: message shape per kind, confirm step for permanent rows, toggles + Submit, Reply → `--text`, edit on
  disappearance, double tap, audit lines.
- Hooks: remote marker set and cleared; AskUserQuestion denied for a teammate always and for a remote lead, allowed
  for a local lead.
- User gate: on the phone, answer a real question dialog, a permanent-row permission prompt (confirm step), a
  multi-select and an Other reply in a scratch project; then a lead tries AskUserQuestion while remote and asks in
  Discord instead.

## Out of scope

- Phone escalation (pushes, calls) for dialogs left unanswered: spec B.
- Answering dialogs by an AI on the user's behalf: never.
