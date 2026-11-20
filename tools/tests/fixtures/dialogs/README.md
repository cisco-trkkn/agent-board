# dialog fixtures: real Claude Code dialog screens

Captured 2026-11-19 from `claude --version` = **2.1.328 (Claude Code)** (Opus 5.5, effort medium), with
`tmux capture-pane -p -J -t "=dc:"` (full 200x50 pane) on a scratch tmux server (`-L dlgcap-<pid> -f /dev/null`)
in a scratch git dir. Plain `claude` sessions, no `--plugin-dir`. Each fixture has an oracle `expect/<name>.json`
(`kind`, `question`, `options` {n, label, permanent}, `multi`, `other`) written by reading the screen.
`check.py` verifies structure, that every label is on the screen, and that this README has a row per `.txt`.
The pane scrollback above the dialog (earlier prompts, banner) is part of the capture; the parser must look only at the dialog.

## Commands used

    S=$(mktemp -d /tmp/dlgcap.XXXXXX); git -C $S init -q
    tmux -L dlgcap-$$ -f /dev/null new-session -d -s dc -x 200 -y 50 -c $S
    tmux ... respawn-pane -k -t =dc: -c $S "claude --permission-mode default"   # then plan: "... --permission-mode plan"; resume: "claude --resume"
    # each request: send-keys -l -- "<text>"; sleep 1; send-keys Enter; poll capture-pane until 'Enter to select'
    tmux ... capture-pane -p -J -t =dc: | sed "s|$S|/tmp/scratch|g" > <name>.txt
    tmux ... kill-server; rm -rf $S

