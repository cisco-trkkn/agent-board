"""Folder listing and recent projects for the board's Open project dialog."""
import json
import os
import tempfile

from artifacts import state_dir

CAP = 500          # entries returned by one listing
RECENT_MAX = 10    # stored recent projects


def resolve(path):
    p = (path or "").strip() or "~"
    return os.path.realpath(os.path.expanduser(p))


def list_dirs(path="", prefix="", hidden=True):
    """Folders (never files) directly under path. Raises NotADirectoryError or PermissionError."""
    root = resolve(path)
    if not os.path.isdir(root):
        raise NotADirectoryError(f"not a folder: {path or '~'}")
    with os.scandir(root) as it:
        entries = sorted(it, key=lambda e: e.name)
    out = []
    for e in entries:
        n = e.name
        if prefix and not n.startswith(prefix):
            continue
        if not hidden and n.startswith("."):
            continue
        try:
            if not e.is_dir(follow_symlinks=True):
                continue
        except OSError:
            continue
        out.append({"name": n, "git": os.path.exists(os.path.join(root, n, ".git")), "hidden": n.startswith(".")})
    parent = None if root == "/" else os.path.dirname(root)
    return {"path": root, "parent": parent, "dirs": out[:CAP], "truncated": len(out) > CAP}


def _recent_file():
    return state_dir() / "recent-projects.json"


def _load():
    try:
        v = json.loads(_recent_file().read_text())
    except (OSError, ValueError):  # missing, unreadable or corrupt: treat as empty
        return []
    return [p for p in v if isinstance(p, str)] if isinstance(v, list) else []


def record_recent(path):
    p = resolve(path)
    items = [p] + [x for x in _load() if x != p]
    f = _recent_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=".recent-")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(items[:RECENT_MAX], fh)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def recent(open_paths=()):
    """Open sessions' paths first, then the stored list; no duplicates, no missing folders."""
    seen, out = set(), []
    for p in list(open_paths) + _load():
        if p and p not in seen and os.path.isdir(p):
            seen.add(p)
            out.append(p)
    return out
