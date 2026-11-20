source "${0:A:h}/lib.zsh"
# claude-orchestrator opts a lead into the Discord channel when its project has a saved token and no other lead holds it;
# the caller's --channels entries are merged with it into one list. A stub `claude` first on PATH records its argv.
export TC_TMUX="$TT_BIN"
tt_setup claude
RT="$TT_DIR/home"; mkdir -p "$RT"
STUB="$TT_DIR/stub"; S="$TT_DIR/out"; mkdir -p "$STUB" "$S"
cat > "$STUB/claude" <<STUBEOF
#!/bin/zsh
print -rl -- "\$@" > $S/argv
print -r -- "\${DISCORD_STATE_DIR-UNSET}" > $S/dsd
print -r -- "\${TELEGRAM_STATE_DIR-UNSET}" > $S/tsd
print -r -- "\$PATH" > $S/path
STUBEOF
chmod +x "$STUB/claude"
not() { ! "$@" }
ORIG_PATH="$PATH"
DC="$TC_STATE/discord/tt"
run() {   # run [env-prefix...] cmd: start the launcher in this pane's session; stderr lands in $S/err
  rm -f $S/argv $S/dsd $S/tsd $S/path $S/err
  env HOME="$RT" PATH="$STUB:$ORIG_PATH" "$@" >/dev/null 2>$S/err
}
nch() { grep -c -- '^--channels' $S/argv }
L="$TT_REPO/bin/claude-orchestrator"
DCH=plugin:discord@claude-plugins-official

run "$L" --continue
check "no token: no --channels"        test "$(nch)" = 0
check "no token: DISCORD_STATE_DIR unset" test "$(<$S/dsd)" = UNSET
check "no token: caller args kept"     grep -qx -- '--continue' $S/argv
check "no token: no stderr"            test ! -s $S/err

mkdir -p "$DC"; print -r -- "DISCORD_BOT_TOKEN=1.x.y" > "$DC/.env"
run "$L" --continue
check "token: one --channels"          test "$(nch)" = 1
check "token: plugin value follows"    test "$(grep -A1 -x -- '--channels' $S/argv | tail -1)" = $DCH
check "token: flag before caller args" test "$(grep -n -x -- '--channels' $S/argv | cut -d: -f1)" -lt "$(grep -n -x -- '--continue' $S/argv | cut -d: -f1)"
check "token: DISCORD_STATE_DIR"       test "$(<$S/dsd)" = "$DC"
check "token: not in tmux session env" not tt show-environment -t '=tt' DISCORD_STATE_DIR
check "token: no stderr"               test ! -s $S/err
run TELEGRAM_STATE_DIR=/bogus "$L"
check "inherited TELEGRAM_STATE_DIR cleared" test "$(<$S/tsd)" = UNSET

# --- idea 132: one --channels list before AB_ARGS; the trailing prompt stays last
run "$L" --channels plugin:x "do it"
check "caller list + prompt: one --channels" test "$(nch)" = 1
check "caller list: theirs then discord follow the flag" test "$(grep -A2 -x -- '--channels' $S/argv | tail -2 | tr '\n' ' ')" = "plugin:x $DCH "
check "caller list + prompt: prompt is the last argv element" test "$(tail -1 $S/argv)" = "do it"
check "caller list: flag after the channel values is --settings" test "$(grep -A3 -x -- '--channels' $S/argv | sed -n 4p)" = --settings
run "$L" --channels $DCH
check "caller names discord: entry appears once" test "$(grep -c -x -- "$DCH" $S/argv)" = 1 -a "$(nch)" = 1
run "$L" --channels=plugin:x --continue
check "--channels=X --continue: one flag, both entries, --continue kept" test "$(nch)" = 1 -a "$(grep -c -x -- 'plugin:x' $S/argv)" = 1 -a "$(grep -c -x -- "$DCH" $S/argv)" = 1 -a -n "$(grep -x -- '--continue' $S/argv)"
check "--channels=X: no =-form left" test "$(grep -c -- '--channels=' $S/argv)" = 0
run "$L" "Read the doc"
check "prompt file present: flag after channel value" test "$(grep -A2 -x -- '--channels' $S/argv | sed -n 3p)" = --settings
check "prompt file present: positional prompt kept, last" test "$(tail -1 $S/argv)" = "Read the doc"
run "$L" --channels server:y --channels plugin:z
check "two caller flags merge into one list" test "$(nch)" = 1 -a -n "$(grep -x 'server:y' $S/argv)" -a -n "$(grep -x 'plugin:z' $S/argv)"
run "$L" --channels untagged "keep me"
check "untagged value is not eaten as a channel" test -n "$(grep -x 'untagged' $S/argv)" -a "$(nch)" = 1
# caller channels with no token and no discord: still one --channels, nothing added
rm -rf "$DC"
run "$L" --channels plugin:x "do it"
check "no token + caller channel: just theirs" test "$(nch)" = 1 -a "$(grep -c -x -- "$DCH" $S/argv)" = 0 -a "$(tail -1 $S/argv)" = "do it"

