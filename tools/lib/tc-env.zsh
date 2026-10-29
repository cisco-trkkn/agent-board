# tc-env.zsh — the one definition of what bin/, the hooks and board/ must agree on.
# Source it (zsh). board/tc_env.py parses the TC_SHELLS and TC_PROMPT_RE lines below, so keep each
# a single-quoted one-liner. Test: board/tests/test_tc_env.py.

# State dir for feeds, runs, locks, artifacts. TC_STATE overrides (the test harness sets it).
TC_STATE_DIR="${TC_STATE:-${${TMPDIR:-/tmp}%/}/tmux-ctl-$UID}"   # set at source time: callers need no subshell
tc_state_dir() { print -r -- "$TC_STATE_DIR" }

# Handoff lineage (one <project>.jsonl per project, a line per relay). Persistent state: it outlives the project's close
# and the $TMPDIR sweep. TC_LINEAGE overrides (the test harness sets it). board/tc_env.py lineage_dir() is the same rule.
TC_LINEAGE_DIR="${TC_LINEAGE:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-board/lineage}"

# pane_current_command values that mean "idle at a shell prompt" (zsh pattern; paneclass.py uses the same list)
TC_SHELLS='(zsh|bash|sh|fish|-zsh|-bash)'

# Claude Code screens that wait on the user (permission prompt, question). ERE: valid for grep -iE and Python re.I.
TC_PROMPT_RE='Do you want to|Would you like to|\(y/n\)|❯ *1\. *Yes|Allow this|Press Enter to continue|Enter to confirm'

# Worker spawn choices (`tmux-ctl agent --model/--effort`, the board's + New agent) and their defaults.
TC_MODELS=(haiku sonnet opus fable)
TC_EFFORTS=(low medium high xhigh)
TC_DEFAULT_MODEL=sonnet
TC_DEFAULT_EFFORT=medium
