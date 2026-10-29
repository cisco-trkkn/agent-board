#!/usr/bin/env zsh
# e2e-context.zsh — shared project context, end to end, on a scratch tmux server (lib.zsh, `-L tctest-… -f /dev/null`):
#   1. a seeded entry reaches a fresh Claude's first turn through the plugin's SessionStart hook (headless haiku, run in
#      the scratch session's pane environment, so the key is `tt`);
#   2. a lead running with claude/orchestrator.md merges a teammate's "Context learned" item with `tmux-ctl context add`
#      (headless sonnet, Bash allowed for `tmux-ctl context` only);
#   3. the hook's truncation on a REAL aged file: a read-only copy of ~/.local/state/agent-board/ideas/agent-board.md
#      (15 KB, entries dated across days; the same bullet shape) is injected cut at an entry boundary within 8 KB;
#   4. the real context folder ~/.local/state/agent-board/context is untouched (listing before == after).
# Not a test_*.zsh: run-all does not pick it up (it makes two small API calls). Run it from the worktree:
#   zsh tools/tests/e2e-context.zsh
# Every write goes to the scratch TC_STATE, TC_IDEAS_DIR and TC_CONTEXT_DIR under $TT_DIR, removed by tt_teardown.
R="${${(%):-%x}:A:h:h:h}"
source "$R/tools/tests/lib.zsh"
source "$R/bin/_ab_claude.zsh"
REAL="$HOME/.local/state/agent-board/context"
before="$(ls -la "$REAL" 2>&1)"
tt_setup claude
export TC_CONTEXT_DIR="$TT_DIR/ctx" TC_IDEAS_DIR="$TT_DIR/ideas" PATH="$R/bin:$PATH"
C="$R/bin/tmux-ctl"; H="$R/claude/plugin/scripts/context-inject.sh"
print -r -- "scratch socket: $TT_SOCK_NAME · TC_CONTEXT_DIR=$TC_CONTEXT_DIR · TC_STATE=$TC_STATE"
print -r -- "--- real context folder before: $before"

# 1. seed (as the lead would) and a fresh agent's first turn
word="QUARTZ-$$"
$C context add Map "the board server is board/server.py and the codeword for this run is $word (files: board/server.py)"
print -r -- "--- seeded file ($TC_CONTEXT_DIR/tt.md):"; cat "$TC_CONTEXT_DIR/tt.md"
work="$TT_DIR/work"; mkdir -p "$work"; git -C "$work" init -q
a1="$(cd "$work" && claude -p --model haiku ${(Q)${(z)"$(ab_claude_args)"}} 'What is the codeword in the shared project context you were given? Reply with the codeword only.' </dev/null 2>"$TT_DIR/a1.err")"
print -r -- "--- first-turn reply (haiku): $a1"
check "1. seeded entry reached a fresh agent's first turn" zsh -c '[[ $1 == *"$2"* ]]' _ "$a1" "$word"
[[ "$a1" == *"$word"* ]] || cat "$TT_DIR/a1.err"

# 2. the lead merges a teammate's "Context learned" item as orchestrator.md says
prompt="A teammate's final report ended with:
Context learned:
- Gotchas: test_ctl_busy.zsh needs an idle tests window first (files: tools/tests/test_ctl_busy.zsh)
Merge it into the shared project context as your rules say, then reply with the single word done."
# the prompt goes on stdin: --allowedTools takes every following word (claude 2.1.312), so a prompt argument after it is swallowed
a2="$(cd "$work" && print -r -- "$prompt" | claude -p --model sonnet ${(Q)${(z)"$(ab_claude_args)"}} --append-system-prompt-file "$R/claude/orchestrator.md" --allowedTools 'Bash(tmux-ctl context:*)' 2>"$TT_DIR/a2.err")"
print -r -- "--- lead reply (sonnet): $a2"
print -r -- "--- file after the merge:"; cat "$TC_CONTEXT_DIR/tt.md"
check "2. the lead merged the item under Gotchas" sh -c "sed -n '/^## Gotchas/,/^## Decisions/p' ${(q)TC_CONTEXT_DIR}/tt.md | grep -q 'test_ctl_busy.zsh needs an idle tests window'"
check "2. Map entry still there (no rewrite of other sections)" grep -q "$word" "$TC_CONTEXT_DIR/tt.md"
grep -q 'test_ctl_busy.zsh needs an idle tests window' "$TC_CONTEXT_DIR/tt.md" || cat "$TT_DIR/a2.err"

# 3. truncation on a real aged file (read-only copy; the real file is never opened for writing)
real_ideas="$HOME/.local/state/agent-board/ideas/agent-board.md"
if [[ -s "$real_ideas" && $(wc -c < "$real_ideas") -gt 8192 ]]; then
  cp "$real_ideas" "$TC_CONTEXT_DIR/tt.md"
  print -r -- "--- real aged file: $real_ideas, $(wc -c < "$real_ideas") bytes, dates $(grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$real_ideas" | sort -u | sed -n '1p;$p' | tr '\n' ' ')"
  print -r -- '{"session_id":"e2e","transcript_path":"/tmp/none.jsonl","cwd":"/tmp","hook_event_name":"SessionStart","source":"startup"}' | "$H" --scoped > "$TT_DIR/o" 2>"$TT_DIR/e"; rc=$?
  check "3. hook exit 0, nothing on stderr" test $rc -eq 0 -a ! -s "$TT_DIR/e"
  check "3. cut at an entry boundary, body <= 8192 bytes, note names the path" python3 - "$TC_CONTEXT_DIR/tt.md" "$TT_DIR/o" <<'PY'
import json, sys
src = open(sys.argv[1]).read(); ctx = json.load(open(sys.argv[2]))["hookSpecificOutput"]["additionalContext"]
preface = "Shared project context, curated by the lead; propose additions as 'Context learned' in your report.\n\n"
assert ctx.startswith(preface); rest = ctx[len(preface):]
note = "… truncated, full file at " + sys.argv[1] + "\n"; assert rest.endswith(note), rest[-200:]
body = rest[:-len(note)]; assert len(body.encode()) <= 8192, len(body.encode())
lines = src.splitlines(keepends=True)
cuts = [i for i, l in enumerate(lines) if l.startswith(("- ", "## "))] + [len(lines)]
best = max(c for c in cuts if len("".join(lines[:c]).encode()) <= 8192)
assert body == "".join(lines[:best]).rstrip("\n") + "\n"
print(f"kept {best} of {len(lines)} lines, {len(body.encode())} bytes; last kept line: {body.rstrip().splitlines()[-1][:80]}")
PY
else
  print -r -- "skip - no real ideas file over 8 KB at $real_ideas"
fi

# 4. real state untouched
after="$(ls -la "$REAL" 2>&1)"
check "4. real context folder unchanged" test "$before" = "$after"
print -r -- "--- real context folder after: $after"
tt_done