# --- the opt-out cases
mkdir -p "$DC"; print -r -- "DISCORD_BOT_TOKEN=1.x.y" > "$DC/.env"
run TC_DISCORD=0 "$L" --continue
check "TC_DISCORD=0: no --channels"    test "$(nch)" = 0
check "TC_DISCORD=0: state dir unset"  test "$(<$S/dsd)" = UNSET
check "TC_DISCORD=0: silent"           test ! -s $S/err
run env -u TMUX -u TMUX_PANE "$L" --continue
check "outside tmux: no --channels"    test "$(nch)" = 0
check "outside tmux: state dir unset"  test "$(<$S/dsd)" = UNSET
check "outside tmux: one stderr line"  test "$(<$S/err)" = "agent-board lead: not in tmux, so no Discord channel"
: > "$DC/.env"; run "$L" --continue
check "empty .env: no --channels"      test "$(nch)" = 0 -a "$(<$S/dsd)" = UNSET
print -r -- 'DISCORD_BOT_TOKEN=' > "$DC/.env"; run "$L" --continue
check "DISCORD_BOT_TOKEN= : no --channels" test "$(nch)" = 0
rm -rf "$DC"
run DISCORD_STATE_DIR=/bogus "$L"
check "inherited state dir cleared"    test "$(<$S/dsd)" = UNSET

# --- -bg session of the same project shares the project's token
mkdir -p "$DC"; print -r -- "DISCORD_BOT_TOKEN=1.x.y" > "$DC/.env"
tt new-session -d -s tt-bg -c "$TT_DIR"; tt set-option -t '=tt-bg:' @tc_bg 1
BGPANE="$(tt display -p -t '=tt-bg:' '#{pane_id}')"
run env TMUX_PANE="$BGPANE" "$L"
check "-bg session: project is tt"     test "$(<$S/dsd)" = "$DC"
tt kill-session -t '=tt-bg'

# --- the second-lead guard, with real fake-holder process trees (node: ps -E hides a platform binary's environment)
if (( $+commands[node] )); then
  FB="$TT_DIR/fb"; mkdir -p "$FB"; ln -sf "${commands[node]:A}" "$FB/claude"
  cat > "$FB/fc.js" <<'FC'
const { spawn } = require('child_process')
require('fs').writeFileSync(process.argv[3], String(process.pid))
spawn(process.execPath, ['-e', 'setTimeout(()=>{},120000)', 'bun', 'run', '--cwd', '/fake/discord/0.0.4', 'start', process.argv[4]],
  { env: { ...process.env, DISCORD_STATE_DIR: process.argv[2] }, stdio: 'ignore' }).on('exit', () => process.exit(0))
