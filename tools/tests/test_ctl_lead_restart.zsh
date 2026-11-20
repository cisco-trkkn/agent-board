#!/usr/bin/env zsh
# tmux-ctl lead-restart <project> [--resume | --doc <handoff>] (spec 2026-11-19-lead-recovery §2, R3 R4 R6),
# and the grouped-session guard of `relay` from a claude-next window (T2 review minor).
# Real scratch tmux server; a stub claude-orchestrator records its argv and sleeps. Never the live server or ~/.claude.
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
STUB="$(mktemp -d "${TMPDIR:-/tmp}/ttstub.XXXXXX")"
mkdir -p "$STUB/repo/bin"
cat > "$STUB/repo/bin/claude-orchestrator" <<'EOF'
#!/bin/sh
printf '%s\n' "$@" > "$LR_OUT"
exec sleep 600
EOF
chmod +x "$STUB/repo/bin/claude-orchestrator"
export PATH="$STUB:$PATH" LR_OUT="$STUB/args"
tt_zdot "$STUB/zdot"
tt_setup claude shell
export AGENT_BOARD_REPO="$STUB/repo"; tt set-environment -g AGENT_BOARD_REPO "$STUB/repo"
export LR_OUT; tt set-environment -g LR_OUT "$LR_OUT"
H="$TC_STATE/handoffs"; mkdir -p "$H/drafts" "$CLAUDE_CONFIG_DIR/sessions"
root="$TT_DIR"   # the session's start dir: a plain, non-git folder, its own project root
old_doc="$H/a-old.md"; new_doc="$H/b-new.md"; other_doc="$H/c-other.md"; draft="$H/drafts/d.md"
print -r -- "Project: $root"$'\n'"# old" > "$old_doc"
print -r -- "Project: $root"$'\n'"# new" > "$new_doc"
print -r -- "Project: /somewhere/else"$'\n'"# other project's, newest" > "$other_doc"
print -r -- "Project: $root"$'\n'"# draft, newest" > "$draft"
touch -t 202601010000 "$old_doc"; touch -t 202601020000 "$new_doc"; touch -t 202601030000 "$other_doc" "$draft"
lead="$(tt display -p -t '=tt:claude' '#{pane_id}')"
pid() { tt display -p -t "$1" '#{pane_pid}' }
# outside tmux: TMUX_DASH_TMUX_ARGS names the scratch server (and keeps tmux-ctl from resetting AGENT_BOARD_REPO to this checkout)
lead_out() { env -u TMUX -u TMUX_PANE TMUX_DASH_TMUX_ARGS="-L $TT_SOCK_NAME" LEAD_RESTART_BOT_WAIT=0 $C lead-restart "$@" 2>&1 }

# a project with no lead pane: exit 1, nothing changed
tt new-session -d -s nolead -n shell -c "$TT_DIR"
np="$(tt display -p -t '=nolead:shell' '#{pane_id}')"; np0="$(pid $np)"
out="$(lead_out nolead)"; rc=$?
check "no lead pane: exit 1"            test $rc -eq 1
check "no lead pane: says so"           test "$out" = "lead-restart: no lead pane for nolead"
check "no lead pane: pane untouched"    test "$(pid $np)" = "$np0"
out="$(lead_out nosuchproject)"; rc=$?
check "unknown project: exit 1"         test $rc -eq 1 -a "$out" = "lead-restart: no lead pane for nosuchproject"

# no resume id and no sessions entry: exit 1, nothing renamed or respawned (a claude-next lead stays claude-next)
tt rename-window -t "=tt:claude" claude-next
p0="$(pid $lead)"
out="$(lead_out tt --resume)"; rc=$?
check "resume without an id: exit 1"    test $rc -eq 1
check "resume without an id: says why"  zsh -c 'print -r -- "$1" | grep -q "no session id"' x "$out"
check "resume without an id: not respawned" test "$(pid $lead)" = "$p0"
check "resume without an id: not renamed"   test "$(tt display -p -t $lead '#{window_name}')" = claude-next
check "resume without an id: no orchestrator run" test ! -e "$LR_OUT"

# --resume and --doc together: exit 2 with a usage line, nothing changed
out="$(lead_out tt --resume --doc "$new_doc")"; rc=$?
check "resume + doc: exit 2"            test $rc -eq 2
check "resume + doc: usage line"        zsh -c 'print -r -- "$1" | grep -q "^usage: tmux-ctl lead-restart\|usage: tmux-ctl lead-restart"' x "$out"
check "resume + doc: not respawned"     test "$(pid $lead)" = "$p0"

# default doc: the newest handoff of THIS project (not another project's newer doc, not drafts/); claude-next -> claude; command is the pane command
out="$(lead_out tt)"; rc=$?
check "doc restart: exit 0"             test $rc -eq 0
check "doc restart: result line"        test "$out" = "lead-restart: tt restarted (doc b-new.md); bot: no bot"
check "doc restart: orchestrator got the newest own-project doc" test "$(cat $LR_OUT)" = "Read $new_doc and continue from where the previous session left off."
check "doc restart: lead pane replaced" test "$(pid $lead)" != "$p0"
check "doc restart: claude-next renamed claude" test "$(tt display -p -t $lead '#{window_name}')" = claude
check "doc restart: orchestrator is the pane's own command" zsh -c 'print -r -- "$1" | grep -qF "$2"' x "$(tt display -p -t $lead '#{pane_start_command}')" "${STUB:gs|//|/|}/repo/bin/claude-orchestrator"
check "doc restart: pane start command ends in a login shell" zsh -c 'print -r -- "$1" | grep -q "exec .*zsh.* -l"' x "$(tt display -p -t $lead '#{pane_start_command}')"
# tmux names the zsh -c wrapper as the pane command for the whole run (R4's `; exec shell -l`): the lead is its child
check "doc restart: the pane runs the orchestrator as a child process" test -n "$(pgrep -P "$(pid $lead)")"

