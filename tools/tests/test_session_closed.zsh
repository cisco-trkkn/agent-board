source "${0:A:h}/lib.zsh"
R="${0:A:h:h:h}"
S="${TC_SESSION_CLOSED:-$R/bin/tmux-session-closed}"
export TC_IDEAS_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ttideas.XXXXXX")"
tt_setup claude
# register the very line config/tmux.conf carries, not a copy ($AGENT_BOARD_REPO comes from the harness server's env)
grep '^set-hook -g session-closed' "${TC_CONF:-$R/config/tmux.conf}" > "$TT_DIR/hook.conf"
check "conf has the hook line" test -s "$TT_DIR/hook.conf"
tt source-file "$TT_DIR/hook.conf"
mk() {   # mk <project>: per-session state files
  local p="$1"
  mkdir -p "$TC_STATE/logs/$p"; print x > "$TC_STATE/logs/$p/r.log"
  for f in artifacts-$p.jsonl lineage-$p.jsonl runs-$p.jsonl feed-$p-tests.log feed-$p-shell.log; do print x > "$TC_STATE/$f"; done
}
has() { test -e "$TC_STATE/artifacts-$1.jsonl" -o -e "$TC_STATE/runs-$1.jsonl" -o -e "$TC_STATE/feed-$1-tests.log" -o -e "$TC_STATE/lineage-$1.jsonl" -o -e "$TC_STATE/feed-$1-shell.log" -o -d "$TC_STATE/logs/$1" }
gone() { ! has "$1" }
mk foo; mk foo-bar; mk proj; print idea > "$TC_IDEAS_DIR/foo.md"
tt new-session -d -s foo -c "$TT_DIR"; tt new-session -d -s foo-bar -c "$TT_DIR"; tt new-session -d -s proj -c "$TT_DIR"
tt new-session -d -s foo-bg -c "$TT_DIR"

tt kill-session -t '=foo-bg'; sleep 1
check "a -bg session closing keeps state"   has foo
tt new-session -d -s _web-1 -t proj; tt kill-session -t '=_web-1'; sleep 1
check "closing a _web view keeps state"     has proj
tt new-session -d -s _web-2 -t proj; tt kill-session -t '=proj'; sleep 1
check "project closed but a grouped view still exists: keep" has proj
tt kill-session -t '=_web-2'; sleep 1
check "view closing later still keeps state (name is _web-)" has proj
tt kill-session -t '=foo'
check "project state removed"               tt_wait 5 gone foo
check "other project (foo-bar) untouched"   has foo-bar
check "ideas file is never deleted"         test -s "$TC_IDEAS_DIR/foo.md"
# hostile session names must never reach a shell
MD="${TMPDIR:-/tmp}/ttm$$"; mkdir -p "$MD"; MARK="$MD/pwned"   # no dots or colons: tmux rewrites those in names
for nm in 'x$(touch '$MARK')' 'x`touch '$MARK'`' "x'; touch $MARK; '" 'x"; touch '$MARK'; "'; do
  tt new-session -d -s "$nm" -c "$TT_DIR"; tt kill-session -t "=$nm"
done
sleep 1.5
check "hostile names run no command"       test ! -e "$MARK"
check "hostile names leave state alone"    has foo-bar
# N1: if the server cannot be asked, delete nothing
mk gone2
TC_TMUX=/usr/bin/false $S gone2
check "list-sessions failure deletes nothing" has gone2
$S ".." ; $S "" ; $S "a/b"
check "bad names are ignored"               has foo-bar
rm -rf "$TC_IDEAS_DIR" "$MD"
tt_done
