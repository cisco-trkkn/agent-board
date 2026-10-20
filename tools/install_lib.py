#!/usr/bin/env python3
"""install_lib: "remove what the old global agent-board install added", used only by `install.sh --migrate`.

  install_lib.py settings FILE [--team] [--dry-run] CMD...   drop hook entries whose command is one of CMD (prints each)
  install_lib.py tmux FILE [--dry-run]                    drop the agent-board hook and binding lines (prints each)
  install_lib.py refs FILE NAME...                        lines that would stay in FILE but call ~/.local/bin/NAME
                                                          (prints "NAME<TAB>line"); migrate keeps those links

Both leave the file alone (not even rewritten) when nothing matches, and write through a temp file + os.replace.
"""
import json
import os
import re
import sys
import tempfile
from pathlib import Path

TEAM_ENV = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# Lines the old global install put in ~/.tmux.conf, matched by the tool they call (not whole-line equality).
# config/tmux.conf carries the same hooks and bindings for the dedicated server.
TMUX_PATTERNS = [
    r"^\s*set-hook\b.*\btmux-teammate-window\b",
    r"^\s*set-hook\b.*\btmux-session-closed\b",
    r"^\s*bind(-key)?\s.*\btmux-agent-cleanup\b",
    r"^\s*bind(-key)?\s.*\btmux-jump\b",
    r"^\s*bind(-key)?\s.*\bDEV_CLIENT=.*[/\s]dev(\s|'|\"|$)",
]


class NotCanonical(ValueError):
    """The file parses but would not survive a rewrite byte for byte; `entries` are what to remove by hand."""
    def __init__(self, message, entries):
        super().__init__(message)
        self.entries = entries


def _pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise _Dup()
    return dict(pairs)


class _Dup(Exception):
    pass


def _write(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, path.stat().st_mode & 0o7777)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _indent(text):
    m = re.search(r"^( +|\t)\"", text, re.M)
    return m.group(1) if m else 2


def strip_settings(path, commands, team=False, dry=False):
    """Drop hook entries whose `command` is in commands (empty groups and events go too); with team=True also
    env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS and teammateMode. Returns what was removed."""
    path = Path(path)
    if not path.exists():
        return []
    text = path.read_text()
    data = json.loads(text)          # bad JSON: ValueError, file untouched
    if not isinstance(data, dict):
        raise ValueError("settings.json is not a JSON object")
    commands, removed = set(commands), []
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = hooks[event]
            if not isinstance(groups, list):
                continue
            kept_groups = []
            for g in groups:
                hs = g.get("hooks") if isinstance(g, dict) else None
                if not isinstance(hs, list):
                    kept_groups.append(g)
                    continue
                kept = [h for h in hs if not (isinstance(h, dict) and h.get("command") in commands)]
                removed += [h["command"] for h in hs if isinstance(h, dict) and h.get("command") in commands]
                if kept:
                    g["hooks"] = kept
                    kept_groups.append(g)
                elif not hs:
                    kept_groups.append(g)       # was already empty: not ours to drop
            if kept_groups:
                hooks[event] = kept_groups
            elif groups:
                del hooks[event]
        if not hooks and removed:
            del data["hooks"]
    if team:
        env = data.get("env")
        if isinstance(env, dict) and TEAM_ENV in env:
            del env[TEAM_ENV]
            removed.append(f"env.{TEAM_ENV}")
            if not env:
                del data["env"]
        if "teammateMode" in data:
            del data["teammateMode"]
            removed.append("teammateMode")
    if removed:
        nl = "\n" if text.endswith("\n") else ""
        indent = _indent(text)
        try:
            canonical = json.dumps(json.loads(text, object_pairs_hook=_pairs), indent=indent, ensure_ascii=False) + nl == text
        except _Dup:
            canonical = False
        if not canonical:
            raise NotCanonical(f"{path.name} is not laid out the way json.dumps writes it (or has duplicate keys), "
                               "so it is left untouched", removed)
        if not dry:
            _write(path, json.dumps(data, indent=indent, ensure_ascii=False) + nl)
    return removed


def strip_tmux(path, patterns=TMUX_PATTERNS, dry=False):
    """Drop the (non-comment) lines matching any pattern; returns them."""
    path = Path(path)
    if not path.exists():
        return []
    rx = [re.compile(p) for p in patterns]
    keep, removed = [], []
    for line in path.read_text().splitlines(keepends=True):
        body = line.rstrip("\n")
        if not body.lstrip().startswith("#") and any(r.search(body) for r in rx):
            removed.append(body)
        else:
            keep.append(line)
    if removed and not dry:
        _write(path, "".join(keep))
    return removed


def remaining_refs(path, names, patterns=TMUX_PATTERNS):
    """(name, line) for each non-comment line of path that survives strip_tmux but calls ~/.local/bin/<name>
    (as ~, $HOME, ${HOME} or the absolute home). Migrate removes those links, so it keeps the ones named here."""
    path = Path(path)
    if not path.exists() or not names:
        return []
    home = re.escape(os.path.expanduser("~").rstrip("/"))
    rx = [(n, re.compile(rf"(?:~|\$HOME|\$\{{HOME\}}|{home})/\.local/bin/{re.escape(n)}(?![\w.-])")) for n in names]
    strip = [re.compile(p) for p in patterns]
    found = []
    for line in path.read_text().splitlines():
        if line.lstrip().startswith("#") or any(r.search(line) for r in strip):
            continue
        found += [(n, line) for n, r in rx if r.search(line)]
    return found


def main(argv):
    try:
        if len(argv) >= 3 and argv[0] == "settings":
            rest = argv[2:]
            flags = [a for a in rest if a in ("--team", "--dry-run")]
            gone = strip_settings(argv[1], [a for a in rest if a not in flags], team="--team" in flags,
                                  dry="--dry-run" in flags)
        elif argv[0] == "refs" and len(argv) >= 3:
            for n, line in remaining_refs(argv[1], argv[2:]):
                print(f"{n}\t{line}")
            return 0
        elif argv[0] == "tmux" and len(argv) in (2, 3):
            gone = strip_tmux(argv[1], dry="--dry-run" in argv[2:])
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except NotCanonical as e:
        print(f"install_lib: {e}", file=sys.stderr)
        for g in e.entries:
            print(f"MANUAL {g}")
        return 3
    except (OSError, ValueError) as e:
        print(f"install_lib: {e}", file=sys.stderr)
        return 1
    for g in gone:
        print(g)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
