# tools/lib/project.zsh — tmux-ctl project new|start (spec 2026-11-23-new-project-remote, §2 tmux-ctl).
# Sourced by bin/tmux-ctl; works outside tmux (the board runs it). Uses tc_tmux from bin/_tc_bins.zsh.
_pj_usage() { print -u2 "usage: tmux-ctl project new <name> --init | --clone <url> | --dir <path> | start <name> [--dir <path>]"; return 2 }
# a name: today's project-name rule, and no '.' (dev maps '.' to '_' in the session name, so the lead would miss the bot's state dir)
_pj_name_ok() { [[ "$1" =~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' ]] }
_pj_root() { print -r -- "${TC_STATE:-$HOME/.local/state/agent-board}" }

project_cmd() {
  emulate -L zsh
  local sub="$1" name="$2" mode="" val="" dir
  shift 2 2>/dev/null || { _pj_usage; return 2 }
  [[ "$sub" == (new|start) ]] || { _pj_usage; return 2 }
  _pj_name_ok "$name" || { print -u2 "project: a name uses letters, digits, '_' and '-' and starts with a letter or digit"; return 2 }
  while (( $# )); do
    case "$1" in
      --init) [[ -z "$mode" && "$sub" == new ]] || { _pj_usage; return 2 }; mode=init; shift ;;
      --clone|--dir)
        [[ -z "$mode" && -n "$2" ]] || { _pj_usage; return 2 }
        [[ "$1" == --clone && "$sub" == start ]] && { _pj_usage; return 2 }
        mode="${1#--}"; val="$2"; shift 2 ;;
      *) _pj_usage; return 2 ;;
    esac
  done
  if [[ "$sub" == start ]]; then _pj_start "$name" "$val"; return $?; fi
  [[ -n "$mode" ]] || { _pj_usage; return 2 }
  _pj_new "$name" "$mode" "$val"
}

_pj_new() {
  local name="$1" mode="$2" val="$3" dir top err
  if tc_tmux has-session -t "=$name" 2>/dev/null; then print -u2 "project: tmux session $name exists"; return 1; fi
  case "$mode" in
    init)
      dir="$HOME/$name"
      if [[ -e "$dir" ]]; then
        # a retry after a half-done init: an empty folder, or one holding only a fresh .git with no commit, is taken as is
        local -a rest=("$dir"/*(DN))
        if (( ${#rest} == 0 )); then :
        elif [[ ${#rest} == 1 && "${rest[1]:t}" == .git ]] && ! git -C "$dir" rev-parse -q --verify HEAD >/dev/null 2>&1; then :
        else print -u2 "project: $dir exists"; return 1; fi
      fi
      mkdir -p -- "$dir" && git -C "$dir" init -q -b main || { print -u2 "project: git init failed in $dir"; return 1 }
      print -r -- "$dir" ;;
    clone)
      dir="$HOME/$name"
      [[ -e "$dir" ]] && { print -u2 "project: $dir exists"; return 1 }
      if ! err="$(git clone -q -- "$val" "$dir" 2>&1 >/dev/null)"; then
        local -a lines=("${(@f)err}")
        print -u2 -r -- "project: clone failed: ${lines[-1]:-git clone exited non-zero}"; return 1
      fi
      print -r -- "$dir" ;;
    dir)
      dir="${val:A}"
      [[ -d "$dir" ]] || { print -u2 "project: $val is not a directory"; return 1 }
      top="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)" || { print -u2 "project: $dir is not a git work tree"; return 1 }
      [[ "${top:A}" == "$dir" ]] || { print -u2 "project: $dir is inside the repo ${top:A}; give its top level"; return 1 }
      [[ "${dir:t}" == "$name" ]] || { print -u2 "project: the folder is named ${dir:t}, not $name (the dev session takes the folder's name)"; return 1 }
      print -r -- "$dir" ;;
  esac
}

_pj_start() {
  local name="$1" dir="${2:-$HOME/$1}" ch prompt lead
  dir="${dir:A}"
  [[ -d "$dir" ]] || { print -u2 "project: $dir is not a directory"; return 1 }
  [[ "${dir:t}" == "$name" ]] || { print -u2 "project: the folder is named ${dir:t}, not $name"; return 1 }
  if tc_tmux has-session -t "=$name" 2>/dev/null; then print -r -- "project: $name already running"; return 0; fi
  lead="${TC_PROJECT_LEAD_CMD:-${_PJ_BIN}/claude-orchestrator}"
  ch="$(jq -r '.channel // empty' "$(_pj_root)/discord/$name/bridge.json" 2>/dev/null)"
  if [[ "$ch" =~ '^[0-9]+$' ]]; then
    prompt="New project $name, set up from Discord. Post exactly \"hello from $name\" in Discord channel $ch with the reply tool, then wait for the user."
    DEV_CLAUDE_CMD="${(q)lead} ${(q)prompt}"
  else
    DEV_CLAUDE_CMD="${(q)lead}"
  fi
  DEV_CLAUDE_CMD="$DEV_CLAUDE_CMD" DEV_NO_ATTACH=1 "${_PJ_BIN}/dev" "$dir" >/dev/null 2>&1 \
    || { print -u2 "project: dev could not start $name"; return 1 }
  tc_tmux has-session -t "=$name" 2>/dev/null || { print -u2 "project: session $name did not start"; return 1 }
  print -r -- "project: started $name"
}
