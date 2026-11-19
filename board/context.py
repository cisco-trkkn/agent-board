#!/usr/bin/env python3
"""context: the per-project shared agent context, ${TC_CONTEXT_DIR:-~/.local/state/agent-board/context}/<project>.md
(spec: docs/superpowers/specs/2026-10-28-shared-project-context-design.md).

One curated Markdown file per project, read by every agent at session start (the plugin's context-inject.sh hook).
Layout, fixed section order:

  # <project>: shared agent context
  Last curated: YYYY-MM-DD

  ## Map
  - <fact> (files: path/a, path/b) · YYYY-MM-DD
  ## How to run
  ## Gotchas
  ## Decisions

One bullet per entry; the trailing date is when the entry was last checked. Only the lead writes (teammates propose
"Context learned" items in their reports). Every writer takes an exclusive lock on <file>.lock, like ideas.py; the lead's
pruning and rewording are ordinary edits of the file.

  context.py show --project P
  context.py path --project P
  context.py add  --project P --section "<Map|How to run|Gotchas|Decisions>" -- TEXT
  context.py search --project P -- WORD…    entries of the core and the archive containing every word

The nightly run condenses the core to CAP bytes and moves the rest to <project>.archive.md beside it (same format).
Writers wait up to 5 s for the lock, then give up with exit 2.
"""
import argparse
import contextlib
import fcntl
import os
import re
import sys
import time
from pathlib import Path

CAP = 8192   # bytes; the core above this is condensed by the nightly run
SECTIONS = ("Map", "How to run", "Gotchas", "Decisions")
DATED_RE = re.compile(r" · \d{4}-\d{2}-\d{2}$")
PROJECT_RE = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9._-]*")   # the same key rule as ideas.ideas_path


def context_dir():
    return Path(os.environ.get("TC_CONTEXT_DIR") or Path.home() / ".local" / "state" / "agent-board" / "context")


def context_path(project):
    if not PROJECT_RE.fullmatch(project or "") or project in (".", ".."):
        raise ValueError(f"bad project name {project!r}")
    return context_dir() / f"{project}.md"


def archive_path(project):
    return context_path(project).with_name(f"{project}.archive.md")


@contextlib.contextmanager
def locked(project, wait=5.0):
    """Exclusive fcntl.lockf on <file>.lock, polled every 0.1 s for up to `wait` seconds; ValueError when it stays held."""
    p = context_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{p}.lock", "w") as lk:
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.lockf(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise ValueError("locked by another writer (the nightly run?); retry in a moment")
                time.sleep(0.1)
        yield p


def entries(text):
    """[(section, line)] for each '- ' bullet in file order; section is the last '## ' heading ('' before any)."""
    out, sec = [], ""
    for l in text.splitlines():
        if l.startswith("## "):
            sec = l[3:].strip()
        elif l.startswith("- "):
            out.append((sec, l))
    return out


def search(project, words):
    """[(source, section, line)], core before archive, for entries containing every word (case-insensitive)."""
    ws = [w.lower() for w in words]
    ap = archive_path(project)
    out = []
    for source, text in (("core", show(project)), ("archive", ap.read_text() if ap.is_file() else "")):
        for sec, line in entries(text):
            low = line.lower()
            if all(w in low for w in ws):
                out.append((source, sec, line))
    return out


def _today(now=None):
    return time.strftime("%Y-%m-%d", time.localtime(now))


def skeleton(project, now=None):
    return (f"# {project}: shared agent context\nLast curated: {_today(now)}\n\n"
            + "\n".join(f"## {s}\n" for s in SECTIONS))


def show(project):
    p = context_path(project)
    return p.read_text() if p.is_file() else ""


def _insert(text, section, line, now=None):
    """Append `line` at the end of `## section` (before the next heading), and set Last curated to today."""
    if not text.endswith("\n"):   # a hand-edited file may lack the final newline; don't fuse lines
        text += "\n"
    lines = text.splitlines(keepends=True)
    heads = [i for i, l in enumerate(lines) if l.rstrip("\n") == f"## {section}"]
    if len(heads) != 1:
        raise ValueError(f"no single '## {section}' heading in the file; restore the four headings")
    i = heads[0] + 1
    end = i
    while end < len(lines) and not lines[end].startswith("## "):
        end += 1
    body = lines[i:end]
    while body and not body[-1].strip():   # trailing blank lines of the section
        body.pop()
    tail = [line + "\n"] + (["\n"] if end < len(lines) else [])
    lines[i:end] = body + tail
    out = "".join(lines)
    out, n = re.subn(r"^Last curated: .*$", f"Last curated: {_today(now)}", out, count=1, flags=re.M)
    return out


def add(project, section, entry, now=None):
    if section not in SECTIONS:
        raise ValueError(f"unknown section {section!r}; one of: {', '.join(SECTIONS)}")
    entry = " ".join(str(entry).split())
    if not entry:
        raise ValueError("empty entry")
    line = f"- {entry}" if DATED_RE.search(entry) else f"- {entry} · {_today(now)}"
    with locked(project) as p:
        text = p.read_text() if p.is_file() else ""
        if not text.strip():
            text = skeleton(project, now)
        new = _insert(text, section, line, now)
        tmp = p.with_name(f".{p.name}.tmp")
        tmp.write_text(new)
        os.replace(tmp, p)
    return line


def main(argv=None):
    ap = argparse.ArgumentParser(description="per-project shared agent context")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("show", "path"):
        sub.add_parser(name).add_argument("--project", required=True)
    a = sub.add_parser("add")
    a.add_argument("--project", required=True)
    a.add_argument("--section", required=True)
    a.add_argument("text", nargs="+")
    se = sub.add_parser("search")
    se.add_argument("--project", required=True)
    se.add_argument("words", nargs="+")
    args = ap.parse_args(argv)
    try:
        if args.cmd == "show":
            sys.stdout.write(show(args.project))
        elif args.cmd == "path":
            print(context_path(args.project))
        elif args.cmd == "search":
            rows = search(args.project, args.words)
            for source, sec, line in rows:
                print(f"[{source}] {sec}: {line}")
            if not rows:
                print("context: no entries match", file=sys.stderr)
        else:
            print(f"added under ## {args.section}: {add(args.project, args.section, ' '.join(args.text))}")
            size = context_path(args.project).stat().st_size
            if size > CAP:
                print(f"context: core over 8 KB ({size}), the nightly run will condense it")
        return 0
    except ValueError as e:
        print(f"context: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
