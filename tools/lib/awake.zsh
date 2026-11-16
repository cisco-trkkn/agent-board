# awake.zsh — sourced by tmux-ctl for `tmux-ctl awake …` (spec 2026-11-05-queue-keep-awake §1).
# Holds `caffeinate -i -s -w <claude pid>` so an overnight queue is not cut short by idle sleep.
# State: $TC_STATE_DIR/awake.json = {"pid", "caffeinatePid", "since"} plus "lid": true, "watchdogPid" in lid mode (spec §1b).
# `on --queue` watches the tmux server instead (a relay replaces the lead, not the server) and records "queue": true;
# a plain `on` over a live plain hold that watches another pid re-points it (spec 2026-11-10-queue-reliability §4).
# TC_AWAKE_ANCESTOR (tests): the command-name substring that marks the claude ancestor (default: claude).

_aw_file() { print -r -- "$TC_STATE_DIR/awake.json" }
_aw_comm() { local c; c="$(ps -o comm= -p "$1" 2>/dev/null)"; print -r -- "${c:t}" }   # command name of pid $1 ('' when gone)
# Is pid $1 a claude? Claude Code runs as .../claude/versions/<n.n.n>, so its basename is a version number:
# match the command name against $2 (TC_AWAKE_ANCESTOR, default claude) as a substring of the basename OR as a whole path component.
_aw_is_claude() {
  local c e; c="$(ps -o comm= -p "$1" 2>/dev/null)"; [[ -n "$c" ]] || return 1
  [[ "${c:t}" == *"$2"* || "/${c:h}/" == *"/$2/"* ]] && return 0
  # Linux ps prints only the 15-char name, no path: the executable's real path (/proc) carries the claude/versions/ component
  e="$(readlink "/proc/$1/exe" 2>/dev/null)"; [[ -n "$e" ]] || return 1
  [[ "${e:t}" == *"$2"* || "/${e:h}/" == *"/$2/"* ]]
}
_aw_alive() { [[ "$(_aw_comm "$1")" == "$2" ]] }                                        # pid $1 is still the process named $2
_aw_power() { pmset -g batt 2>/dev/null | head -2 }
_aw_on_battery() { [[ "$(pmset -g batt 2>/dev/null)" == *'Battery Power'* ]] }
_aw_pct() { local o; o="$(pmset -g batt 2>/dev/null)"; [[ "$o" =~ '([0-9]+)%' ]] && print -r -- "$match[1]" }   # battery percent ('' when none)
_aw_sleepdisabled() { [[ "$(pmset -g 2>/dev/null)" =~ 'SleepDisabled[[:space:]]+1' ]] }
_aw_ctl() { print -r -- "${TC_SELF:-${${(%):-%x}:A:h:h:h}/bin/tmux-ctl}" }
# Is the sudoers rule for `pmset -a disablesleep <$1>` present? Reads STDOUT for the exact line: Privilege Manager exits 0 without a rule.
_aw_rule() { local o; o="$(sudo -n -l /usr/bin/pmset -a disablesleep "$1" 2>/dev/null)"; [[ $'\n'"$o"$'\n' == *$'\n'"/usr/bin/pmset -a disablesleep $1"$'\n'* ]] }
_aw_release() { sudo -n /usr/bin/pmset -a disablesleep 0 >/dev/null 2>&1 }   # returns sudo's status: callers must not drop the record on failure
_AW_RELFAIL="awake: lid hold release failed (run: sudo pmset -a disablesleep 0)"
_aw_edit() {   # _aw_edit <jq filter> [jq args…]: rewrite awake.json in place (no-op when absent)
  local f="$(_aw_file)" prog="$1"; [[ -f "$f" ]] || return 0; shift
  jq "$@" "$prog" "$f" > "$f.$$" 2>/dev/null && mv "$f.$$" "$f" || rm -f "$f.$$"
}
_aw_queue_recorded() { [[ "$(jq -r '.queue // false' "$(_aw_file)" 2>/dev/null)" == true ]] }
_aw_lid_recorded() { [[ "$(jq -r '.lid // false' "$(_aw_file)" 2>/dev/null)" == true ]] }
_aw_is_watchdog() { [[ -n "$1" && "$(ps -o args= -p "$1" 2>/dev/null)" == *"tmux-ctl awake _watchdog"* ]] }
_aw_stale_warn() { _aw_sleepdisabled && ! _aw_lid_recorded && print -r -- "awake: stale lid hold: SleepDisabled is 1 with no owner; run tmux-ctl awake off"; return 0 }

