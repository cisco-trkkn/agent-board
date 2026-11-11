#!/usr/bin/env python3
"""metrics: the queue run log (docs/superpowers/metrics/runs.jsonl) and its commands.

Run log: one JSON object per line, kind in batch|start|run|defect (analysis is reserved; readers ignore unknown
kinds). Append-only; readers take the last `run` per (batch, spec); a malformed line is skipped and counted.
Nothing private goes in a line: no session ids, prompts, agent names, absolute paths.

CLI: metrics.py [--repo DIR] <batch start|start|record|defect|report|compare|backfill|gate|status> ...
A failing command prints one line `metrics: <sub>: <reason>` to stderr and exits 1. `tmux-ctl metrics` calls this.
"""
import argparse
import calendar
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


# ---- record: the git- and file-derived half of a run line -------------------------------------------------------

EXCLUDED = "docs/superpowers/"
OUTCOMES = ("merged", "mr", "kept", "failed")
RESERVED = ("manifest_tokens", "lock_wait_s", "lock_wait_cause", "repair_runs", "integration_s", "integration_tokens")
LEDGER_KEYS = ("bounces", "fix_rounds", "final_findings", "fix_wave", "rulings", "parked")


def _git_try(repo, *args):
    """(rc, stdout) without raising."""
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return p.returncode, p.stdout


def _epoch(iso):
    return calendar.timegm(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))


def _read(repo, ref, rel):
    """File text from the working tree, else from `ref`'s tree; None when neither has it."""
    p = Path(repo) / rel
    if p.is_file():
        return p.read_text()
    if ref:
        rc, out = _git_try(repo, "show", f"{ref}:{rel}")
        if rc == 0:
            return out
    return None


def _spec_core(spec):
    return re.sub(r"#part-\d+$", "", spec)


def find_plan(repo, spec):
    """(plan path, text, ref) of the plan whose header names the spec, else None. Working tree first, then branches."""
    core = _spec_core(spec)
    sources = []
    for f in sorted((Path(repo) / "docs/superpowers/plans").glob("*.md")):
        sources.append(("", str(f.relative_to(repo)), f.read_text()))
    rc, refs = _git_try(repo, "for-each-ref", "--format=%(refname)", "refs/heads")
    for ref in refs.split() if rc == 0 else []:
        rc, names = _git_try(repo, "ls-tree", "--name-only", ref, "docs/superpowers/plans/")
        for n in names.split() if rc == 0 else []:
            if n.endswith(".md"):
                rc, text = _git_try(repo, "show", f"{ref}:{n}")
                if rc == 0:
                    sources.append((ref, n, text))
    hits = []
    for ref, path, text in sources:
        for line in text.splitlines()[:40]:
            if "**Spec:**" in line and core in line:
                hits.append((ref, path, text, spec in line))
                break
    if not hits:
        return None
    hits.sort(key=lambda h: (not h[3], h[0] != ""))  # a line carrying the #part-N suffix first, working tree first
    ref, path, text, _ = hits[0]
    return path, text, ref or None


def parse_tasks(text):
    """{"tasks": n, "tiers": {tier: n}, "declared": set of repo-relative files minus docs/superpowers/}."""
    d = json.loads(text)
    tiers, declared, n = {}, set(), 0
    for t in d.get("tasks", []):
        n += 1
        meta = _fence(t.get("description") or "", "json:metadata") or {}
        tier = meta.get("modelTier") or "unspecified"
        tiers[tier] = tiers.get(tier, 0) + 1
        declared.update(f for f in meta.get("files", []) if isinstance(f, str) and not f.startswith(EXCLUDED))
    return {"tasks": n, "tiers": tiers, "declared": declared}


