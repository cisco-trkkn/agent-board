source "${0:A:h}/lib.zsh"
# tmux-ctl improve: propose, list and show against a temp engine dir with a fixture engine DB, outside tmux.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
T="$(mktemp -d "${TMPDIR:-/tmp}/ctlimp.XXXXXX")"; T="${T:A}"
export TC_ENGINE_DIR="$T/engine" TC_STATE="$T/state" TC_PROJECT=proj
mkdir -p "$TC_ENGINE_DIR"
python3 -I -c 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute("CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, spec TEXT, job TEXT, kind TEXT, detail TEXT)"); c.commit()' "$TC_ENGINE_DIR/proj.sqlite"
print -r -- $'--- a/claude/x.md\n+++ b/claude/x.md\n@@ -1,1 +1,1 @@\n-a\n+b' > "$T/p.diff"
out="$(env -u TMUX $C improve list 2>&1)"; rc=$?
check "improve list outside tmux does not die not inside tmux" zsh -c '[[ $1 != *"not inside tmux"* ]]' _ "$out"
check "improve list on an empty store exits 0" test $rc -eq 0
id="$(env -u TMUX $C improve propose --kind rule --target claude/x.md --patch "$T/p.diff" --evidence '[{"type":"run","ref":"r1"}]' 2>&1)"
check "propose prints the id P1" test "$id" = P1
check "list prints one line per proposal" zsh -c '[[ "$(env -u TMUX "$1" improve list)" == "P1 proposed high rule claude/x.md" ]]' _ "$C"
check "show prints the patch" zsh -c 'env -u TMUX "$1" improve show P1 | grep -qF "+b"' _ "$C"
check "show --json has the id and state" zsh -c 'env -u TMUX "$1" improve show P1 --json | python3 -c "import json,sys; j=json.load(sys.stdin); sys.exit(0 if (j[\"id\"],j[\"state\"])==(\"P1\",\"proposed\") else 1)"' _ "$C"
err="$(env -u TMUX $C improve propose --kind rule --target t --patch "$T/p.diff" 2>&1 >/dev/null)"; rc=$?
check "propose without evidence is one error line, exit 1" zsh -c '[[ $1 == "improve: propose: no deterministic evidence" ]]' _ "$err"
check "propose without evidence exits 1" test $rc -eq 1
check "outcome status says too early" zsh -c 'env -u TMUX "$1" improve outcome status | grep -q "O1 too early"' _ "$C"
rm -rf "$T"
tt_done
