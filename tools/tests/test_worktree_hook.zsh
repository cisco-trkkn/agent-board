# test_worktree_hook.zsh — the PostToolUse hook that starts a detached `agent-worktrees sweep <repo>` after a merge-like command.
# AW_CLI points at a stub; the hook script under test is the real one (via its legacy symlink). Scratch tmux server + scratch repos only.
source "${0:A:h}/lib.zsh"
H="${TC_WTSWEEP:-$TT_REPO/claude/hooks/worktree-sweep.sh}"
tt_setup
unset AGENT_BOARD   # a board-opened shell exports it; the dedupe test sets it itself
W="$TT_DIR/w"; mkdir -p "$W"
argvf="$W/argv"; pidf="$W/pid"
feed="$TC_STATE/feed-tt-shell.log"

# stub CLI: records argv, prints a canned sweep summary
cat > "$W/aw-stub" <<STUB
#!/bin/sh
echo "\$@" >> "$argvf"
printf 'removed wt-a\nkept wt-b (unmerged)\nstale wt-c (9d)\n'
STUB
cat > "$W/aw-slow" <<STUB
#!/bin/sh
echo "\$@" >> "$argvf"
echo \$\$ > "$pidf"
exec sleep 5
STUB
chmod +x "$W/aw-stub" "$W/aw-slow"
export AW_CLI="$W/aw-stub"

# scratch repo with a linked worktree, and a non-repo dir
R="$W/repo"; mkdir -p "$R" "$W/plain"
git -C "$R" init -q -b main && git -C "$R" -c user.name=t -c user.email=t@t commit -q --allow-empty -m i
git -C "$R" worktree add -q "$W/repo-wt" -b feat
R="${R:A}"; LW="${W:A}/repo-wt"
R2="$W/repo2"; mkdir -p "$R2"; git -C "$R2" init -q -b main; R2="${R2:A}"

payload() {   # payload <command> [cwd]
  python3 -I -c 'import json,sys; print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"Bash","cwd":sys.argv[2],"tool_input":{"command":sys.argv[1]},"tool_response":{"stdout":"","stderr":""}}))' "$1" "${2:-$R}"
}
run() { payload "$@" 2>/dev/null | "$H" "${HOOK_ARGS[@]}"; }   # run <command> [cwd]
HOOK_ARGS=()
waitfor() { tt_wait 5 test -s "$1"; }   # waitfor <file>
fires() {   # fires <command> [cwd]: the stub got called
  rm -f "$argvf"; run "$@" >/dev/null; waitfor "$argvf"
}
silent() {  # silent <command> [cwd]: no call within 0.7s
  rm -f "$argvf"; run "$@" >/dev/null; sleep 0.7; [[ ! -e "$argvf" ]]
}

for c in 'git merge x' 'cd a && git pull' 'glab mr merge 3' 'git branch -d f' "git -C $R merge x" 'git branch -D f' 'git pull --rebase' \
         'tmux-ctl run tests "git merge x"' 'git -c core.x=1 merge x' "bash -c 'git merge x'"; do
  check "fires: $c" fires "$c"
done
for c in 'git status' 'echo "git merge"' 'git log --merges' 'git branch -a' 'git branch --list' 'git commit -m "git pull"' 'echo git-merge' 'git mergetool'; do
  check "silent: $c" silent "$c"
done

# repo resolution
fires 'git merge x' "$LW"
check "repo = main checkout of cwd (from a linked worktree)" test "$(<$argvf)" = "sweep $R"
fires 'git merge x' "$R"
check "repo = cwd's checkout" test "$(<$argvf)" = "sweep $R"
fires "git -C $R2 merge x" "$R"
check "git -C beats cwd" test "$(<$argvf)" = "sweep $R2"
check "git -C into a non-repo: no-op" silent "git -C $W/plain merge x" "$R"
check "non-repo cwd: no-op" silent 'git merge x' "$W/plain"
check "bad json: no-op, exit 0" zsh -c 'echo nope | "$1"' _ "$H"
check "non-Bash tool: no-op" zsh -c 'rm -f "$2"; echo "{\"tool_name\":\"Write\",\"cwd\":\"$3\",\"tool_input\":{\"command\":\"git merge x\"}}" | "$1"; sleep 0.7; [[ ! -e "$2" ]]' _ "$H" "$argvf" "$R"

# silent stdout, exit 0
out="$(payload 'git merge x' | "$H" 2>&1)"; rcode=$?
check "stdout empty, exit 0" test -z "$out" -a $rcode -eq 0

# feed + sweep log
tt_wait 5 grep -q swept: "$feed" 2>/dev/null; sleep 0.5   # let the sweep from the stdout test finish
rm -f "$feed" "$argvf"; run 'git merge x' >/dev/null
tt_wait 5 grep -q 'swept:' "$feed" 2>/dev/null
check "feed entry written to the shell feed" test -s "$feed"
check "header: agent worktree-sweep, cwd, exit 0, epoch" grep -qE '^── [0-9]{2}:[0-9]{2}:[0-9]{2} · worktree-sweep · .* · exit 0 · @[0-9]{9,}$' "$feed"
check "command line shows the sweep" grep -qxF "\$ agent-worktrees sweep $R" "$feed"
check "body: removed/kept/stale summary" grep -qxF 'swept: removed wt-a; kept wt-b (unmerged); stale wt-c (9d)' "$feed"
check "one entry per merge" test "$(grep -c '^── ' "$feed")" -eq 1
check "engine invoked with the repo (stub argv)" test "$(<$argvf)" = "sweep $R"
check "hook writes no worktree-sweep.log (the engine owns the sweep log)" test -z "$(find "$TC_STATE" -name 'worktree-sweep.log*')"

# no dev session (no shell window): the sweep still runs, no feed
tt rename-window -t '=tt:shell' other
rm -f "$feed" "$argvf"; run 'git merge x' >/dev/null
tt_wait 5 test -s "$argvf"; sleep 0.5
check "no shell window: sweep still runs" test "$(<$argvf)" = "sweep $R"
check "no shell window: no feed" test ! -e "$feed"
tt rename-window -t '=tt:other' shell

# dedupe rule
export AGENT_BOARD=1; HOOK_ARGS=()
check "AGENT_BOARD=1 without --scoped: skipped" silent 'git merge x'
HOOK_ARGS=(--scoped)
check "AGENT_BOARD=1 with --scoped: runs" fires 'git merge x'
unset AGENT_BOARD; HOOK_ARGS=()

# detached: hook returns fast while a 5s sweep runs; its stdout stays empty
export AW_CLI="$W/aw-slow"; rm -f "$pidf"
t0=$EPOCHREALTIME
out="$(payload 'git merge x' | "$H")"
el=$(( EPOCHREALTIME - t0 ))
check "hook exits < 1s with a 5s sweep (took ${el[1,5]}s), silent" test -z "$out" -a $(( el < 1.0 )) -eq 1
tt_wait 3 test -s "$pidf"
check "slow sweep really started" test -s "$pidf"
[[ -s "$pidf" ]] && kill "$(<$pidf)" 2>/dev/null   # by PID: the stub exec'd into sleep
export AW_CLI="$W/aw-stub"
sleep 0.5

# leak check: no stub left running
check "no sweep process left behind" test -z "$(pgrep -f "$W/aw-")"
tt_done
