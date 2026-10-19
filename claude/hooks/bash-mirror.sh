#!/usr/bin/env zsh
# bash-mirror.sh — PostToolUse/PostToolUseFailure hook: append each agent Bash call to the
# session's tests/shell feed log. Silent, always exits 0.
# Entry header: `── HH:MM:SS · <agent> · <cwd> · exit N · @<epoch>` (the epoch orders entries across midnight).
emulate -L zsh
source "${${(%):-%x}:A:h:h:h}/tools/lib/tc-env.zsh" 2>/dev/null || exit 0   # tc-env: state dir, shell/prompt patterns (resolves the symlink into the repo)
zmodload zsh/datetime
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
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
c = cmd.lstrip()
if re.match(r"(~/\.local/bin/|\S*/)?tmux-ctl(\s|$)", c): sys.exit(1)
ev = d.get("hook_event_name") or ""
r = d.get("tool_response")
if not isinstance(r, dict): r = {}
code = None
for k in ("exit_code", "returncode"):
    if isinstance(r.get(k), int): code = r[k]; break
err = d.get("error") if isinstance(d.get("error"), str) else ""
if code is None:
    if ev == "PostToolUseFailure":
        m = re.search(r"^Exit code (\d+)", err, re.M); code = int(m.group(1)) if m else 1
    else:
        code = 0
out = "".join(str(r.get(k) or "") for k in ("stdout", "stderr"))
if not out and err: out = re.sub(r"^Exit code \d+\n?", "", err)
tail = "\n".join(out.rstrip("\n").split("\n")[-12:]) if out.strip() else ""
first = cmd.strip("\n").split("\n")[0] if cmd.strip() else ""
if "\n" in cmd.strip(): first += " …"
SEP = r"(?:^|&&|\|\||;|\||\()\s*"
WRAP = r"(?:(?:time|env|sudo|nohup|npx|pnpx|bunx|uv\s+run|poetry\s+run|pipenv\s+run|python3?\s+-m)\s+(?:\w+=\S+\s+)*)*"
TOOL = (r"(?:pytest|py\.test|tox|nox|jest|vitest|make|ruff|mypy|eslint|tsc|tflint|shellcheck|bats|agent-ci|gradle|mvn"
  r"|(?:\./)?(?:gradlew|mvnw)|unittest|(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build|lint)|go\s+(?:test|build|vet)"
  r"|cargo\s+(?:test|build|clippy)|terraform\s+(?:plan|validate|fmt))(?![\w-])")
pat = re.compile(SEP + r"(?:\w+=\S+\s+)*" + WRAP + TOOL)
def classify(c):
    for m in re.finditer(r"(?:^|&&|\|\||;|\||\()\s*(?:bash|sh|zsh)\s+-c\s+([\x27\"])(.*?)\1", c):
        if classify(m.group(2)) == "tests": return "tests"
    plain = re.sub(r"\"(?:\\.|[^\"\\])*\"|\x27[^\x27]*\x27", chr(34)*2, c)
    return "tests" if pat.search(plain) else "shell"
kind = classify(cmd)
cwd = d.get("cwd") or ""
home = os.path.expanduser("~")
if cwd == home or cwd.startswith(home + "/"): cwd = "~" + cwd[len(home):]
sys.stdout.write("\0".join([kind, first, cwd, str(code), tail]))
')" || exit 0
  parts=("${(@0)fields}")
  kind=$parts[1] first=$parts[2] cwd=$parts[3] code=$parts[4] tail=$parts[5]
  [[ -n "$kind" ]] || exit 0
  T="${TC_TMUX:-$HOME/.local/bin/tmux}"
  info="$("$T" display -p -t "$TMUX_PANE" '#{session_name}'$'\t''#{window_name}'$'\t''#{?session_group,#{session_group},#{session_name}}')" || exit 0
  session="${info%%$'\t'*}" rest="${info#*$'\t'}"
  caller="${rest%%$'\t'*}" canon="${rest#*$'\t'}"
  caller="${caller#✦ }"
  wins="$("$T" list-windows -t "=$session" -F '#{window_name}')" || exit 0
  winarr=("${(@f)wins}")
  # feeds are written for dev sessions: the agents' window lives in <project>-bg (or, before migration, here)
  "$T" has-session -t "=$canon-bg" 2>/dev/null || (( ${winarr[(Ie)$kind]} )) || exit 0
  STATE="$TC_STATE_DIR"; mkdir -p "$STATE"
  log="$STATE/feed-$canon-$kind.log"
  if [[ -f "$log" ]] && (( $(wc -c < "$log") > 2097152 )); then
    tail -c 1048576 "$log" > "$log.tmp.$$" && mv "$log.tmp.$$" "$log"
  fi
  entry="── $(date +%H:%M:%S) · $caller · $cwd · exit $code · @$EPOCHSECONDS"$'\n'"\$ $first"
  [[ -n "$tail" ]] && entry+=$'\n'"$tail"
  entry+=$'\n'
  print -r -- "$entry" >> "$log"
} >/dev/null 2>&1
exit 0
