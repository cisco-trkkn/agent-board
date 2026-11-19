source "${0:A:h}/lib.zsh"
# context-recall: UserPromptSubmit hook that injects archived entries matching the repo paths a session's first prompt names.
# Runs for real inside the scratch server (key `tt`); TC_CONTEXT_DIR and TC_STATE point at temp dirs.
H="${TC_CTXRECALL:-$TT_REPO/claude/plugin/scripts/context-recall.sh}"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx"; mkdir -p "$TC_CONTEXT_DIR"
f="$TC_CONTEXT_DIR/tt.archive.md"
BRIEF="$(<"${0:A:h}/fixtures/context-recall/brief.md")"
HEAD="Archived project context matching the files in your task:"
# payload <prompt> [session] [cwd]: the UserPromptSubmit stdin keys (probed): cwd, hook_event_name, permission_mode, prompt, prompt_id, session_id, transcript_path
payload() { python3 -c 'import json,sys; print(json.dumps({"session_id":sys.argv[2],"transcript_path":"/tmp/none.jsonl","cwd":sys.argv[3],"permission_mode":"default","hook_event_name":"UserPromptSubmit","prompt":sys.argv[1],"prompt_id":"p1"}))' "$1" "${2:-s1}" "${3:-$TT_REPO}" }
run_hook() { payload "$@" | "$H" --scoped >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)" }
ctx() { print -r -- "$out" | python3 -c 'import json,sys; h=json.load(sys.stdin)["hookSpecificOutput"]; assert h["hookEventName"]=="UserPromptSubmit", h; sys.stdout.write(h["additionalContext"])' 2>/dev/null }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]] }
marker() { print -r -- "$TC_STATE/context-recall/$1" }
mkarchive() { python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n",
 "- usage rows carry a source (files: board/usage.py) · 2026-10-05 · archived 2026-11-18\n",
 "- plan limits come from the freshest tap (files: board/usage.py, board/server.py) · 2026-10-29 · archived 2026-11-10\n",
 "- metrics resolve from the main checkout (files: board/metrics.py) · 2026-10-20 · archived 2026-11-18\n",
 "- the hooks module is one per plugin (files: claude/plugin/hooks/hooks.json) · 2026-11-05 · archived 2026-11-02\n",
 "- the readme is short (files: README.md) · 2026-09-01 · archived 2026-11-18\n",
 "- scripts dir note (files: claude/elsewhere/other.sh) · 2026-10-01 · archived 2026-11-18\n",
 "- whole board dir note (files: board/) · 2026-08-01 · archived 2026-11-18\n",
 "\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
}
mkarchive
rm -rf "$TC_STATE/context-recall"
run_hook "$BRIEF" s-brief
check "brief: exit 0, nothing on stderr, output present"  test $rc -eq 0 -a -z "$err" -a -n "$out"
check "brief: header line then entry lines"               test "$(ctx | head -1)" = "$HEAD"
check "same-file entries match; newest own date first (2026-11-05, 10-29, 10-20, 10-05), not archive date" test "$(ctx | tail -n +2 | grep -o '· 20[0-9-]* ' | tr -d '·\n ')" = "2026-11-052026-10-292026-10-202026-10-05"
check "no parent match for README.md or other.sh entries"  zsh -c '! print -r -- "$1" | grep -qE "README|other.sh"' _ "$(ctx)"
check "board/ directory entry does not match a file prompt only by parent rule" zsh -c '! print -r -- "$1" | grep -q "whole board dir"' _ "$(ctx)"
check "marker written"                                     test -e "$(marker s-brief)"
run_hook "$BRIEF" s-brief
check "second prompt of the session: nothing"              silent
run_hook "$BRIEF" s-other
check "another session id runs again"                      test -n "$out"
# directory prompt: entry under it matches
run_hook "look at board/ please" s-dir
check "prompt names a directory: entries under it match"  zsh -c 'print -r -- "$1" | grep -q "usage rows carry"' _ "$(ctx)"
run_hook "see board/usage.py:12, and \`board/metrics.py\`." s-tok
check "trailing :line, backticks and trailing dot stripped" zsh -c 'print -r -- "$1" | grep -q "metrics resolve" && print -r -- "$1" | grep -q "usage rows"' _ "$(ctx)"
run_hook "look at $TT_REPO/board/metrics.py" s-abs
check "absolute path under the repo matches"              zsh -c 'print -r -- "$1" | grep -q "metrics resolve"' _ "$(ctx)"
# top-level files: empty parent never matches
run_hook "edit CLAUDE.md now" s-top
check "top-level file does not match another top-level file"  silent
# no path
run_hook "fix it, see /tmp/handoff/x.md and nothing/else.md" s-nopath
check "no path in the prompt: silent"                      silent
check "marker written when nothing matched"                test -e "$(marker s-nopath)"
run_hook "edit board/usage.py" s-nopath
check "a later prompt in the same session injects nothing" silent
# silent cases
rm -f "$f"; run_hook "$BRIEF" s-noarch;   check "no archive file: silent"      silent
: > "$f"; run_hook "$BRIEF" s-empty;      check "empty archive: silent"        silent
mkarchive
payload "$BRIEF" s-kill | TC_CONTEXT=0 "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "TC_CONTEXT=0: silent"                               silent
payload "$BRIEF" s-notmux | TMUX= TMUX_PANE= "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "no tmux pane: silent"                               silent
echo 'not json' | "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "garbage stdin: silent"                              silent
mkdir -p "$TT_DIR/nogit"; run_hook "$BRIEF" s-nogit "$TT_DIR/nogit"
check "cwd not a git repo: silent"                         silent
run_hook "$BRIEF" '../x'
check "session_id ../x: silent, no file written"           zsh -c '[[ $1 == 0 && -z "$2" ]] && [[ ! -e "$3/context-recall/../x" && ! -e "$3/x" ]]' _ $rc "$out" "$TC_STATE"
# the fixture brief names six paths; one archive entry per path, each must be injected (the real extraction, via the hook)
python3 - "$f" <<'PY'
import sys
paths = ["claude/plugin/scripts/context-inject.sh", "board/discord_controls.py", "board/metrics.py", "claude/plugin/hooks/hooks.json", "claude/overseer-settings.json", "board/usage.py"]
L = ["# tt: archived agent context\n", "\n", "## Map\n"] + [f"- note for {p} (files: {p}) · 2026-10-{i + 1:02d} · archived 2026-11-18\n" for i, p in enumerate(paths)] + ["\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
run_hook "$BRIEF" s-six
check "fixture brief yields the six named paths: one entry per path injected" zsh -c 'for p in claude/plugin/scripts/context-inject.sh board/discord_controls.py board/metrics.py claude/plugin/hooks/hooks.json claude/overseer-settings.json board/usage.py; do print -r -- "$1" | grep -qF "note for $p " || { print -u2 "missing $p"; exit 1; }; done' _ "$(ctx)"
# the cap: 6 KB of matching entries, distinct dates
python3 - "$f" <<'PY'
import sys
L = ["# tt: archived agent context\n", "\n", "## Map\n"]
for n in range(60):
    L.append(f"- big entry {n:02d} " + "x" * 75 + f" (files: board/usage.py) · 2026-09-{1 + n % 28:02d} · archived 2026-11-18\n")
L += ["\n", "## How to run\n", "\n", "## Gotchas\n", "\n", "## Decisions\n"]
open(sys.argv[1], "w").write("".join(L))
PY
run_hook "see board/usage.py" s-cap
ctx | tail -n +2 > "$TT_DIR/lines.txt"
check "6 KB of matches: entry lines <= 4096 bytes, and at least one present" python3 - "$TT_DIR/lines.txt" <<'PY'
import sys
b = open(sys.argv[1], "rb").read()
assert 0 < len(b) <= 4096, len(b)
PY
check "newest fit, entry cut at the cap absent as a whole, only whole lines" python3 - "$TT_DIR/lines.txt" "$f" <<'PY'
import sys, re
got = open(sys.argv[1]).read().splitlines()
src = [l for l in open(sys.argv[2]).read().splitlines() if l.startswith("- ")]
date = lambda l: re.search(r"· (\d{4}-\d{2}-\d{2})", l).group(1)
order = sorted(range(len(src)), key=lambda i: (date(src[i]), ), reverse=True)
assert all(g in src for g in got), "partial line"
assert [date(g) for g in got] == sorted([date(g) for g in got], reverse=True)
want, used = [], 0
for i in order:
    n = len(src[i].encode()) + 1
    if used + n > 4096: break
    want.append(src[i]); used += n
assert sorted(got) == sorted(want), (len(got), len(want))
assert len(got) < len(src)
PY
tt_done
