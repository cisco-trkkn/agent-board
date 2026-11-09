# approve.zsh — sourced by tmux-ctl for `tmux-ctl approve <win> once|deny [--expect <text>]` (spec 2026-11-09-remote-access §5).
# Presses the one-time Yes or the No of the permission prompt showing in <win>'s main pane, by its digit alone (claude 2.1.321:
# a digit answers a permission prompt, no Enter; tools/tests/fixtures/approve/README.md). Only an option labelled exactly `Yes`
# (once) or `No` (deny) is ever chosen: "Yes, and don’t ask again…", "Yes, and switch to auto mode…" rows are never pressed.
# Uses tmux-ctl's t, use_win, exists, target. TC_APPROVE_BEFORE_SEND (tests): a command run between the capture and the re-capture.

_ap_screen() { t capture-pane -p -J -t "$1" 2>/dev/null | tail -40 | sed -e 's/[[:space:]]*$//' | grep -v '^$' }

# _ap_prompt: stdin = the screen; prints the prompt block (from the last divider above the last "Do you want…" line, else from that line)
# or nothing when no numbered options follow such a line.
_ap_prompt() {
  awk '
    { l[NR]=$0 }
    END {
      q=0; for (i=1;i<=NR;i++) if (l[i] ~ /(Do you want|Would you like)/) q=i
      if (!q) exit
      n=0; for (i=q+1;i<=NR;i++) if (l[i] ~ /^[[:space:]]*(❯)?[[:space:]]*[0-9]+\.[[:space:]]+/) n++
      if (!n) exit
      s=q; for (i=q;i>=1;i--) if (l[i] ~ /^─{10}/) { s=i; break }
      for (i=s;i<=NR;i++) print l[i]
    }'
}

approve_cmd() {
  local win="$1" act="$2" expect="" pane block again line label digit want
  shift 2 2>/dev/null
  while (( $# )); do
    case "$1" in
      --expect) expect="$2"; shift 2 2>/dev/null || die "usage: tmux-ctl approve <win> once|deny [--expect <text>]" ;;
      *) die "usage: tmux-ctl approve <win> once|deny [--expect <text>]" ;;
    esac
  done
  [[ -n "$win" && ( "$act" == once || "$act" == deny ) ]] || die "usage: tmux-ctl approve <win> once|deny [--expect <text>]"
  use_win "$win"; exists "$win"
  pane="$(target "$win")"
  block="$(_ap_screen "$pane" | _ap_prompt)"
  [[ -n "$block" ]] || { print -u2 "approve: no permission prompt in $win"; return 1 }
  if [[ -n "$expect" && "$block" != *"$expect"* ]]; then print -u2 "approve: the prompt in $win changed"; return 1; fi
  [[ "$act" == once ]] && want=Yes || want=No
  while IFS= read -r line; do
    if [[ "$line" =~ '^[[:space:]]*(❯)?[[:space:]]*([0-9]+)\.[[:space:]]+(.*)$' ]]; then
      label="${match[3]}"; label="${label%"${label##*[![:space:]]}"}"
      [[ "$label" == "$want" ]] && { digit="${match[2]}"; break }
    fi
  done <<< "$block"
  if [[ -z "$digit" ]]; then
    [[ "$act" == once ]] && print -u2 "approve: no one-time Yes in $win" || print -u2 "approve: no No option in $win"
    return 1
  fi
  [[ -n "$TC_APPROVE_BEFORE_SEND" ]] && eval "$TC_APPROVE_BEFORE_SEND" >/dev/null 2>&1
  again="$(_ap_screen "$pane" | _ap_prompt)"
  if [[ "$again" != "$block" ]]; then print -u2 "approve: the prompt in $win changed"; return 1; fi
  t send-keys -t "$pane" "$digit"
  print -r -- "approve: $win: chose \"$want\""
}
