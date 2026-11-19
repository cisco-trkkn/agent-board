#!/usr/bin/env zsh
# check_real_dialog_show.zsh — real-state check for `tmux-ctl dialog <win> show` (spec 2026-11-19-remote-discord-only §1; not a
# test_*.zsh: run by hand). Runs `show` on every pane of the REAL tmux server whose command is claude and prints one line per
# pane: `dialog` (exit 0 and valid JSON of the documented shape) or `none` (exit 1 and exactly `dialog: none in <pane>`).
# Any other result fails. Read-only: every tmux call of the run goes through a logging wrapper, and the check fails when one
# of them is not a read (capture-pane, display, list-*, show-options, has-session). No key is sent, no window is made.
# The server: the one this shell is in ($TMUX), else agent-board's socket under ${TC_REAL_TMUX_TMPDIR:-${TMUX_TMPDIR:-/tmp}}
# (tools/tests/all.zsh gives every job its own TMUX_TMPDIR and exports the real one as TC_REAL_TMUX_TMPDIR).
# Ends with `REAL CHECK PASS: <n> panes`, or exits 1.
emulate -L zsh; setopt extendedglob   # `##` in the claude-pane pattern
REPO="${0:A:h:h:h}"
source "$REPO/bin/_tc_bins.zsh"
REAL="$(tc_tmux_bin)"
if [[ -n "$TMUX" && -S "${TMUX%%,*}" ]]; then SOCK="${TMUX%%,*}"
else SOCK="${TC_REAL_TMUX_TMPDIR:-${TMUX_TMPDIR:-/tmp}}/tmux-$UID/${AGENT_BOARD_TMUX_SOCKET:-agent-board}"; fi
[[ -S "$SOCK" ]] || { print -r -- "FAIL - no tmux server socket at $SOCK"; exit 1 }
W="${$(mktemp -d "${TMPDIR:-/tmp}/dlgreal.XXXXXX"):A}"
trap 'rm -rf "$W"' EXIT INT TERM
# the wrapper: one line per tmux call (the arguments after the server options), then the real tmux
print -rl -- '#!/bin/sh' 'log="$1"; real="$2"; shift 2' 'first=; skip=0' \
  'for a in "$@"; do if [ $skip = 1 ]; then skip=0; continue; fi; case "$a" in -S|-L|-f) skip=1 ;; *) first="$a"; break ;; esac; done' \
  'printf "%s\n" "$first" >> "$log"' 'exec "$real" "$@"' > "$W/tmux-log.sh"
print -rl -- '#!/bin/sh' "exec /bin/sh ${(q)W}/tmux-log.sh ${(q)W}/calls ${(q)REAL} \"\$@\"" > "$W/tmux"; chmod +x "$W/tmux"
: > "$W/calls"
FAILS=0; n=0; nd=0; nn=0
fail() { print -r -- "FAIL - $1"; (( FAILS++ )) }
print -r -- "server: $SOCK"
"$REAL" -S "$SOCK" list-panes -a -F '#{pane_id} #{pane_current_command} #{session_name}:#{window_name}' > "$W/panes" || { print -r -- "FAIL - list-panes on $SOCK"; exit 1 }
while read -r pid cmd where; do
  # a claude pane: the command is a version number (2.1.328) or names claude (board/paneclass.py is_claude)
  [[ "$cmd" == [0-9]##.[0-9]##.[0-9]##* || "${cmd:l}" == *claude* ]] || continue
  out="$(env -u TMUX_DASH_TMUX_ARGS -u TC_SESSION TMUX="$SOCK,0,0" TMUX_PANE= TC_TMUX="$W/tmux" "$REPO/bin/tmux-ctl" dialog "$pid" show 2>"$W/err")"; rc=$?
  err="$(<"$W/err")"
  if (( rc == 2 )) && ! "$REAL" -S "$SOCK" display -p -t "$pid" '#{pane_id}' >/dev/null 2>&1; then
    print -r -- "gone    $pid $where (closed during the check; not counted)"; continue
  fi
  (( n++ ))
  if (( rc == 0 )); then
    sum="$(print -r -- "$out" | python3 -I -c 'import json, sys
d = json.load(sys.stdin)
assert list(d) == ["kind", "question", "options", "multi", "other", "lines"], list(d)
assert d["kind"] in ("permission", "question", "trust", "resume", "login", "unknown"), d["kind"]
assert isinstance(d["question"], str) and d["question"]
assert d["options"] and all(list(o) == ["n", "label", "permanent"] and type(o["n"]) is int and isinstance(o["label"], str) and o["label"] and type(o["permanent"]) is bool for o in d["options"])
assert type(d["multi"]) is bool and type(d["other"]) is bool
assert d["lines"] and all(isinstance(x, str) and x and x == x.rstrip() for x in d["lines"])
print("%s, %d options, %d lines: %s" % (d["kind"], len(d["options"]), len(d["lines"]), d["question"][:60]))' 2>"$W/pyerr")"
    if [[ $? -eq 0 && -z "$err" ]]; then print -r -- "dialog  $pid $where ($sum)"; (( nd++ ))
    else fail "$pid $where: exit 0 but not the documented JSON ($(tail -1 "$W/pyerr")) stderr=[$err]"; fi
  elif [[ $rc -eq 1 && -z "$out" && "$err" == "dialog: none in $pid" ]]; then
    print -r -- "none    $pid $where"; (( nn++ ))
  else
    fail "$pid $where: exit $rc, stdout ${#out} bytes, stderr [$err]"
  fi
done < "$W/panes"
(( n > 0 )) || fail "no claude pane on the server: nothing was checked"
# read-only evidence: every tmux call the runs made
calls="$(sort "$W/calls" | uniq -c | awk '{ printf "%s%s x%s", (NR > 1 ? ", " : ""), $2, $1 }')"
bad="$(grep -v -x -E 'capture-pane|display|display-message|list-panes|list-windows|show-options|has-session' "$W/calls" | sort -u | tr '\n' ' ')"
[[ -s "$W/calls" ]] || fail "the tmux wrapper logged no call: the run did not go through it"
[[ -z "$bad" ]] && print -r -- "ok   - tmux calls of the runs are reads only: $calls" || fail "a tmux call that is not a read: $bad"
(( FAILS == 0 )) || { print -r -- "REAL CHECK FAILED: $FAILS"; exit 1 }
print -r -- "REAL CHECK PASS: $n panes"
