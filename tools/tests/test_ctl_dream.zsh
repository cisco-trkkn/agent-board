source "${0:A:h}/lib.zsh"
# tmux-ctl context dream / dream-report: the nightly run through the CLI, with and without tmux (board/dream.py).
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
T="${$(mktemp -d "${TMPDIR:-/tmp}/ttdream.XXXXXX"):A}"
export HOME="$T/home"; mkdir -p "$HOME"
export TC_CONTEXT_DIR="$T/ctx" TASK_OBSERVER_WORKSPACE="$T/obs"
export TC_DREAM_CLAUDE="$TT_REPO/board/tests/fixtures/dream/claude" FAKE_DREAM_MODE=good FAKE_DREAM_LOG="$T/fake.log"
mkdir -p "$TC_CONTEXT_DIR" "$T/repo/docs/superpowers/ledgers/s1"
print -r -- 'Ruling: x' > "$T/repo/docs/superpowers/ledgers/s1/progress.md"
git -C "$T/repo" init -q && git -C "$T/repo" -c user.email=t@t -c user.name=t add -A && git -C "$T/repo" -c user.email=t@t -c user.name=t commit -qm init
tt_setup claude   # sets TC_STATE (a temp dir) and the scratch tmux server
export TC_TMUX="$TT_BIN"   # the scratch tmux binary; the live-session lookup of dream.py reads the scratch server, never the real one
python3 - "$TC_CONTEXT_DIR/tt.md" <<'PY'
import sys
out = ["# tt: shared agent context", "Last curated: 2026-11-01", ""]
for s in ("Map", "How to run", "Gotchas", "Decisions"):
    out.append(f"## {s}")
    out += [f"- {s} fact {i} {'x' * 250} (files: board/gone-{i}.py) · 2026-11-{i + 1:02d}" for i in range(8)]
    out.append("")
open(sys.argv[1], "w").write("\n".join(out))
PY
before="$(shasum "$TC_CONTEXT_DIR/tt.md")"
out="$($C context dream tt --dry-run --root "$T/repo")"; rc=$?
check "dry run exits 0"                       test $rc -eq 0
check "dry run prints the dry run line"       zsh -c '[[ $1 == "dream: tt dry run — merged "* ]]' _ "$out"
check "dry run leaves the core alone"         test "$(shasum "$TC_CONTEXT_DIR/tt.md")" = "$before"
out="$($C context dream tt --root "$T/repo")"; rc=$?
check "a good run through tmux-ctl"           zsh -c '[[ $1 == "dream: tt ok — merged 0, archived "* ]]' _ "$out"
check "the core is now within the cap"        test "$(wc -c < "$TC_CONTEXT_DIR/tt.md")" -le 8192
check "dream.json written"                    test -s "$TC_CONTEXT_DIR/tt.dream.json"
out="$(TMUX= TMUX_PANE= $C context dream tt --force --root "$T/repo")"; rc=$?
check "dream works with TMUX unset"           test $rc -eq 0 -a -n "$out"
out="$(TMUX= TMUX_PANE= $C context dream --all --force --root "$T/repo")"
check "dream --all works with TMUX unset"     zsh -c '[[ $1 == "dream: tt "* ]]' _ "$out"
out="$(TMUX= TMUX_PANE= $C context dream-report tt)"
check "dream-report prints the run"           zsh -c '[[ $1 == *"outcome: "* && $1 == *"fake summary"* ]]' _ "$out"
check "dream-report with no run"              test "$($C context dream-report nobody)" = "dream: nobody has no run yet"
$C context dream >/dev/null 2>&1; rc=$?
check "dream with no argument exits 2"        test $rc -eq 2
out="$(TMUX= TMUX_PANE= $C context show 2>&1)"; rc=$?
check "context show outside tmux still dies"  zsh -c '[[ $1 == *"not inside tmux"* ]]' _ "$out"
check "help lists context dream"              sh -c "$C help | grep -q 'tmux-ctl context dream '"
check "help lists context dream-report"       sh -c "$C help | grep -q 'tmux-ctl context dream-report'"
check "help still ends at the blank line"     test "$($C help | tail -1)" = ""
rm -rf "$T"
tt_done
