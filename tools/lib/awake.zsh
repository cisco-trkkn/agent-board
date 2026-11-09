# awake.zsh — sourced by tmux-ctl for `tmux-ctl awake …` (spec 2026-11-05-queue-keep-awake §1).
# Holds `caffeinate -i -s -w <claude pid>` so an overnight queue is not cut short by idle sleep.
# State: $TC_STATE_DIR/awake.json = {"pid", "caffeinatePid", "since"}.
# TC_AWAKE_ANCESTOR (tests): the command-name substring that marks the claude ancestor (default: claude).

_aw_file() { print -r -- "$TC_STATE_DIR/awake.json" }
_aw_comm() { local c; c="$(ps -o comm= -p "$1" 2>/dev/null)"; print -r -- "${c:t}" }   # command name of pid $1 ('' when gone)
_aw_alive() { [[ "$(_aw_comm "$1")" == "$2" ]] }                                        # pid $1 is still the process named $2
_aw_power() { pmset -g batt 2>/dev/null | head -2 }
_aw_on_battery() { pmset -g batt 2>/dev/null | grep -q 'Battery Power' }

# The live hold, if any: prints "<caffeinatePid>\t<watched pid>\t<since>". A dead or reused pid removes the file.
_aw_current() {
  local f="$(_aw_file)" cp
  [[ -f "$f" ]] || return 1
  cp="$(jq -r '.caffeinatePid // empty' "$f" 2>/dev/null)"
  if [[ -n "$cp" ]] && _aw_alive "$cp" caffeinate; then
    jq -r '[.caffeinatePid, .pid, .since] | @tsv' "$f"
    return 0
  fi
  rm -f "$f"; return 1
}

_aw_claude_pid() {   # nearest ancestor of this shell whose command name contains claude
  local want="${TC_AWAKE_ANCESTOR:-claude}" p=$$ n=0 line
  while (( p > 1 && n++ < 40 )); do
    line="$(ps -o ppid=,comm= -p "$p" 2>/dev/null)" || return 1
    [[ -n "$line" ]] || return 1
    p="${${(z)line}[1]}"
    [[ "$(_aw_comm "$p")" == *"$want"* ]] && { print -r -- "$p"; return 0 }
  done
  return 1
}

_aw_epoch() {   # _aw_epoch <ISO UTC | local 'YYYY-MM-DD HH:MM'> -> epoch seconds
  zmodload -F zsh/datetime b:strftime 2>/dev/null
  local s="$1" e
  if [[ "$s" == *Z ]]; then TZ=UTC strftime -r -s e '%Y-%m-%dT%H:%M:%SZ' "$s" 2>/dev/null || TZ=UTC strftime -r -s e '%Y-%m-%dT%H:%MZ' "$s" 2>/dev/null
  else strftime -r -s e '%Y-%m-%d %H:%M:%S' "$s" 2>/dev/null || strftime -r -s e '%Y-%m-%d %H:%M' "$s" 2>/dev/null
  fi || return 1
  print -r -- "$e"
}

awake_cmd() {
  local sub="$1"; [[ -n "$sub" ]] && shift
  (( $+commands[caffeinate] && $+commands[pmset] )) || { print -r -- "awake: unsupported here"; return 0 }
  local f="$(_aw_file)" cur cp since
  case "$sub" in
    on)
      local pid=""
      while (( $# )); do
        case "$1" in --pid) pid="$2"; shift 2 ;; *) print -u2 "usage: tmux-ctl awake on [--pid N]"; return 2 ;; esac
      done
      if cur="$(_aw_current)"; then
        local -a c=("${(@ps:\t:)cur}")
        print -r -- "awake: already on (pid $c[1], since $c[3])"; return 0
      fi
      [[ -n "$pid" ]] || pid="$(_aw_claude_pid)" || { print -r -- "awake: no claude ancestor; pass --pid"; return 1 }
      caffeinate -i -s -w "$pid" >/dev/null 2>&1 </dev/null &!
      cp=$!
      since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      jq -n --argjson pid "$pid" --argjson cp "$cp" --arg since "$since" '{pid:$pid, caffeinatePid:$cp, since:$since}' > "$f"
      _aw_on_battery && print -r -- "awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night"
      print -r -- "awake: on (pid $cp, watching $pid)" ;;
    off)
      if [[ -f "$f" ]]; then
        cp="$(jq -r '.caffeinatePid // empty' "$f" 2>/dev/null)"
        [[ -n "$cp" ]] && _aw_alive "$cp" caffeinate && kill "$cp" 2>/dev/null
        rm -f "$f"
      fi
      print -r -- "awake: off" ;;
    status)
      if cur="$(_aw_current)"; then
        local -a c=("${(@ps:\t:)cur}")
        print -r -- "on (pid $c[1], watching $c[2], since $c[3])"
      else print -r -- "off"; fi
      _aw_power ;;
    sleeps)
      [[ -n "$1" ]] || { print -u2 "usage: tmux-ctl awake sleeps <since>"; return 2 }
      local from; from="$(_aw_epoch "$1")" || { print -u2 "awake: cannot read time '$1'"; return 2 }
      zmodload -F zsh/datetime b:strftime 2>/dev/null
      local line ts ty rest e reason lt
      pmset -g log 2>/dev/null | awk '($4=="Sleep"||$4=="Wake"||$4=="DarkWake") && $5!="Requests"' | while IFS= read -r line; do
        ts="${line[1,25]}"; ty="${${(z)line}[4]}"; rest="${line#*$'\t'}"
        strftime -r -s e '%Y-%m-%d %H:%M:%S %z' "$ts" 2>/dev/null || continue
        (( e >= from )) || continue
        if [[ "$ty" == Sleep ]]; then reason="${${rest#*\'}%%\'*}"
        else reason="${${rest#*from }%% \[*}"; fi
        strftime -s lt '%Y-%m-%d %H:%M:%S' "$e"
        print -r -- "$lt $ty $reason"
      done
      return 0 ;;
    *) print -u2 "usage: tmux-ctl awake on [--pid N] | off | status | sleeps <since>"; return 2 ;;
  esac
}
