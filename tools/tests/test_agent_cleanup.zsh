#!/usr/bin/env zsh
# tmux-agent-cleanup: the four lock cases and the remove-all-safe row, against temp repos and a stub fzf.
# The stub selects the rows matching $FZF_PICK (grep), every row when unset; it saves what it was offered to $FZF_SEEN.
# Needs no tmux server. Lock-line format captured from Claude Code 2.1.301 (see board/tests/test_worktree_lock.py).
here="${0:A:h}"; root="${here:h:h}"
source "$here/lib.zsh"
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@t GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@t
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null
T="$(mktemp -d)"; T="${T:A}"; started=()
cleanup() { local p; for p in "${started[@]}"; do kill "$p" 2>/dev/null; done; rm -rf "$T"; tt_teardown }
trap cleanup EXIT INT TERM

repo="$T/repo"; mkdir -p "$repo"
git -C "$repo" init -qb main && git -C "$repo" commit -q --allow-empty -m init
print -r -- $'#!/bin/sh\ntee "${FZF_SEEN:-/dev/null}" | if [ -n "$FZF_PICK" ]; then grep -- "$FZF_PICK"; else cat; fi' > "$T/fzf-stub"; chmod +x "$T/fzf-stub"
print -r -- $'#!/bin/sh\nexit 0' > "$T/tmux-stub"; print -r -- $'#!/bin/sh\necho "[]"' > "$T/glab-stub"; chmod +x "$T/tmux-stub" "$T/glab-stub"
export AW_TMUX="$T/tmux-stub" AW_GLAB="$T/glab-stub"   # the engine never reaches a real tmux server or glab
export AW_STATE_DIR="$T/state"   # the engine's sweep log goes here, not to the real ~/.local/state
print -r -- $'#!/bin/sh\nwhile :; do sleep 1; done' > "$T/claude-fake"; chmod +x "$T/claude-fake"

mk() { git -C "$repo" worktree add -q "$repo/.claude/worktrees/$1" -b "$1" }
dead() { true & local p=$!; wait $p; print $p }
"$T/claude-fake" & live=$!; started+=($live)
sleep 0.3

mk dead;   git -C "$repo" worktree lock --reason "claude session dead (pid $(dead) start Fri Oct 16 19:12:53 2026)" "$repo/.claude/worktrees/dead"
mk live;   git -C "$repo" worktree lock --reason "claude session live (pid $live start Fri Oct 16 19:12:53 2026)" "$repo/.claude/worktrees/live"
mk manual; git -C "$repo" worktree lock --reason "manual hold" "$repo/.claude/worktrees/manual"
dreason="claude session dirty (pid $(dead) start Fri Oct 16 19:12:53 2026)"
mk dirty;  git -C "$repo" worktree lock --reason "$dreason" "$repo/.claude/worktrees/dirty"
print mine > "$repo/.claude/worktrees/dirty/keep.txt"

out="$(FZF_PICK='/.claude/worktrees/' FZF_BIN="$T/fzf-stub" zsh "$root/bin/tmux-agent-cleanup" "$repo" </dev/null 2>&1)"
list="$(git -C "$repo" worktree list --porcelain)"
sect() { print -r -- "$out" | awk -v n="› $1" '$0==n{f=1;next} /^› /{f=0} f' }

check "dead-pid lock: unlocked and removed" test -z "$(grep 'worktrees/dead$' <<<"$list")"
check "dead-pid lock: reports removal" grep -q "removed worktree" <<<"$(sect dead)"
check "live claude pid: kept, in use" grep -q "kept: in use by a running Claude session (pid $live)" <<<"$(sect live)"
check "live claude pid: still listed and locked" grep -q "worktrees/live$" <<<"$list"
check "manual hold: kept with reason" grep -q "kept: locked by something other than Claude (manual hold)" <<<"$(sect manual)"
check "manual hold: still locked" grep -q "^locked manual hold$" <<<"$list"
check "dirty: refused, files named" grep -q "kept: dirty has uncommitted or untracked files" <<<"$(sect dirty)"
check "dirty: still locked with original reason" grep -qxF "locked $dreason" <<<"$list"
check "dirty: file untouched" test "$(cat $repo/.claude/worktrees/dirty/keep.txt)" = mine

# remove-all-safe row: a merged worktree goes, an unmerged one stays, a 9-day-old unmerged one shows `stale 9d`
repo2="$T/repo2"; mkdir -p "$repo2"
git -C "$repo2" init -qb main && git -C "$repo2" commit -q --allow-empty -m init
mk2() { git -C "$repo2" worktree add -q "$repo2/.claude/worktrees/$1" -b "$1" }
mk2 merged; mk2 unmerged; mk2 old
git -C "$repo2/.claude/worktrees/unmerged" commit -q --allow-empty -m wip
old_d="$(date -v-9d +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -d '9 days ago' +%Y-%m-%dT%H:%M:%S)"
GIT_AUTHOR_DATE="$old_d" GIT_COMMITTER_DATE="$old_d" git -C "$repo2/.claude/worktrees/old" commit -q --allow-empty -m ancient
export FZF_SEEN="$T/seen"
out2="$(FZF_PICK='remove all safe' FZF_BIN="$T/fzf-stub" zsh "$root/bin/tmux-agent-cleanup" "$repo2" </dev/null 2>&1)"
list2="$(git -C "$repo2" worktree list --porcelain)"
check "first row is ⟳ remove all safe (1)" test "$(head -1 "$T/seen" | cut -f3)" = "⟳ remove all safe (1)"
check "a 9-day-old unmerged row shows stale 9d" grep -q 'old.*stale 9d' "$T/seen"
check "all-safe row: merged worktree removed" test -z "$(grep 'worktrees/merged$' <<<"$list2")"
check "all-safe row: unmerged worktree kept" grep -q 'worktrees/unmerged$' <<<"$list2"
check "all-safe row: stale worktree kept" grep -q 'worktrees/old$' <<<"$list2"
check "all-safe row: reports the engine's sweep" grep -q 'removed merged' <<<"$out2"
check "no tmux-agent-cleanup lock/merge logic left" test -z "$(grep -E 'merge-base|kill -0|worktree (remove|unlock|lock)' "$root/bin/tmux-agent-cleanup")"

# marking a stale row removes just that one, through the engine
out3="$(FZF_PICK=$'worktrees/old\t' FZF_BIN="$T/fzf-stub" zsh "$root/bin/tmux-agent-cleanup" "$repo2" </dev/null 2>&1)"
check "marked row removed through the engine" test -z "$(git -C "$repo2" worktree list --porcelain | grep 'worktrees/old$')"
check "marked unmerged row: branch kept, said so" grep -q 'kept branch old (not merged)' <<<"$out3"

# agent-board worktrees <args> runs the CLI
tbl="$(zsh "$root/bin/agent-board" worktrees classify --offline "$repo2" 2>&1)"
check "agent-board worktrees classify prints the plain table" grep -qE '^unmerged	kept	not merged$' <<<"$tbl"
tt_done
