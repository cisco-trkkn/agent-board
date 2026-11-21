#!/usr/bin/env python3
"""taskwin_hist: what the tasks window reads besides the task list: spec titles, the queue's morning report, the
history journal (taskwin_state.append_journal), past SDD ledgers and queue reports. Every parse is cached by
(path, mtime); unreadable or unparseable files are skipped. Never raises on I/O.

entries(root, journal) -> [{"key", "day", "name", "spec", "outcome", "tasks": [task_done lines], "ledger"}],
newest day first; within a day, newest activity first.
"""
import json
import math
import re
import time
from pathlib import Path

LEDGERS = Path("docs/superpowers/ledgers")
REPORTS = Path("docs/superpowers/reports")
_PLAN = re.compile(r"^# SDD ledger — plan: (\S+)")
_SPEC = re.compile(r"\bSpec: (\S+?\.md)\b")
_BRANCH = re.compile(r"\bbranch (\S+)")
_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_TICK = re.compile(r"`([^`]+)`")
_cache = {}


def _cached(path, parse):
    try:
        m = Path(path).stat().st_mtime_ns
    except OSError:
        return None
    hit = _cache.get((str(path), parse.__name__))
    if hit and hit[0] == m:
        return hit[1]
    try:
        v = parse(Path(path))
    except (OSError, ValueError, UnicodeDecodeError):
        v = None
    _cache[(str(path), parse.__name__)] = (m, v)
    return v


def day_of(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def hm(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def _title(p):
    with open(p, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if line.startswith("# "):
                return line[2:].strip()
            if i > 40:
                break
    return None


def spec_title(root, spec):
    """First `# ` heading of the spec file (`#part` dropped), else None."""
    return _cached(Path(root) / spec.split("#")[0], _title) if spec else None


def _ledger(p):
    with open(p, encoding="utf-8") as f:
        head = [f.readline() for _ in range(6)]
    m = _PLAN.match(head[0])
    day = _DAY.match(p.parent.name)
    if not m or not day:
        return None
    rest = " ".join(head[1:])
    spec, branch = _SPEC.search(rest), _BRANCH.search(rest)
    plan = m.group(1)
    stem = Path(plan).name[:-3] if plan.endswith(".md") else Path(plan).name
    return {"plan": plan, "stem": stem, "spec": spec.group(1) if spec else "",
            "branch": branch.group(1) if branch else "", "day": day.group(1),
            "dir": str(LEDGERS / p.parent.name) + "/"}


def ledgers(root):
    out = []
    for p in sorted((Path(root) / LEDGERS).glob("*/progress.md")):
        v = _cached(p, _ledger)
        if v:
            out.append(v)
    return out


def _report(p):
    day = _DAY.match(p.name)
    rows, inside = [], False
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            inside = line.strip() == "## Outcomes"
            continue
        if not inside or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("#", "") or set(cells[0]) <= set("-: "):
            continue
        spec = _TICK.search(cells[1])
        led = _TICK.search(cells[3])
        rows.append({"spec": spec.group(1) if spec else (cells[1].split() or [""])[0],
                     "outcome": cells[2].replace("`", ""), "ledger": led.group(1).rstrip("/") + "/" if led else "",
                     "day": day.group(1) if day else ""})
    return rows


def report_rows(root):
    out = []
    for p in sorted((Path(root) / REPORTS).glob("*-queue.md")):
        out.extend(_cached(p, _report) or [])
    return out


def queue_report(root, queue_tasks):
    """docs/superpowers/reports/<first answeredAt date>-queue.md when it exists, else ''."""
    days = sorted(t["answeredAt"][:10] for t in queue_tasks if _DAY.match(t.get("answeredAt") or ""))
    if not days:
        return ""
    rel = REPORTS / f"{days[0]}-queue.md"
    return str(rel) if (Path(root) / rel).is_file() else ""


_STR_FIELDS = ("plan", "spec", "id", "subject", "outcome", "owner", "tier")


def _valid(e):
    """A journal line whose `at` is a real timestamp and whose text fields are strings when present."""
    at = e.get("at")
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        return False
    try:
        if not math.isfinite(at):
            return False
        time.localtime(at)
    except (OverflowError, OSError, ValueError):
        return False
    return all(isinstance(e[k], str) for k in _STR_FIELDS if k in e)


def _journal(p):
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and e.get("kind") in ("task_done", "queue_outcome") and _valid(e):
            out.append(e)
    return out


def read_journal(path):
    return (_cached(path, _journal) or []) if path else []


def entries(root, journal):
    """History rows from the journal, ledgers and queue reports (see the module docstring)."""
    lines = read_journal(journal)
    by_key, order = {}, []

    def get(key, name):
        if key not in by_key:
            by_key[key] = {"key": key, "day": "", "name": name, "spec": "", "outcome": "", "tasks": [],
                           "ledger": "", "_at": 0}
            order.append(key)
        return by_key[key]

    for led in ledgers(root):
        e = get("plan:" + led["stem"], led["stem"])
        e.update(spec=led["spec"], ledger=led["dir"], day=led["day"])
    for j in lines:
        if j["kind"] == "task_done":
            e = get("plan:" + (j.get("plan") or ""), j.get("plan") or "(no plan)")
            e["tasks"].append(j)
            if j["at"] >= e["_at"]:
                e["_at"], e["day"] = j["at"], day_of(j["at"])
    for j in lines:
        if j["kind"] != "queue_outcome":
            continue
        spec = str(j.get("spec") or "").split("#")[0]
        e = by_key.get("plan:" + j["plan"]) if j.get("plan") else None
        e = e or next((x for x in by_key.values() if spec and x["spec"].split("#")[0] == spec), None)
        if e is None:
            e = get("spec:" + str(j.get("spec")), str(j.get("spec")))
            e["spec"] = str(j.get("spec"))
        if j.get("outcome"):
            e["outcome"] = j["outcome"]
        if not e["day"]:
            e["day"], e["_at"] = day_of(j["at"]), j["at"]
    for r in report_rows(root):
        e = next((x for x in by_key.values() if r["ledger"] and x["ledger"] == r["ledger"]), None)
        e = e or next((x for x in by_key.values() if r["spec"] and x["spec"] == r["spec"]), None)
        if e is None:
            e = get("spec:" + r["spec"], r["spec"])
            e.update(spec=r["spec"], day=r["day"])
        if not e["outcome"]:
            e["outcome"] = r["outcome"]
    out = [by_key[k] for k in order]
    for e in out:
        e["tasks"].sort(key=lambda j: j["at"])
    out.sort(key=lambda e: (e["day"], e["_at"], e["name"]), reverse=True)
    for e in out:
        e.pop("_at", None)
    return out
