#!/usr/bin/env zsh
# tmux-agent-cleanup: the four lock cases, against a temp repo and a stub fzf (selects every row).
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
print -r -- $'#!/bin/sh\ncat' > "$T/fzf-stub"; chmod +x "$T/fzf-stub"
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

out="$(FZF_BIN="$T/fzf-stub" zsh "$root/bin/tmux-agent-cleanup" "$repo" </dev/null 2>&1)"
list="$(git -C "$repo" worktree list --porcelain)"
sect() { print -r -- "$out" | awk -v n="› $1" '$0==n{f=1;next} /^› /{f=0} f' }

check "dead-pid lock: unlocked and removed" test -z "$(grep 'worktrees/dead$' <<<"$list")"
check "dead-pid lock: reports removal" grep -q "removed worktree" <<<"$(sect dead)"
check "live claude pid: kept, in use" grep -q "kept (in use by a running Claude session, pid $live)" <<<"$(sect live)"
check "live claude pid: still listed and locked" grep -q "worktrees/live$" <<<"$list"
check "manual hold: kept with reason" grep -q "kept (locked: manual hold)" <<<"$(sect manual)"
check "manual hold: still locked" grep -q "^locked manual hold$" <<<"$list"
check "dirty: git error printed" grep -q "kept: .*\(contains modified or untracked files\|use --force\)" <<<"$(sect dirty)"
check "dirty: still locked with original reason" grep -qxF "locked $dreason" <<<"$list"
check "dirty: file untouched" test "$(cat $repo/.claude/worktrees/dirty/keep.txt)" = mine
tt_done
