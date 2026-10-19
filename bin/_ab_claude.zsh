# _ab_claude.zsh — sourced. The flags and PATH every agent-board Claude starts with.
AB_REPO="${${(%):-%x}:A:h:h}"
ab_claude_args() { print -r -- "--settings ${(q)AB_REPO}/claude/settings.json --plugin-dir ${(q)AB_REPO}/claude/plugin" }
ab_path() { print -r -- "$AB_REPO/bin:$PATH" }
