#!/usr/bin/env python3
"""Per-session and per-agent usage, lifetime and context figures.

usage: session_metrics.py --root R --repo P [--repo P2] --days N --out F

Output {"sessions": [...], "totals": {...}}. Scalar metrics are objects {"value", "source"}; an unavailable
value is null with a sibling "value_reason". Token dicts hold input/output/cache_read/cache_creation.
peak_context = max over main-agent requests of input + cache_read + cache_creation (measured).
Each agents[] entry also carries tokens, tokens_by_model and its own peak_context (measured); the session-level
peak_context stays main-only. Every token dict and totals carries "source": "measured".
orchestrator_share = main's tokens / all tokens, all four token fields summed (derived).
A teammate session (lines carrying agentName) is attributed to its team:<name> agent under its own session id.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcripts as T

FIELDS = ("input", "output", "cache_read", "cache_creation")


def _zero():
    return dict.fromkeys(FIELDS, 0)


def _add(acc, e):
    for k in FIELDS:
        acc[k] += e[k]


def _metric(value, source, reason):
    if value is None:
        return {"value": None, "value_reason": reason, "source": source}
    return {"value": value, "source": source}


def _tag(group):
    """Copy a {name: token dict} map, marking each token dict measured."""
    return {k: dict(v, source="measured") for k, v in group.items()}


def _kind(agent):
    return agent.split(":", 1)[0] if ":" in agent else agent


def compute(events):
    sessions = {}
    totals = {"tokens": _zero(), "by_agent_kind": {"main": _zero(), "sub": _zero(), "team": _zero()}, "by_model": {}}
    for e in events:
        s = sessions.setdefault(e["session"], {"by_model": {}, "by_agent": {}, "agents": {}, "turns": 0,
                                               "ts": [], "peak": None, "files": set()})
        ag = s["agents"].setdefault(e["agent"], {"agent": e["agent"], "first_ts": None, "last_ts": None, "requests": 0,
                                                 "tokens": _zero(), "by_model": {}, "peak": None})
        if e["ts"] is not None:
            s["ts"].append(e["ts"])
            ag["first_ts"] = e["ts"] if ag["first_ts"] is None else min(ag["first_ts"], e["ts"])
            ag["last_ts"] = e["ts"] if ag["last_ts"] is None else max(ag["last_ts"], e["ts"])
        if e["kind"] == "prompt":
            s["turns"] += 1
        elif e["kind"] == "usage":
            ag["requests"] += 1
            _add(ag["tokens"], e)
            _add(ag["by_model"].setdefault(e["model"], _zero()), e)
            actx = e["input"] + e["cache_read"] + e["cache_creation"]
            ag["peak"] = actx if ag["peak"] is None else max(ag["peak"], actx)
            _add(s["by_model"].setdefault(e["model"], _zero()), e)
            _add(s["by_agent"].setdefault(e["agent"], _zero()), e)
            _add(totals["tokens"], e)
            _add(totals["by_agent_kind"].setdefault(_kind(e["agent"]), _zero()), e)
            _add(totals["by_model"].setdefault(e["model"], _zero()), e)
            if e["agent"] == "main":
                ctx = e["input"] + e["cache_read"] + e["cache_creation"]
                s["peak"] = ctx if s["peak"] is None else max(s["peak"], ctx)
    out = []
    for sid, s in sorted(sessions.items()):
        all_tok = sum(sum(v.values()) for v in s["by_agent"].values())
        main_tok = sum(s["by_agent"].get("main", _zero()).values())
        span = (max(s["ts"]) - min(s["ts"])) if len(s["ts"]) >= 2 else None
        out.append({
            "session": sid,
            "source": "measured",
            "tokens_by_model": _tag(s["by_model"]),
            "tokens_by_agent": _tag(s["by_agent"]),
            "orchestrator_share": _metric(main_tok / all_tok if all_tok else None, "derived", "no usage events in session"),
            "peak_context": _metric(s["peak"], "measured", "no main-agent requests in session"),
            "turns": _metric(s["turns"], "measured", None),
            "wall_clock_s": _metric(span, "measured", "fewer than two timestamped events"),
            "agents": [{"agent": a["agent"], "first_ts": a["first_ts"], "last_ts": a["last_ts"], "requests": a["requests"],
                        "tokens": dict(a["tokens"], source="measured"), "tokens_by_model": _tag(a["by_model"]),
                        "peak_context": _metric(a["peak"], "measured", "agent made no requests in session"),
                        "source": "measured"}
                       for a in sorted(s["agents"].values(), key=lambda a: a["agent"])],
        })
    totals["sessions"] = {"value": len(out), "source": "measured"}
    totals["tokens"] = dict(totals["tokens"], source="measured")
    totals["by_agent_kind"] = _tag(totals["by_agent_kind"])
    totals["by_model"] = _tag(totals["by_model"])
    totals["source"] = "measured"
    return {"sessions": out, "totals": totals}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/.claude/projects"))
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = compute(T.iter_events(a.root, a.repo, a.days))
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(res, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
