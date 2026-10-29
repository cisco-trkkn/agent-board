source "${0:A:h}/lib.zsh"
# context-inject: SessionStart hook that injects ${TC_CONTEXT_DIR}/<project>.md as additionalContext, capped at 8 KB.
# The hook runs for real inside the scratch server: tt_setup exports TMUX and TMUX_PANE for session `tt`, so the key is `tt`.
H="${TC_CTXINJECT:-$TT_REPO/claude/plugin/scripts/context-inject.sh}"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx"; mkdir -p "$TC_CONTEXT_DIR"
f="$TC_CONTEXT_DIR/tt.md"
CAP=8192
PREFACE="Shared project context, curated by the lead; propose additions as 'Context learned' in your report."
# stdin shape of a real SessionStart (claude 2.1.312, probed 2026-10-28): session_id, transcript_path, cwd, hook_event_name, source
payload() { print -r -- '{"session_id":"s1","transcript_path":"/tmp/none.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' }
run_hook() { payload | "$H" "$@" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)" }
ctx() { print -r -- "$out" | python3 -c 'import json,sys; h=json.load(sys.stdin)["hookSpecificOutput"]; assert h["hookEventName"]=="SessionStart", h; sys.stdout.write(h["additionalContext"])' 2>/dev/null }
silent() { [[ $rc == 0 && -z "$out" && -z "$err" ]] }

run_hook;                       check "no file: no output, exit 0"            silent
: > "$f"; run_hook;             check "empty file: no output, exit 0"         silent
print -n '  \n\n' > "$f"; run_hook; check "whitespace-only file: no output"   silent
small=$'# tt: shared agent context\nLast curated: 2026-10-28\n\n## Map\n- the board is board/server.py (files: board/server.py) · 2026-10-28\n\n## How to run\n\n## Gotchas\n\n## Decisions\n'
print -rn -- "$small" > "$f"; run_hook
check "small file: exit 0, nothing on stderr"            test $rc -eq 0 -a -z "$err"
check "small file: preface, blank line, file verbatim"   test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
run_hook --scoped
check "--scoped: same output"                            test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
payload | TC_CONTEXT=0 "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "TC_CONTEXT=0: no output, exit 0"                  silent
echo 'not json' | "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "garbage stdin: exit 0, still injects (stdin is drained, not parsed)"  test $rc -eq 0 -a -z "$err" -a -n "$out"
payload | TMUX= TMUX_PANE= "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "outside tmux: no output, exit 0"                  silent
chmod 000 "$f"; run_hook; chmod 644 "$f"
check "unreadable file: no output, exit 0"               silent
head -c 300 /dev/urandom > "$f"; run_hook
check "binary file: exit 0, nothing on stderr"           test $rc -eq 0 -a -z "$err"
# a -bg pane (hidden tests/shell session, @tc_bg set) reads the project's file, never <project>-bg.md
bgpane="$(tt new-session -d -s tt-bg -c "$TT_DIR" -P -F '#{pane_id}')"; tt set-option -t '=tt-bg:' @tc_bg 1
print -rn -- "$small" > "$f"
payload | TMUX_PANE="$bgpane" "$H" >"$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?; out="$(<$TT_DIR/o)"; err="$(<$TT_DIR/e)"
check "-bg pane: injects the project's file"             test "$(ctx)" = "$PREFACE"$'\n\n'"${small%$'\n'}"
# over the cap: an aged, multi-day file (entries dated across 2026-10-01..30, some with continuation lines), built so the
# entry that straddles the 8192-byte boundary has its first line inside the cap and its continuation line over it
python3 - "$f" "$CAP" <<'PY'
import sys
cap = int(sys.argv[2])
nbytes = lambda ls: len("".join(ls).encode())
lines = ["# tt: shared agent context\n", "Last curated: 2026-10-28\n", "\n", "## Map\n"]
n = 0
while nbytes(lines) + 100 <= cap - 60:                      # ~100-byte entries, every fifth one with a continuation line
    lines.append(f"- map entry {n:03d} " + "x" * 58 + f" (files: board/f{n}.py) · 2026-10-{1 + n % 30:02d}\n")
    if n % 5 == 0:
        lines.append("  continuation detail " + "y" * 40 + "\n")
    n += 1
room = cap - nbytes(lines)                                   # 60..159 bytes left
first = "- straddling entry " + "s" * (room - 10 - len("- straddling entry  · 2026-10-29\n".encode())) + " · 2026-10-29\n"
lines.append(first)                                          # fits, with 10 bytes to spare
assert nbytes(lines) <= cap, nbytes(lines)
lines.append("  continuation of the straddling entry " + "c" * 40 + "\n")   # overflows: the whole entry must go
assert nbytes(lines) > cap
lines += ["\n", "## How to run\n"]
for m in range(30):
    lines.append(f"- run entry {m:03d} " + "z" * 60 + f" (files: tools/t{m}.zsh) · 2026-10-{1 + m % 30:02d}\n")
lines += ["\n", "## Gotchas\n", "- g1 · 2026-10-02\n", "\n", "## Decisions\n", "- d1 · 2026-10-03\n"]
open(sys.argv[1], "w").write("".join(lines))
PY
check "fixture is over the cap"  test "$(wc -c < "$f")" -gt $CAP
run_hook
check "over the cap: exit 0, nothing on stderr"          test $rc -eq 0 -a -z "$err"
ctx > "$TT_DIR/ctx.txt"
check "over the cap: cut at an entry boundary, body <= 8192 bytes, note names the path" python3 - "$f" "$TT_DIR/ctx.txt" "$PREFACE" "$CAP" <<'PY'
import sys
src, got, preface, cap = open(sys.argv[1]).read(), open(sys.argv[2]).read(), sys.argv[3], int(sys.argv[4])
assert got.startswith(preface + "\n\n"), got[:120]
rest = got[len(preface) + 2:]
note = "… truncated, full file at " + sys.argv[1] + "\n"
assert rest.endswith(note), rest[-200:]
body = rest[: -len(note)]
assert len(body.encode()) <= cap, len(body.encode())
# oracle: the longest prefix of the file that ends right before an entry/heading start (or EOF) and fits the cap
lines = src.splitlines(keepends=True)
cuts = [i for i, l in enumerate(lines) if l.startswith(("- ", "## "))] + [len(lines)]
best = max(c for c in cuts if len("".join(lines[:c]).encode()) <= cap)
assert body == "".join(lines[:best]).rstrip("\n") + "\n", (body[-300:], "".join(lines[:best])[-300:])
assert body.rstrip("\n").splitlines()[-1].startswith("- "), body[-200:]     # last kept line is a complete entry
assert "- straddling entry" not in body, body[-300:]                     # the entry over the boundary went whole
assert "## How to run" not in body                                           # everything after it went too
PY
tt_done
