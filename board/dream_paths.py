#!/usr/bin/env python3
"""dream_paths: where the nightly run keeps things (G1 of the memory-consolidation plan). Imports only context,
so `dream.py` and the revert/file code of Task 5 can share it."""
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import context  # noqa: E402

RUN_ID_RE = re.compile(r"^\d{8}-\d{4}$")


def run_id(now):
    return time.strftime("%Y%m%d-%H%M", time.localtime(now))


def id_time(run):
    """Epoch seconds of a run id (local time), or None when it is not one."""
    if not RUN_ID_RE.match(run or ""):
        return None
    return time.mktime(time.strptime(run, "%Y%m%d-%H%M"))


def project_dir(project):
    return context.context_dir() / "dream" / project


def run_dir(project, run):
    return project_dir(project) / run


def backups_dir():
    return context.context_dir() / "backups"


def backup_core(project, run):
    return backups_dir() / f"{project}.md.{run}"


def backup_archive(project, run):
    """An empty file means the archive did not exist before that run (a real archive is never empty)."""
    return backups_dir() / f"{project}.archive.md.{run}"


def dream_json(project):
    return context.context_dir() / f"{project}.dream.json"


def load(project):
    try:
        d = json.loads(dream_json(project).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(project, data):
    p = dream_json(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp, p)


def iso_utc(now):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def parse_iso(s):
    import calendar
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None