Requests are the ones in the task brief (AskUserQuestion with the stated question/options; plan: "Plan how to add a file
hello.txt containing hi, then present the plan for approval." in `--permission-mode plan`).

## Files

| file | screen |
|---|---|
| `trust.txt` | folder-trust dialog: `❯ No, exit` is the default row, 2 `Yes, I trust this folder`; footer `Enter to confirm · Esc to cancel` |
| `question-single.txt` | AskUserQuestion, 1 question, 2 options: rows 1 Apple, 2 Pear, 3 `Type something.` (the Other row, ends with a period), and below a rule 4 `Chat about this`; footer `Enter to select · ↑/↓ to navigate · Esc to cancel` |
| `question-multi.txt` | multiSelect: `N. [ ] label` rows 1-3, 4 `[ ] Type something` (no period), an unnumbered `Submit` row, below a rule 5 `Chat about this` |
| `question-two.txt` | one call, two questions: tab bar `←  ☐ Fruit  ☐ Size  ✔ Submit  →`, first question shown; footer `Tab/Arrow keys to navigate` |
| `question-handoff.txt` | the handoff skill's question: Yes / Not yet (each with a wrapped-free description line), 3 `Type something.`, 4 `Chat about this`; header chip `☐ Switch` |
| `plan.txt` | plan approval ("Ready to code?" plan box, then `Would you like to proceed?`): 1 `Yes, and use auto mode`, 2 `Yes, manually approve edits`, 3 `Tell Claude what to change` (sub-line `shift+tab to approve with this feedback`). No Other row |
| `resume.txt` | `claude --resume` picker: `Resume session`, search box, session rows without numbers (title line, then `<age> · <branch> · <size>`), `❯` marks the selected one |

| `team-request.txt` | LEAD pane (120x49) while a teammate's permission request shows: an ordinary Bash permission dialog whose header row is ` Bash command · from the prober agent` (row 38). Rows 37-49 are the dialog: top rule, header, tip, description, `╌` rule, command, `╌` rule, `Do you want to proceed?`, 1 `Yes`, 2 `Yes, and switch to auto mode · …`, 3 `No`, blank, footer `Esc to cancel · Tab to amend`. No oracle in `expect/` yet (see "Teammate request") |
| `team-waiting.txt` | TEAMMATE pane (79x49) at the same moment: the `╭…╮` box `✽ Waiting for team lead approval` / `⏺ @prober` / `Tool:    Bash` / `Action:  Create probe2 file` / `Permission request sent to team "session-7bb5ac65" leader` (rows 34-43), then the `─── @prober ─` divider, an empty `❯` prompt and the status rows. Not a dialog: no options, no key-hint footer |

## Teammate request (team-request.txt, team-waiting.txt)

Captured 2026-11-19 from `claude --version` = **2.1.329 (Claude Code)** (Opus 5.5, effort medium). Full setup, the hook
probes and the extra screens: `docs/superpowers/notes/2026-11-19-teammate-probes.md`.

    S=$(mktemp -d "${TMPDIR%/}/tmreq.XXXXXX"); git -C $S init -q      # .claude/settings.json: "ask": ["Bash(touch probe)"] + dump hooks
    env -i HOME=… USER=… SHELL=/bin/zsh TERM=xterm-256color LANG=… TMPDIR=… PATH=… \
      tmux -L tmreq-cap -f /dev/null new-session -d -s tr -x 200 -y 50 -c $S        # env -i: the caller was itself a teammate
    tmux … send-keys -t "=tr:" 'CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude --permission-mode default' Enter   # trust: Down, Enter
    # typed into the lead: "Create an agent team with one teammate named prober. Its whole task: run the Bash command `touch probe` …"
    # second request (the one saved): "Send prober a message asking it to run the Bash command `touch probe2` …"
    tmux … resize-pane -t "=tr:0.0" -x 120                                            # the split had left the lead 59 columns
    tmux … capture-pane -p -J -t "=tr:0.0" | sed "s|$S|/tmp/scratch|g" > team-request.txt
    tmux … capture-pane -p -J -t "=tr:0.1" | sed "s|$S|/tmp/scratch|g" > team-waiting.txt

- **Teammate mode:** split pane. Inside tmux, with no dev hooks, the teammate was a second pane of the lead's window
  (`backendType: tmux`, `tmuxPaneId: %1` in the team config), a separate `claude --agent-name prober …` process.
- **How the name appears, lead side:** only in the dialog's header row, as `<Tool title> · from the <name> agent`
  (` Bash command · from the prober agent`). The rest of the dialog is the same as the lead's own Bash prompt
  (`fixtures/approve/`), minus the permanent row: the options were 1 `Yes`, 2 `Yes, and switch to auto mode · …`, 3 `No`,
  while the lead's own prompt in the same session had 4 rows with 2 `Yes, and don’t ask again for: python3 *`.
- **How the name appears, teammate side:** `⏺ @prober` inside the box and `@prober` at the right end of the divider
  above the prompt. The pane banner shows the agent type (`@general-purpose`), not the name.
- **The lead need not be idle.** Seen three ways: (1) and (2) lead idle at its prompt after its turn ended: the
  request replaced the input box; (3) lead mid-turn, its own Bash tool running (`python3 -c "import time; time.sleep(50)"`):
  the request rendered under the running tool row at once. When the lead's own permission prompt was already showing,
  the teammate's request queued behind it: the lead's header row ended with `1 of 2`, and after that prompt was answered
  the teammate's request showed with `2 of 2` at the right end of its header row (` Bash command · from the prober agent … 2 of 2`).
- **In a narrow lead pane (59 columns)** option 2 wraps onto two rows (`   2. Yes, and switch to auto mode · auto mode handles` /
  `      these prompts for you`) and so does the tip row; the screen is in the notes file.
- **Keys really sent in the lead pane:** digit `1` alone approved (requests 1 and 2: the teammate ran the command); digit `3`
  alone denied (request 3: the teammate pane showed `Did not run 1 call` / `⎿  Not run · rejected`). Option 2 was never pressed.
- **Redaction:** the scratch dir became `/tmp/scratch` and its basename `scratch` (sed), which shortened two rows;
  `grep -c '/Users/\|/var/folders'` → 0 for both files.
- **Cleanup:** `kill-server`, `rm -rf $S`, the stale socket file removed; evidence in the notes file. Side effects as for the
  other fixtures: a trust entry in `~/.claude.json` and transcripts under `~/.claude/projects/` for the deleted path.

After-answer screens seen (not saved): single answered with `2` → `⏺ Answered Claude's questions: ⎿ · Which fruit? → Pear`;
multi and two-question end with a review screen (see probes).

## Key probes

All keys below were really sent (tmux `send-keys`). Permission prompts: see `fixtures/approve/README.md` (a digit alone
answers a permission prompt with no Enter; Down/Enter also works; the "always"/"don't ask again" row was never pressed).

| kind | choose option n | toggle | submit | free text in the Other row |
|---|---|---|---|---|
| permission | digit `n` alone (approve README) | n/a | the digit itself | n/a |
| single question | digit `n` alone answers at once (`2` → Pear) | n/a | the digit itself | `3` focuses the Other row (cursor `❯ 3.`, the row turns into the input), type `hello` (`send-keys -l`), `Enter` submits → `→ hello`. Digit `3` alone does NOT submit |
| multi-select | a digit only toggles `[ ]`↔`[✔]` (pressed `1` twice: on, off; `2` on); the cursor `❯` stays where it was | digit `n` (`4` toggled the Other row on with empty text; pressed again to clear) | `Down` x (rows+1) onto `Submit` then `Enter`, which opens a review screen `Review your answers`, `1. Submit answers` / `2. Cancel`; digit `1` there submitted | digit `4` toggles the row but typed text then goes nowhere (the cursor stays on row 1); instead `Down` x3 onto `❯ 4. [ ] Type something`, type `hello` (`send-keys -l`): the row becomes `❯ 4. [✔] hello` (auto-checked), then `Down` to `Submit`, `Enter`, review screen, `1` → `Which fruit? → hello` |
| two-question | digit `n` answers question 1 at once and advances to the tab of question 2 (`←  ☒ Fruit  ☐ Size  ✔ Submit  →`) | n/a | after the last question the same review screen appears; `1` submits, `2` cancels (pressed `2`, nothing submitted) | on the second question (after `1` on the first): `3`, type `medium`, `Enter` → review screen `Which size? → medium`, `1` submits → `· Which fruit? → Apple · Which size? → medium` |
| trust | `Down` then `Enter` for Yes (cursor starts on `No, exit`); a digit `2` does NOT move the cursor (still `❯ No, exit` after `2`) | n/a | `Enter` | n/a |
| plan | digit `3` alone only moves the cursor to `❯ 3.` (does NOT answer); digits 1 and 2 are "Yes" rows and were not pressed; `Esc` leaves the dialog (prompt in plan mode, nothing executed) | n/a | `Enter` on the typed row answers: Claude revised the plan with the feedback and drew the dialog again | row 3 "Tell Claude what to change" takes free text: after `3`, typing `use hi2` (`send-keys -l`) turns the row into `❯ 3. use hi2` (sub-line `shift+tab to approve with this feedback` stays); `Enter` submits it (`other: true`) |
| resume | `Esc` closes the picker (back to the shell pane) | n/a | n/a | n/a |

## Not captured

- **login expiry** (login always): needs the user's account logged out; not attempted and not invented.
- Permission prompts were not re-captured here: `fixtures/approve/` already holds them (claude 2.1.321 and the teammate captures).
- The key that picks a plan option was not sent (only `Esc`); digits on the plan dialog are unverified.

## Redaction

The scratch dir (`/private/tmp/dlgcap.XXXXXX`, and its basename on the resume picker) was replaced by `/tmp/scratch` / `scratch` (sed).
`grep -c '/Users/'` per file: `trust.txt` 0, `question-single.txt` 0, `question-multi.txt` 0, `question-two.txt` 0,
`question-handoff.txt` 0, `plan.txt` 0, `resume.txt` 0. The plan screen shows `~/.claude/plans/<name>.md` (tilde form, no home path).

## Cleanup evidence

After `kill-server` and `rm -rf $S`: `ps -ax | grep -c '[d]lgcap'` → 0 (checked again after the processes exited), the scratch dir
gone (`No such file or directory`). Side effect: the trust dialog was answered Yes for the scratch dir, so `~/.claude.json`
holds a trust entry for the deleted path; scratch sessions also left transcripts under `~/.claude/projects/` for that path.
No "always" / "don't ask again" row was pressed; the plan was left with Esc and a single Cancel was chosen on one review screen.
