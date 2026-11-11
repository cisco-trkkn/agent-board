#!/usr/bin/env python3
"""telegram_cache.py clear — drop the telegram MCP failure Claude Code cached for 15 minutes.

Claude Code skips a plugin stdio MCP server whose last start failed less than 15 minutes ago, machine-wide, from
<config dir>/mcp-needs-auth-cache.json (key plugin:telegram:telegram). A lead that starts inside that window never dials
telegram. `clear` removes that one key (temp file in the same dir, then rename) and leaves the other keys alone.
A missing or unreadable file, bad JSON or a write error does nothing and exits 0: it must never fail a launch."""
import json
import os
import sys
import tempfile

KEY = "plugin:telegram:telegram"


def cache_path():
    return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"),
                        "mcp-needs-auth-cache.json")


def clear(path=None):
    """True when the key was removed."""
    path = path or cache_path()
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or KEY not in data:
            return False
        del data[KEY]
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".mcp-needs-auth-cache.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, separators=(",", ":"))
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return True
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    if sys.argv[1:] == ["clear"]:
        clear()
        sys.exit(0)
    print("usage: telegram_cache.py clear", file=sys.stderr)
    sys.exit(2)
