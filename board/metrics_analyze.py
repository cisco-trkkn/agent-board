"""metrics analyze: trends, by_tier_model, flags and coverage over every project's runs.jsonl and tasks.jsonl.

analyze(projects, since_ts, now, tasks_log=None, source="args") -> dict is pure code over the two logs of each project
directory (<dir>/docs/superpowers/metrics/). It imports nothing from `metrics`. Numbers are rounded once, here (M-rounding):
$ to 2 decimals, ratios and rates to 4, medians of counts and seconds to 1. `stats` holds project names, never paths.
lookup(stats, "trends.median_usd_per_spec.current") resolves a stable key path; by_tier_model keys hold `|`, never `.`.
"""
import calendar
import json
import math
import statistics
import subprocess
import sys
import time
from pathlib import Path

METRICS_DIR = Path("docs/superpowers/metrics")
FAMILIES = ("haiku", "sonnet", "opus", "fable")
FRONTIER = ("fable", "opus")
UNDER_FIX_ROUNDS, UNDER_MIN_TASKS, UNDER_ESCALATION = 2, 5, 0.30
COSTLY_N = 10
# (trend key, run field, decimals): the specs_* counts are integers
MEDIANS = (("median_usd_per_spec", "usd", 2), ("median_lead_share", "lead_share", 4), ("median_fix_rounds_per_spec", "fix_rounds", 1),
           ("median_elapsed_s", "elapsed_s", 1), ("median_active_min", "active_min", 1),
           ("questions_per_spec", "questions", 1), ("rulings_per_spec", "rulings", 1))


def _epoch(iso):
    try:
        return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))
    except (TypeError, ValueError):
        return None


