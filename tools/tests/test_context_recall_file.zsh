source "${0:A:h}/lib.zsh"
# context-recall-file: PostToolUse hook (Read|Edit|Write|Grep|Glob) that injects archived entries citing the path a tool touched,
# once per (session, path), skipping entries already injected in the session. Runs for real inside the scratch server (key `tt`);
# TC_CONTEXT_DIR and TC_STATE point at temp dirs. Spec: docs/superpowers/specs/2026-11-23-hardening-design.md, part c.
H="${TC_CTXRECALL_FILE:-$TT_REPO/claude/plugin/scripts/context-recall-file.sh}"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx"; mkdir -p "$TC_CONTEXT_DIR"
f="$TC_CONTEXT_DIR/tt.archive.md"
# payload <tool> <input json> [session] [cwd]: the PostToolUse stdin keys (as spec-boundary-nudge.sh and teammate-remind.sh read them)
payload() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[3],"transcript_path":"/tmp/none.jsonl","cwd":sys.argv[4],"permission_mode":"default","hook_event_name":"PostToolUse","tool_name":sys.argv[1],"tool_input":json.loads(sys.argv[2]),"tool_response":{},"tool_use_id":"t1"}))' "$1" "$2" "${3:-s1}" "${4:-$TT_REPO}" }
run_hook() { payload "$@" | "$H" --scoped >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)" }
fp() { print -r -- "{\"file_path\": \"$1\"}" }
ctx() { print -r -- "$out" | python3 -c 'import json,sys; h=json.load(sys.stdin)["hookSpecificOutput"]; assert h["hookEventName"]=="PostToolUse", h; sys.stdout.write(h["additionalContext"])' 2>/dev/null }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]] }
mkarchive() { python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n",
 "- usage rows carry a source (files: board/usage.py) · 2026-10-05 · archived 2026-11-18\n",
 "- plan limits come from the freshest tap (files: board/usage.py, board/server.py) · 2026-10-29 · archived 2026-11-10\n",
 "- metrics resolve from the main checkout (files: board/metrics.py) · 2026-10-20 · archived 2026-11-18\n",
 "- the readme is short (files: README.md) · 2026-09-01 · archived 2026-11-18\n",
 "- whole board dir note (files: board/) · 2026-08-01 · archived 2026-11-18\n",
 "\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
}
mkarchive
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s1
check "Read of a cited path: exit 0, nothing on stderr, output present" test $rc -eq 0 -a -z "$err" -a -n "$out"
check "header names the path"                                  test "$(ctx | head -1)" = "Archived project context for board/usage.py:"
check "entries citing the file and its directory, newest own date first" test "$(ctx | tail -n +2 | grep -o '· 20[0-9-]* ' | tr -d '·\n ')" = "2026-10-292026-10-052026-08-01"
check "an entry citing another file is not injected"           zsh -c '! print -r -- "$1" | grep -q "metrics resolve"' _ "$(ctx)"
check "marker file records the path"                            grep -qxF "path	board/usage.py" "$TC_STATE/context-recall/s1.paths"
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s1
check "second Read of the same path in the session: nothing"   silent
run_hook Edit "$(fp board/server.py)" s1
check "Edit of a path whose entries were all injected already: nothing" silent
run_hook Read "$(fp "$TT_REPO/board/metrics.py")" s1
check "a new cited path in the same session injects only its new entry" test "$(ctx | tail -n +2)" = "- metrics resolve from the main checkout (files: board/metrics.py) · 2026-10-20 · archived 2026-11-18"
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s2
check "another session id gets the entries again"              zsh -c 'print -r -- "$1" | grep -q "usage rows carry"' _ "$(ctx)"
run_hook Write "$(fp "$TT_REPO/bin/tmux-ctl")" s3
check "a path no entry cites: nothing"                          silent
run_hook Grep '{"pattern": "x", "path": "board"}' s4
check "Grep on a directory: only entries citing that directory" test "$(ctx | tail -n +2)" = "- whole board dir note (files: board/) · 2026-08-01 · archived 2026-11-18"
run_hook Glob '{"pattern": "*.md"}' s5
check "Glob without a path: nothing"                            silent
run_hook Bash '{"command": "cat README.md"}' s5
check "another tool: nothing"                                    silent
run_hook Read '{"file_path": "/etc/hosts"}' s5
check "a path outside the repo: nothing"                          silent
run_hook Read "$(fp "$TT_REPO/README.md")" '../x'
check "session_id ../x: silent, no file written"                  zsh -c '[[ $1 == 0 && -z "$2" ]] && [[ ! -e "$3/context-recall/../x.paths" && ! -e "$3/x.paths" ]]' _ $rc "$out" "$TC_STATE"
payload Read "$(fp "$TT_REPO/README.md")" s-kill | TC_CONTEXT=0 "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "TC_CONTEXT=0: silent"                                      silent
payload Read "$(fp "$TT_REPO/README.md")" s-notmux | TMUX= TMUX_PANE= "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "no tmux pane: silent"                                      silent
echo 'not json' | "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "garbage stdin: silent"                                     silent
rm -f "$f"; run_hook Read "$(fp "$TT_REPO/README.md")" s-noarch
check "no archive file: silent"                                   silent
# the cap: 6 KB of entries citing one path
python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n"]
for n in range(60):
    L.append(f"- big entry {n:02d} " + "x" * 75 + f" (files: board/usage.py) · 2026-09-{1 + n % 28:02d} · archived 2026-11-18\n")
L += ["\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s-cap
ctx | tail -n +2 > "$TT_DIR/lines.txt"
check "6 KB of matches: entry lines <= 4096 bytes, whole lines, newest first, fewer than all 60" python3 - "$TT_DIR/lines.txt" "$f" <<'PY'
import re, sys
b = open(sys.argv[1], "rb").read()
assert 0 < len(b) <= 4096, len(b)
got = b.decode().splitlines()
src = [l for l in open(sys.argv[2]).read().splitlines() if l.startswith("- ")]
date = lambda l: re.search(r"· (\d{4}-\d{2}-\d{2})", l).group(1)
assert all(g in src for g in got), "partial line"
assert [date(g) for g in got] == sorted([date(g) for g in got], reverse=True)
assert 0 < len(got) < len(src), len(got)
PY
run_hook Read "$(fp "$TT_REPO/board/usage.py")" s-cap
check "once per (session, path): a second Read after the cap injects nothing more" silent
tt_done
