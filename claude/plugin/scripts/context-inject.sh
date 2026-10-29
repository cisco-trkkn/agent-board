#!/usr/bin/env bash
# SessionStart: inject the project's shared context file, ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md,
# as additionalContext (spec: docs/superpowers/specs/2026-10-28-shared-project-context-design.md). <project> is the ideas key:
# the pane's session group, else its session name, with a -bg suffix stripped when the session carries @tc_bg (the same rule
# as tmux-ctl's FEEDKEY). Cap 8 KB on the file part: over it, the file is cut at the end of the last whole entry that fits and
# a truncation note names the full path. No file, an empty one, no tmux pane, or any error: no output, exit 0 (the session
# always starts). The hook JSON on stdin (session_id, transcript_path, cwd, hook_event_name, source) is drained, not read.
# Kill switch: TC_CONTEXT=0. --scoped (the plugin registration) is accepted and changes nothing.
[[ "$TC_CONTEXT" == 0 ]] && { cat >/dev/null; exit 0; }
cat >/dev/null
[[ -n "$TMUX" && -n "$TMUX_PANE" ]] || exit 0
tmux_bin="${TC_TMUX:-$HOME/.local/bin/tmux}"; [[ -x "$tmux_bin" ]] || tmux_bin=tmux
sock="${TMUX%%,*}"
project=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{?session_group,#{session_group},#{session_name}}' 2>/dev/null) || exit 0
sess=$("$tmux_bin" -S "$sock" display -p -t "$TMUX_PANE" '#{session_name}' 2>/dev/null) || exit 0
[[ -n "$("$tmux_bin" -S "$sock" show-options -qv -t "=$sess:" @tc_bg 2>/dev/null)" ]] && project="${project%-bg}"
[[ "$project" =~ ^[A-Za-z0-9_-][A-Za-z0-9._-]*$ ]] || exit 0
dir="${TC_CONTEXT_DIR:-$HOME/.local/state/agent-board/context}"
python3 -I - "$dir/$project.md" <<'PY' 2>/dev/null || exit 0
import json, sys
CAP = 8192
PREFACE = "Shared project context, curated by the lead; propose additions as 'Context learned' in your report."
try:
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    if not data.strip():
        sys.exit(0)
    body = data.decode("utf-8", "replace")
    if len(data) > CAP:
        lines = body.splitlines(keepends=True)
        keep, used, start = len(lines), 0, 0      # start: where the entry or heading that holds the current line began
        for i, line in enumerate(lines):
            if line.startswith(("- ", "## ")):
                start = i
            used += len(line.encode())
            if used > CAP:
                keep = start
                break
        body = "".join(lines[:keep]).rstrip("\n") + "\n… truncated, full file at " + path + "\n"
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": PREFACE + "\n\n" + body}}))
except SystemExit:
    raise
except Exception:
    sys.exit(0)
PY
exit 0
