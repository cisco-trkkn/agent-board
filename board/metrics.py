#!/usr/bin/env python3
"""metrics: the queue run log (docs/superpowers/metrics/runs.jsonl) and its commands.

Run log: one JSON object per line, kind in batch|start|run|defect (analysis is reserved; readers ignore unknown
kinds). Append-only; readers take the last `run` per (batch, spec); a malformed line is skipped and counted.
Nothing private goes in a line: no session ids, prompts, agent names, absolute paths.

CLI: metrics.py [--repo DIR] <batch start|start|record|defect|report|compare|backfill|gate|status> ...
A failing command prints one line `metrics: <sub>: <reason>` to stderr and exits 1. `tmux-ctl metrics` calls this.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python3 -I does not add the script dir
import usage  # noqa: E402

METRICS_DIR = Path("docs/superpowers/metrics")
SUBS = ("batch start", "start", "record", "defect", "report", "compare", "backfill", "gate", "status")


class MetricsError(Exception):
    pass


def _git(repo, *args):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise MetricsError((p.stderr.strip().splitlines() or ["git failed"])[-1])
    return p.stdout.strip()


def repo_root(repo_arg=None):
    return Path(_git(repo_arg or ".", "rev-parse", "--show-toplevel"))


def log_path(repo):
    return Path(repo) / METRICS_DIR / "runs.jsonl"


def read_log(repo):
    """(lines, malformed_count): every parsed JSON object (unknown kinds kept), bad lines counted."""
    p = log_path(repo)
    if not p.exists():
        return [], 0
    out, bad = [], 0
    for raw in p.read_text().splitlines():
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except ValueError:
            bad += 1
            continue
        if isinstance(d, dict):
            out.append(d)
        else:
            bad += 1
    return out, bad


def append(repo, obj):
    p = log_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def last_runs(lines):
    """{(batch, spec): last `run` line}; other kinds are ignored."""
    out = {}
    for d in lines:
        if d.get("kind") == "run":
            out[(d.get("batch"), d.get("spec"))] = d
    return out


def _fence(text, tag):
    m = re.search(r"```" + re.escape(tag) + r"[ \t]*\n(.*?)\n```", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None


def _load(repo, sub, name, tag):
    p = Path(repo) / METRICS_DIR / sub / (name + ".md")
    if not p.exists():
        return None
    return _fence(p.read_text(), tag)


def load_config(repo, id):
    return _load(repo, "configs", id, "json:config")


def load_gate(repo, id):
    return _load(repo, "gates", id, "json:gate")


def utc(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def new_batch_id(repo, today):
    n = sum(1 for d in read_log(repo)[0] if d.get("kind") == "batch" and str(d.get("batch", "")).startswith(today + "-"))
    return f"{today}-{n + 1}"


def unit_key(batch_id, first_spec):
    return hashlib.sha256((batch_id + first_spec).encode()).hexdigest()


def assign(batch_id, specs, groups, configs, baseline):
    """{spec: config}. Units (a group, or a lone spec) sorted by hash, configs alternate starting with the baseline."""
    if len(configs) == 1:
        return {s: configs[0] for s in specs}
    grouped = {s for g in groups for s in g}
    units = [list(g) for g in groups] + [[s] for s in specs if s not in grouped]
    units.sort(key=lambda u: unit_key(batch_id, u[0]))
    cyc = [baseline] + [c for c in configs if c != baseline]
    out = {}
    for i, u in enumerate(units):
        for s in u:
            out[s] = cyc[i % len(cyc)]
    return out


def _baseline(repo, configs):
    flagged = [c for c in configs if (load_config(repo, c) or {}).get("baseline") is True]
    return flagged[0] if len(flagged) == 1 else configs[0]


def cmd_batch_start(repo, args):
    configs = args.config
    for c in configs:
        if load_config(repo, c) is None:
            raise MetricsError(f"unknown config {c}")
    groups = [[s.strip() for s in g.split(",") if s.strip()] for g in args.group]
    specs = args.specs
    for g in groups:
        for s in g:
            if s not in specs:
                raise MetricsError(f"group member {s} is not a listed spec")
    bid = new_batch_id(repo, time.strftime("%Y-%m-%d", time.gmtime()))
    asg = assign(bid, specs, groups, configs, _baseline(repo, configs))
    append(repo, {"kind": "batch", "batch": bid, "base": _git(repo, "rev-parse", "main"), "configs": configs,
                  "assignment": asg, "groups": groups, "at": utc()})
    print(bid)
    for s in specs:
        print(f"{s} {asg[s]}")


def cmd_start(repo, args):
    if not any(d.get("kind") == "batch" and d.get("batch") == args.batch for d in read_log(repo)[0]):
        raise MetricsError(f"unknown batch {args.batch}")
    now = time.time()
    pl = usage.plan_limits(usage.tap_entries(now, 10 ** 9))
    rec = {"kind": "start", "batch": args.batch, "spec": args.spec, "at": utc(now), "main": _git(repo, "rev-parse", "main")}
    if pl:
        rec["limits"] = {"five_hour": pl.get("five_hour"), "seven_day": pl.get("seven_day")}
    else:
        rec["limits"] = None
        rec["missing"] = ["limits"]
    append(repo, rec)


def cmd_defect(repo, args):
    append(repo, {"kind": "defect", "spec": args.spec, "what": args.what, "date": time.strftime("%Y-%m-%d", time.gmtime())})


def _parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="metrics", parents=[common])
    sp = ap.add_subparsers(dest="sub")
    b = sp.add_parser("batch", parents=[common]).add_subparsers(dest="bsub")
    bs = b.add_parser("start", parents=[common])
    bs.add_argument("--config", action="append", required=True)
    bs.add_argument("--group", action="append", default=[])
    bs.add_argument("specs", nargs="+")
    st = sp.add_parser("start", parents=[common])
    st.add_argument("spec")
    st.add_argument("--batch", required=True)
    df = sp.add_parser("defect", parents=[common])
    df.add_argument("spec")
    df.add_argument("what")
    for name in ("record", "report", "compare", "backfill", "gate", "status"):
        sp.add_parser(name, parents=[common], add_help=False).add_argument("rest", nargs="*")
    return ap


class _ArgError(Exception):
    pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    sub = "metrics"
    try:
        ap = _parser()
        ap.error = lambda msg: (_ for _ in ()).throw(_ArgError(msg))
        for a in ap._subparsers._group_actions[0].choices.values():
            a.error = ap.error
        try:
            args = ap.parse_args(argv)
        except _ArgError as e:
            first = next((a for a in argv if not a.startswith("-") and a in [s.split()[0] for s in SUBS]), "metrics")
            sub = first
            raise MetricsError(str(e).splitlines()[0])
        sub = args.sub or "metrics"
        if args.sub == "batch":
            sub = "batch start"
            if args.bsub != "start":
                raise MetricsError("usage: metrics batch start --config C [--group a,b] <spec>...")
        if not args.sub:
            raise MetricsError("usage: metrics <" + "|".join(SUBS) + "> ...")
        if args.sub in ("record", "report", "compare", "backfill", "gate", "status"):
            raise MetricsError("not implemented")
        repo = repo_root(getattr(args, "repo", None))
        {"batch": cmd_batch_start, "start": cmd_start, "defect": cmd_defect}[args.sub](repo, args)
        return 0
    except MetricsError as e:
        print(f"metrics: {sub}: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # never a traceback to the user
        print(f"metrics: {sub}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
