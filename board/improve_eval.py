"""improve_eval: the improve loop's tick (spec 2026-11-16 §2). Order: start (its event seq is the tick id, passed to every
insert for the retire cap) -> adapters -> observe -> evaluate trials -> evaluate outcomes -> pick -> digest, one `improve_step`
event `{step, counts, tick}` each. Trials are judged by metrics.compare_halves; the guardrail breach check and outcomes by
metrics.compare_to_baseline (rulings A12, A11: no engine-run record is `too early`, never a transition).
Later tasks plug in through `hooks`, a dict of optional callables (an absent one is skipped; see load_hooks):
  apply(store, pid)            Task 10, after a trial is kept
  card(kind, payload)          Task 12: kind awaiting_you | breach | achieved
  pick(store, runs, tick_id)   Task 9, returns a counts dict
  digest(store, tick_id)       Task 12, returns a counts dict
The outcome file is protected: it is never written; `achieved` is one improve_outcome event and one card call.
Protected (docs/superpowers/improve/protected.txt). Test: tests/test_improve_eval.py."""
import importlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import improve_adapters  # noqa: E402
import improve_trials  # noqa: E402
import metrics  # noqa: E402

SIGNAL = "tokens_per_merged_task"
GUARDRAILS = ("failed_specs", "red_after_merge", "final_review_crit_imp_per_spec")
E1_METRICS = ("fix_rounds_per_task", "bounces_per_task")
NO_SIGNAL_AT = 15
HOOK_MODULES = (("apply", "improve_apply", "apply"), ("pick", "improve_pick", "pick"),
                ("digest", "improve_digest", "digest"), ("card", "improve_cards", "card"))


def load_hooks():
    """The hooks whose module exists now; the rest of the loop is not written yet and is skipped."""
    out = {}
    for key, mod, fn in HOOK_MODULES:
        try:
            out[key] = getattr(importlib.import_module(mod), fn)
        except (ImportError, AttributeError):
            pass
    return out


def _iso(ts):
    return metrics.utc(ts) if ts else None


def _engine(runs):
    return [r for r in runs if r.get("budget") is not None]


def _event(store, kind, detail, spec=None):
    c = store._conn()
    try:
        cur = c.execute("INSERT INTO events(ts, spec, job, kind, detail) VALUES (?, ?, NULL, ?, ?)",
                        (store.now(), spec, kind, json.dumps(detail)))
        return cur.lastrowid
    finally:
        c.close()


def _events(store, kind):
    c = store._conn()
    try:
        return [(r["seq"], r["ts"], json.loads(r["detail"])) for r in c.execute("SELECT seq, ts, detail FROM events WHERE kind = ? ORDER BY seq", (kind,))]
    finally:
        c.close()


def last_tick_ts(store):
    """Time of the most recent tick's start event, or None."""
    starts = [ts for _, ts, d in _events(store, "improve_step") if d.get("step") == "start"]
    return starts[-1] if starts else None


def _fmt(v):
    return "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def _line(name, v):
    if v["verdict"] == "too early" and v.get("index") is None and name not in GUARDRAILS:
        return f"{name} too early ({v['n_trial']}/{v['n_control']} specs)"
    extra = f" index {_fmt(v['index'])}" if v.get("index") is not None else f" {v['trial_value']} vs {v['control_value']}"
    return f"{name} {v['verdict']}{extra} ({v['n_trial']}/{v['n_control']} specs)"


# ---- trials ------------------------------------------------------------------------------------------------------

def _halves(runs, row):
    pid = row["id"]
    eng = _engine(runs)
    trial = [r for r in eng if pid in (r.get("variants") or [])]
    since = _iso(row["trial_started_at"]) or ""
    ctl = [r for r in eng if pid not in (r.get("variants") or []) and not improve_trials.in_trial(r.get("spec") or "", pid)
           and (r.get("ended_at") or "") >= since]
    return trial, ctl


def _blame(store, trial, pid):
    specs = {r.get("spec") for r in trial}
    pat = re.compile(r"Trial " + re.escape(pid) + r"\b")
    c = store._conn()
    try:
        for r in c.execute("SELECT seq, spec, kind, detail FROM events ORDER BY seq"):
            if r["spec"] in specs and (r["kind"] == "ruling" or "finding" in r["kind"]) and pat.search(r["detail"] or ""):
                return r["seq"]
    finally:
        c.close()
    return None


