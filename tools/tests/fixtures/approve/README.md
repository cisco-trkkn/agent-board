# approve fixtures: real Claude Code permission prompts

Captured 2026-11-09 from `claude --version` = **2.1.321 (Claude Code)** (Opus 5.5, effort medium), with
`tmux capture-pane -p -J -t ap` (the full 200x50 pane, trailing blank lines included) on a scratch tmux
server in a scratch git dir.

These screens come from a plain `claude` session, not a teammate's or a subagent's.

## Commands used

    S=$(mktemp -d); git -C $S init -q
    ~/.local/bin/tmux -L apcap -f /dev/null new-session -d -s ap -x 200 -y 50 -c $S
    tmux ... send-keys -t ap "claude --permission-mode default" Enter
    # folder-trust dialog (first run in a new dir): Down, Enter = "Yes, I trust this folder"
    # each request: send-keys "text"; sleep 1; send-keys Enter; poll capture-pane until 'Do you want'
    ~/.local/bin/tmux -L apcap -f /dev/null kill-server

Requests: "Use the Bash tool to run exactly: touch made-by-test", "Use the Write tool to create a new
file notes.txt containing the single line hello", "Use the Bash tool to run exactly: git config user.name probe-user".

## Files

| file | screen |
|---|---|
| `bash-touch.txt` | Bash prompt: 1 Yes / 2 "Yes, and always allow access to <dir> from this project" / 3 "Yes, and switch to auto mode" / 4 No |
| `bash-git.txt` | Bash prompt: 1 Yes / 2 "Yes, and don’t ask again for: git config *" (curly apostrophe) / 3 switch to auto mode / 4 No |
| `write.txt` | Write prompt "Do you want to create notes.txt?": 1 Yes / 2 "Yes, and switch to accept edits ..." / 3 No (no "always" option, only 3 options) |
| `bash-multiline.txt` | Bash prompt for a two-line command (asked: "Use the Bash tool to run a two-line command: the first line is echo a and the second line is … ──── echo probe", claude 2.1.321, captured 2026-11-09 the same way): the preview lines are drawn ` │ echo a` and ` │ ──── echo probe`, every one indented, even a line that starts with `────` or `╌╌╌╌` (a second probe, not saved, showed ` │ ╌╌╌╌ echo probe2`); the tip line precedes the description; 4 options as in `bash-git.txt` |
| `after-yes.txt` | the pane after answering `touch made-by-test` with `1` (prompt gone, "Ran 1 shell command") |
| `after-no-arrows.txt` | the pane after Down, Down, Enter on `write.txt` (No); blank lines removed (`grep -v '^$' | tail -8`) |
| `no-prompt.txt` | idle pane after answering `git config` with `4` (No): empty `❯` input, no prompt |

The option numbers and texts differ per prompt kind, and an "always" option is NOT always option 2
(Write has none). `approve` must read the screen, not assume a number.

## Selection-key probe (what Task 4's `tmux-ctl approve` sends)

- **A digit alone answers a permission prompt**, no Enter needed: `send-keys -t ap 1` on the Bash
  prompt ran the command at once (`made-by-test` appeared in the dir; `after-yes.txt`). `4` on
  `bash-git.txt` answered No (the global git user was still unchanged; `no-prompt.txt`).
- Down, Down, Enter also answers (selected row 3 "No" on `write.txt`; notes.txt was not created).
- On the folder-trust dialog (not a permission prompt) the digit `2` did NOT move the selection and
  Enter then chose "No, exit" (claude exited); that one needs Down + Enter.
- Never pressed an "always"/"don't ask again" option: option 2 of `bash-touch.txt`/`bash-git.txt` was left alone so no rule was written to the user's settings.
  Side effect: the trust dialog was answered Yes for the scratch dir, so `~/.claude.json` holds a trust entry for the deleted scratch path.

## Redaction

The scratch dir `/private/tmp/claude-503/apcap.XXXX` was replaced by `/tmp/scratch` (sed). No `/Users/`
paths, tokens or secrets were in the captures (`grep -c '/Users/'` → 0 for every file).

## Cleanup evidence

After `kill-server`: `ps -ax` scanned 972 processes, 0 matched `apcap`; the scratch dir was removed
(`ls` of it: "No such file or directory").
