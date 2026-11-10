# approve.zsh — sourced by tmux-ctl for `tmux-ctl approve <win> once|deny --expect <text>` (spec 2026-11-09-remote-access §5).
# --expect is required and must be EVERY line of the prompt's command preview (or a non-Bash prompt's file path), newline-separated, in order:
# the approval passes only when the preview's lines equal the --expect lines exactly (same count, same order). Presses the one-time Yes or the No of the permission prompt showing in <win>'s main pane, by its digit alone (claude 2.1.321:
# a digit answers a permission prompt, no Enter; tools/tests/fixtures/approve/README.md). Only an option labelled exactly `Yes`
# (once) or `No` (deny) is ever chosen: "Yes, and don’t ask again…", "Yes, and switch to auto mode…" rows are never pressed.
# Uses tmux-ctl's t, use_win, exists, target. TC_APPROVE_BEFORE_SEND (tests): a command run between the capture and the re-capture.

# the whole visible pane (a dialog can sit anywhere on it), trailing blanks dropped
_ap_screen() { t capture-pane -p -J -t "$1" 2>/dev/null | sed -e 's/[[:space:]]*$//' | grep -v '^$' }

# _ap_prompt: stdin = the screen. Prints nothing when no prompt shows. Otherwise prints `B:<line>` for each line of the prompt block
# (from the solid divider above the command preview, through the last option), `P:<line>` for each line --expect must equal, in order, and `O:<n>:<label>` for each option.
# The options are only the contiguous run `1.` `2.` … right after the last "Do you want…"/"Would you like…" line, so option-shaped
# text inside the command preview is never one. Byte-literal divider and cursor (no {n}, no multibyte class): same result in any locale.
_ap_prompt() {
  awk '
    function optnum(x,   t) {   # the number of an option row, else 0
      t = x; sub(/^[ \t]*(❯)?[ \t]*/, "", t)
      if (t ~ /^[0-9]+\.[ \t]+/) { sub(/\..*/, "", t); return t + 0 }
      return 0
    }
    function emit(x,   t) { t = x; sub(/^[ \t]+/, "", t); sub(/[ \t]+$/, "", t); if (t != "") print "P:" t }
    function optlabel(x,   t) { t = x; sub(/^[ \t]*(❯)?[ \t]*[0-9]+\.[ \t]+/, "", t); sub(/[ \t]+$/, "", t); return t }
    { l[NR] = $0 }
    END {
      q = 0; e = 0
      for (i = 1; i < NR; i++) {
        if (l[i] !~ /(Do you want|Would you like)/ || optnum(l[i+1]) != 1) continue
        j = i + 1; n = 1
        while (j <= NR && optnum(l[j]) == n) { j++; n++ }
        q = i; e = j - 1
      }
      if (!q) exit
      for (i = e + 1; i <= NR; i++) if (l[i] !~ /^[ \t]*Esc to cancel/) exit   # only the footer may follow the options
      s = q
      for (i = q; i >= 1; i--) if (index(l[i], "──────────") == 1) { s = i; break }
      for (i = s; i <= e; i++) print "B:" l[i]
      # P: the lines --expect may equal, trimmed: the command of a Bash prompt (between its two ╌ rules); any other prompt also its
      # header-area lines below the title (the file path only). Never the Bash description, the question or the option rows.
      # X:ambiguous (no P lines) when the preview could fake its own frame: a solid divider or ╌ rule at column 1 above the chosen divider,
      # or not exactly two ╌ rules between the divider and the question.
      r1 = 0; r2 = 0; nr = 0
      for (i = s + 1; i < q; i++) if (index(l[i], "╌╌╌╌╌╌╌╌╌╌") == 1) { nr++; if (!r1) r1 = i; else if (!r2) r2 = i }
      amb = (nr != 2)
      # Claude Code indents every preview line (" cmd", or " │ line" for a multi-line command; fixtures/approve/bash-multiline.txt), so a
      # non-space first character between the two rules is not part of the command.
      for (i = r1 + 1; r1 && r2 && i < r2; i++) if (l[i] ~ /^[^ \t]/) amb = 1
      for (i = 1; i < s; i++) if (index(l[i], "──────────") == 1 || index(l[i], "╌╌╌╌╌╌╌╌╌╌") == 1) amb = 1
      if (amb) print "X:ambiguous"
      else if (r1 && r2) {
        if (l[s+1] !~ /^[ \t]*Bash command/) { for (i = s + 2; i < r1; i++) emit(l[i]) }   # file path only; never the file content
        else for (i = r1 + 1; i < r2; i++) emit(l[i])
      }
      for (i = q + 1; i <= e; i++) print "O:" optnum(l[i]) ":" optlabel(l[i])
    }'
}

approve_cmd() {
  local win="$1" act="$2" expect="" have_expect=0 pane block again line digit want u="usage: tmux-ctl approve <win> once|deny --expect <text>"
  shift 2 2>/dev/null
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
  block="$(_ap_screen "$pane" | _ap_prompt)"
  [[ -n "$block" ]] || { print -u2 "approve: no permission prompt in $win"; return 1 }
  # the preview's P: lines must equal the --expect lines (trimmed, empty ones dropped), same count and order; an ambiguous prompt has no P: lines, so it never matches
  local got want_lines
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
  again="$(_ap_screen "$pane" | _ap_prompt)"
  if [[ "$again" != "$block" ]]; then print -u2 "approve: the prompt in $win changed"; return 1; fi
  [[ "$(t display -p -t "$pane" '#{pane_in_mode}' 2>/dev/null)" == 1 ]] && { print -u2 "approve: $win is in copy mode"; return 1 }
  t send-keys -t "$pane" "$digit"
  print -r -- "approve: $win: chose \"$want\""
}