def ledger_fields(progress, final_review):
    """M-ledger counters from the progress text and (optional) final-review text."""
    lines = progress.splitlines()
    out = {
        "bounces": sum(1 for l in lines if re.search(r"review.*❌|quality ❌", l)),
        "fix_rounds": sum(1 for l in lines if "fix round" in l),
        "fix_wave": any("fix wave" in l.lower() for l in lines),
        "rulings": sum(1 for l in lines if l.startswith("Ruling:")),
        "parked": sum(1 for l in lines if "minor (deferred)" in l or "parked" in l),
    }
    n, active = 0, False
    for l in (final_review or "").splitlines():
        if l.startswith("#"):
            active = "Important" in l or "Critical" in l
        elif active and l.startswith("- "):
            n += 1
    out["final_findings"] = n
    return out


def _first_commit(repo, path):
    rc, out = _git_try(repo, "log", "--all", "--reverse", "--format=%H %ct", "--", path)
    first = out.splitlines()[0].split() if rc == 0 and out.strip() else None
    return (first[0], int(first[1])) if first else (None, None)


def find_merge(repo, plan_commit, since_ts, slug):
    """The first-parent merge on main (at/after since_ts) that brought the plan's work in.

    1. the first merge whose second parent contains the plan's first commit and whose first parent does not;
    2. else, when the plan commit was already on main, the first merge whose subject branch ends with `slug`
       (the plan basename without its date prefix);
    3. else None."""
    rc, out = _git_try(repo, "log", "--first-parent", "--merges", "--reverse", "main", "--format=%H%x09%P%x09%ct%x09%s")
    if rc != 0:
        return None
    cands = []
    for line in out.splitlines():
        sha, parents, ct, subject = (line.split("\t", 3) + [""])[:4]
        ps = parents.split()
        if len(ps) >= 2 and int(ct) >= since_ts:
            cands.append({"sha": sha, "first": ps[0], "second": ps[1], "ct": int(ct), "subject": subject})

    def has(commit):
        return _git_try(repo, "merge-base", "--is-ancestor", plan_commit, commit)[0] == 0

    for c in cands:
        if has(c["second"]) and not has(c["first"]):
            return c
    for c in cands:
        m = re.match(r"Merge branch '([^']+)'", c["subject"])
        if m and slug and m.group(1).endswith(slug):
            return c
    return None


def _numstat(repo, base, head):
    rc, out = _git_try(repo, "diff", "--numstat", "--no-renames", f"{base}..{head}")
    if rc != 0:
        return None
    touched, lines = set(), 0
    for l in out.splitlines():
        a, b, path = l.split("\t", 2)
        if path.startswith(EXCLUDED):
            continue
        touched.add(path)
        lines += (int(a) if a.isdigit() else 0) + (int(b) if b.isdigit() else 0)
    return touched, lines


def stale_base(repo, base, batch_base, head):
    """merge-tree probe. Layout of `git merge-tree --write-tree --name-only --merge-base=B X Y`:
    line 1 the result tree OID; on conflict (rc 1) the conflicted paths follow, one per line, then a blank line and
    the informational messages; rc 0 prints only the OID; any other rc (128: bad object) is a failure."""
    p = subprocess.run(["git", "-C", str(repo), "merge-tree", "--write-tree", "--name-only", f"--merge-base={base}",
                        batch_base, head], capture_output=True, text=True)
    if p.returncode == 0:
        return {"result": "clean", "paths": []}
    if p.returncode == 1:
        paths = []
        for l in p.stdout.splitlines()[1:]:
            if not l.strip():
                break
            paths.append(l)
        return {"result": "conflict", "paths": paths}
    return None


