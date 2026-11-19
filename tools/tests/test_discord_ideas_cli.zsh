source "${0:A:h}/lib.zsh"
# tmux-ctl discord ideas-list|ideas-post: rows, exit codes, stdin, free-text argv never taken for a token.
# No tmux and no network: temp TC_STATE, TC_IDEAS_DIR with a fixture ideas file, HOME elsewhere. Nothing real is read or written.
C="${TC_CTL:-$TT_REPO/bin/tmux-ctl}"
S="${$(mktemp -d "${TMPDIR:-/tmp}/ttdi.XXXXXX"):A}"
mkdir -p "$S/state" "$S/ideas" "$S/home"
export TC_STATE="$S/state" TC_IDEAS_DIR="$S/ideas" HOME="$S/home"
trap 'rm -rf "$S"; tt_teardown' EXIT INT TERM
print -r -- $'- [ ] 2026-11-18 10:00 · alpha first\n- [-] 2026-11-18 10:00 · alpha dropped\n- [ ] 2026-11-18 10:00 · alpha second' > "$S/ideas/alpha.md"
print -r -- $'- [ ] 2026-11-18 10:00 · beta only' > "$S/ideas/beta.md"
run() { "$@" > "$S/out" 2> "$S/err"; rc=$?; out="$(<$S/out)"; err="$(<$S/err)" }

run $C discord ideas-list alpha
check "ideas-list alpha: rc 0, two open rows id<TAB>project<TAB>text" test $rc -eq 0 -a "$(print -r -- "$out" | wc -l | tr -d ' ')" = 2 -a -n "$(print -r -- "$out" | grep -E $'^[0-9a-f]{10}\talpha\talpha first$')" -a -z "$(print -r -- "$out" | grep dropped)"
run $C discord ideas-list
check "ideas-list: every project" test $rc -eq 0 -a "$(print -r -- "$out" | wc -l | tr -d ' ')" = 3 -a -n "$(print -r -- "$out" | grep -E $'\tbeta\tbeta only$')"
run $C discord ideas-list a.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
check "ideas-list: a token-looking argument is not refused as a token" test $rc -eq 0 -a -z "$(print -r -- "$err" | grep -i token)"
run $C discord ideas-list a b c
check "ideas-list: too many arguments is rc 2" test $rc -eq 2

ID1="$($C discord ideas-list alpha | head -1 | cut -f1)"
ID2="$($C discord ideas-list alpha | tail -1 | cut -f1)"
mkdir -p "$S/state/discord/_ops/ideas"
mkreq() { python3 -c 'import json,sys,time; json.dump({"id":sys.argv[1],"project":"alpha","bridge":"_ops","ts":time.time(),"state":"open"}, open(sys.argv[2],"w"))' "$1" "$S/state/discord/_ops/ideas/req-$1.json" }
doc() { print -r -- "{\"request\":\"$1\",\"groups\":[{\"title\":\"T\",\"emoji\":\"🧩\",\"project\":\"alpha\",\"ideas\":[\"$ID1\",\"$ID2\"]}]}" }

mkreq aaaa1111
doc aaaa1111 > "$S/g1.json"
run $C discord ideas-post "$S/g1.json" --dry-run
check "ideas-post --dry-run: valid file rc 0, nothing queued" test $rc -eq 0 -a -z "$(ls $S/state/discord/_ops/outbox 2>/dev/null)"
run $C discord ideas-post "$S/g1.json"
check "ideas-post file: rc 0 and a post op queued" test $rc -eq 0 -a -n "$(ls $S/state/discord/_ops/outbox 2>/dev/null)"
mkreq bbbb2222
run sh -c "'$C' discord ideas-post - < /dev/stdin" < <(doc bbbb2222)
check "ideas-post -: reads the groups from stdin, rc 0" test $rc -eq 0
run sh -c "'$C' discord ideas-post -" < <(doc nosuchreq)
check "ideas-post: unknown request is refused rc 1 with a reason" test $rc -eq 1 -a -n "$err"
print -r -- 'not json' > "$S/bad.json"
run $C discord ideas-post "$S/bad.json"
check "ideas-post: unreadable document rc 1" test $rc -eq 1
run $C discord ideas-post
check "ideas-post: no argument rc 2" test $rc -eq 2
run $C discord ideas-post "$S/g1.json" --bogus
check "ideas-post: bad flag rc 2" test $rc -eq 2
# Task 4: the overseer may run exactly ideas-list and ideas-post; its deny list is the one before; overseer.md names the flow.
OS="$TT_REPO/claude/overseer-settings.json"
check "overseer settings: allows ideas-list and ideas-post" test "$(jq -r '[.permissions.allow[] | select(test("tmux-ctl discord"))] | sort | join("|")' $OS)" = 'Bash(tmux-ctl discord ideas-list*)|Bash(tmux-ctl discord ideas-post*)'
check "overseer settings: deny list identical to a773c48" test "$(jq -cS .permissions.deny $OS)" = "$(git -C $TT_REPO show a773c48:claude/overseer-settings.json | jq -cS .permissions.deny)"
check "overseer settings: no other allow changed" test "$(jq -cS '[.permissions.allow[] | select(test("tmux-ctl discord") | not)]' $OS)" = "$(git -C $TT_REPO show a773c48:claude/overseer-settings.json | jq -cS .permissions.allow)"
check "overseer.md: /ideas section names list, post and stdin form" test "$(grep -c -e 'tmux-ctl discord ideas-list' -e 'ideas-post - <<< '"'" $TT_REPO/claude/overseer.md)" -ge 2
check "nothing leaked outside the scratch state" test ! -e "$HOME/.local/state"
tt_done
