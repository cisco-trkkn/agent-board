source "${0:A:h}/lib.zsh"
# tmux-ctl context show|path|add: the shared project context file, keyed like `tmux-ctl idea` (board/context.py).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
export TC_CONTEXT_DIR="${$(mktemp -d "${TMPDIR:-/tmp}/ttctx.XXXXXX"):A}"
tt_setup claude
f="$TC_CONTEXT_DIR/tt.md"
check "path before any add"                  test "$($C context path)" = "$f"
check "show before any add: empty, exit 0"   sh -c "out=\$($C context show) && [ -z \"\$out\" ]"
out="$($C context add Map 'the board is board/server.py (files: board/server.py)')"
check "add creates the file under the session key"   test -s "$f"
check "add prints the line"                  zsh -c '[[ $1 == "added under ## Map: - the board is board/server.py (files: board/server.py) · "[0-9]* ]]' _ "$out"
check "four headings in order"               test "$(grep '^## ' "$f" | sed 's/^## //' | tr '\n' '|')" = 'Map|How to run|Gotchas|Decisions|'
check "entry under Map, dated"               grep -q '^- the board is board/server.py (files: board/server.py) · 20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]$' "$f"
$C context add 'How to run' 'zsh tools/tests/run-all.zsh (files: tools/tests/run-all.zsh)' >/dev/null
check "a two-word section name works"        sh -c "sed -n '/^## How to run/,/^## Gotchas/p' ${(q)f} | grep -q run-all"
check "show prints the file"                 test "$($C context show)" = "$(<$f)"
check "unknown section exits 2"              sh -c "! $C context add Notes x 2>/dev/null"
check "unknown section writes nothing"       test "$(grep -c '^- ' "$f")" -eq 2
check "no subcommand exits 2"                sh -c "! $C context 2>/dev/null"
check "add without an entry exits 2"         sh -c "! $C context add Map 2>/dev/null"
# the key is the ideas key: from a -bg pane it is the project, never <project>-bg (the rule `tmux-ctl idea` follows)
tt new-session -d -s tt-bg -c "$TT_DIR"; tt set-option -t '=tt-bg:' @tc_bg 1
TC_SESSION=tt-bg $C context add Gotchas "from the bg pane" >/dev/null
check "key strips -bg"                       grep -q 'from the bg pane' "$f"
check "no -bg-bg key"                        test ! -e "$TC_CONTEXT_DIR/tt-bg.md"
# search: core rows then archive rows, G12 formats
print -r -- $'# tt: archive\n\n## Decisions\n- usage tap was dropped in the archive · 2026-10-01' > "$TC_CONTEXT_DIR/tt.archive.md"
$C context add Map 'usage tap rows come from the tap (files: board/usage.py)' >/dev/null
sr="$($C context search usage tap)"
check "search prints a [core] row"           zsh -c '[[ $1 == *"[core] Map: - usage tap rows come from the tap"* ]]' _ "$sr"
check "search prints an [archive] row"       zsh -c '[[ $1 == *"[archive] Decisions: - usage tap was dropped in the archive · 2026-10-01" ]]' _ "$sr"
check "core row comes before archive row"    test "$(print -r -- "$sr" | sed -n '1p' | cut -c1-6)" = "[core]"
nm="$($C context search zzznomatch 2>&1 >/dev/null)"; nrc=$?
check "no match: stderr line, exit 0"        test "$nm" = "context: no entries match" -a $nrc -eq 0
check "no match: nothing on stdout"          test -z "$($C context search zzznomatch 2>/dev/null)"
check "search with no word exits 2"          sh -c "! $C context search 2>/dev/null"
check "search with no word says usage"       sh -c "$C context search 2>&1 | grep -q 'usage: tmux-ctl context search'"
check "help lists context search"            sh -c "$C help | grep -q 'tmux-ctl context search'"
check "help lists context"                   sh -c "$C help | grep -q 'tmux-ctl context'"
check "help still ends at the blank line"    test "$($C help | tail -1)" = ""
# the file opens in the board's artifacts panel (spec: tmux-ctl artifact "$(tmux-ctl context path)")
$C artifact "$($C context path)" >/dev/null
check "artifact registers the context file"  test "$(jq -r --arg p "$f" 'select(.path==$p)|.kind' "$TC_STATE/artifacts-tt.jsonl" | tail -1)" = other
rm -rf "$TC_CONTEXT_DIR"
tt_done
