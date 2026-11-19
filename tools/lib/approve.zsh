# approve.zsh — sourced by tmux-ctl for `tmux-ctl approve <win> once|deny --expect <text>` (spec 2026-11-09-remote-access §5).
# --expect is required and must be EVERY line of the prompt's command preview (or a non-Bash prompt's file path), newline-separated, in order:
# the approval passes only when the preview's lines equal the --expect lines exactly (same count, same order). Presses the one-time Yes or the No of the permission prompt showing in <win>'s main pane, by its digit alone (claude 2.1.321:
# a digit answers a permission prompt, no Enter; tools/tests/fixtures/approve/README.md). Only an option labelled exactly `Yes`
# (once) or `No` (deny) is ever chosen: "Yes, and don’t ask again…", "Yes, and switch to auto mode…" rows are never pressed.
# Uses tmux-ctl's t, use_win, exists, target. TC_APPROVE_BEFORE_SEND (tests): a command run between the capture and the re-capture.

# The screen read, the prompt parse (permission prompts only) and the key send are dialog.zsh's: _dlg_screen | _dlg_parse, then
# _dlg_approve_view (T:, P:, O:, X:ambiguous) and _dlg_press_keys. This file keeps the approve rules: the P: compare with --expect,
# the exact Yes/No label, the messages.
source "${${(%):-%x}:A:h}/dialog.zsh"

approve_cmd() {
  local win="$1" act="$2" expect="" have_expect=0 pane block raw again line digit want got u="usage: tmux-ctl approve <win> once|deny --expect <text>"
  shift 2 2>/dev/null
  if [[ "$act" == show ]]; then   # read-only: print the prompt's tool (T:) and its --expect lines (P:); sends no keys
    [[ -n "$win" && $# -eq 0 ]] || die "usage: tmux-ctl approve <win> show"
    use_win "$win"; exists "$win"
    pane="$(target "$win")"
    block="$(_dlg_screen "$pane" | _dlg_parse | _dlg_approve_view)"
    [[ -n "$block" ]] || { print -u2 "approve: no permission prompt in $win"; return 1 }
    if print -r -- "$block" | grep -aq '^X:ambiguous$'; then print -u2 "approve: ambiguous prompt in $win"; return 1; fi
    got="$(print -r -- "$block" | grep -a '^P:')"
    [[ -n "$got" ]] || { print -u2 "approve: no expect lines in $win"; return 1 }
    print -r -- "$block" | grep -a '^T:'
    print -r -- "$got"
    return 0
  fi
  while (( $# )); do
    case "$1" in
      --expect) (( $# >= 2 )) || die "$u"; expect="$2"; have_expect=1; shift 2 ;;
      *) die "$u" ;;
    esac
  done
  [[ -n "$win" && ( "$act" == once || "$act" == deny ) ]] || die "$u"
  (( have_expect )) || die "--expect <text> is required: the exact command or path text of the prompt ($u)"
  [[ -n "$expect" ]] || die "--expect needs the exact command or path text (every preview line, newline-separated), not an empty value ($u)"
  use_win "$win"; exists "$win"
  pane="$(target "$win")"
  raw="$(_dlg_screen "$pane" | _dlg_parse)"; block="$(print -r -- "$raw" | _dlg_approve_view)"
  [[ -n "$block" ]] || { print -u2 "approve: no permission prompt in $win"; return 1 }
  # the preview's P: lines must equal the --expect lines (trimmed, empty ones dropped), same count and order; an ambiguous prompt has no P: lines, so it never matches
  local want_lines
  got="$(print -r -- "$block" | grep -a '^P:' | sed -e 's/^P://')"
  want_lines="$(print -r -- "$expect" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | grep -v '^$')"
  if [[ "$got" != "$want_lines" || -z "$got" ]]; then print -u2 "approve: the prompt in $win changed"; return 1; fi
  [[ "$act" == once ]] && want=Yes || want=No
  while IFS= read -r line; do
    [[ "$line" == O:<->:"$want" ]] && { digit="${${line#O:}%%:*}"; break }
  done <<< "$block"
  if [[ -z "$digit" ]]; then
    [[ "$act" == once ]] && print -u2 "approve: no one-time Yes in $win" || print -u2 "approve: no No option in $win"
    return 1
  fi
  [[ -n "$TC_APPROVE_BEFORE_SEND" ]] && eval "$TC_APPROVE_BEFORE_SEND" >/dev/null 2>&1
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "approve: $win is in copy mode"; return 1 }
  # the whole parsed dialog (every row, the options too) must be the same on the second read; _dlg_parse already writes the auto-mode
  # countdown of its warning row as M:SS (it ticks every second), so only that time is masked
  again="$(_dlg_screen "$pane" | _dlg_parse)"
  if [[ "$again" != "$raw" ]]; then print -u2 "approve: the prompt in $win changed"; return 1; fi
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "approve: $win is in copy mode"; return 1 }
  _dlg_press_keys "$pane" permission 0 0 0 0 "$digit"   # a digit alone answers a permission prompt
  print -r -- "approve: $win: chose \"$want\""
}
