source "${0:A:h}/lib.zsh"
zmodload zsh/datetime
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
tt_setup claude shell
export CLAUDE_CODE_SESSION_ID=lead-1
D="$TC_STATE/teammates/lead-1"; mkdir -p "$D"
ts=1700000000; hm="$(strftime %H:%M $ts)"
wr() { python3 -I -c 'import json,sys; json.dump({"ts": int(sys.argv[2]), "name": sys.argv[1], "first_line": sys.argv[3], "text": sys.argv[3]}, open(sys.argv[4], "w"))' "$1" "$2" "$3" "$D/$1.json" }

# nothing at all
check "no teammates when none"       test "$($C teammates)" = "no teammates"
check "no session id -> no teammates" test "$(env -u CLAUDE_CODE_SESSION_ID $C teammates; echo rc=$?)" = $'no teammates\nrc=0'

# a live window a, a dead teammate b (status only), a window-only c; a malformed file; noise files
tt new-window -d -t '=tt:' -n '✦ a'
tt new-window -d -t '=tt:' -n '✦ c'
tt_wait 5 tt_all_idle
wr a $ts "report from a"
wr b $ts "$(printf 'x%.0s' {1..120})"
print -r -- '{not json' > "$D/bad.json"
: > "$D/a.reminded"; : > "$D/.last-remind"
out="$($C teammates; echo rc=$?)"
print -r -- "$out" > "$TT_DIR/out"
check "a is alive and idle with time and first line" grep -qx "a yes idle $hm report from a" "$TT_DIR/out"
check "b is dead, first line cut to 80"  grep -qx "b no - $hm $(printf 'x%.0s' {1..80})" "$TT_DIR/out"
check "window-only c shows dashes"       grep -qx "c yes idle - -" "$TT_DIR/out"
check "rows sorted by name"              test "$(grep -v rc= "$TT_DIR/out" | cut -d' ' -f1 | tr '\n' ' ')" = "a b c "
check "malformed file skipped, exit 0"   sh -c "! grep -q bad '$TT_DIR/out' && grep -qx rc=0 '$TT_DIR/out'"

# busy: a command running in a's pane
tt send-keys -t '=tt:✦ a' 'sleep 60' Enter
tt_wait 5 sh -c "$C teammates | grep -q '^a yes busy'"
check "running pane is busy"             sh -c "$C teammates | grep -q '^a yes busy'"
tt send-keys -t '=tt:✦ a' C-c
tt_done