FC
  typeset -a HPIDS=()
  hold() {   # hold <pane>: a live fake lead holding $DC, its TMUX_PANE being <pane>; sets HP
    local f="$FB/pid.$RANDOM"; env TMUX_PANE="$1" "$FB/claude" "$FB/fc.js" "$DC" "$f" "$FB" >/dev/null 2>&1 &
    local i; for i in {1..50}; do [[ -s "$f" ]] && break; sleep 0.1; done
    HP="$(<$f)"; HPIDS+=($HP); sleep 0.5; HPIDS+=($(ps -A -o pid=,ppid= | awk -v p=$HP '$2==p{print $1}'))
  }
  release() { local p; for p in $HPIDS; do kill $p 2>/dev/null; done; HPIDS=(); sleep 0.3 }
  trap 'release; tt_teardown' EXIT INT TERM
  OTHER="$(tt new-window -d -P -F '#{pane_id}' -t '=tt:' -n holderwin -c "$TT_DIR")"
  # a grouped view of the session (the board's _web-* sessions): the line must name the group, never the view
  tt new-session -d -s _web-view -t tt -c "$TT_DIR"
  hold "$OTHER"
  run "$L" --continue
  check "held elsewhere: no --channels"     test "$(nch)" = 0
  check "held elsewhere: state dir unset"   test "$(<$S/dsd)" = UNSET
  check "held elsewhere: claude still started" grep -qx -- '--continue' $S/argv
  check "held elsewhere (grouped view exists): exactly one stderr line, naming group:window and pid" test "$(<$S/err)" = "discord: tt's bot is held by the lead in tt:holderwin (pid $HP); this lead starts without it"
  run "$L" --channels $DCH plugin:x "do it"
  check "held elsewhere + caller names discord: only plugin:x is passed" test "$(nch)" = 1 -a "$(grep -c -x -- "$DCH" $S/argv)" = 0 -a "$(grep -A1 -x -- '--channels' $S/argv | tail -1)" = plugin:x -a "$(tail -1 $S/argv)" = "do it"
  tt kill-session -t '=_web-view'
  release
  hold %9999
  run "$L" --continue
  check "held, pane unknown: another process" test "$(<$S/err)" = "discord: tt's bot is held by another process (pid $HP); this lead starts without it"
  check "held, pane unknown: no channel"    test "$(nch)" = 0
  release
  # a stale holder in this very pane (an in-place replacement) does not block the new lead
  hold "$TMUX_PANE"
  run "$L" --continue
  check "holder in this pane: channel added" test "$(nch)" = 1 -a "$(<$S/dsd)" = "$DC"
  check "holder in this pane: silent"       test ! -s $S/err
  release
  run "$L" --continue
  check "holder gone: channel added"        test "$(nch)" = 1
  # --- the same project's old lead (window claude / claude-next) releases the bot: the new lead waits for it
  zmodload zsh/datetime
  NEXTP="$(tt new-window -d -P -F '#{pane_id}' -t '=tt:' -n claude-next -c "$TT_DIR")"
  # Timing is keyed to the launcher's own "waiting" line, never to the clock from before the launcher started: a loaded
  # machine can take many seconds to reach its first holder scan, so a fixed release time or a whole-run bound races it.
  bgrun() {   # bgrun <run args>: start the launcher in the background; WLT = when its waiting line first showed (empty if never)
    rm -f $S/err; run "$@" & BGP=$!; WLT=
    local i; for i in {1..1200}; do
      grep -q '^discord: waiting' $S/err 2>/dev/null && { WLT=$EPOCHREALTIME; break }
      kill -0 $BGP 2>/dev/null || break; sleep 0.05
    done
  }
  settle() {   # settle <secs>: wait for the launcher up to <secs>, SETTLED=1 if it ended; else free it so the test fails, not hangs
    local i; SETTLED=0
    for i in {1..$(( $1 * 20 ))}; do kill -0 $BGP 2>/dev/null || { SETTLED=1; break }; sleep 0.05; done
    (( SETTLED )) || { release; pkill -P $BGP 2>/dev/null; kill $BGP 2>/dev/null }
    wait $BGP 2>/dev/null; return 0
  }
  hold "$NEXTP"
  bgrun TC_DC_WAIT=30 TC_DC_POLL=1 "$L" --continue
  check "old lead releases in the wait: the waiting line shows" test -n "$WLT"
  sleep 3; release
  settle 25; el=$(( EPOCHREALTIME - ${WLT:-EPOCHREALTIME} ))
  check "old lead releases in the wait: channel added" test "$(nch)" = 1 -a "$(<$S/dsd)" = "$DC"
  check "old lead releases in the wait: waited for the release, not the full wait" test $SETTLED = 1 -a $(( el >= 2.5 && el < 25 )) = 1
  check "old lead releases in the wait: one waiting line, no held line" test "$(<$S/err)" = "discord: waiting up to 30s for the lead in tt:claude-next to release tt's bot"
  hold "$NEXTP"
  t0=$EPOCHREALTIME
  run TC_DC_WAIT=3 TC_DC_POLL=1 "$L" --continue
  el=$(( EPOCHREALTIME - t0 ))
  check "old lead never releases: starts without the channel" test "$(nch)" = 0 -a "$(<$S/dsd)" = UNSET
  check "old lead never releases: waited the full wait" test $(( el >= 2.9 )) = 1
  check "old lead never releases: waiting line then today's message" test "$(<$S/err)" = "discord: waiting up to 3s for the lead in tt:claude-next to release tt's bot
