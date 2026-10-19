source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"            # the checkout under test, not the live install
tt_setup
stub="$(mktemp -d)"; trap 'rm -rf "$stub"; tt_teardown' EXIT INT TERM
print -r -- '#!/bin/sh
for a in "$@"; do printf "%s\n" "$a"; done
printf "PATH=%s\n" "$PATH"' > "$stub/claude"; chmod +x "$stub/claude"
out="$(PATH="$stub:$PATH" $R/bin/claude-orchestrator)"
check "orchestrator uses -file flag"  grep -qxF -- '--append-system-prompt-file' <<< "$out"
check "orchestrator passes path"      grep -qxF -- "$HOME/.claude/orchestrator.md" <<< "$out"
check "no prompt text in argv"        test -z "$(grep -F 'tmux-ctl run' <<< "$out")"
check "worker rules via -file"        grep -qE 'append-system-prompt-file (~|"\$HOME)/\.claude/worker\.md' $R/bin/tmux-ctl
check "no inline worker.md"           test -z "$(grep -F '$(<~/.claude/worker.md)' $R/bin/tmux-ctl)"

# agent-board session config on every launcher
check "orchestrator passes --settings"      grep -qxF -- '--settings' <<< "$out"
check "orchestrator settings path"          grep -qxF -- "$R/claude/settings.json" <<< "$out"
check "orchestrator puts <repo>/bin first"  grep -qE "^PATH=${R}/bin:" <<< "$out"
check "set-environment AGENT_BOARD_REPO"    test "$(tt show-environment -t '=tt:' AGENT_BOARD_REPO 2>&1)" = "AGENT_BOARD_REPO=$R"
check "set-environment PATH has <repo>/bin" grep -qE "^PATH=${R}/bin:" <<< "$(tt show-environment -t '=tt:' PATH 2>&1)"
out2="$(TC_TMUX=/nonexistent PATH="$stub:$PATH" $R/bin/claude-orchestrator 2>&1)"
check "failing set-environment does not stop the launch" grep -qxF -- '--settings' <<< "$out2"

dry="$(TC_AGENT_DRYRUN=1 $R/bin/tmux-ctl agent w --force "a b" 2>&1)"
check "agent dry run keeps DRYRUN task"     grep -qF 'DRYRUN task: a b' <<< "$dry"
check "agent line has --settings"           grep -qF -- "--settings $R/claude/settings.json" <<< "$dry"
check "agent line has PATH=<repo>/bin:"     grep -qF -- "PATH=$R/bin:" <<< "$dry"
check "agent line has AGENT_BOARD_REPO"     grep -qF -- "AGENT_BOARD_REPO=$R" <<< "$dry"
tt_done
