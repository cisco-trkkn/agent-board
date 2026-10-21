# The hooks find tools/lib/tc-env.zsh through the symlink they are installed behind
# (~/.claude/hooks/X -> repo/claude/hooks/X), and a missing lib is loud, not silent.
# Seam: isolated tmux server + scratch TC_STATE/TMPDIR (lib.zsh); hooks only write there.
here="${0:A:h}"; root="${here:h:h}"
source "$here/lib.zsh"; F="$here/fixtures"
tt_setup
mkdir -p "$TT_DIR/home/.claude/hooks"
tlog="$TC_STATE/feed-tt-tests.log"; m="$TC_STATE/artifacts-tt.jsonl"

# 1. through a symlink (silent: tc-env must load, so no warning and no error log)
export TMPDIR="$TT_DIR/tmp"; mkdir -p "$TMPDIR"; elog="$TMPDIR/tmux-ctl-hook-errors.log"
ln -s "$root/claude/hooks/bash-mirror.sh" "$TT_DIR/home/.claude/hooks/bash-mirror.sh"
ln -s "$root/claude/hooks/artifact-register.sh" "$TT_DIR/home/.claude/hooks/artifact-register.sh"
err1="$("$TT_DIR/home/.claude/hooks/bash-mirror.sh" < "$F/ok.json" 2>&1 >/dev/null)"
check "bash-mirror via symlink: empty stderr" test -z "$err1"
check "bash-mirror via symlink writes the feed" test -s "$tlog"
mkdir -p "$TT_DIR/r/docs/superpowers/plans"; plan="$TT_DIR/r/docs/superpowers/plans/p.md"; print "# P" > "$plan"
tt rename-window -t '=tt:claude' '✦ impl'
err2="$(print -r -- "{\"tool_name\":\"Write\",\"session_id\":\"S1\",\"tool_input\":{\"file_path\":\"$plan\"}}" | "$TT_DIR/home/.claude/hooks/artifact-register.sh" 2>&1 >/dev/null)"
check "artifact-register via symlink: empty stderr" test -z "$err2"
check "via symlink: no hook error log" test ! -e "$elog"
check "artifact-register via symlink records" test -s "$m"

# 2. tc-env.zsh missing: copies of the hooks in a tree without tools/lib
mkdir -p "$TT_DIR/bare/claude/hooks"; cp "$root"/claude/hooks/{bash-mirror,artifact-register}.sh "$TT_DIR/bare/claude/hooks/"
for h in bash-mirror artifact-register; do
  rm -f "$TMPDIR"/tmux-ctl-hook-errors.log
  err="$("$TT_DIR/bare/claude/hooks/$h.sh" < "$F/ok.json" 2>&1 >/dev/null)"; rc=$?
  check "$h missing lib: exit 0"        test $rc -eq 0
  check "$h missing lib: stderr line"   grep -q 'tc-env.zsh' <<<"$err"
  check "$h missing lib: logged"        grep -q "$h.*tc-env.zsh" "$TMPDIR/tmux-ctl-hook-errors.log"
done
# the plugin keeps working without tc-env: the feed / manifest are still written (default state dir)
n0="$(grep -c '^── ' "$tlog")"; m0="$(wc -l < "$m")"
sed "s|__HOME__|$HOME|" "$F/ok.json" | "$TT_DIR/bare/claude/hooks/bash-mirror.sh" 2>/dev/null
check "bash-mirror missing lib: feed still written" test "$(grep -c '^── ' "$tlog")" -eq $(( n0 + 1 ))
"$TT_DIR/bare/claude/hooks/artifact-register.sh" --path "$plan" --agent you --project tt 2>/dev/null
check "artifact-register missing lib: manifest still written" test "$(wc -l < "$m")" -gt "$m0"
tt_done
