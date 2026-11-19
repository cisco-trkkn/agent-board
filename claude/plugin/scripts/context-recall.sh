#!/usr/bin/env bash
# UserPromptSubmit: at a session's first prompt, inject the archived context entries (${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.archive.md)
# whose `files:` paths match the repo paths the prompt names (spec: docs/superpowers/specs/2026-11-12-memory-consolidation-design.md, G13).
# <project> is the ideas key, as in context-inject.sh. Once per session_id: a marker <state dir>/context-recall/<session_id> is written at the first
# prompt, whether or not anything matched. Output: at most 4096 bytes of whole entry lines, newest own date first. Any error, no match, no archive,
# no tmux pane, a cwd outside a git repo: no output, exit 0. Kill switch: TC_CONTEXT=0. --scoped (the plugin registration) changes nothing.
[[ "$TC_CONTEXT" == 0 ]] && { cat >/dev/null; exit 0; }
payload=$(cat)
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
tmux_bin="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$tmux_bin" ]] || tmux_bin=tmux
sock="${TMUX%%,*}"
project=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null) || exit 0
sess=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null) || exit 0
[[ -n "$("$tmux_bin" -S "$sock" show-options -qv -t "=$sess:" @tc_bg 2>/dev/null)" ]] && project="${project%-bg}"
[[ "$project" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] || exit 0
dir="${TC_CONTEXT_DIR:-$HOME/.local/state/agent-board/context}"
state="${TC_STATE:-${TMPDIR:-/tmp}/tmux-ctl-$(id -u)}"
HOOK_PAYLOAD="$payload" python3 -I - "$dir/$project.archive.md" "$state" <<'PY' 2>/dev/null || exit 0
import json, os, re, subprocess, sys
CAP = 4096
HEAD = "Archived project context matching the files in your task:"
try:
    hook = json.loads(os.environ["HOOK_PAYLOAD"])
    prompt, sid, cwd = hook["prompt"], hook["session_id"], hook["cwd"]
    if not (isinstance(prompt, str) and isinstance(sid, str) and isinstance(cwd, str)):
        sys.exit(0)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    marker_dir = os.path.join(sys.argv[2], "context-recall")
    marker = os.path.join(marker_dir, sid)
    if os.path.exists(marker):
        sys.exit(0)
    os.makedirs(marker_dir, exist_ok=True)
    open(marker, "w").close()
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(0)
    root = os.path.realpath(r.stdout.strip())
    paths = set()
    for tok in prompt.split():
        tok = tok.strip("\"'`[]()<>")
        tok = re.sub(r"[.,;:)]+$", "", tok)
        tok = re.sub(r":\d+$", "", tok).strip("\"'`[]()<>")
        tok = re.sub(r"[.,;:)]+$", "", tok)
        if not tok or ("/" not in tok and "." not in tok):
            continue
        full = tok if os.path.isabs(tok) else os.path.join(root, tok)
        full = os.path.realpath(full)
        if full == root or not full.startswith(root + os.sep) or not os.path.exists(full):
            continue
        rel = os.path.relpath(full, root)
        paths.add((rel, os.path.isdir(full)))
    if not paths:
        sys.exit(0)
    with open(sys.argv[1], "rb") as f:
        text = f.read().decode("utf-8", "replace")
    files = {p for p, d in paths if not d}
    dirs = {p for p, d in paths if d}
    parents = {os.path.dirname(p) for p in files} - {""}
    def hit(path):
        path = os.path.normpath(path.strip())
        if not path or path == ".":
            return False
        if path in files or path in dirs:
            return True
        par = os.path.dirname(path)
        if par and par in parents:
            return True
        return any(path.startswith(d + "/") for d in dirs)
    entries = []
    for line in text.splitlines():
        m = re.match(r"^- .+ · (\d{4}-\d{2}-\d{2})(?: · archived \d{4}-\d{2}-\d{2})?(?: · stale: .+ gone)?$", line)
        if not m:
            continue
        g = re.search(r"\(files: ([^)]*)\)", line)
        if g and any(hit(p) for p in g.group(1).split(",")):
            entries.append((m.group(1), line))
    entries.sort(key=lambda e: e[0], reverse=True)        # stable: file order among equal dates
    keep, used = [], 0
    for _, line in entries:
        n = len(line.encode()) + 1
        if used + n > CAP:
            break
        keep.append(line); used += n
    if keep:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": HEAD + "\n" + "\n".join(keep)}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
