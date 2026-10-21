#!/usr/bin/env python3
"""Stop hook: after a long session, have Claude run /revise-claude-md once.

Fires at most once per session, when the transcript holds at least
CLAUDE_MD_REVISE_MIN_TOOL_USES tool calls (default 40). The revise command
shows proposed CLAUDE.md diffs and asks before editing, so nothing is written
without approval. Set CLAUDE_MD_REVISE_HOOK=0 to disable (e.g. headless runs).
"""

import json
import os
import re
import sys
from pathlib import Path

MARKER_DIR = Path.home() / ".claude" / "state" / "revise-claude-md"


def main() -> int:
    if os.environ.get("CLAUDE_MD_REVISE_HOOK", "1") == "0":
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if data.get("stop_hook_active"):
        return 0  # never chain a second block

    session = re.sub(r"[^A-Za-z0-9_-]", "", str(data.get("session_id", "")))
    transcript = data.get("transcript_path")
    if not session or not transcript:
        return 0
    marker = MARKER_DIR / session
    if marker.exists():
        return 0

    try:
        text = Path(transcript).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    threshold = int(os.environ.get("CLAUDE_MD_REVISE_MIN_TOOL_USES", "40"))
    if len(re.findall(r'"type":\s*"tool_use"', text)) < threshold:
        return 0

    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker.touch()
    if "revise-claude-md" in text:
        return 0  # already run by hand this session

    reason = (
        "Long session: before stopping, run the claude-md-management:revise-claude-md "
        "skill once to capture what this session taught (commands, gotchas, "
        "workflow quirks). Show the proposed diffs and ask the user before editing; "
        "if nothing is worth adding, say so in one line and stop."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
