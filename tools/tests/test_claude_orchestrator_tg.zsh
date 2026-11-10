source "${0:A:h}/lib.zsh"
# claude-orchestrator opts a lead into the Telegram channel when its project has a saved token.
# A stub `claude` first on PATH records what it was started with.
tt_setup claude
RT="$TT_DIR/home"; mkdir -p "$RT"
STUB="$TT_DIR/stub"; S="$TT_DIR/out"; mkdir -p "$STUB" "$S"
cat > "$STUB/claude" <<STUBEOF
#!/bin/zsh
print -rl -- "\$@" > $S/argv
print -r -- "\${TELEGRAM_STATE_DIR-UNSET}" > $S/tsd
print -r -- "\$PATH" > $S/path
STUBEOF
chmod +x "$STUB/claude"
not() { ! "$@" }
ORIG_PATH="$PATH"
TG="$TC_STATE/telegram/tt"
run() {   # run [env-prefix...] -- [args]: start the launcher in this pane's session
  rm -f $S/argv $S/tsd $S/path
  env HOME="$RT" PATH="$STUB:$ORIG_PATH" "$@" >/dev/null 2>&1
}
argv() { print -r -- "$(<$S/argv)" }
nch() { grep -c -- '^--channels' $S/argv }
L="$TT_REPO/bin/claude-orchestrator"

run "$L" --continue
check "no token: no --channels"        test "$(nch)" = 0
check "no token: TELEGRAM_STATE_DIR unset" test "$(<$S/tsd)" = UNSET
check "no token: caller args kept"     grep -qx -- '--continue' $S/argv

mkdir -p "$TG"; : > "$TG/.env"
run "$L" --continue
check "token: one --channels"          test "$(nch)" = 1
check "token: plugin value follows"    test "$(grep -A1 -x -- '--channels' $S/argv | tail -1)" = plugin:telegram@claude-plugins-official
check "token: flag before caller args" test "$(grep -n -x -- '--channels' $S/argv | cut -d: -f1)" -lt "$(grep -n -x -- '--continue' $S/argv | cut -d: -f1)"
check "token: TELEGRAM_STATE_DIR"      test "$(<$S/tsd)" = "$TG"
check "token: not in tmux session env" not tt show-environment -t '=tt' TELEGRAM_STATE_DIR

run TC_TELEGRAM=0 "$L" --continue
check "TC_TELEGRAM=0: no --channels"   test "$(nch)" = 0
check "TC_TELEGRAM=0: state dir unset" test "$(<$S/tsd)" = UNSET

run "$L" --channels plugin:x
check "caller --channels X: not doubled" test "$(nch)" = 1
check "caller --channels X: theirs kept" grep -qx 'plugin:x' $S/argv
run "$L" --channels=plugin:x
check "caller --channels=X: no second flag" test "$(grep -c -- '--channels' $S/argv)" = 1

run env -u TMUX -u TMUX_PANE "$L" --continue
check "outside tmux: no --channels"    test "$(nch)" = 0
check "outside tmux: state dir unset"  test "$(<$S/tsd)" = UNSET

rm -rf "$TG"
run TELEGRAM_STATE_DIR=/bogus "$L"
check "inherited state dir cleared"    test "$(<$S/tsd)" = UNSET

# -bg session of the same project shares the project's token
mkdir -p "$TG"; : > "$TG/.env"
tt new-session -d -s tt-bg -c "$TT_DIR"; tt set-option -t '=tt-bg:' @tc_bg 1
BGPANE="$(tt display -p -t '=tt-bg:' '#{pane_id}')"
run env TMUX_PANE="$BGPANE" "$L"
check "-bg session: project is tt"     test "$(<$S/tsd)" = "$TG"
tt kill-session -t '=tt-bg'

# bun dir
run "$L"
has() { [[ "$1" == *"$2"* ]] }
check "no ~/.bun/bin: PATH unchanged"  not has "$(<$S/path)" "$RT/.bun/bin"
mkdir -p "$RT/.bun/bin"
run "$L"
check "~/.bun/bin on claude's PATH"    test "${${(s.:.)$(<$S/path)}[1]}" = "$RT/.bun/bin" -o "${${(s.:.)$(<$S/path)}[2]}" = "$RT/.bun/bin"
check "~/.bun/bin in session env PATH" has "$(tt show-environment -t '=tt' PATH)" "$RT/.bun/bin"

# the exec line without a prompt file (no claude/orchestrator.md next to the launcher) carries the flag too
mkdir -p "$TT_DIR/repo2/bin"; cp "$TT_REPO"/bin/{claude-orchestrator,_ab_claude.zsh,_tc_bins.zsh} "$TT_DIR/repo2/bin/"
rm -rf "$RT/.config"
run "$TT_DIR/repo2/bin/claude-orchestrator" --continue
check "no prompt file: one --channels"  test "$(nch)" = 1
check "no prompt file: no --append-system-prompt-file" not grep -q -- '--append-system-prompt-file' $S/argv

# --channels is variadic: the element after its value must be a flag, or a positional prompt is swallowed as a channel
after_ch() { grep -A2 -x -- '--channels' $S/argv | sed -n 3p }
run "$L" "Read the doc"
check "prompt file present: flag after channel value" test "$(after_ch)" = --settings
check "prompt file present: positional prompt kept" grep -qx 'Read the doc' $S/argv
run "$TT_DIR/repo2/bin/claude-orchestrator" "Read the doc"
check "no prompt file: flag after channel value"      test "$(after_ch)" = --settings
check "no prompt file: positional prompt kept"        grep -qx 'Read the doc' $S/argv

tt_done
