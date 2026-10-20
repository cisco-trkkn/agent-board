#!/usr/bin/env zsh
# ci-debug.zsh — temporary: show the pane after the first tmux-ctl run on a CI runner.
source "${0:A:h}/lib.zsh"
C="$TT_REPO/bin/tmux-ctl"
tt_setup claude shell
print -r -- "SHELL=$SHELL TERM=$TERM CI=$CI ZDOTDIR=$ZDOTDIR HOME=$HOME LANG=$LANG user=$(id -un) zsh=$(zsh --version) tmux=$($TT_BIN -V)"
print -r -- "--- zdot: $(ls -A $ZDOTDIR) ; HOME rc: $(ls -A $HOME | grep -E '^\.z' | tr '\n' ' ')"
print -r -- "--- /etc/zsh:"; ls -la /etc/zsh 2>&1 | head; ls -la /etc/zshenv /etc/zshrc /etc/zprofile 2>&1 | head
zmodload zsh/datetime
t0=$EPOCHREALTIME; ZDOTDIR=$ZDOTDIR zsh -i -c exit </dev/null >/dev/null 2>&1; print -r -- "--- interactive zsh start: $(( EPOCHREALTIME - t0 ))s (rc $?)"
print -r -- "--- shell pane right after setup:"; tt capture-pane -p -J -t '=tt:shell' | cat -v | head -10
t0=$EPOCHREALTIME; print -r -- "--- run output:"; $C run tests 'echo hi' 2>&1 | cat -v; print -r -- "first run took $(( EPOCHREALTIME - t0 ))s"; $C run tests 'echo hi2' 2>&1 | cat -v
print -r -- "--- pane dump:"; tt capture-pane -p -J -t '=tt-bg:tests' -S -20 2>&1 | cat -v | head -30
print -r -- "--- runs record:"; cat "$TC_STATE"/runs-tt.jsonl 2>&1 | head -5
print -r -- "--- env:"; env | grep -E '^(ZSH|ZDOT|TERM|LC_|LANG|PROMPT|PS1|ENV|BASH_ENV|SHLVL|XDG)' 
