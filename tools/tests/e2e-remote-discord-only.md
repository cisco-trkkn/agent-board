# e2e: remote means Discord-only (spec C), run by the user on the phone

Not automated: it needs the real bots, the phone and the real `claude`. Tick a box only after you saw the stated
observation. Spec: `docs/superpowers/specs/2026-11-19-remote-discord-only-design.md`. Use a scratch project (a throwaway
git directory opened with `dev`, with its own bot: `docs/INSTALL.md` → "Remote access"). Replace `<project>`.

## Preconditions, in this order (after the merge to `main`)

1. The branch is merged and `main` is checked out in the main checkout: `git -C ~/agent-board log -1 --format=%s`.
2. Before any restart, the read-only check on the real tmux server: `zsh ~/agent-board/tools/tests/check_real_dialog_show.zsh`
   ends `REAL CHECK PASS: <n> panes` (it sends no key; it is not in `all.zsh` because it reads the real server).
3. Message Content Intent is on for every bot whose bridge runs. Human gate: it is a switch in the Discord Developer
   Portal (Bot → Privileged Gateway Intents) and cannot be read from here. Project bots have it from the install steps.
4. Bridges first, so no `dialog` op meets an old bridge: `tmux-ctl discord bridge stop && tmux-ctl discord bridge start`
   in each project with a bridge, then `tmux-ctl discord bridge --ops stop && tmux-ctl discord bridge --ops start`.
   Check: `tmux-ctl discord status` shows `bridge: running` (a bridge that exits at once lacks the intent of line 3).
5. The board: `agent-board dash stop && agent-board dash start`.
6. The scratch project's lead, so it loads the new hooks: `agent-board lead --continue` in its `claude` window.
   Check: `/hooks` lists `remote-ask-guard.sh` (`remote-marker.sh` is not registered yet: lead ruling F13).
7. You are away from the Mac's keyboard for items 1 to 7: answer only on the phone.

## Items

- [ ] **1. The remote marker.** From the phone, send the scratch lead: "ping, then try AskUserQuestion once to ask me yes or no". Expect its answer on Discord as a numbered list (the guard denied the dialog). On the Mac (or ask the lead to run it): `ls -l ${TMPDIR:-/tmp}/tmux-ctl-$UID/remote/` shows a file named after the lead's session id, minutes old.
- [ ] **2. A lead asks in Discord, not in a dialog.** From the phone: "ask me which of two colours I prefer, as a
  question". Expect a numbered list in Discord, no ❓ dialog message, and the lead's reply naming the hook's text if
  it tried AskUserQuestion.
Before item 3: clear the markers so a plain `claude` may open dialogs: `rm -f ${TMPDIR:-/tmp}/tmux-ctl-$UID/remote/*` (ask the scratch lead to run it).
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
- [ ] **9. A user gate.** In the scratch lead, ask it to create a pending task with the subject
  `User gate: try the gate button`. Expect within about 20 s a `🚧 <project> · user gate: User gate: try the gate button`
  message with `Done` / `Not yet`. Tap `Not yet`: the message and its buttons stay. Tap `Done`: the message reads
  `→ Done (from Discord)` and the lead receives the line `[Discord] gate done User gate: try the gate button`.
Before item 10: repeat item 1's message to the scratch lead, so a marker is fresh again (an idle item is posted only then).
- [ ] **10. A typed-answer wait.** In the plain `claude` window: "ask me for one word in plain text, not with
  AskUserQuestion, and wait for my answer". When it stops, expect `❓ <project> · <window> is waiting for your reply`
  with its last screen lines and only `Reply`. Reply "banana" to that message: the pane gets `banana` typed and
  submitted, and the message reads `→ banana (from Discord)`.
- [ ] **11. Keys and screens checked only on recordings.** Tick each when you have seen it on a real pane; open ones
  are recorded, they do not block closing: the trust dialog answered from Discord (both rows); the plan-approval
  dialog's rows 1 and 2; the resume picker; a multi-select with the cursor moved onto `Submit` or onto
  `Chat about this` at the keyboard before tapping; a multi-select with a box ticked at the keyboard before `Submit`
  from Discord; a permission prompt in a window whose task list is 28 rows or longer (expected NOT to reach Discord:
  a known limit of the board's 40-row capture).
- [ ] **12. A hook inside a teammate.** In the scratch lead, start a teammate and have it try `AskUserQuestion`.
  Expect the deny text `ask the lead with SendMessage; the user is not at your window` in its window and no dialog.
  This probes the environment a hook sees inside a teammate, which was not probed when the plan was written.

## Group 1: teammate requests and reminders

Precondition: group 1 is merged, and the bridge, board and scratch lead are restarted as in Preconditions 4-6 above.
Take `<ISO>` from before you start: `date -u +%FT%TZ`.

- [ ] **G1. A teammate's request in the lead's window.** In the scratch lead, ask it to start one teammate named `prober`
  that runs `touch probe`. Setup: the scratch lead's repo has `.claude/settings.json` holding
  `{"permissions": {"ask": ["Bash(touch probe)"]}}`, so the call asks (a `deny` rule would never ask). Expect a `🔐 <project> · prober (in the lead's
  window) wants to …` message on Discord. Tap Allow once, then expect the message to read `→ … (from Discord)`.
  Command: `tmux-ctl discord audit --since <ISO> | grep dialog`.
- [ ] **G2. A gone teammate's request is denied.** Repeat G1, but kill `✦ prober` (`tmux kill-window -t '=<session>:✦ prober'`)
  while the request waits. Within a minute, expect the message edited to `→ denied: prober is gone` and the feed line
  `denied stale request from prober (window gone)`. Command: `tmux-ctl discord audit --since <ISO> | grep stale-deny`.
- [ ] **G3. The reminder when a teammate stops.** Ask the scratch lead to start a teammate that writes one line and stops
  without messaging. Expect the reminder `prober stopped at HH:MM: <first line> — read its report file.` in the lead, and
  `tmux-ctl teammates` (run by the lead) showing the row with that time.
- [ ] **G4. An in-process teammate.** Same as G3 with teammate mode in-process, if the scratch lead offers it
  (`teammateMode`). Tick it or note "not available".
- [ ] **G5. A wrapped auto-mode countdown.** In an 80-column `✦` pane in auto mode, trigger a prompt with the
  `⚠ … will automatically block this request in M:SS` row. Expect ONE Discord message for it, not one per tick. Before
  answering, save `tmux capture-pane -p -J -t <pane> > /tmp/countdown-80.txt` and hand it to the lead as a real fixture,
  since the current one is synthetic.
- [ ] **G6. A foreground subagent's prompt has no `from`.** In a lead pane, run one foreground subagent whose prompt asks
  for permission. While it waits, run
  `tmux-ctl dialog <pane> show | python3 -c 'import json,sys; print(json.load(sys.stdin).get("from"))'`. Expect `None`;
  a name there means the stale Deny could press No on it after 30 s.
- [ ] **G7. A waiting box and a real dialog on one screen.** When a teammate's "waiting on the lead" box and a real dialog
  are both on its screen, note whether the dialog still posted to Discord (the pane class scans 20 rows).
