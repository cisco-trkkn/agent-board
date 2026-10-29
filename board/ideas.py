#!/usr/bin/env python3
"""ideas: the per-project ideas inbox, ${TC_IDEAS_DIR:-~/.local/state/agent-board/ideas}/<project>.md
(reads the old ~/.claude/ideas/<project>.md until the first write copies it across).

Each idea is "- [ ] YYYY-MM-DD HH:MM · text" with detail as indented lines; [x] = taken up
(followed by "→ <spec>"), [-] = dropped. Ideas are never deleted. Every writer appends under an
exclusive lock on <file>.lock. Agents do not read this file while a plan is running.
An idea pushed to GitLab carries " · gl#<iid>" before any " → …" suffix (see gitlab_sync.py).
The board can edit, drop/restore and move ideas; a move appends to the target and marks the source "[-] … → moved to <target>".

  ideas.py add --project P [--detail D] -- TEXT
  ideas.py list --project P
  ideas.py sync --project P [--dry-run]
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

LINE_RE = re.compile(r"^- \[( |x|-)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")
STATUS = {" ": "open", "x": "taken", "-": "dropped"}
MOVED_RE = re.compile(r" → moved to ([A-Za-z0-9_-][A-Za-z0-9._-]*)$")
ISSUE_RE = re.compile(r" · gl#(\d+)(?= → |$)")   # the GitLab issue token gitlab_sync.py writes


class Stale(ValueError):
    """The key no longer names exactly one idea: the file changed since it was loaded."""


def ideas_dir():
    return Path(os.environ.get("TC_IDEAS_DIR") or Path.home() / ".local" / "state" / "agent-board" / "ideas")


def _legacy_path(project):
    """The pre-install-refactor file; only consulted when TC_IDEAS_DIR is not set."""
    if os.environ.get("TC_IDEAS_DIR"):
        return None
    return Path.home() / ".claude" / "ideas" / f"{project}.md"


def _seed(p, project):
    """Under the lock: if the new file does not exist yet, copy the legacy one across (the original stays)."""
    old = _legacy_path(project)
    if old is not None and old.is_file() and not p.exists():
        tmp = p.with_name(f".{p.name}.seed")
        shutil.copyfile(old, tmp)
        os.replace(tmp, p)


def ideas_path(project):
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", project or "") or project in (".", ".."):
        raise ValueError(f"bad project name {project!r}")
    return ideas_dir() / f"{project}.md"


def _append(project, first, detail_lines):
    p = ideas_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = first + "\n" + "".join(f"  {l}\n" for l in detail_lines)
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        _seed(p, project)
        new = not p.exists() or p.stat().st_size == 0
        with open(p, "a") as f:
            if new:
                f.write(f"# Ideas: {project}\n\n")
            f.write(entry)


def _kick(project):
    """Start a background GitLab sync for a mapped project. Capture must never fail because of it."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))   # python3 -I implies -P
        import gitlab_sync
        gitlab_sync.kick(project)
    except Exception:
        pass


def _split_issue(text):
    """'a · gl#12 → b' -> ('a → b', 12); text without the token -> (text, None)."""
    m = ISSUE_RE.search(text)
    return (text[:m.start()] + text[m.end():], int(m[1])) if m else (text, None)


def _clean_detail(detail):
    return [l.strip() for l in str(detail).splitlines() if l.strip()]


def add(project, text, detail="", now=None):
    text = _split_issue(" ".join(str(text).split()))[0]   # a typed gl#N must not point at someone else's issue
    if not text:
        raise ValueError("empty idea")
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    first = f"- [ ] {stamp} · {text}"
    _append(project, first, _clean_detail(detail))
    _kick(project)
    return first


def _rewrite(project, key, change):
    """Under the lock, find the one idea whose key matches and replace it (first line + detail)
    with change(box, ts, raw_text, detail_lines) -> (first_line, detail_lines)."""
    p = ideas_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        _seed(p, project)
        lines = p.read_text().splitlines(keepends=True) if p.exists() else []
        hits = [i for i, l in enumerate(lines)
                if (m := LINE_RE.match(l.rstrip("\n"))) and f"{m[2]} · {m[3]}" == key]
        if len(hits) != 1:
            raise Stale("the idea changed since you loaded it")
        i = j = hits[0]
        j += 1
        while j < len(lines) and lines[j].startswith("  ") and lines[j].strip():
            j += 1
        m = LINE_RE.match(lines[i].rstrip("\n"))
        first, detail = change(m[1], m[2], m[3], [l.strip() for l in lines[i + 1:j]])
        lines[i:j] = [first + "\n"] + [f"  {d}\n" for d in detail]
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text("".join(lines))
        os.replace(tmp, p)
        return first