# --doc names the doc
rm -f "$LR_OUT"
out="$(lead_out tt --doc "$old_doc")"; rc=$?
check "--doc: exit 0 and says doc a-old.md" test $rc -eq 0 -a "$out" = "lead-restart: tt restarted (doc a-old.md); bot: no bot"
check "--doc: orchestrator got that doc" test "$(cat $LR_OUT)" = "Read $old_doc and continue from where the previous session left off."
out="$(lead_out tt --doc "$STUB/missing.md")"; rc=$?
check "--doc missing file: exit 1"      test $rc -eq 1

# a project with only another project's handoffs: exit 1, nothing changed
rm -f "$new_doc" "$old_doc"; p1="$(pid $lead)"
out="$(lead_out tt)"; rc=$?
check "no handoff for the project: exit 1" test $rc -eq 1
check "no handoff: not respawned"       test "$(pid $lead)" = "$p1"

# --resume: the id from ~/.claude/sessions/*.json (here under CLAUDE_CONFIG_DIR) whose tmux field ends with the pane id
print -r -- "{\"sessionId\":\"SID-OLD\",\"tmux\":\"tt:@9.$lead\",\"updatedAt\":100}" > "$CLAUDE_CONFIG_DIR/sessions/1.json"
print -r -- "{\"sessionId\":\"SID-NEW\",\"tmux\":\"tt:@9.$lead\",\"updatedAt\":200}" > "$CLAUDE_CONFIG_DIR/sessions/2.json"
rm -f "$LR_OUT"
out="$(lead_out tt --resume)"; rc=$?
check "resume: exit 0, result line"     test $rc -eq 0 -a "$out" = "lead-restart: tt restarted (resume SID-NEW); bot: no bot"
check "resume: argv is --resume <id>"   test "$(cat $LR_OUT | tr '\n' ' ')" = "--resume SID-NEW "

# the bot line: a token but no holder is "not held", and the restart still exits 0
mkdir -p "$TC_STATE/discord/tt"; print -r -- "DISCORD_BOT_TOKEN=abc.def" > "$TC_STATE/discord/tt/.env"
out="$(lead_out tt --resume)"; rc=$?
check "token, no holder: exit 0, not held" test $rc -eq 0 -a "$out" = "lead-restart: tt restarted (resume SID-NEW); bot: not held"

# nothing is typed into a pane: a send-keys wrapper on PATH would show it; assert via the pane history instead (no keys echo)
check "nothing typed: the pane never showed the launch line" test -z "$(tt capture-pane -p -t "$lead" -S -50 | grep 'cd -- ')"

# grouped session: the project key is the group name, which is no session's name. The lead lives in a member session.
tt new-session -d -s g1 -n claude -c "$TT_DIR"
tt new-session -d -t g1 -s g1view
tt rename-session -t '=g1' g1real
gp="$(tt display -p -t '=g1real:claude' '#{pane_id}')"; gp0="$(pid $gp)"
check "group fixture: no session is named g1" test -z "$(tt list-sessions -F '#{session_name}' | grep -x g1)"
tt new-session -d -s g1-bg -n shell -c "$TT_DIR"; tt set-option -t '=g1-bg:' @tc_bg 1
print -r -- "Project: $root"$'\n'"# for g1" > "$H/g1.md"
out="$(lead_out g1 --doc "$H/g1.md")"; rc=$?
check "grouped project: restarted through a member session" test $rc -eq 0 -a "$out" = "lead-restart: g1 restarted (doc g1.md); bot: no bot"
check "grouped project: the real pane was replaced" test "$(pid $gp)" != "$gp0"
check "grouped project: the -bg session is not the lead" test -z "$(pgrep -P "$(pid "$(tt display -p -t '=g1-bg:shell' '#{pane_id}')")")"

# the T2 minor: relay from a claude-next window of a grouped session refuses when a claude window already exists there.
# $FEEDKEY is the group name (g1), which is no session: the duplicate check must list the caller's own session.
tt new-window -d -t '=g1real:' -n claude-next
cn="$(tt display -p -t '=g1real:claude-next' '#{pane_id}')"
print "# handoff" > "$TT_DIR/rh.md"
out="$(env TMUX_PANE=$cn AGENT_BOARD_LEAD=1 TC_SESSION=g1real $C relay "$TT_DIR/rh.md" 2>&1)"; rc=$?
check "grouped relay: duplicate claude refused" test $rc -eq 2
check "grouped relay: names a member session, not the group" zsh -c 'print -r -- "$1" | grep -qE "relay: a claude window already exists in g1(real|view)$"' x "$out"   # a window of a grouped session lists under every member: tmux answers with either
check "grouped relay: claude-next not renamed" test "$(tt display -p -t $cn '#{window_name}')" = claude-next

# R5: the allow rule that covers lead-restart is still there
check "settings.json allows Bash(tmux-ctl:*)" jq -e '.permissions.allow | index("Bash(tmux-ctl:*)")' "$TT_REPO/claude/settings.json" >/dev/null
check "help lists lead-restart"         zsh -c '"$1" help | grep -q "tmux-ctl lead-restart <project>"' x "$C"
tt_done
