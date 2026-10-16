#!/usr/bin/env python3
"""ideas: the per-project ideas inbox, ${TC_IDEAS_DIR:-~/.claude/ideas}/<project>.md.

Each idea is "- [ ] YYYY-MM-DD HH:MM · text" with detail as indented lines; [x] = taken up
(followed by "→ <spec>"), [-] = dropped. Ideas are never deleted. Every writer appends under an
exclusive lock on <file>.lock. Agents do not read this file while a plan is running.

  ideas.py add --project P [--detail D] -- TEXT
  ideas.py list --project P
"""
import argparse
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

LINE_RE = re.compile(r"^- \[( |x|-)\] (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) · (.*)$")
STATUS = {" ": "open", "x": "taken", "-": "dropped"}


def ideas_dir():
    return Path(os.environ.get("TC_IDEAS_DIR") or Path.home() / ".claude" / "ideas")


def ideas_path(project):
    if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", project or "") or project in (".", ".."):
        raise ValueError(f"bad project name {project!r}")
    return ideas_dir() / f"{project}.md"


def add(project, text, detail="", now=None):
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("empty idea")
    p = ideas_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    first = f"- [ ] {stamp} · {text}"
    entry = first + "\n" + "".join(f"  {l.strip()}\n" for l in str(detail).splitlines() if l.strip())
    with open(f"{p}.lock", "w") as lk:
        fcntl.lockf(lk, fcntl.LOCK_EX)
        new = not p.exists() or p.stat().st_size == 0
        with open(p, "a") as f:
            if new:
                f.write(f"# Ideas: {project}\n\n")
            f.write(entry)
    return first


def load(project):
    p = ideas_path(project)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        m = LINE_RE.match(line)
        if m:
            out.append({"status": STATUS[m[1]], "ts": m[2], "text": m[3], "detail": ""})
        elif out and line.startswith("  ") and line.strip():
            d = out[-1]["detail"]
            out[-1]["detail"] = f"{d}\n{line.strip()}" if d else line.strip()
    return out


def open_count(project):
    return sum(1 for i in load(project) if i["status"] == "open")


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-project ideas inbox")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--detail", default="")
    a.add_argument("text", nargs="+")
    ls = sub.add_parser("list")
    ls.add_argument("--project", required=True)
    args = ap.parse_args(argv)
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
