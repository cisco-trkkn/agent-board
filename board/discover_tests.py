"""Opportunity discovery: test-history and run-log signal collectors.

flaky_tests / slow_tests read the all.zsh history file; failed_runs reads the
project's run log. Each returns candidates in the shared shape
{signal, key, title, evidence[], first_seen, count}. Stdlib only.
"""
import hashlib
import json
import os
import re
import statistics
from datetime import datetime
from pathlib import Path

DAY = 86400
WINDOW = 30 * DAY
MAX_EVIDENCE = 20


def _date(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _valid(d):
    return (isinstance(d, dict) and isinstance(d.get("ts"), (int, float))
            and not isinstance(d.get("ts"), bool) and isinstance(d.get("jobs"), dict))


def load_history(path, now):
    """History lines inside the 30-day window; malformed lines are skipped."""
    try:
        text = Path(path).read_text()
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if _valid(d) and now - WINDOW <= d["ts"] <= now:
            out.append(d)
    return out


def _job_results(history):
    """{job: [(ts, root, head, dirty, full, rc, secs)]} sorted by ts."""
    jobs = {}
    for h in history:
        for name, val in h["jobs"].items():
            try:
                rc, secs = int(val[0]), float(val[1])
            except (TypeError, ValueError, IndexError):
                continue
            jobs.setdefault(name, []).append(
                (h["ts"], h.get("root") or "", h.get("head"), bool(h.get("dirty")),
                 bool(h.get("full")), rc, secs))
    for rows in jobs.values():
        rows.sort(key=lambda r: r[0])
    return jobs


def _ev(row):
    ts, root, head, _dirty, _full, rc, _secs = row
    text = f"{_date(ts)} {os.path.basename(root.rstrip('/'))} @{(head or '-')[:8]} rc={rc}"
    return {"text": text, "path": None, "line": None, "url": None}


def _cand(signal, key, title, rows_or_ev, count, first_ts):
    return {"signal": signal, "key": key, "title": title,
            "evidence": rows_or_ev[-MAX_EVIDENCE:], "first_seen": _date(first_ts),
            "count": count}


def _flips(rows):
    n = 0
    for a, b in zip(rows, rows[1:]):
        if (a[5] == 0) != (b[5] == 0):
            n += 1
    return n


def flaky_tests(history, now):
    out = []
    for name, rows in sorted(_job_results(history).items()):
        by_head = {}
        for r in rows:
            if r[2] and not r[3]:
                by_head.setdefault(r[2], set()).add(r[5] == 0)
        same_head = any(len(v) == 2 for v in by_head.values())
        by_root = {}
        for r in rows:
            by_root.setdefault(r[1], []).append(r)
        flipping = any(_flips(v) >= 2 for v in by_root.values())
        if not (same_head or flipping):
            continue
        fails = [r for r in rows if r[5] != 0]
        out.append(_cand("flaky_test", f"flaky_test:{name}", f"Flaky test: {name}",
                         [_ev(r) for r in fails], len(fails), fails[0][0]))
    return out


def slow_tests(history, now):
    full = {}
    for name, rows in _job_results(history).items():
        rows = [r for r in rows if r[4]]
        if rows:
            full[name] = rows
    current = {n: statistics.median(r[6] for r in rows[-3:]) for n, rows in full.items()}
    slowest = sorted(current, key=lambda n: (-current[n], n))[:5]
    out = []
    for name in sorted(slowest):
        rows = full[name]
        base_rows = [r[6] for r in rows if r[0] < now - WINDOW + 7 * DAY]
        if not base_rows:
            continue
        baseline = statistics.median(base_rows)
        cur = current[name]
        if baseline <= 0 or cur < 1.25 * baseline:
            continue
        last = rows[-3:]
        pct = round(100 * (cur - baseline) / baseline)
        out.append(_cand("slow_test", f"slow_test:{name}",
                         f"Slow test: {name} +{pct}%", [_ev(r) for r in last], pct,
                         last[0][0]))
    return out


_RC = re.compile(r"^rc=(\d+)$", re.M)


def _run_rc(rec):
    log = rec.get("log")
    if log:
        try:
            m = _RC.findall(Path(log).read_text(errors="replace"))
        except OSError:
            m = []
        if m:
            return int(m[-1])
    ex = rec.get("exit")
    return ex if isinstance(ex, int) and not isinstance(ex, bool) else None


def _real(p):
    return os.path.realpath(p) if isinstance(p, str) else None


def failed_runs(records_path, root, now):
    try:
        text = Path(records_path).read_text()
    except OSError:
        return []
    final = {}
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if (isinstance(d, dict) and d.get("exit") is not None and d.get("id") is not None
                and isinstance(d.get("ts"), (int, float)) and isinstance(d.get("cmd"), str)):
            final[d["id"]] = d
    top = os.path.realpath(root)
    runs = []
    for d in final.values():
        if _real(d.get("cwd")) != top or d["ts"] < now - WINDOW:
            continue
        rc = _run_rc(d)
        if rc is not None:
            runs.append((d["ts"], d["cmd"], rc, d))
    runs.sort(key=lambda r: r[0])
    by_cmd = {}
    for r in runs:
        by_cmd.setdefault(r[1], []).append(r)
    out = []
    for cmd, rs in sorted(by_cmd.items()):
        if rs[-1][2] == 0:
            continue
        fails = [r for r in rs if r[2] != 0]
        qualifying = [f for f in fails if f[0] <= now - DAY
                      and not any(g[2] == 0 and f[0] <= g[0] <= f[0] + DAY for g in rs)]
        if not qualifying:
            continue
        ev = [{"text": f"{_date(f[0])} rc={f[2]} {cmd[:80]}", "path": f[3].get("log"),
               "line": None, "url": None} for f in fails]
        key = "failed_run:" + hashlib.sha1(cmd.encode()).hexdigest()[:10]
        out.append(_cand("failed_run", key, f"Failing run: {cmd[:60]}", ev, len(fails),
                         fails[0][0]))
    return out