discord: tt's bot is held by the lead in tt:claude-next (pid $HP); this lead starts without it"
  release
  tt new-session -d -s other -c "$TT_DIR"; tt rename-window -t '=other:' claude
  OTHERP="$(tt display -p -t '=other:' '#{pane_id}')"
  hold "$OTHERP"
  run TC_DC_WAIT=20 TC_DC_POLL=1 "$L" --continue
  check "holder in another project: no wait" test "$(nch)" = 0 -a -z "$(grep waiting $S/err)"
  check "holder in another project: today's message only" test "$(<$S/err)" = "discord: tt's bot is held by the lead in other:claude (pid $HP); this lead starts without it"
  release; tt kill-session -t '=other'
  hold %9999
  run TC_DC_WAIT=20 TC_DC_POLL=1 "$L" --continue
  check "holder another process: no wait" test "$(nch)" = 0 -a -z "$(grep waiting $S/err)"
  release
  hold "$OTHER"
  run TC_DC_WAIT=20 TC_DC_POLL=1 "$L" --continue
  check "same project, other window name: no wait" test "$(nch)" = 0 -a -z "$(grep waiting $S/err)"
  release
  # bad knobs fall back to the defaults, and the wait is a deadline: a never-released same-project holder must end the
  # wait in time (settle frees the holder after 40 s so a regression fails the test instead of hanging it)
  hold "$NEXTP"
  for bad in abc 0 -2 1.5; do
    bgrun TC_DC_WAIT=6 TC_DC_POLL=$bad "$L" --continue
    settle 40
    check "TC_DC_POLL=$bad: ends within the wait, no channel" test $SETTLED = 1 -a "$(nch)" = 0 -a "$(<$S/dsd)" = UNSET
    check "TC_DC_POLL=$bad: no math error, the wait line is the default shape" test -z "$(grep -i 'bad math\|not valid\|division' $S/err)" -a -n "$(grep -x 'discord: waiting up to 6s for .*' $S/err)"
  done
  bgrun TC_DC_WAIT=6 TC_DC_POLL=1 "$L" --continue
  settle 40; el=$(( EPOCHREALTIME - ${WLT:-EPOCHREALTIME} ))
  check "deadline: WAIT=6 never released ends about 6 s after the waiting line (one poll and scans over)" test $SETTLED = 1 -a $(( el >= 3 )) = 1 -a "$(nch)" = 0
  bgrun TC_DC_WAIT=1x TC_DC_POLL=1 "$L" --continue
  release; settle 25
  check "TC_DC_WAIT=1x: no math error on stderr, falls back to 60 in the wait line" test -z "$(grep -i 'bad math\|not valid' $S/err)" -a -n "$(grep -x 'discord: waiting up to 60s for .*' $S/err)"
  # the old lead dying mid-wait: dc_holder can see its pid with no pane for one scan (a dying process has no readable
  # environment). That is the same holder going away, not "another process": the wait goes on. dc_holder is a seam here:
  # a repo copy whose dc_holder answers pane, then pane-less, then nothing.
  R3="$TT_DIR/repo3"; mkdir -p "$R3/bin" "$R3/tools/lib" "$R3/claude/plugin/scripts"
  cp "$TT_REPO"/bin/{claude-orchestrator,_ab_claude.zsh,_tc_bins.zsh} "$R3/bin/"
  cp "$TT_REPO"/tools/lib/discord*.zsh "$R3/tools/lib/"; cp "$TT_REPO/tools/discord_cache.py" "$R3/tools/"
  cp "$TT_REPO"/claude/plugin/scripts/discord-mcp-* "$R3/claude/plugin/scripts/"
  cp "$TT_REPO/claude/orchestrator.md" "$R3/claude/"
  print -r -- "dc_holder() { local n=\$(( \$(<$R3/n) + 1 )); print -r -- \$n > $R3/n; case \$n in 1|2) print -r -- '4242 $NEXTP';; 3|4) print -r -- '4242 -';; esac }" >> "$R3/tools/lib/discord.zsh"
  print -r -- 0 > "$R3/n"
  run TC_DC_WAIT=30 TC_DC_POLL=1 "$R3/bin/claude-orchestrator" --continue
  check "old lead dying mid-wait (pid seen without a pane): the wait goes on, channel added" test "$(nch)" = 1 -a "$(<$S/dsd)" = "$DC"
  check "old lead dying mid-wait: one waiting line, no held line" test "$(<$S/err)" = "discord: waiting up to 30s for the lead in tt:claude-next to release tt's bot"
  release; tt kill-window -t "$NEXTP"
  for i in {1..30}; do [[ -z "$(ps -A -o args= | grep -F "start $FB" | grep -v grep)" ]] && break; sleep 0.1; done
  # scoped to this run's own holders ($FB is unique): test_discord_holder.zsh runs fakes with the same --cwd in parallel
  check "leak: no fake holder left"        test -z "$(ps -A -o args= | grep -F "start $FB" | grep -v grep)"
