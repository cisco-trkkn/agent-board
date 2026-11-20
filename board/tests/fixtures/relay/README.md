Real captures of the agent-board lead pane (%138, session agent-board, window claude), read-only, 2026-11-20.

    tmux capture-pane -p -J -S -40 -t %138 | sed -e "s#$HOME#~#g" > working-lead.txt          # taken while the footer showed `esc to interrupt`
    tmux capture-pane -p -J -S -40 -t %138 | sed -e "s#$HOME#~#g" > idle-lead-tasklist.txt    # taken once the footer no longer showed it

The idle one has a task list (`32/54 tasks done`) under the reply and above the input box, and the status rows below.
No secrets were present; the sed only maps the home path to ~.
