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
| plan | not probed with a digit; left with `Esc` (back to the prompt in plan mode, nothing executed) | n/a | n/a | n/a |
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