def build_record_static(repo, spec, batch, outcome, now, branch=None):
    """The `run` line fields that come from git, the plan and the ledger. Missing sources are null and named in `missing`."""
    repo = Path(repo)
    lines, _ = read_log(repo)
    batch_line = next((d for d in reversed(lines) if d.get("kind") == "batch" and d.get("batch") == batch), None)
    start = next((d for d in reversed(lines) if d.get("kind") == "start" and d.get("batch") == batch and d.get("spec") == spec), None)
    missing = []
    rec = {"kind": "run", "batch": batch, "spec": spec, "at": utc(now)}

    def null(*keys):
        for k in keys:
            rec[k] = None
            missing.append(k)

    rec["started_at"] = start["at"] if start else None
    if not start:
        missing.append("started_at")

    plan = find_plan(repo, spec)
    plan_path = plan_ref = None
    if plan:
        plan_path, _, plan_ref = plan
    rec["plan"] = plan_path
    if not plan:
        missing.append("plan")
    plan_commit, plan_ts = _first_commit(repo, plan_path) if plan else (None, None)

    merge = None
    if plan_commit:
        since = _epoch(start["at"]) if start else plan_ts
        slug = re.sub(r"^\d{4}-\d\d-\d\d-", "", Path(plan_path).name[:-3])
        merge = find_merge(repo, plan_commit, since, slug)
    head = base = None
    if merge:
        m = re.match(r"Merge branch '([^']+)'", merge["subject"])
        branch = m.group(1) if m else branch
        head = merge["second"]
        rc, mb = _git_try(repo, "merge-base", merge["first"], head)
        base = mb.strip() if rc == 0 and mb.strip() else None
        rec["merge"] = merge["sha"]
    else:
        rec["merge"] = None
        if not branch and plan_commit:
            rc, out = _git_try(repo, "branch", "--contains", plan_commit, "--format=%(refname:short)")
            branch = next((b for b in out.split() if b != "main"), None) if rc == 0 else None
        if branch:
            rc, tip = _git_try(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
            head = tip.strip() if rc == 0 and tip.strip() else None
            if head:
                rc, mb = _git_try(repo, "merge-base", "main", head)
                base = mb.strip() if rc == 0 and mb.strip() else None
    rec["branch"], rec["head"], rec["base"] = branch, head, base
    for k in ("branch", "head", "base"):
        if rec[k] is None:
            missing.append(k)
    if rec["merge"] is None:
        missing.append("merge")
    rec["ended_at"] = utc(merge["ct"]) if merge else utc(now)

    word = (outcome or "").split()[0].lower() if (outcome or "").strip() else None
    if word is None:
        rec["outcome"] = "merged" if rec["merge"] else "kept"
    else:
        rec["outcome"] = word
        if word not in OUTCOMES:
            missing.append("outcome")

    info = None
    tasks_text = _read(repo, plan_ref, plan_path + ".tasks.json") if plan_path else None
    if tasks_text:
        try:
            info = parse_tasks(tasks_text)
        except (ValueError, AttributeError, TypeError):
            info = None
    if info:
        rec["tasks"], rec["tiers"], rec["declared_files"] = info["tasks"], info["tiers"], len(info["declared"])
    else:
        null("tasks", "tiers", "declared_files")

    ns = _numstat(repo, base, head) if base and head else None
    if ns:
        touched, rec["diff_lines"] = ns
        rec["touched_files"] = len(touched)
    else:
        touched = None
        null("touched_files", "diff_lines")
    if info and touched is not None:
        both = len(info["declared"] & touched)
        rec["manifest"] = {"declared": len(info["declared"]), "touched": len(touched), "both": both,
                           "precision": round(both / len(info["declared"]), 4) if info["declared"] else None,
                           "recall": round(both / len(touched), 4) if touched else None}
    else:
        null("manifest")

    progress = None
    if plan_path:
        ldir = "docs/superpowers/ledgers/" + Path(plan_path).name[:-3]
        progress = _read(repo, plan_ref, ldir + "/progress.md")
    if progress is not None:
        rec.update(ledger_fields(progress, _read(repo, plan_ref, ldir + "/final-review.md")))
    else:
        null(*LEDGER_KEYS)

    sb = stale_base(repo, base, batch_line["base"], head) if base and head and batch_line and batch_line.get("base") else None
    rec["stale_base"] = sb
    if sb is None:
        missing.append("stale_base")
    for k in RESERVED:
        rec[k] = None
    rec["missing"] = missing
    return rec


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
