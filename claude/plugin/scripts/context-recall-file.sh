#!/usr/bin/env bash
# PostToolUse (Read|Edit|Write|Grep|Glob): inject the archived context entries (${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.archive.md)
# whose `files:` cite the path the tool touched, so a teammate (its spawn prompt fires no UserPromptSubmit) gets recall too
# (spec: docs/superpowers/specs/2026-11-23-hardening-design.md, part c). The path: tool_input.file_path (Read, Edit, Write) or tool_input.path
# (Grep, Glob), resolved against cwd, repo-relative. An entry matches when it cites that path, or (for a file) a directory above it.
# Once per (session, path): <state dir>/context-recall/<session_id>.paths holds `path<TAB><rel>` and `entry<TAB><sha1>` lines, under flock;
# an entry already injected in this session is skipped. Output: at most 4096 bytes of whole entry lines, newest own date first.
# Same project resolution, kill switch (TC_CONTEXT=0) and silent failure as context-recall.sh. --scoped (the plugin registration) changes nothing.
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
import fcntl, hashlib, json, os, re, subprocess, sys
CAP = 4096
try:
    hook = json.loads(os.environ["HOOK_PAYLOAD"])
    sid, cwd, tool, ti = hook["session_id"], hook["cwd"], hook.get("tool_name"), hook.get("tool_input")
    if not (isinstance(sid, str) and isinstance(cwd, str) and isinstance(ti, dict)) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    arg = ti.get("file_path") if tool in ("Read", "Edit", "Write") else ti.get("path") if tool in ("Grep", "Glob") else None
    if not isinstance(arg, str) or not arg.strip():
        sys.exit(0)
    r = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        sys.exit(0)
    root = os.path.realpath(r.stdout.strip())
    full = os.path.realpath(arg if os.path.isabs(arg) else os.path.join(cwd, arg))
    if full == root or not full.startswith(root + os.sep):
        sys.exit(0)
    rel, is_dir = os.path.relpath(full, root), os.path.isdir(full)
    try:
        with open(sys.argv[1], "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        text = ""
    marker_dir = os.path.join(sys.argv[2], "context-recall")
    os.makedirs(marker_dir, exist_ok=True)
    keep = []
    with open(os.path.join(marker_dir, sid + ".paths"), "a+", encoding="utf-8") as mf:
        fcntl.flock(mf, fcntl.LOCK_EX)
        mf.seek(0)
        done = mf.read().splitlines()
        if "path\t" + rel in done:
            sys.exit(0)
        seen = {l.split("\t", 1)[1] for l in done if l.startswith("entry\t")}
        mf.write("path\t" + rel + "\n")
        def hit(p):
            p = os.path.normpath(p.strip())
            if not p or p == ".":
                return False
            return p == rel or (not is_dir and rel.startswith(p + "/"))
        entries = []
        for line in text.splitlines():
            m = re.match(r"^- .+ · (\d{4}-\d{2}-\d{2})(?: · archived \d{4}-\d{2}-\d{2})?(?: · stale: .+ gone)?$", line)
            if not m:
                continue
            g = re.search(r"\(files: ([^)]*)\)", line)
            sha = hashlib.sha1(line.encode()).hexdigest()
            if g and sha not in seen and any(hit(p) for p in g.group(1).split(",")):
                entries.append((m.group(1), line, sha))
        entries.sort(key=lambda e: e[0], reverse=True)        # stable: file order among equal dates
        used = 0
        for _, line, sha in entries:
            n = len(line.encode()) + 1
            if used + n > CAP:
                break
            keep.append(line); used += n
            mf.write("entry\t" + sha + "\n")
    if keep:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": f"Archived project context for {rel}:\n" + "\n".join(keep)}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
