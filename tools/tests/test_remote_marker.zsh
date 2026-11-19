source "${0:A:h}/lib.zsh"
# UserPromptSubmit remote marker. Payload keys (prompt, session_id) as in test_context_recall; the channel tag text is the
# real one from the lead transcript probe of 2026-11-19. TC_STATE comes from tt_setup, so the allowlist and the marker land in the temp dir.
H="${TC_REMOTE_MARKER:-$TT_REPO/claude/plugin/scripts/remote-marker.sh}"
tt_setup shell
tmp="$(mktemp -d "${TMPDIR:-/tmp}/rmk.XXXXXX")"
trap 'rm -rf "$tmp"; tt_teardown' EXIT INT TERM
mkdir -p "$TC_STATE/discord/proj" "$TC_STATE/discord/_ops"
print -r -- '{"dmPolicy":"allowlist","allowFrom":["111"],"groups":{},"pending":{}}' > "$TC_STATE/discord/proj/access.json"
print -r -- '{"dmPolicy":"allowlist","allowFrom":["222"]}' > "$TC_STATE/discord/_ops/access.json"
M="$TC_STATE/remote/sess-1"
DISC='<channel source="plugin:discord:discord" chat_id="1" message_id="2" user="u" user_id="UID" ts="2026-01-01T00:00:00.000Z">'$'\nhi\n</channel>'

# run <session_id> <prompt>
run() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[1],"prompt":sys.argv[2],"hook_event_name":"UserPromptSubmit"}))' "$1" "$2" | "$H" --scoped >"$tmp/o" 2>"$tmp/e"; rc=$?; out="$(<$tmp/o)"; err="$(<$tmp/e)"; }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]]; }

run sess-1 "${DISC/UID/111}"
check "allowlisted discord prompt creates the marker"      test -f "$M"
check "  ... silently, rc 0"                                silent
run sess-1 "typed at the terminal"
check "typed prompt removes the marker"                     test ! -e "$M"
run sess-1 "${DISC/UID/333}"
check "discord prompt from a user not in any access.json: no marker"  test ! -e "$M"   # mutation: skip the allowlist -> fails
run sess-1 "${DISC/UID/222}"
check "allowlist of another channel dir counts (any access.json)"      test -f "$M"
run sess-1 '<teammate-message teammate_id="x">report</teammate-message>'
check "teammate-message after a marker keeps it"            test -f "$M"
run sess-1 '<task-notification>done</task-notification>'
check "task-notification keeps it"                          test -f "$M"
run sess-1 '<cross-session-message from="a">x</cross-session-message>'
check "cross-session-message keeps it"                      test -f "$M"
run sess-1 '<channel source="plugin:telegram:telegram" user_id="111">x</channel>'
check "telegram channel prompt leaves the marker"           test -f "$M"
rm -f "$M"
run sess-1 '<channel source="plugin:telegram:telegram" user_id="111">x</channel>'
check "telegram channel prompt creates nothing"             test ! -e "$M"
run sess-1 "${DISC/UID/111}"
touch -t 202001010000 "$M"; run sess-1 "${DISC/UID/111}"
check "a second discord prompt moves the mtime forward"     test "$(python3 -c 'import os,sys;print(int(os.path.getmtime(sys.argv[1])>1700000000))' "$M")" = 1
n0=$(find "$TT_DIR" -type f | wc -l)
run '../x' "${DISC/UID/111}"; silent; r1=$?
run 'a/b' "${DISC/UID/111}"
n1=$(find "$TT_DIR" -type f | wc -l)
check "bad session_id writes nothing anywhere under the temp dir"   test "$n0" = "$n1"
check "bad session_id: silent rc 0"                         silent
echo 'not json' | "$H" >"$tmp/o" 2>"$tmp/e"; rc=$?
check "malformed json: rc 0, no output"                     test $rc -eq 0 -a ! -s "$tmp/o" -a ! -s "$tmp/e"
tt_done
