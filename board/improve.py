#!/usr/bin/env python3
"""improve: `tmux-ctl improve list|show|propose|variants|tick|revert|outcome status` (spec 2026-11-16 §5). Protected (docs/superpowers/improve/protected.txt).
Errors are one line `improve: <sub>: <reason>` on stderr, exit 1.
Rule R3 (ruling A20; for any Stop gate the loop adds later): it checks `stop_hook_active` and blocks at most once per stop,
never again for the same stop.
Tests: tests/test_improve_store.py, tests/test_improve_eval.py, tests/test_improve_apply.py (revert, the tick's sweeps)."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dream_paths  # noqa: E402
import improve_apply  # noqa: E402
import improve_class  # noqa: E402
import improve_eval  # noqa: E402
import improve_store  # noqa: E402
import improve_trials  # noqa: E402
import metrics  # noqa: E402

OUTCOMES = improve_class.REPO / "docs" / "superpowers" / "outcomes"


class Fail(Exception):
    pass


def project_name(arg=None):
    if arg or os.environ.get("TC_PROJECT"):
        return arg or os.environ["TC_PROJECT"]
    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True)
    if r.returncode:
        raise Fail("not in a git repository and no TC_PROJECT")
    return Path(r.stdout.strip()).parent.name


def cmd_list(a, store):
    rows = store.list(a.state)
    if a.json:
        print(json.dumps(rows))
    for r in ([] if a.json else rows):
        print(f"{r['id']} {r['state']} {r['class']} {r['kind']} {r['target']}")


def cmd_show(a, store):
    r = store.get(a.id)
    if not r:
        raise Fail(f"no proposal {a.id}")
    if a.json:
        print(json.dumps(r))
        return
    for k in ("id", "state", "class", "kind", "target", "source", "outcome", "reason", "title", "shrinks_reads"):
        print(f"{k}: {r[k]}")
    if r["trial_started_at"] is not None:
        print(f"trial: started {r['trial_started_at']}, length {r['trial_len']} specs")
    print(f"commit: {r['commit_sha'] or '-'}")
    print("evidence:")
    for e in json.loads(r["evidence"] or "[]"):
        print(f"  {json.dumps(e)}")
    print("patch:")
    print(r["patch"] if r["patch"] is not None else "(none)")


def cmd_propose(a, store, project):
    try:
        patch = Path(a.patch).read_text()
    except OSError as e:
        raise Fail(f"cannot read patch {a.patch}: {e.strerror}")
    try:
        evidence = json.loads(a.evidence) if a.evidence else []
    except ValueError:
        raise Fail("--evidence is not JSON")
    if not isinstance(evidence, list):
        raise Fail("--evidence must be a JSON list")
    source = "manual"
    if a.from_dream:
        run, _, idx = a.from_dream.rpartition(":")
        if not run or not idx.isdigit():
            raise Fail("--from-dream wants <run>:<index>")
        rep = dream_paths.run_dir(project, run) / "out" / "report.json"
        try:
            n = len(json.loads(rep.read_text()).get("proposals", []))
        except (OSError, ValueError):
            raise Fail(f"cannot read dream report {rep}")
        if int(idx) >= n:
            raise Fail(f"dream report has {n} proposals, no index {idx}")
        source = "dream"
        evidence.append({"type": "report", "ref": f"{rep}#proposals[{idx}]"})
    print(store.insert(source, a.kind, a.target, patch, evidence, outcome=a.outcome, shrinks_reads=a.shrinks_reads))


def load_outcomes():
    """Every outcome file as a dict, with `_path`; unreadable ones are skipped."""
    out = []
    for f in sorted(OUTCOMES.glob("*.json")):
        try:
            o = json.loads(f.read_text())
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("id"):
            out.append({**o, "_path": str(f)})
    return out


def load_configs():
    """{name: config} of the metrics configs, for the baseline flag."""
    out = {}
    d = metrics.mdir(improve_class.REPO) / "configs"
    for f in sorted(d.glob("*.md")) if d.is_dir() else []:
        c = metrics._fence(f.read_text(), "json:config")
        if isinstance(c, dict):
            out[f.stem] = c
    return out


def _runs():
    return list(metrics.last_runs(metrics.read_log(improve_class.REPO)[0]).values())


def cmd_outcome(a, store):
    active = [o for o in load_outcomes() if o.get("state") == "active" and (not a.id or o["id"] == a.id)]
    if a.id and not active:
        raise Fail(f"no active outcome {a.id}")
    runs, configs = _runs(), load_configs()
    for o in active:
        st = improve_eval.outcome_status(runs, o, configs, improve_eval.first_commit(o["_path"]))
        sig = st["signal"]
        print(f"{o['id']} {st['verdict']}")
        print(f"  tokens_per_merged_task {improve_eval._fmt(sig['trial_value'])} vs baseline {improve_eval._fmt(sig['control_value'])}, "
              f"index {improve_eval._fmt(sig['index'])} ({sig['verdict']}, {sig['n_trial']}/{sig['n_control']} specs, {st['batches']} batches)")
        for m, v in st["guardrails"].items():
            print(f"  {m} {v['verdict']} ({v['trial_value']} vs {v['control_value']})")


def cmd_tick(a, store, project):
    # before the tick: commits that waited for a busy checkout; after it: drafted specs for protected proposals
    print(f"apply {json.dumps(improve_apply.sweep_apply(store))}")
    lines = metrics.read_log(improve_class.REPO)[0]
    out = improve_eval.tick(store, project, lines, load_outcomes(), configs=load_configs())
    for k, v in out.items():
        print(f"{k} {json.dumps(v)}")
    print(f"drafts {json.dumps(improve_apply.sweep_drafts(store))}")


def cmd_revert(a, store):
    try:
        sha = improve_apply.revert(store, a.id)
    except improve_apply.ApplyError as e:
        raise Fail(str(e))
    print(f"reverted {a.id}: {sha}")


def cmd_variants(a, store):
    v = improve_trials.variants(a.spec, store)
    if a.json:
        print(json.dumps(v))
        return
    print(f"{v['spec']}: {len(v['variants'])} variant(s)")
    for e in v["variants"]:
        print(f"{e['id']} {e['kind']} {e['target']}")


def parser():
    p = argparse.ArgumentParser(prog="improve")
    p.add_argument("--project")
    sub = p.add_subparsers(dest="sub", required=True)
    s = sub.add_parser("list"); s.add_argument("--state"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("show"); s.add_argument("id"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("propose")
    s.add_argument("--kind", required=True); s.add_argument("--target", required=True); s.add_argument("--patch", required=True)
    s.add_argument("--outcome"); s.add_argument("--evidence"); s.add_argument("--shrinks-reads", action="store_true")
    s.add_argument("--from-dream")
    s = sub.add_parser("variants"); s.add_argument("spec"); s.add_argument("--json", action="store_true")
    sub.add_parser("tick")
    s = sub.add_parser("revert"); s.add_argument("id")
    s = sub.add_parser("outcome"); o = s.add_subparsers(dest="osub", required=True)
    o = o.add_parser("status"); o.add_argument("id", nargs="?")
    return p


def main(argv):
    try:
        a = parser().parse_args(argv)
    except SystemExit as e:
        return 1 if e.code else 0
    try:
        project = project_name(a.project)
        store = improve_store.Store(project)
        {"list": lambda: cmd_list(a, store), "show": lambda: cmd_show(a, store), "propose": lambda: cmd_propose(a, store, project),
         "outcome": lambda: cmd_outcome(a, store), "tick": lambda: cmd_tick(a, store, project), "revert": lambda: cmd_revert(a, store), "variants": lambda: cmd_variants(a, store)}[a.sub]()
    except improve_store.ImproveError as e:
        m = str(e)
        print(m if m.startswith("improve: no engine database") else f"improve: {a.sub}: {m.removeprefix('improve: ')}", file=sys.stderr)
        return 1
    except Fail as e:
        print(f"improve: {a.sub}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