def _tokens(rs):
    return sum((r.get("tokens") or {}).get("total") or 0 for r in rs)


def _breach(runs, configs, last_tick):
    since = _iso(last_tick)
    for m in GUARDRAILS:
        v = metrics.compare_to_baseline(runs, configs, m, since=since)
        if v["verdict"] == "worse":
            return m, v
    return None


def _kept_since(store, last_tick):
    return [r["id"] for r in store.list("kept") if last_tick is None or r["updated_at"] >= last_tick]


def _decide(store, row, trial, ctl):
    """(target state, reason) or None to continue."""
    sig = metrics.compare_halves(trial, ctl, SIGNAL)
    checks = [(m, metrics.compare_halves(trial, ctl, m)) for m in GUARDRAILS]
    if row["shrinks_reads"]:
        checks += [(m, metrics.compare_halves(trial, ctl, m)) for m in E1_METRICS]
    lines = [_line(SIGNAL, sig)] + [_line(m, v) for m, v in checks]
    numbers = "; ".join(lines)
    bad = [m for m, v in checks if v["verdict"] == "worse"]
    low = row["class"] == "low"
    if sig["verdict"] == "too early" and not bad:
        if len(trial) < NO_SIGNAL_AT:
            return None
        return ("reverted" if low else "awaiting_you"), "no signal" if low else f"no signal; {numbers}"
    if not low:
        return "awaiting_you", numbers
    if bad:
        return "reverted", f"guardrail worse: {', '.join(bad)}; {numbers}"
    if sig["verdict"] == "worse":
        return "reverted", f"signal worse; {numbers}"
    return "kept", numbers


def evaluate_trials(store, runs, now, configs=None, last_tick=None, hooks=None):
    """Judge every `trial` proposal. Returns counts {evaluated, kept, reverted, awaiting_you, too_early, breach}."""
    hooks = hooks if hooks is not None else load_hooks()
    counts = {"evaluated": 0, "kept": 0, "reverted": 0, "awaiting_you": 0, "too_early": 0, "breach": 0}
    trials = store.list("trial")
    if not _engine(runs):   # ruling A11: nothing to judge by
        counts["too_early"] = len(trials)
        return counts
    hit = _breach(runs, configs or {}, last_tick)
    if hit:
        counts["breach"] = 1
        kept = _kept_since(store, last_tick)
        for row in trials:
            store.transition(row["id"], "reverted", "guardrail breach")
            counts["reverted"] += 1
        if hooks.get("card"):
            hooks["card"]("breach", {"metric": hit[0], "numbers": _line(hit[0], hit[1]), "kept": kept})
        return counts
    for row in trials:
        pid = row["id"]
        trial, ctl = _halves(runs, row)
        if not trial:
            counts["too_early"] += 1
            continue
        seq = _blame(store, trial, pid)
        if seq is not None:
            store.transition(pid, "reverted", f"variant blamed: {seq}")
            counts["reverted"] += 1
            continue
        if ctl and _tokens(trial) > 2 * (_tokens(ctl) / len(ctl)) * (row["trial_len"] or 5):
            store.transition(pid, "reverted", "over budget")
            counts["reverted"] += 1
            continue
        if len(trial) < (row["trial_len"] or 5):
            counts["too_early"] += 1
            continue
        counts["evaluated"] += 1
        d = _decide(store, row, trial, ctl)
        if d is None:
            counts["too_early"] += 1
            continue
        to, reason = d
        store.transition(pid, to, reason)
        counts[to] += 1
        if to == "kept" and hooks.get("apply"):
            hooks["apply"](store, pid)
        if to == "awaiting_you" and hooks.get("card"):
            hooks["card"]("awaiting_you", {"id": pid, "reason": reason})
    return counts


# ---- outcomes ----------------------------------------------------------------------------------------------------

def first_commit(path):
    """ISO time of the first commit that added `path`, or None (not in git, no history)."""
    p = Path(path)
    r = subprocess.run(["git", "log", "--diff-filter=A", "--format=%aI", "--", p.name], cwd=p.parent, capture_output=True, text=True)
    lines = r.stdout.split() if r.returncode == 0 else []
    if not lines:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_parse_iso(lines[-1])))


