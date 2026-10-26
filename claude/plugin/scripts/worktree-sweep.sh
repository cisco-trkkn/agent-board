#!/usr/bin/env zsh
# worktree-sweep.sh — PostToolUse Bash hook: after git merge / git pull / glab mr merge / git branch -d|-D, start a
# detached `agent-worktrees sweep <repo>`. Silent, always exits 0. The sweep's summary goes to the sweep log and, when
# the session has a dev layout, to the shell feed (same entry header as bash-mirror).
# Test seam: AW_CLI overrides the agent-worktrees command.
emulate -L zsh
_tcenv="${${(%):-%x}:A:h:h:h:h}/tools/lib/tc-env.zsh"
source "$_tcenv" 2>/dev/null || {
  _m="${${(%):-%x}:t}: cannot load $_tcenv: using the default state dir (a plugin copied away from its repo has no tc-env)"
  print -u2 -r -- "$_m"; print -r -- "$(date +%FT%T) $_m" >> "${${TMPDIR:-/tmp}%/}/tmux-ctl-hook-errors.log" 2>/dev/null
  TC_STATE_DIR="${TC_STATE:-${${TMPDIR:-/tmp}%/}/tmux-ctl-$UID}"
}
zmodload zsh/datetime

# detached child: --sweep-child <repo> <feed log or ""> <caller> <cwd>. Runs the sweep, logs it, appends the feed entry.
if [[ "$1" == --sweep-child ]]; then
  repo=$2 feedlog=$3 caller=$4 cwd=$5
  STATE="$TC_STATE_DIR"; mkdir -p "$STATE"
  out="$("${(@Q)${(z)AW_CLI}}" sweep "$repo" 2>&1)"; code=$?
  print -r -- "$(date +%FT%T) sweep $repo (exit $code)"$'\n'"$out" >> "$STATE/worktree-sweep.log"
  [[ -n "$feedlog" ]] || exit 0
  removed=() kept=() stale=()
  for l in "${(@f)out}"; do
    case "$l" in
      "removed "*) removed+=("${l#removed }") ;;
      "kept "*)    kept+=("${l#kept }") ;;
      "stale "*)   stale+=("${l#stale }") ;;
    esac
  done
  parts=()
  (( $#removed )) && parts+=("removed ${(j:, :)removed}")
  (( $#kept ))    && parts+=("kept ${(j:, :)kept}")
  (( $#stale ))   && parts+=("stale ${(j:, :)stale}")
  (( $#parts )) || parts=("nothing to remove")
  if [[ -f "$feedlog" ]] && (( $(wc -c < "$feedlog") > 2097152 )); then
    tail -c 1048576 "$feedlog" > "$feedlog.tmp.$$" && mv "$feedlog.tmp.$$" "$feedlog"
  fi
  print -r -- "── $(date +%H:%M:%S) · worktree-sweep · $cwd · exit $code · @$EPOCHSECONDS"$'\n'"\$ agent-worktrees sweep $repo"$'\n'"swept: ${(j:; :)parts}"$'\n' >> "$feedlog"
  exit 0
fi

# dedupe: the scoped registration (--scoped) covers agent-board sessions; the legacy global one defers to it
[[ "$1" == --scoped || "$AGENT_BOARD" != 1 ]] || exit 0
{
  payload="$(cat)"
  fields="$(print -r -- "$payload" | python3 -I -c '
import sys, json, re, os
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
if d.get("tool_name") != "Bash": sys.exit(1)
cmd = (d.get("tool_input") or {}).get("command") or ""
cwd = d.get("cwd") or ""
SEP = r"(?:^|&&|\|\||;|\||\()\s*"
WRAP = r"(?:(?:time|env|sudo|nohup|npx|pnpx|bunx|uv\s+run|poetry\s+run|pipenv\s+run)\s+(?:\w+=\S+\s+)*)*"
GITOPT = r"(?:\s+(?:-[Cc]\s+\S+|--[\w-]+(?:=\S+)?))*"
END = r"(?![\w-])"
SUB = (r"(?:git" + GITOPT + r"\s+(?:merge|pull)" + END +
       r"|git" + GITOPT + r"\s+branch\s+[^;&|]*?(?<=\s)(?:-[a-zA-Z]*[dD][a-zA-Z]*|--delete)(?=\s|$)"
       r"|glab\s+mr\s+merge" + END + ")")
pat = re.compile(SEP + r"(?:\w+=\S+\s+)*" + WRAP + SUB)
def hit(c):
    for m in re.finditer(r"(?:^|&&|\|\||;|\||\()\s*(?:bash|sh|zsh)\s+-c\s+([\x27\"])(.*?)\1", c):
        if hit(m.group(2)): return True
    plain = re.sub(r"\"(?:\\.|[^\"\\])*\"|\x27[^\x27]*\x27", chr(34)*2, c)
    return bool(pat.search(plain))
# tmux-ctl wraps its command in quotes: the quoted command is still a merge
cands = [cmd] + [m.group(2) for m in re.finditer(r"tmux-ctl\s+run\b.*?([\x27\"])(.*)\1", cmd, re.S)]
if not any(hit(c) for c in cands): sys.exit(1)
m = re.search(r"\bgit\s+(?:-c\s+\S+\s+)*-C\s+(\"[^\"]*\"|\x27[^\x27]*\x27|\S+)", cmd)
target = cwd
if m:
    t = m.group(1).strip("\"\x27")
    t = os.path.expanduser(t)
    target = t if os.path.isabs(t) else os.path.join(cwd, t)
home = os.path.expanduser("~")
shown = "~" + cwd[len(home):] if cwd == home or cwd.startswith(home + "/") else cwd
sys.stdout.write("\0".join([target, shown]))
')" || exit 0
  parts=("${(@0)fields}")
  target=$parts[1] shown=$parts[2]
  [[ -d "$target" ]] || exit 0
  common="$(git -C "$target" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || exit 0
  [[ "${common:t}" == .git ]] || exit 0     # bare repos have no main checkout to sweep from
  repo="${common:h}"
  # the agent-worktrees command: AW_CLI, else bin/ of this repo, else ~/.local/bin, else PATH
  if [[ -z "$AW_CLI" ]]; then
    for c in "${${(%):-%x}:A:h:h:h:h}/bin/agent-worktrees" "$HOME/.local/bin/agent-worktrees" "${commands[agent-worktrees]}"; do
      [[ -n "$c" && -x "$c" ]] && { AW_CLI="$c"; break; }
    done
  fi
  [[ -n "$AW_CLI" ]] || exit 0
  # feed: located the way bash-mirror does it; none without a dev session (the sweep log is written anyway)
  feedlog= caller=
  if [[ -n "$TMUX" && -n "$TMUX_PANE" ]]; then
    RES="${${(%):-%x}:A:h:h:h:h}/bin/_tc_bins.zsh"
    if [[ -r "$RES" ]]; then source "$RES"; T=tc_tmux
    else T=("${TC_TMUX:-$([[ -x $HOME/.local/bin/tmux ]] && print -r -- $HOME/.local/bin/tmux || print -r -- ${commands[tmux]:-$HOME/.local/bin/tmux})}" -S "${TMUX%%,*}"); fi
    info="$("${T[@]}" display -p -t "$TMUX_PANE" '#{session_name}'$'\t''#{window_name}'$'\t''#{?session_group,#{session_group},#{session_name}}' 2>/dev/null)"
    if [[ -n "$info" ]]; then
      session="${info%%$'\t'*}" rest="${info#*$'\t'}"
      caller="${rest%%$'\t'*}" canon="${rest#*$'\t'}"
      caller="${caller#✦ }"
      wins="$("${T[@]}" list-windows -t "=$session" -F '#{window_name}' 2>/dev/null)"
      winarr=("${(@f)wins}")
      if "${T[@]}" has-session -t "=$canon-bg" 2>/dev/null || (( ${winarr[(Ie)shell]} )); then
        mkdir -p "$TC_STATE_DIR"; feedlog="$TC_STATE_DIR/feed-$canon-shell.log"
      fi
    fi
  fi
  export AW_CLI TC_STATE_DIR
  nohup zsh "${${(%):-%x}:A}" --sweep-child "$repo" "$feedlog" "$caller" "$shown" </dev/null >/dev/null 2>&1 &!
} >/dev/null 2>&1
exit 0