def edit(project, key, text, detail=""):
    text = _split_issue(" ".join(str(text).split()))[0]
    if not text:
        raise ValueError("empty idea")
    new_detail = _clean_detail(detail)

    def change(box, ts, raw, old):
        if box != " ":
            raise ValueError("only open ideas can be edited")
        iid = _split_issue(raw)[1]
        return f"- [ ] {ts} · {text}" + (f" · gl#{iid}" if iid else ""), new_detail
    out = _rewrite(project, key, change)[6:]
    _kick(project)
    return out


def set_status(project, key, status):
    flip = {"dropped": (" ", "-"), "open": ("-", " ")}
    if status not in flip:
        raise ValueError(f"bad status {status!r}")
    want, to = flip[status]

    def change(box, ts, raw, detail):
        if box != want:
            raise ValueError(f"the idea is {STATUS[box]}")
        if to == " " and MOVED_RE.search(raw):
            raise ValueError("a moved idea cannot be restored here; restore it in the project it moved to")
        return f"- [{to}] {ts} · {raw}", detail
    out = _rewrite(project, key, change)
    _kick(project)
    return out


def move(project, key, target):
    ideas_path(target)   # validates the name
    if target == project:
        raise ValueError("the idea is already in that project")
    got = [i for i in load(project) if i["key"] == key]
    if len(got) != 1:
        raise Stale("the idea changed since you loaded it")
    idea = got[0]
    if idea["status"] != "open":
        raise ValueError("only open ideas can be moved")
    # append first: a failure before the source is marked leaves a duplicate, never a lost idea
    _append(target, f"- [ ] {idea['ts']} · {idea['text']}", idea["detail"].splitlines())

    def change(box, ts, raw, detail):
        if box != " ":
            raise Stale("the idea changed since you loaded it")
        return f"- [-] {ts} · {raw} → moved to {target}", detail
    out = _rewrite(project, key, change)
    _kick(project)
    _kick(target)
    return out


def set_issue(project, key, iid):
    """Record GitLab issue #iid on the idea: the token goes before a ' → …' suffix on a closed idea,
    at the end of an open one. Called by gitlab_sync only; it never triggers a sync."""
    def change(box, ts, raw, detail):
        have = _split_issue(raw)[1]
        if have is not None and have != iid:
            raise Stale(f"the idea already has issue #{have}")
        if have == iid:
            return f"- [{box}] {ts} · {raw}", detail
        cut = raw.rfind(" → ") if box != " " else -1
        raw = raw[:cut] + f" · gl#{iid}" + raw[cut:] if cut >= 0 else raw + f" · gl#{iid}"
        return f"- [{box}] {ts} · {raw}", detail
    return _rewrite(project, key, change)


def load(project):
    p = ideas_path(project)
    if not p.exists():
        old = _legacy_path(project)
        if old is None or not old.is_file():
            return []
        p = old
    out = []
    for line in p.read_text().splitlines():
        m = LINE_RE.match(line)
        if m:
            mv = MOVED_RE.search(m[3]) if m[1] == "-" else None
            text, iid = _split_issue(m[3][:mv.start()] if mv else m[3])
            out.append({"status": STATUS[m[1]], "ts": m[2], "text": text, "issue": iid,
                        "detail": "", "key": f"{m[2]} · {m[3]}", "moved_to": mv[1] if mv else ""})
        elif out and line.startswith("  ") and line.strip():
            d = out[-1]["detail"]
            out[-1]["detail"] = f"{d}\n{line.strip()}" if d else line.strip()
    return out


def open_count(project):
    return sum(1 for i in load(project) if i["status"] == "open")


def _sync(project, dry_run):
    """Push the project's ideas to GitLab. 0 ok or unmapped, 1 a push failed, 2 bad config."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # python3 -I implies -P
    import gitlab_sync   # lazy: gitlab_sync imports this module
    try:
        r = gitlab_sync.sync(project, dry_run=dry_run)
    except gitlab_sync.ConfigError as e:
        print(f"ideas: gitlab config: {e}", file=sys.stderr)
        return 2
    for line in r["actions"]:
        print(line)
    if r["error"]:
        print(f"ideas: {r['error']}", file=sys.stderr)
    return 0 if r["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-project ideas inbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--detail", default="")
    a.add_argument("text", nargs="+")
    ls = sub.add_parser("list")
    ls.add_argument("--project", required=True)
    sy = sub.add_parser("sync")
    sy.add_argument("--project", required=True)
    sy.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "sync":
        return _sync(args.project, args.dry_run)
    try:
        if args.cmd == "add":
            print(f"noted for later: {add(args.project, ' '.join(args.text), args.detail)}")
        else:
            print(json.dumps(load(args.project), indent=1))
        return 0
    except ValueError as e:
        print(f"ideas: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