def _parse_iso(s):
    import calendar
    from datetime import datetime
    return calendar.timegm(datetime.fromisoformat(s.replace("Z", "+00:00")).utctimetuple())


def outcome_status(runs, outcome, configs, since):
    """{signal, guardrails: {metric: verdict dict}, batches, verdict}: verdict is achieved-ready | worse | too early | on track."""
    sig = metrics.compare_to_baseline(runs, configs, SIGNAL, since=since)
    gs = {}
    for g in outcome.get("guardrails") or []:
        m = "tokens_per_merged_task" if g["metric"] == "tokens_per_task" else g["metric"]
        gs[m] = metrics.compare_to_baseline(runs, configs, m, since=since)
    batches = len({r.get("batch") for r in _engine(runs) if not since or (r.get("ended_at") or "") >= since})
    comp = outcome.get("completion") or {}
    need = 1 + (comp.get("change") if comp.get("change") is not None else -0.25)
    gworse = any(v["verdict"] == "worse" for v in gs.values())
    if sig["verdict"] == "too early" or any(v["verdict"] == "too early" and v["n_trial"] == 0 for v in gs.values()):
        verdict = "too early"
    elif sig["verdict"] == "worse" or gworse:
        verdict = "worse"
    elif sig["verdict"] == "better" and sig["index"] <= need and batches >= comp.get("min_queues", 2):
        verdict = "achieved-ready"
    else:
        verdict = "on track"
    return {"signal": sig, "guardrails": gs, "batches": batches, "verdict": verdict}


def evaluate_outcomes(store, runs, outcomes, last_tick, configs=None, hooks=None, since_of=None):
    """Evaluate each active outcome; report `achieved` once. Returns counts {evaluated, achieved}."""
    hooks = hooks if hooks is not None else load_hooks()
    since_of = since_of or (lambda o: first_commit(o["_path"]) if o.get("_path") else None)
    counts = {"evaluated": 0, "achieved": 0}
    done = {d.get("outcome") for _, _, d in _events(store, "improve_outcome") if d.get("status") == "achieved"}
    for o in outcomes:
        if o.get("state") != "active":
            continue
        counts["evaluated"] += 1
        if o["id"] in done or not _engine(runs):
            continue
        st = outcome_status(runs, o, configs or {}, since_of(o))
        if st["verdict"] == "achieved-ready":
            _event(store, "improve_outcome", {"outcome": o["id"], "status": "achieved", "index": st["signal"]["index"],
                                              "batches": st["batches"]})
            counts["achieved"] += 1
            if hooks.get("card"):
                hooks["card"]("achieved", {"id": o["id"], "index": st["signal"]["index"], "batches": st["batches"]})
    return counts


# ---- the tick ----------------------------------------------------------------------------------------------------

class _TickStore:
    """The store with the tick id on every insert, so adapters need no change (retire cap per tick)."""
    def __init__(self, store, tick):
        self._s, self._t = store, tick

    def insert(self, *a, **kw):
        kw.setdefault("tick", self._t)
        return self._s.insert(*a, **kw)

    def __getattr__(self, n):
        return getattr(self._s, n)


def tick(store, project, lines, outcomes, configs=None, hooks=None, adapters=None):
    """Run one tick over the raw run-log `lines` and the loaded `outcomes`. Returns {step: counts}."""
    hooks = hooks if hooks is not None else load_hooks()
    adapters = adapters or improve_adapters.run_all
    last = last_tick_ts(store)
    tid = _event(store, "improve_step", {"step": "start", "counts": {}})
    out = {}

    def step(name, counts):
        out[name] = counts
        _event(store, "improve_step", {"step": name, "counts": counts, "tick": tid})

    step("adapters", {k: v for k, v in (adapters(project, store=_TickStore(store, tid)) or {}).items()})
    runs = list(metrics.last_runs(lines).values())
    step("observe", {"records": len(runs), "engine_run": len(_engine(runs))})
    step("trials", evaluate_trials(store, runs, store.now(), configs=configs, last_tick=last, hooks=hooks))
    step("outcomes", evaluate_outcomes(store, runs, outcomes, last, configs=configs, hooks=hooks))
    if hooks.get("pick"):
        step("pick", hooks["pick"](store, runs, tid) or {})
    if hooks.get("digest"):
        step("digest", hooks["digest"](store, tid) or {})
    return out