else
  print "skip - no node (guard cases)"
fi

# --- bun dir
run "$L"
has() { [[ "$1" == *"$2"* ]] }
check "no ~/.bun/bin: PATH unchanged"  not has "$(<$S/path)" "$RT/.bun/bin"
mkdir -p "$RT/.bun/bin"
run "$L"
check "~/.bun/bin on claude's PATH"    test "${${(s.:.)$(<$S/path)}[1]}" = "$RT/.bun/bin" -o "${${(s.:.)$(<$S/path)}[2]}" = "$RT/.bun/bin"
check "~/.bun/bin in session env PATH" has "$(tt show-environment -t '=tt' PATH)" "$RT/.bun/bin"

# --- the exec line without a prompt file carries the list too
mkdir -p "$TT_DIR/repo2/bin" "$TT_DIR/repo2/tools/lib"; cp "$TT_REPO"/bin/{claude-orchestrator,_ab_claude.zsh,_tc_bins.zsh} "$TT_DIR/repo2/bin/"
cp "$TT_REPO"/tools/lib/discord*.zsh "$TT_DIR/repo2/tools/lib/"; cp "$TT_REPO/tools/discord_cache.py" "$TT_DIR/repo2/tools/"
mkdir -p "$TT_DIR/repo2/claude/plugin/scripts"; cp "$TT_REPO"/claude/plugin/scripts/discord-mcp-* "$TT_DIR/repo2/claude/plugin/scripts/"
rm -rf "$RT/.config"
run "$TT_DIR/repo2/bin/claude-orchestrator" --channels plugin:x "Read the doc"
check "no prompt file: one --channels, both entries" test "$(nch)" = 1 -a -n "$(grep -x 'plugin:x' $S/argv)" -a -n "$(grep -x -- "$DCH" $S/argv)"
check "no prompt file: no --append-system-prompt-file" not grep -q -- '--append-system-prompt-file' $S/argv
check "no prompt file: positional prompt last" test "$(tail -1 $S/argv)" = "Read the doc"
check "no prompt file: flag after channel values" test "$(grep -A3 -x -- '--channels' $S/argv | sed -n 4p)" = --settings

# --- agent-board lead
rm -f $S/argv
env HOME="$RT" PATH="$STUB:$ORIG_PATH" "$TT_REPO/bin/agent-board" lead --continue >/dev/null 2>&1
check "agent-board lead --continue: reaches claude with --continue" grep -qx -- '--continue' $S/argv
check "agent-board help lists lead"    test -n "$("$TT_REPO/bin/agent-board" help | grep -F 'agent-board lead [args]  start a dev lead (claude-orchestrator) in this pane')"
tt_done
