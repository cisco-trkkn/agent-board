# teammates.zsh — sourced by tmux-ctl for `tmux-ctl teammates`.
# One row per teammate of this lead (CLAUDE_CODE_SESSION_ID): <name> <yes|no> <busy|idle|-> <HH:MM|-> <first line>.
# Teammates = names in <state>/teammates/<lead id>/<name>.json (written by the teammate Stop hook) plus the `✦ <name>` windows
# of this session. Window alive = such a window exists; busy/idle is pane_idle, the check `list` uses. Needs tmux-ctl's t, pane_idle, main_pane.
zmodload zsh/datetime

tm_list() {
  local sid="$CLAUDE_CODE_SESSION_ID" dir name rec w mp
  typeset -A tsof firstof alive
  if [[ "$sid" =~ '^[A-Za-z0-9_-]+$' && -d "$STATE/teammates/$sid" ]]; then
    # python skips an unreadable or malformed file; one tab-separated line per good one: name, ts, first line
    while IFS=$'\t' read -r name rec w; do
      [[ -n "$name" ]] || continue
      tsof[$name]="$rec"; firstof[$name]="$w"
    done < <(python3 -I -c '
import json, os, sys
d = sys.argv[1]
for f in sorted(os.listdir(d)):
    if not f.endswith(".json") or f.startswith("."):
        continue
    try:
        with open(os.path.join(d, f)) as fh:
            j = json.load(fh)
        ts = int(j["ts"])
        first = str(j.get("first_line") or "")
    except Exception:
        continue
    name = f[:-5]
    print("%s\t%d\t%s" % (name, ts, " ".join(first.split())[:80]))
' "$STATE/teammates/$sid")
  fi
  for w in ${(f)"$(t list-windows -t "=$SESSION" -F '#{window_name}' 2>/dev/null)"}; do
    [[ "$w" == "✦ "* ]] && alive[${w#✦ }]=1
  done
  local -a names=( ${(ko)tsof} ${(ko)alive} )
  names=( ${(u)names} ); names=( ${(o)names} )
  (( $#names )) || { print -r -- "no teammates"; return 0 }
  local live state when
  for name in $names; do
    live=no state=-; when=-
    if (( ${+alive[$name]} )); then
      live=yes; state=busy
      mp="$(main_pane "✦ $name")"
      pane_idle "${mp:-=$SESSION:✦ $name}" && state=idle
    fi
    (( ${+tsof[$name]} )) && when="$(strftime %H:%M ${tsof[$name]})"
    print -r -- "$name $live $state $when ${firstof[$name]:--}"
  done
}
