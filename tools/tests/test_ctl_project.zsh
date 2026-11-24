source "${0:A:h}/lib.zsh"
# tmux-ctl project new|start (spec 2026-11-23-new-project-remote §2 tmux-ctl). Scratch tmux server (lib.zsh, -f /dev/null);
# HOME and TC_STATE are temp; the lead is a stub (TC_PROJECT_LEAD_CMD) that prints its arguments; the dev layout is off.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude
H="$TT_DIR/home"; mkdir -p "$H"
export HOME="$H" TC_LAYOUT=/usr/bin/true GIT_CONFIG_NOSYSTEM=1 GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
print -r -- '#!/bin/sh
echo "LEAD-STUB $*"' > "$TT_DIR/lead"; chmod +x "$TT_DIR/lead"
export TC_PROJECT_LEAD_CMD="$TT_DIR/lead"
N=0
run() { (( N++ )); "$@" > "$TT_DIR/out.$N" 2>&1; rc=$?; out="$(<$TT_DIR/out.$N)" }

# --- new --init
run $C project new np1 --init
check "init: exit 0"                     test $rc = 0
check "init: prints the folder"          test "$out" = "$H/np1"
check "init: a git repo on main"         test "$(git -C $H/np1 symbolic-ref --short HEAD 2>/dev/null)" = main
run $C project new np1 --init
check "init again (fresh .git, no commit): exit 0" test $rc = 0
git -C $H/np1 commit -q --allow-empty -m c
run $C project new np1 --init
check "init over a repo with a commit: exit 1"  test $rc = 1
check "init over a repo: says exists"           test "$out" = "project: $H/np1 exists"
mkdir -p $H/full; : > $H/full/f
run $C project new full --init
check "init over a non-empty folder: exit 1"    test $rc = 1

# --- new --clone (a local bare repo)
git init -q --bare -b main "$TT_DIR/src.git"
git clone -q "$TT_DIR/src.git" "$TT_DIR/w" 2>/dev/null; git -C "$TT_DIR/w" commit -q --allow-empty -m first; git -C "$TT_DIR/w" push -q origin main 2>/dev/null
run $C project new np2 --clone "$TT_DIR/src.git"
check "clone: exit 0"                    test $rc = 0
check "clone: prints the folder"         test "$out" = "$H/np2"
check "clone: has the commit"            test "$(git -C $H/np2 log -1 --format=%s)" = first
run $C project new np3 --clone "$TT_DIR/nope.git"
check "clone failure: exit 1"            test $rc = 1
check "clone failure: git's last stderr line" test "${out#project: clone failed: fatal: }" != "$out"
check "clone failure: no folder left"    test ! -e $H/np3
run $C project new np2 --clone "$TT_DIR/src.git"
check "clone into an existing folder: exit 1" test $rc = 1

# --- new --dir
git init -q -b main $H/np4
run $C project new np4 --dir $H/np4
check "dir: exit 0"                      test $rc = 0
check "dir: prints the folder"           test "$out" = "$H/np4"
mkdir -p $H/plain
run $C project new plain --dir $H/plain
check "dir not a work tree: exit 1"      test $rc = 1
check "dir not a work tree: says so"     test "$out" = "project: $H/plain is not a git work tree"
mkdir -p $H/np4/sub
run $C project new sub --dir $H/np4/sub
check "dir inside a repo: exit 1"        test $rc = 1
run $C project new other --dir $H/np4
check "dir with another name: exit 1"    test $rc = 1
run $C project new np5 --dir $H/missing
check "dir missing: exit 1"              test $rc = 1

# --- refusals
run $C project new 'bad.name' --init
check "name with a dot: exit 2"          test $rc = 2
run $C project new '-x' --init
check "name starting with '-': exit 2"   test $rc = 2
run $C project new np6
check "no source: exit 2"                test $rc = 2
run $C project new np6 --init --clone x
check "two sources: exit 2"              test $rc = 2
run $C project new tt --init
check "existing tmux session: exit 1"    test $rc = 1
check "existing tmux session: says so"   test "$out" = "project: tmux session tt exists"
check "existing tmux session: no folder" test ! -e $H/tt

# --- start
mkdir -p "$TC_STATE/discord/np1"; print -r -- '{"channel": "4242", "user": "U1"}' > "$TC_STATE/discord/np1/bridge.json"
run env -u TMUX -u TMUX_PANE $C project start np1
check "start: exit 0"                    test $rc = 0
check "start: says started"              test "$out" = "project: started np1"
check "start: session exists"            tt has-session -t '=np1'
check "start: session runs in the folder" test "$(tt display -p -t '=np1:claude' '#{pane_current_path}')" = "$H/np1"
tt_wait 5 sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=np1:claude' | grep -q 'LEAD-STUB New project np1'"
check "start: the lead got the hello prompt with the channel" sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -J -t '=np1:claude' | grep -q 'LEAD-STUB New project np1, set up from Discord. Post exactly \"hello from np1\" in Discord channel 4242'"
run env -u TMUX -u TMUX_PANE $C project start np1
check "start again: exit 0, no second session" test "$rc $out" = "0 project: np1 already running"
run $C project start np2
tt_wait 5 sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -t '=np2:claude' | grep -q 'LEAD-STUB'"
check "start without a channel: plain lead, no prompt" sh -c "$TT_BIN -L $TT_SOCK_NAME capture-pane -p -J -t '=np2:claude' | grep 'LEAD-STUB' | grep -qv 'hello from'"
run $C project start np4 --dir $H/np4
check "start --dir: exit 0"              test $rc = 0
run $C project start ghost
check "start without a folder: exit 1"   test $rc = 1

# --- help
h="$($C help)"
check "help: project line"               test -n "$(print -r -- "$h" | grep -F 'tmux-ctl project new <name> --init|--clone <url>|--dir <path> | start <name> [--dir <path>]')"
check "help: ends at the header's last line" test "$(print -r -- "$h" | tail -1)" = "  tmux-ctl metrics <sub> …                run-log metrics (board/metrics.py)"
tt_done
