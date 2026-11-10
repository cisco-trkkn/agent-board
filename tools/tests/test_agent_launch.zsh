# tmux-ctl agent: a long task must reach claude intact even when the window's shell is slow to start.
# Keys typed before ZLE starts sit in the tty's canonical buffer (MAX_CANON 1024 bytes on macOS) and the rest is dropped.
source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"
tt_setup
work="$(mktemp -d)"; trap 'rm -rf "$work"; tt_teardown' EXIT INT TERM
stub="$work/stub"; mkdir -p "$stub"
print -r -- '#!/bin/sh
: > "$STUB_OUT.tmp"
for a in "$@"; do printf "%s\0" "$a" >> "$STUB_OUT.tmp"; done
mv "$STUB_OUT.tmp" "$STUB_OUT"' > "$stub/claude"; chmod +x "$stub/claude"
# the new window's shell reads its input only after 2s, like a slow rc file
slowz="$work/slowz"; mkdir -p "$slowz"
print -r -- 'unsetopt GLOBAL_RCS' > "$slowz/.zshenv"; print -r -- 'sleep 2' > "$slowz/.zshrc"
tt set-environment -g ZDOTDIR "$slowz"
repo="$work/repo"; mkdir -p "$repo"; git -C "$repo" init -q
TC_STATE_DIR="$work/st"; export STUB_OUT="$work/argv"
tt set-environment -g STUB_OUT "$STUB_OUT"   # the server started before the export
nl=$'\n'
task="it's \$HOME \`id\` \$(whoami) \"q\" line1${nl}line2 ${(l:1600::x:)}"
print -rn -- "$task" > "$work/task"
( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent launchtest --force "$task" ) > "$work/out" 2>&1
check "agent command reports started" grep -q "started worker 'launchtest'" "$work/out"
have_argv() { [[ -f "$STUB_OUT" ]] }
check "claude was run within 10s" tt_wait 10 have_argv
verdict="$(python3 -I - "$STUB_OUT" "$work/task" <<'PY'
import sys
try:
    argv = open(sys.argv[1], 'rb').read().split(b'\0')[:-1]
except OSError:
    print("no argv"); sys.exit()
task = open(sys.argv[2], 'rb').read()
print("task-ok" if argv and argv[-1] == task else "task-bad")
print("name-ok" if b'-n' in argv and argv[argv.index(b'-n') + 1] == b'launchtest' else "name-bad")
PY
)"
check "last argv word is the task byte for byte" grep -qx task-ok <<< "$verdict"
check "-n launchtest arrived intact"             grep -qx name-ok <<< "$verdict"
check "launch file under TC_STATE_DIR/agents"    test -n "$(print -rl -- $TC_STATE_DIR/agents/*-launchtest.zsh(N))"
dry="$(cd "$repo" && TC_STATE="$TC_STATE_DIR" TC_SESSION=tt TC_AGENT_DRYRUN=1 "$R/bin/tmux-ctl" agent dryw --force "a b" 2>&1)"
check "dry run prints DRYRUN launch:"  grep -q '^DRYRUN launch: .*agents/tt-dryw\.zsh' <<< "$dry"
check "dry run writes no launch file"  test ! -e "$TC_STATE_DIR/agents/tt-dryw.zsh"
check "launch file is mode 600"  test "$(mode "$TC_STATE_DIR"/agents/tt-launchtest.zsh)" = 600
check "agents dir is mode 700"   test "$(mode "$TC_STATE_DIR/agents")" = 700
dry2="$(cd "$repo" && TC_STATE="$TC_STATE_DIR" TC_SESSION='my sess:1' TC_AGENT_DRYRUN=1 "$R/bin/tmux-ctl" agent dryw --force "a b" 2>&1)"
check "session part of the file name is sanitized" grep -qF "DRYRUN launch: $TC_STATE_DIR/agents/my_sess_1-dryw.zsh" <<< "$dry2"
has_win() { tt list-windows -t '=tt' -F '#{window_name}' | grep -qxF -- "$1" }
chmod 500 "$TC_STATE_DIR/agents"
( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent rofail --force "a b" ) > "$work/out2" 2>&1; rc=$?
chmod 700 "$TC_STATE_DIR/agents"
check "unwritable agents dir: nonzero exit"   test $rc -ne 0
check "unwritable agents dir: no orphan window" test -z "$(tt list-windows -t '=tt' -F '#{window_name}' | grep -xF rofail)"
( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent a/b --force "a b" ) > "$work/out3" 2>&1; rc=$?
check "name a/b: refused with exit 2"  test $rc -eq 2
check "name a/b: no window"            test -z "$(tt list-windows -t '=tt' -F '#{window_name}' | grep -F 'a/b')"
check "name a/b: no stray file"        test -z "$(print -rl -- $TC_STATE_DIR/agents/*a*b*(N) | grep -F 'a/b')"
# a refused re-launch must not overwrite a running worker's launch file
tt new-window -d -t '=tt:' -n existing -c "$repo"
print -r -- ORIG > "$TC_STATE_DIR/agents/tt-existing.zsh"
( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent existing --force "a b" ) > "$work/out4" 2>&1; rc=$?
check "existing window: refused"                      test $rc -ne 0
check "existing window: launch file left untouched"   test "$(<"$TC_STATE_DIR/agents/tt-existing.zsh")" = ORIG
# modes are guaranteed even when the dir and file already existed with looser ones
chmod 755 "$TC_STATE_DIR/agents"; : > "$TC_STATE_DIR/agents/tt-modes.zsh"; chmod 644 "$TC_STATE_DIR/agents/tt-modes.zsh"
( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent modes --force "a b" ) > "$work/out5" 2>&1
check "pre-existing file tightened to 600"  test "$(mode "$TC_STATE_DIR/agents/tt-modes.zsh")" = 600
check "pre-existing dir tightened to 700"   test "$(mode "$TC_STATE_DIR/agents")" = 700
# names that look like options or paths are refused
for bad in -x .. .; do
  ( cd "$repo" && PATH="$stub:$PATH" TC_STATE="$TC_STATE_DIR" TC_SESSION=tt "$R/bin/tmux-ctl" agent "$bad" --force "a b" ) > "$work/out6" 2>&1; rc=$?
  check "name '$bad' refused with exit 2"  test $rc -eq 2
  check "name '$bad': no window"           test -z "$(tt list-windows -t '=tt' -F '#{window_name}' | grep -xF -- "$bad")"
done
tt_done
