source "${0:A:h}/lib.zsh"
stub="$(mktemp -d)"; trap 'rm -rf "$stub"' EXIT
print -r -- '#!/bin/sh
for a in "$@"; do printf "%s\n" "$a"; done' > "$stub/claude"; chmod +x "$stub/claude"
out="$(PATH="$stub:$PATH" ~/.local/bin/claude-orchestrator)"
check "orchestrator uses -file flag"  grep -qxF -- '--append-system-prompt-file' <<< "$out"
check "orchestrator passes path"      grep -qxF -- "$HOME/.claude/orchestrator.md" <<< "$out"
check "no prompt text in argv"        test -z "$(grep -F 'tmux-ctl run' <<< "$out")"
check "worker rules via -file"        grep -qE 'append-system-prompt-file (~|"\$HOME)/\.claude/worker\.md' ~/.local/bin/tmux-ctl
check "no inline worker.md"           test -z "$(grep -F '$(<~/.claude/worker.md)' ~/.local/bin/tmux-ctl)"
tt_done
