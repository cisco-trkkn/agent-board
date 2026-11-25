# Workers launched by `tmux-ctl agent` must not be blocked by end-of-session nudges.
# Seam: isolated tmux server (lib.zsh, -f /dev/null) plus a stub `claude` first on the
# panes' PATH that records its environment instead of starting a session.
here="${0:A:h}"; root="${here:h:h}"
source "$here/lib.zsh"
C="$root/bin/tmux-ctl"; hook="$root/claude/hooks/revise-claude-md-nudge.py"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
tt_setup
stub="$TT_DIR/stub"; mkdir -p "$stub"
print -r -- '#!/bin/sh
{ echo "HOOK=$CLAUDE_MD_REVISE_HOOK"; echo "ROLE=$TC_ROLE"; echo "CM=$CLAUDE_CODE_EXPERIMENTAL_CODE_MODE"; echo "TV=$TRIAL_VALUE"; } > "$TT_DIR/seen.tmp"; mv "$TT_DIR/seen.tmp" "$TT_DIR/seen"' > "$stub/claude"; chmod +x "$stub/claude"
# panes run a bare sh (no rc files, which would reset PATH; PATH has no spaces, tmux splits the command) with the stub first on PATH
tt set-environment -g TT_DIR "$TT_DIR"
tt set-option -g default-command "env PATH=$stub:/usr/bin:/bin /bin/sh -i"
repo="$TT_DIR/repo"; mkdir -p "$repo"; git -C "$repo" init -qb main; git -C "$repo" commit -q --allow-empty -m init

(cd "$repo" && PATH="$stub:$PATH" $C agent w1 "Goal: check env. Scope: nothing at all here. Done: the stub saw its env vars set.") >/dev/null 2>&1
tt_wait 8 test -s "$TT_DIR/seen"
check "worker env: nudge hook off"   grep -qx 'HOOK=0' "$TT_DIR/seen"
check "worker env: TC_ROLE=worker"   grep -qx 'ROLE=worker' "$TT_DIR/seen"
line="$(<"$TC_STATE/agents/tt-w1.zsh")"   # the launch line is typed from a file, not into the pane
check "launch line has CLAUDE_MD_REVISE_HOOK=0" grep -qF 'CLAUDE_MD_REVISE_HOOK=0' <<<"$line"
check "launch line has TC_ROLE=worker"          grep -qF 'TC_ROLE=worker' <<<"$line"
check "no --env: the worker sees no Code Mode variable" grep -qx 'CM=' "$TT_DIR/seen"

# --env K=V (the engine's per-job env, improve spec section 4 E5) reaches the worker's process
rm -f "$TT_DIR/seen"
(cd "$repo" && PATH="$stub:$PATH" $C agent w2 --env CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1 --env "TRIAL_VALUE=two words; \$HOME" "Goal: check env. Scope: nothing at all here. Done: the stub saw its env vars set.") >/dev/null 2>&1
tt_wait 8 test -s "$TT_DIR/seen"
check "--env: the worker sees CLAUDE_CODE_EXPERIMENTAL_CODE_MODE=1" grep -qx 'CM=1' "$TT_DIR/seen"
check "--env: a value with spaces and shell characters arrives verbatim" grep -qxF 'TV=two words; $HOME' "$TT_DIR/seen"
check "--env: the fixed worker variables are still set" grep -qx 'ROLE=worker' "$TT_DIR/seen"

# hook honours the opt-out: exit 0, no output, even on a long session
tr="$TT_DIR/long.jsonl"; for i in {1..60}; do print -r -- '{"type": "tool_use"}'; done > "$tr"
payload="{\"session_id\":\"envtest\",\"transcript_path\":\"$tr\"}"
out="$(print -r -- "$payload" | HOME="$TT_DIR/home" CLAUDE_MD_REVISE_HOOK=0 python3 "$hook")"; rc=$?
check "hook opt-out: exit 0"        test $rc -eq 0
check "hook opt-out: no output"     test -z "$out"
out="$(print -r -- "$payload" | HOME="$TT_DIR/home" python3 "$hook")"
check "hook control: blocks without opt-out" grep -q '"block"' <<<"$out"
tt_done