def _utc(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _read(p):
    out = []
    try:
        text = Path(p).read_text()
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def family(model):
    m = (model or "").lower()
    return next((f for f in FAMILIES if f in m), None)


def _model_key(t):
    """by_tier_model model part: `nomodel` when the record says no source named a model, else the family or `unknown`."""
    if t.get("model_source") == "none":
        return "nomodel"
    return family(t.get("model_used")) or "unknown"


def _nums(vals):
    return [v for v in vals if isinstance(v, (int, float)) and not isinstance(v, bool)]


def median(vals):
    v = _nums(vals)
    return statistics.median(v) if v else None


def p90(vals):
    v = sorted(_nums(vals))
    return v[math.ceil(0.9 * len(v)) - 1] if v else None


def _round(x, d):
    """Rounded to d decimals; a metric with decimals stays a float (a whole `0` would read as 0 decimals downstream)."""
    return round(x, d) if d == 0 else round(float(x), d)


def _r(x, d):
    return None if x is None else _round(x, d)


def _change(cur, prev, d):
    return _round(cur - prev, d) if cur is not None and prev is not None else None


def _trend(cur, prev, d):
    return {"current": _r(cur, d), "previous": _r(prev, d), "change": _change(cur, prev, d)}


def _load(projects, tasks_log):
    """[(name, runs {(batch, spec): last run line}, tasks {(batch, spec, task_id): last task line})]."""
    out = []
    for i, d in enumerate(projects):
        base = Path(d) / METRICS_DIR
        runs = {}
        for r in _read(base / "runs.jsonl"):
            if r.get("kind") == "run":
                runs[(r.get("batch"), r.get("spec"))] = r
        tasks = {}
        for t in _read(tasks_log if tasks_log and i == 0 else base / "tasks.jsonl"):
            tasks[(t.get("batch"), t.get("spec"), t.get("task_id"))] = t
        out.append((Path(d).resolve().name, runs, tasks))
    return out


def _in(run, lo, hi, closed):
    e = _epoch(run.get("ended_at"))
    return e is not None and e >= lo and (e <= hi if closed else e < hi)


def analyze(projects, since_ts, now, tasks_log=None, source="args"):
    prev_since = since_ts - (now - since_ts)
    loaded = _load(projects, tasks_log)
    cur_runs, prev_runs, cur_tasks = [], [], []   # runs as (project, run); tasks as (project, task)
    for name, runs, tasks in loaded:
        in_cur = set()
        for key, r in runs.items():
            if _in(r, since_ts, now, True):
                cur_runs.append((name, r))
                in_cur.add(key)
            elif _in(r, prev_since, since_ts, False):
                prev_runs.append((name, r))
        cur_tasks.extend((name, t) for (b, s, _), t in tasks.items() if (b, s) in in_cur)
    cur_tasks.sort(key=lambda p: (p[0], str(p[1].get("spec")), str(p[1].get("batch")), p[1].get("task_id") or 0))

    def field(rs, k):
        return [r.get(k) for _, r in rs]

    def count(rs, outcome):
        return sum(1 for _, r in rs if r.get("outcome") == outcome)

    def count_prefix(rs, prefix):
        return sum(1 for _, r in rs if str(r.get("outcome")).startswith(prefix))

    trends = {"specs_run": _trend(len(cur_runs), len(prev_runs), 0),
              "specs_merged": _trend(count(cur_runs, "merged"), count(prev_runs, "merged"), 0),
              "specs_mr": _trend(count_prefix(cur_runs, "mr"), count_prefix(prev_runs, "mr"), 0),
              "specs_failed": _trend(count(cur_runs, "failed"), count(prev_runs, "failed"), 0)}
    for key, f, d in MEDIANS:
        trends[key] = _trend(median(field(cur_runs, f)), median(field(prev_runs, f)), d)
        if key == "median_usd_per_spec":
            trends["p90_usd_per_spec"] = _trend(p90(field(cur_runs, "usd")), p90(field(prev_runs, "usd")), 2)
    trends = {k: trends[k] for k in ("specs_run", "specs_merged", "specs_mr", "specs_failed", "median_usd_per_spec", "p90_usd_per_spec",
                                     "median_lead_share", "median_fix_rounds_per_spec", "median_elapsed_s", "median_active_min",
                                     "questions_per_spec", "rulings_per_spec")}

    groups = {}
    for name, t in cur_tasks:
        groups.setdefault(f"{t.get('tier') or 'unspecified'}|{_model_key(t)}", []).append(t)
    by_tier_model, raw_rates = {}, {}
    for key in sorted(groups):
        ts = groups[key]
        n = len(ts)
        esc = round(sum(1 for t in ts if t.get("escalated")) / n, 4)
        fixes = median([t.get("fix_rounds") for t in ts])
        raw_rates[key] = (n, fixes, esc)
        sev = {s: round(sum((t.get("findings") or {}).get(s) or 0 for t in ts) / n, 4) for s in ("critical", "important", "minor")}
        by_tier_model[key] = {"tasks": n, "median_usd": _r(median([t.get("usd") for t in ts]), 2),
                              "median_tokens": _r(median([t.get("tokens") for t in ts]), 1), "median_fix_rounds": _r(fixes, 1),
                              "findings_per_task": sev, "escalation_rate": esc,
                              "failure_rate": round(sum(1 for t in ts if t.get("outcome") != "complete") / n, 4)}

    overpowered = [{"project": p, "spec": t.get("spec"), "task_id": t.get("task_id"), "subject": t.get("subject"),
                    "model_used": t.get("model_used"), "tier": t.get("tier")}
                   for p, t in cur_tasks
                   if family(t.get("model_used")) in FRONTIER and t.get("code_in_steps") and t.get("fix_rounds") == 0]

    underpowered = []
    for key, (n, fixes, esc) in raw_rates.items():
        why = []
        if n >= UNDER_MIN_TASKS and fixes is not None and fixes >= UNDER_FIX_ROUNDS:
            why.append(f"median fix rounds {fixes} over {n} tasks")
        if n >= UNDER_MIN_TASKS and esc >= UNDER_ESCALATION:
            why.append(f"escalation rate {esc}")
        if why:
            underpowered.append({"tier_model": key, "tasks": n, "median_fix_rounds": _r(fixes, 1), "escalation_rate": esc,
                                 "reason": "; ".join(why)})

    priced = [(p, t) for p, t in cur_tasks if isinstance(t.get("usd"), (int, float))]
    priced.sort(key=lambda pt: (-pt[1]["usd"], pt[0], str(pt[1].get("spec")), pt[1].get("task_id") or 0))
    costly = [{"project": p, "spec": t.get("spec"), "task_id": t.get("task_id"), "subject": t.get("subject"), "usd": _round(t["usd"], 2)}
              for p, t in priced[:COSTLY_N]]

    def per_hour(r):
        u, a = r.get("usd"), r.get("active_min")
        return u / (a / 60) if isinstance(u, (int, float)) and isinstance(a, (int, float)) and a > 0 else None

    med_hour = median([per_hour(r) for _, r in cur_runs])
    handoffs = [{"project": p, "spec": r.get("spec"), "handoffs": r["handoffs"], "usd_per_active_hour": round(per_hour(r), 2),
                 "median_usd_per_active_hour": _r(med_hour, 2)}
                for p, r in cur_runs if isinstance(r.get("handoffs"), (int, float)) and r["handoffs"] > 0 and per_hour(r) is not None]

    def manifest(rs, k):
        return [(r.get("manifest") or {}).get(k) for _, r in rs]

    forecast = {"median_precision": _r(median(manifest(cur_runs, "precision")), 4),
                "median_recall": _r(median(manifest(cur_runs, "recall")), 4),
                "below_half": [{"project": p, "spec": r.get("spec"), "recall": _round(r["manifest"]["recall"], 4)}
                               for p, r in cur_runs
                               if isinstance((r.get("manifest") or {}).get("recall"), (int, float)) and r["manifest"]["recall"] < 0.5]}

    return {"window": {"since": _utc(since_ts), "until": _utc(now), "previous_since": _utc(prev_since)},
            "projects": [name for name, _, _ in loaded], "projects_source": source,
            "trends": trends, "by_tier_model": by_tier_model,
            "flags": {"overpowered": overpowered, "underpowered": underpowered, "costly_steps": costly,
                      "handoffs": handoffs, "forecast": forecast},
            "coverage": {"with_cost": len(priced), "tasks": len(cur_tasks)}}


def lookup(stats, path):
    """The value at a dotted key path; list steps are indexes. KeyError names the missing step."""
    cur = stats
    for step in path.split("."):
        if isinstance(cur, dict) and step in cur:
            cur = cur[step]
        elif isinstance(cur, list) and step.isdigit() and int(step) < len(cur):
            cur = cur[int(step)]
        else:
            raise KeyError(path)
    return cur


def overview_projects():
    """Project directories from `overview.py --json` (R4). Raises on any failure; the caller falls back to the repo alone."""
    p = subprocess.run([sys.executable, "-I", str(Path(__file__).resolve().parent / "overview.py"), "--json"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        raise RuntimeError("overview failed")
    paths = [d["path"] for d in json.loads(p.stdout)["projects"]]
    if not paths:
        raise RuntimeError("overview lists no projects")
    return paths
