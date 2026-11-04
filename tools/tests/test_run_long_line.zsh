# tmux-ctl run/send: a command over 900 bytes must reach a freshly started lane intact.
# Keys typed before ZLE starts sit in the tty's canonical buffer (MAX_CANON 1024 bytes on macOS) and the rest is dropped.
source "${0:A:h}/lib.zsh"
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup
work="$(mktemp -d)"; trap 'rm -rf "$work"; tt_teardown' EXIT INT TERM
mkdir -p "$TT_DIR/proj"
# the bg session (tests/shell) is made with normal shells; only the lanes made later get a slow rc file
( cd "$TT_DIR/proj" && $C run tests true >/dev/null )
busy() { tt send-keys -t '=tt-bg:tests' 'sleep 60' Enter; tt_wait 3 test "$(tt display -p -t '=tt-bg:tests' '#{pane_current_command}')" = sleep }
busy
slowz="$work/slowz"; mkdir -p "$slowz"
print -r -- 'unsetopt GLOBAL_RCS' > "$slowz/.zshenv"; # a builtin wait: no child process, so the pane looks idle while ZLE is not up yet
print -r -- 'zmodload zsh/zselect; zselect -t 200' > "$slowz/.zshrc"
tt set-environment -g ZDOTDIR "$slowz"
lane='=tt-bg:tests·claude'
ctl() { ( cd "$TT_DIR/proj" && $C "$@" ) }
fill="${(l:1500::x:)}"
# (1) long run with quotes, $, backtick, newline, into a fresh lane
cmd="printf '%s\\n' 'it'\\''s $fill'
echo \"\$HOME\" \`echo bt\`"
exp="it's $fill
$HOME bt"
out="$(ctl run -t 25 tests "$cmd" 2>/dev/null)"; rc=$?
check "long run: output exact"   test "$out" = "$exp
[exit 0]"
check "long run: exit 0"         test $rc -eq 0
check "long run: cmds dir empty" test -z "$(print -rl -- $TC_STATE/cmds/*(N))"
# (2) same, failing
tt kill-window -t "$lane" 2>/dev/null
out="$(ctl run -t 25 tests "printf '%s\\n' '$fill'; (exit 3)" 2>/dev/null)"; rc=$?
check "long failing run: output"  test "$(print -r -- "$out" | head -1)" = "$fill"
check "long failing run: exit 3"  test "$(print -r -- "$out" | tail -1)" = "[exit 3]" -a $rc -eq 3
# (3) long send into a fresh lane, then run on the same lane
tt kill-window -t "$lane" 2>/dev/null
v="${(l:1100::y:)}"
ctl send tests "export LONGV=$v; cd /tmp" 2>/dev/null
sleep 3
out="$(ctl run -t 25 -C /tmp tests 'print -r -- ${#LONGV} $PWD' 2>/dev/null)"
check "long send: env and cwd persist" test "$(print -r -- "$out" | head -1)" = "1100 /private/tmp" -o "$(print -r -- "$out" | head -1)" = "1100 /tmp"
check "long send: cmds dir empty"      test -z "$(print -rl -- $TC_STATE/cmds/*(N))"
# (4) a short command is typed as is (fresh lane, so the pane holds nothing of the cases above)
tt kill-window -t "$lane" 2>/dev/null
out="$(ctl run -t 25 tests 'echo short-$RANDOM' 2>/dev/null)"
check "short run: ran" grep -q '^short-[0-9]' <<< "$out"
pane="$(tt capture-pane -p -J -t "$lane" -S -100)"
check "short run: command typed literally" grep -qF 'echo short-$RANDOM' <<< "$pane"
check "short run: no sourcing line"        sh -c '! grep -q "^[^ ]* *\. .*cmds/" <<< "$1"' _ "$pane"
tt_done
