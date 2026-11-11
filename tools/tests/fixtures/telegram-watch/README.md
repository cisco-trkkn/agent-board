Screens captured from a real Claude Code 2.1.322 pane (scratch tmux server, `capture-pane -p -J`, trailing blanks trimmed), 2026-11-10.
idle: empty prompt. typed-input: `half a sentence` in the input line. typed-list: `/mcp reconnect plugin:telegram:telegram` typed, not submitted.
reconnect-ok / reconnect-unknown: after `/mcp reconnect plugin:telegram:telegram` and `/mcp reconnect nosuch` (the transcript above keeps earlier lines).
working: a turn just started (`✽ Actioning…`). after-turn: the turn done.
real-idle-1 / real-idle-2: a real 2.1.322 lead (`--channels plugin:telegram@claude-plugins-official`, scratch tmux socket, fake-token TELEGRAM_STATE_DIR) captured twice, 3 s apart, 2026-11-10: identical, placeholder included. Its telegram server was then killed and `telegram_watch.py --once` logged `reconnect: ok`.
