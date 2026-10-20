#!/usr/bin/env zsh
# artifact-register.sh — record session artifacts for the Agent Board.
#   hook mode (PostToolUse Write|Edit|MultiEdit|Artifact): reads the hook JSON on stdin
#   manual mode: artifact-register.sh --path P [--kind K] [--agent A] [--project NAME]
# Appends {ts,path,kind,agent,hash,url,session_id,epoch} to $STATE/artifacts-<project>.jsonl.
# epoch = lines in $STATE/lineage-<project>.jsonl (one per handoff relay). Silent; always exits 0.
emulate -L zsh
STATE="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$UID}"
# tmux: the repo's resolver; if the plugin was copied away from its repo, the server this pane is on
RES="${0:A:h:h:h:h}/bin/_tc_bins.zsh"
if [[ -r "$RES" ]]; then source "$RES"; TMUX_BIN=tc_tmux
else TMUX_BIN=("${TC_TMUX:-$([[ -x $HOME/.local/bin/tmux ]] && print -r -- $HOME/.local/bin/tmux || print -r -- ${commands[tmux]:-$HOME/.local/bin/tmux})}"); [[ -n "$TMUX" ]] && TMUX_BIN+=(-S "${TMUX%%,*}"); fi
{
  apath= kind= agent= project= manual=0 scoped=0
  while (( $# )); do
    case "$1" in
      --path)    apath="$2"; manual=1; shift 2 ;;
      --scoped)  scoped=1; shift ;;
      --kind)    kind="$2"; shift 2 ;;
      --agent)   agent="$2"; shift 2 ;;
      --project) project="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  # dedupe: the scoped registration covers agent-board sessions; the legacy global one defers (manual --path always runs)
  (( manual || scoped )) || [[ "$AGENT_BOARD" != 1 ]] || exit 0
  if [[ -z "$project" ]]; then
    [[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
    project="$("${TMUX_BIN[@]}" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}')" || exit 0
  fi
  [[ "$project" =~ '^[A-Za-z0-9._-]+$' ]] || exit 0
  if [[ -z "$agent" ]]; then
    [[ -n "$TMUX_PANE" ]] && agent="$("${TMUX_BIN[@]}" display -p -t "$TMUX_PANE" '#{window_name}')"
    agent="${agent#✦ }"; agent="${agent:-claude}"
  fi
  mkdir -p "$STATE"
  lineage="$STATE/lineage-$project.jsonl"
  epoch=0; [[ -f "$lineage" ]] && epoch=$(( $(wc -l < "$lineage") ))
  if (( manual )); then payload='{}'; else payload="$(cat)"; fi
  line="$(print -r -- "$payload" | python3 -I -c '
import hashlib, json, os, re, sys, time
manual, path, kind, agent, epoch, home, tmp = sys.argv[1:8]
manual = manual == "1"
url = sid = ""
if not manual:
    try:
        d = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    tool = d.get("tool_name") or ""
    ti = d.get("tool_input") or {}
    sid = d.get("session_id") or ""
    if tool == "Artifact":
        m = re.search(r"https://claude\.ai/[\w/.-]+", json.dumps(d.get("tool_response") or ""))
        if not m:
            sys.exit(0)
        url, kind = m.group(0), "published"
        path = ti.get("file_path") or url
    elif tool in ("Write", "Edit", "MultiEdit"):
        path = ti.get("file_path") or ""
    else:
        sys.exit(0)
if not path:
    sys.exit(0)
if not url:
    path = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(path):
        sys.exit(0)
def kind_of(p):
    if not p.endswith(".md"):
        return ""
    h, t, base = os.path.realpath(home), os.path.realpath(tmp), os.path.basename(p)
    if "/docs/superpowers/plans/" in p: return "plan"
    if "/docs/superpowers/specs/" in p: return "spec"
    for hd in ((".local", "state", "agent-board", "handoffs"), (".claude", "handoffs")):
        if p.startswith(os.path.join(h, *hd) + os.sep): return "handoff"
    if p.startswith(t + os.sep) and "handoff" in base: return "handoff"
    if "/scratchpad/" in p and "report" in base: return "report"
    return ""
if not kind:
    kind = kind_of(path) or ("other" if manual else "")
if not kind:
    sys.exit(0)
digest = ""
if not url:
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
print(json.dumps({"ts": time.time(), "path": path, "kind": kind, "agent": agent, "hash": digest,
                  "url": url, "session_id": sid, "epoch": int(epoch)}))
' "$manual" "$apath" "$kind" "$agent" "$epoch" "$HOME" "${TMPDIR:-/tmp}")"
  [[ -n "$line" ]] && print -r -- "$line" >> "$STATE/artifacts-$project.jsonl"
} >/dev/null 2>&1
exit 0