_aw_lid_on() {   # the lid step of `on --lid`, after the plain hold is up
  local f="$(_aw_file)" pct wd lead
  _aw_lid_recorded && return 0
  if ! _aw_rule 1; then print -r -- "awake: lid hold unavailable (run tmux-ctl awake lid-setup)"; return 0; fi
  pct="$(_aw_pct)"
  if _aw_on_battery && [[ -n "$pct" ]] && (( pct < 30 )); then print -r -- "awake: battery $pct%: no lid hold below 30%"; return 0; fi
  if ! sudo -n /usr/bin/pmset -a disablesleep 1 >/dev/null 2>&1; then print -r -- "awake: lid hold unavailable (run tmux-ctl awake lid-setup)"; return 0; fi
  lead="$(jq -r .pid "$f")"
  "$(_aw_ctl)" awake _watchdog "$lead" >/dev/null 2>&1 </dev/null &!
  wd=$!
  _aw_edit ".lid = true | .watchdogPid = $wd"
  print -r -- "awake: lid hold on: the Mac stays awake with the lid shut; keep it ventilated (not in a closed bag on battery for long)"
}

# The live hold, if any: prints "<caffeinatePid>\t<watched pid>\t<since>". A dead or reused pid removes the file.
_aw_current() {
  local f="$(_aw_file)" cp
  [[ -f "$f" ]] || return 1
  cp="$(jq -r '.caffeinatePid // empty' "$f" 2>/dev/null)"
  if [[ -n "$cp" ]] && _aw_alive "$cp" caffeinate; then
    jq -r '[.caffeinatePid, .pid, .since] | @tsv' "$f"
    return 0
  fi
  _aw_lid_recorded || rm -f "$f"   # a recorded lid hold outlives caffeinate until it is released
  return 1
}

_aw_claude_pid() {   # nearest ancestor of this shell whose command name contains claude
  local want="${TC_AWAKE_ANCESTOR:-claude}" p=$$ n=0 line
  while (( p > 1 && n++ < 40 )); do
    line="$(ps -o ppid=,comm= -p "$p" 2>/dev/null)" || return 1
    [[ -n "$line" ]] || return 1
    p="${${(z)line}[1]}"
    _aw_is_claude "$p" "$want" && { print -r -- "$p"; return 0 }
  done
  return 1
}

