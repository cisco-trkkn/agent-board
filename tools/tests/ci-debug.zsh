#!/usr/bin/env zsh
# ci-debug.zsh — print what tmux-ctl run returns in the CI pane shell (not a test; run by .github/workflows/test.yml).
source "${0:A:h}/lib.zsh"
C="$TT_REPO/bin/tmux-ctl"
tt_setup claude shell
print -r -- "SHELL=$SHELL TERM=$TERM CI=$CI zsh=$(zsh --version) tmux=$($TT_BIN -V)"
print -r -- "--- pane shell: $(tt display -p -t '=tt:shell' '#{pane_current_command} #{pane_pid}')"
print -r -- "--- run output (cat -v):"
$C run tests 'echo hi' 2>&1 | cat -v
print -r -- "--- pane dump:"
tt capture-pane -p -J -t '=tt-bg:tests' -S -20 2>&1 | cat -v | head -30
print -r -- "--- runs record:"; cat "$TC_STATE"/runs-tt.jsonl 2>&1 | head -5
