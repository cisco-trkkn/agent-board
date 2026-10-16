source "${0:A:h}/lib.zsh"
H="${TC_MIRROR:-$HOME/.claude/hooks/bash-mirror.sh}"; F="${0:A:h}/fixtures"
tt_setup
tlog="$TC_STATE/feed-tt-tests.log"; slog="$TC_STATE/feed-tt-shell.log"
run_hook() { "$H" < "$1"; }   # env (TMUX, TMUX_PANE, TC_STATE) comes from tt_setup

out="$(run_hook "$F/ok.json")"
check "silent stdout"           test -z "$out"
check "tests log written"       test -s "$tlog"
check "header format"           grep -qE '^── [0-9]{2}:[0-9]{2}:[0-9]{2} · claude · .* · exit 0( · @[0-9]+)?$' "$tlog"
check "header carries an epoch" grep -qE '^── [0-9:]{8} · .* · exit 0 · @[0-9]{9,}$' "$tlog"
check "cwd home as ~"           grep -qE ' · ~/proj · exit' "$tlog"
check "command line"            grep -qxF '$ pytest -q tests/unit' "$tlog"
check "trimmed to 12 lines"     test "$(grep -c '^line' "$tlog")" -eq 12

run_hook "$F/fail.json"
check "shell log written"       grep -qE ' · exit 2( · @[0-9]+)?$' "$slog"

run_hook "$F/multiline.json"
check "multiline first line"    grep -qxF '$ echo a …' "$slog"

before="$(cat "$tlog" "$slog" | wc -c)"
run_hook "$F/tmuxctl.json"
echo 'not json' | "$H"
( unset TMUX TMUX_PANE; "$H" < "$F/ok.json" )
check "skips: tmux-ctl, bad json, no tmux" test "$(cat "$tlog" "$slog" | wc -c)" = "$before"

tt rename-window -t "$TMUX_PANE" '✦ tester'
run_hook "$F/ok.json"
check "caller from window name" grep -qE ' · tester · ' "$tlog"

head -c 2200000 /dev/zero | tr '\0' 'x' > "$tlog"
run_hook "$F/ok.json"
check "rotated to ~1MB"         test "$(wc -c < "$tlog")" -lt 1100000

# classification matrix: command -> expected log
classify() {   # classify <command> -> prints tests|shell
  rm -f "$tlog" "$slog"
  python3 -I -c 'import json,sys; print(json.dumps({"hook_event_name":"PostToolUse","tool_name":"Bash","cwd":"/tmp","tool_input":{"command":sys.argv[1]},"tool_response":{"stdout":"x","stderr":""}}))' "$1" | "$H"
  if [[ -s "$tlog" ]]; then print tests; elif [[ -s "$slog" ]]; then print shell; else print none; fi
}
for c in 'pytest -q' 'X=1 pytest' 'cd x && make test' 'pnpm test' 'time pytest' 'env X=1 pytest' 'uv run pytest' \
         'poetry run pytest' 'python -m pytest' 'python3 -m pytest' 'npx jest' 'sudo make' './gradlew test' \
         "bash -c 'pytest'" 'sh -c "make test"'; do
  check "tests: $c" test "$(classify "$c")" = tests
done
for c in 'ls -la' 'git status' "git commit -m 'fix; make it'" 'echo "pytest"'; do
  check "shell: $c" test "$(classify "$c")" = shell
done
tt_done