# Sleep reasons that are not a real sleep (the Mac was already asleep and went back to it). A deny-list: a reason
# that is not listed here counts as real, so a new one still shows in `awake sleeps`.
_AW_NOT_REAL=('Maintenance Sleep' 'Sleep Service Back to Sleep' 'Notification Wake Back to Sleep')

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
      local pid="" lid=0 queue=0 old="" usage="usage: tmux-ctl awake on [--queue | --pid N] [--lid]"
      while (( $# )); do
        case "$1" in --pid) pid="$2"; shift 2 ;; --lid) lid=1; shift ;; --queue) queue=1; shift ;; *) print -u2 -r -- "$usage"; return 2 ;; esac
      done
      (( queue )) && [[ -n "$pid" ]] && { print -u2 -r -- "$usage"; return 2 }
      [[ -z "$pid" || "$pid" == <-> ]] || { print -u2 -r -- "$usage"; return 2 }   # before anything is killed or written
      if (( queue )); then   # the tmux server outlives every lead of the queue
        pid="$(tc_tmux display -p '#{pid}' 2>/dev/null)"
        [[ "$pid" == <-> ]] || { print -r -- "awake: no tmux server; run on without --queue"; return 1 }
      fi
      if cur="$(_aw_current)"; then
        local -a c=("${(@ps:\t:)cur}")
        if _aw_queue_recorded; then   # a queue hold is never re-pointed
          print -r -- "awake: already on (queue)"
          (( lid )) && _aw_lid_on
          _aw_stale_warn; return 0
        fi
        [[ -n "$pid" ]] || pid="$(_aw_claude_pid)"   # no claude ancestor: the caller is unknown, so the hold is kept
        if (( ! queue )) && [[ -z "$pid" || "$pid" == "$c[2]" ]]; then
          print -r -- "awake: already on (pid $c[1], since $c[3])"
          (( lid )) && _aw_lid_on
          _aw_stale_warn; return 0
        fi
        kill "$c[1]" 2>/dev/null; old="$c[2]"   # re-point: the hold watched another pid
      fi
      [[ -n "$pid" ]] || pid="$(_aw_claude_pid)" || { print -r -- "awake: no claude ancestor; pass --pid"; return 1 }
      caffeinate -i -s -w "$pid" >/dev/null 2>&1 </dev/null &!
      cp=$!
      since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
      if [[ -n "$old" ]]; then   # keep lid and watchdogPid as they are; the watchdog reads .pid each tick
        _aw_edit ".pid = \$pid | .caffeinatePid = \$cp | .since = \$since | $( (( queue )) && print -r -- '.queue = true' || print -r -- 'del(.queue)' )" --argjson pid "$pid" --argjson cp "$cp" --arg since "$since"
      else
        jq -n --argjson pid "$pid" --argjson cp "$cp" --arg since "$since" --argjson q "$queue" '{pid:$pid, caffeinatePid:$cp, since:$since} + (if $q == 1 then {queue:true} else {} end)' > "$f"
      fi
      _aw_on_battery && print -r -- "awake: on battery: idle sleep is held, but a closed lid still sleeps; plug in for the night"
      if [[ -n "$old" ]]; then print -r -- "awake: on (re-pointed from $old to $pid)"
      else print -r -- "awake: on (pid $cp, watching $pid)"; fi
      (( lid )) && _aw_lid_on
      _aw_stale_warn; return 0 ;;
    off)
      local lidwas=0 wd
      if [[ -f "$f" ]]; then
        cp="$(jq -r '.caffeinatePid // empty' "$f" 2>/dev/null)"
        wd="$(jq -r '.watchdogPid // empty' "$f" 2>/dev/null)"
        _aw_lid_recorded && lidwas=1
        [[ -n "$cp" ]] && _aw_alive "$cp" caffeinate && kill "$cp" 2>/dev/null
        if (( lidwas )); then
          if _aw_release; then _aw_is_watchdog "$wd" && kill "$wd" 2>/dev/null; rm -f "$f"
          else print -u2 -r -- "$_AW_RELFAIL"; return 1; fi   # keep the record and the watchdog: status shows it, the watchdog retries
        else rm -f "$f"; fi
      fi
      if (( lidwas )); then :
      elif _aw_sleepdisabled; then   # a stale hold with no record: clear it when the rule allows
        if _aw_rule 0; then _aw_release
        else print -r -- "awake: lid hold still on: install the rule (tmux-ctl awake lid-setup) or run: sudo pmset -a disablesleep 0"; fi
      fi
      print -r -- "awake: off" ;;
    status)
      if cur="$(_aw_current)"; then
        local -a c=("${(@ps:\t:)cur}")
        print -r -- "on (pid $c[1], watching $c[2], since $c[3])"
        _aw_queue_recorded && print -r -- "queue: on"
      else print -r -- "off"; fi
      if _aw_lid_recorded; then print -r -- "lid: on"; else print -r -- "lid: off"; fi
      _aw_stale_warn
      _aw_power ;;
    lid-setup)
      print -r -- "Add this sudoers rule (it lets $(id -un) switch lid-closed sleep off and on without a password):"
      print -r -- "$(id -un) ALL=(root) NOPASSWD: /usr/bin/pmset -a disablesleep 0, /usr/bin/pmset -a disablesleep 1"
      print -r -- "Install it with:  sudo visudo -f /etc/sudoers.d/agent-board-awake"
      return 0 ;;
    _watchdog)   # detached by `on --lid`: releases the lid hold when the lead dies or the battery drops below 15%
      local lead="$1" tick="${TC_AWAKE_TICK:-60}" pct wp fl
      zmodload zsh/zselect 2>/dev/null
      while :; do
        zselect -t $(( tick * 100 )) 2>/dev/null
        if [[ -f "$f" ]]; then   # a newer hold owns the file: not ours to release
          wp="$(jq -r '.watchdogPid // empty' "$f" 2>/dev/null)"
          [[ -n "$wp" && "$wp" != "$$" ]] && return 0
          fl="$(jq -r '.pid // empty' "$f" 2>/dev/null)"; [[ "$fl" == <-> ]] && lead="$fl"   # a re-pointed hold: follow its watched pid
        fi
        if ! kill -0 "$lead" 2>/dev/null; then
          if _aw_release; then _aw_edit 'del(.lid, .watchdogPid)'; return 0; fi
          print -r -- "$_AW_RELFAIL" >> "$TC_STATE_DIR/awake.log"; continue   # keep the record, retry next tick
        fi
        if _aw_on_battery; then
          pct="$(_aw_pct)"
          if [[ -n "$pct" ]] && (( pct < 15 )); then
            print -r -- "awake: lid hold released: battery $pct%" >> "$TC_STATE_DIR/awake.log"
            if _aw_release; then _aw_edit 'del(.lid, .watchdogPid)'; return 0; fi
            print -r -- "$_AW_RELFAIL" >> "$TC_STATE_DIR/awake.log"
          fi
        fi
      done ;;
    sleeps)
      # default: one line per real sleep period, "<start> – <end> <reason>"; --all: every Sleep, Wake and DarkWake line
      local all=0 sarg="" susage="usage: tmux-ctl awake sleeps <since> [--all]"
      while (( $# )); do
        if [[ "$1" == --all ]]; then all=1
        elif [[ -z "$sarg" ]]; then sarg="$1"
        else print -u2 -r -- "$susage"; return 2; fi
        shift
      done
      [[ -n "$sarg" ]] || { print -u2 -r -- "$susage"; return 2 }
      local from; from="$(_aw_epoch "$sarg")" || { print -u2 "awake: cannot read time '$sarg'"; return 2 }
      zmodload -F zsh/datetime b:strftime 2>/dev/null
      local line ts ty rest e reason lt pstart="" preason=""
      pmset -g log 2>/dev/null | awk '($4=="Sleep"||$4=="Wake"||$4=="DarkWake") && $5!="Requests"' | while IFS= read -r line; do
        ts="${line[1,25]}"; ty="${${(z)line}[4]}"; rest="${line#*$'\t'}"
        strftime -r -s e '%Y-%m-%d %H:%M:%S %z' "$ts" 2>/dev/null || continue
        if [[ "$ty" == Sleep ]]; then reason="${${rest#*\'}%%\'*}"
        else reason="${${rest#*from }%% \[*}"; fi
        strftime -s lt '%Y-%m-%d %H:%M:%S' "$e"
        if (( all )); then
          (( e >= from )) && print -r -- "$lt $ty $reason"
        elif [[ "$ty" == Sleep ]]; then   # a period opens at the first real Sleep line at or after <since>
          [[ -z "$pstart" ]] && (( e >= from )) && (( ! ${_AW_NOT_REAL[(Ie)$reason]} )) && { pstart="$lt"; preason="$reason" }
        elif [[ "$ty" == Wake && -n "$pstart" ]]; then   # and closes at the next Wake; DarkWake lines are dropped
          print -r -- "$pstart – $lt $preason"; pstart=""
        fi
      done
      [[ -n "$pstart" ]] && print -r -- "$pstart – … $preason"
      return 0 ;;
    *) print -u2 "usage: tmux-ctl awake on [--queue | --pid N] [--lid] | off | status | sleeps <since> [--all] | lid-setup"; return 2 ;;
  esac
}
